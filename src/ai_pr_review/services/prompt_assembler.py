"""Prompt Assembler 模块。

负责组装代码审查所需的 system prompt、user prompt，以及约束输出的 JSON
Schema。该模块尽量保持输出稳定，方便后续接入 LLM 或做快照测试。
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from ai_pr_review.config import PromptAssemblerConfig
from ai_pr_review.services.context_builder import FileContext

BASE_SYSTEM_PROMPT = """You are a code reviewer. Output findings in the specified JSON format ONLY.
No preamble, no markdown fences, no commentary outside the JSON.

PRINCIPLES:
1. Flag bugs, security issues, and logic errors. Ignore style, formatting,
   and naming unless they cause functional defects.
2. Each finding must reference a specific file and changed line from the diff.
3. If a finding can be detected by ESLint, Pylint, RuboCop, or similar static
   analysis tools, lower confidence to 0.5 or below, or omit it.
4. Confidence reflects certainty: 0.9+ = certain bug, 0.7-0.9 = likely issue,
   0.5-0.7 = worth mentioning, <0.5 = do not report.
5. Report only issues that are actionable and supported by the provided diff
   and context.
"""

LANGUAGE_SPECIFIC_PROMPTS = {
    "python": """PYTHON SPECIFIC CHECKS:
- bare except without raise -> error_handling
- mutable default arg (def f(x=[])) -> logic
- async without await -> logic
- f-string with user input in SQL -> security
- file handle not in context manager -> error_handling
- eval/exec on user input -> security""",
    "javascript": """TS/JS SPECIFIC CHECKS:
- null/undefined access without guard -> error_handling
- any type bypassing type safety -> logic
- missing await on Promise -> logic
- prototype pollution (Object.assign on user input) -> security
- XSS via innerHTML/dangerouslySetInnerHTML -> security""",
    "typescript": """TS/JS SPECIFIC CHECKS:
- null/undefined access without guard -> error_handling
- any type bypassing type safety -> logic
- missing await on Promise -> logic
- prototype pollution (Object.assign on user input) -> security
- XSS via innerHTML/dangerouslySetInnerHTML -> security""",
}


class Finding(BaseModel):
    """单条审查发现。"""

    severity: str = Field(pattern="^(critical|high|medium|low|info)$")
    category: str = Field(
        pattern=(
            "^(correctness|security|resource|error_handling|performance|"
            "concurrency|architecture)$"
        )
    )
    file: str
    line_start: int
    line_end: int
    title: str
    problem: str
    suggestion: str
    confidence: float
    code_snippet: str


class ReviewResult(BaseModel):
    """审查结果。"""

    summary: str
    findings: list[Finding]


class PromptAssembler:
    """组装代码审查 Prompt 与输出 Schema。"""

    def __init__(self, config: PromptAssemblerConfig | None = None):
        self._config = config or PromptAssemblerConfig()

    def build_system_prompt(self, language: str) -> str:
        """组装完整的 system prompt。"""
        normalized_language = self._normalize_language(language)
        sections = [BASE_SYSTEM_PROMPT.strip()]

        language_prompt = LANGUAGE_SPECIFIC_PROMPTS.get(normalized_language)
        if language_prompt is not None:
            sections.append(language_prompt)

        if self._config.include_custom_rules_in_system_prompt and self._config.custom_rules:
            rendered_rules = "\n".join(f"- {rule}" for rule in self._config.custom_rules)
            sections.append(f"CUSTOM REVIEW RULES:\n{rendered_rules}")

        output_instructions = [
            "OUTPUT REQUIREMENTS:",
            "- Return a single JSON object matching the required schema.",
            "- Do not include markdown fences or explanatory text.",
            "- If there are no valid findings, return an empty findings list and a brief summary.",
        ]

        if self._config.include_json_schema_in_system_prompt:
            schema_json = self._schema_to_json_text(self.get_json_schema())
            output_instructions.append("JSON SCHEMA:")
            output_instructions.append(schema_json)

        sections.append("\n".join(output_instructions))
        return "\n\n".join(sections)

    def build_user_prompt(self, file_context: FileContext) -> str:
        """组装用户 prompt（包含 diff 和上下文）。"""
        imports = self._render_list(file_context.imports)
        functions = self._render_functions(file_context)
        classes = self._render_classes(file_context)
        diff = self._truncate_text(file_context.diff, self._config.max_diff_chars)
        diff_with_context = self._truncate_text(
            file_context.diff_with_context,
            self._config.max_context_chars,
        )

        sections = [
            "Review the following changed file and report only valid findings supported by the diff.",
            f"File: {file_context.file_path}",
            f"Language: {file_context.language}",
            f"Parse mode: {file_context.parse_mode}",
            f"Imports: {imports}",
            f"Functions: {functions}",
            f"Classes: {classes}",
            "Diff:",
            diff or "<empty>",
            "Context:",
            diff_with_context or "<empty>",
        ]
        return "\n".join(sections)

    def get_json_schema(self) -> dict:
        """获取输出的 JSON Schema。"""
        return ReviewResult.model_json_schema()

    def _normalize_language(self, language: str) -> str:
        normalized = language.strip().lower()
        if normalized in {"js", "node", "javascript"}:
            return "javascript"
        if normalized in {"ts", "tsx", "typescript"}:
            return "typescript"
        if normalized in {"py", "python"}:
            return "python"
        return normalized

    def _render_list(self, values: list[str]) -> str:
        if not values:
            return "none"
        return ", ".join(values)

    def _render_functions(self, file_context: FileContext) -> str:
        if not file_context.functions:
            return "none"

        rendered = []
        for function in file_context.functions:
            async_prefix = "async " if function.is_async else ""
            params = ", ".join(function.parameters)
            return_type = f" -> {function.return_type}" if function.return_type else ""
            rendered.append(
                f"{async_prefix}{function.name}({params}){return_type} [{function.start_line}-{function.end_line}]"
            )
        return "; ".join(rendered)

    def _render_classes(self, file_context: FileContext) -> str:
        if not file_context.classes:
            return "none"

        rendered = []
        for class_info in file_context.classes:
            parents = (
                f" extends {', '.join(class_info.parent_classes)}"
                if class_info.parent_classes
                else ""
            )
            methods = ", ".join(class_info.methods) if class_info.methods else "none"
            rendered.append(
                f"{class_info.name}{parents} methods=[{methods}] [{class_info.start_line}-{class_info.end_line}]"
            )
        return "; ".join(rendered)

    def _truncate_text(self, value: str, max_chars: int | None) -> str:
        if max_chars is None or len(value) <= max_chars:
            return value
        return value[:max_chars].rstrip() + "\n[truncated]"

    def _schema_to_json_text(self, schema: dict) -> str:
        return json.dumps(schema, ensure_ascii=True, indent=2)
