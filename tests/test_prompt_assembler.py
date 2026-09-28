"""Prompt Assembler 模块单元测试。"""

import json

from ai_pr_review.config import PromptAssemblerConfig
from ai_pr_review.services.context_builder import ClassInfo, FileContext, FunctionInfo
from ai_pr_review.services.prompt_assembler import Finding, PromptAssembler, finding_has_source


def build_file_context(language: str = "python") -> FileContext:
    return FileContext(
        file_path="src/service.py",
        language=language,
        diff="@@ -1,2 +1,3 @@\n import os\n+value = eval(user_input)\n return 1",
        diff_with_context=(
            "@@ context 1:3 @@\n"
            "    1: import os\n"
            ">   2: value = eval(user_input)\n"
            "    3: return 1"
        ),
        imports=["import os"],
        functions=[
            FunctionInfo(
                name="run",
                start_line=10,
                end_line=14,
                parameters=["user_input: str"],
                return_type="int",
                is_async=True,
            )
        ],
        classes=[
            ClassInfo(
                name="Service",
                start_line=5,
                end_line=20,
                methods=["run"],
                parent_classes=["BaseService"],
            )
        ],
        parse_mode="regex",
    )


class TestPromptAssembler:
    """Prompt Assembler 测试。"""

    def test_build_system_prompt_includes_base_language_rules_and_schema(self):
        assembler = PromptAssembler()

        prompt = assembler.build_system_prompt("python")

        assert "You are a code reviewer." in prompt
        assert "PYTHON SPECIFIC CHECKS:" in prompt
        assert "mutable default arg" in prompt
        assert '"title"' in prompt
        assert '"findings"' in prompt

    def test_build_system_prompt_supports_typescript_alias_and_custom_rules(self):
        assembler = PromptAssembler(
            PromptAssemblerConfig(
                custom_rules=["Flag unsafe deserialization from untrusted payloads."],
            )
        )

        prompt = assembler.build_system_prompt("ts")

        assert "TS/JS SPECIFIC CHECKS:" in prompt
        assert "CUSTOM REVIEW RULES:" in prompt
        assert "unsafe deserialization" in prompt

    def test_build_system_prompt_omits_optional_sections_when_disabled(self):
        assembler = PromptAssembler(
            PromptAssemblerConfig(
                include_json_schema_in_system_prompt=False,
                include_custom_rules_in_system_prompt=False,
                custom_rules=["Do not render me."],
            )
        )

        prompt = assembler.build_system_prompt("javascript")

        assert "JSON SCHEMA:" not in prompt
        assert "Do not render me." not in prompt

    def test_build_user_prompt_renders_file_context(self):
        assembler = PromptAssembler()

        prompt = assembler.build_user_prompt(build_file_context())

        assert "File: src/service.py" in prompt
        assert "Language: python" in prompt
        assert "Parse mode: regex" in prompt
        assert "Imports: import os" in prompt
        assert "Functions: async run(user_input: str) -> int [10-14]" in prompt
        assert "Classes: Service extends BaseService methods=[run] [5-20]" in prompt
        assert "@@ -1,2 +1,3 @@" in prompt
        assert "@@ context 1:3 @@" in prompt

    def test_build_user_prompt_truncates_large_sections(self):
        assembler = PromptAssembler(PromptAssemblerConfig(max_diff_chars=20, max_context_chars=20))

        prompt = assembler.build_user_prompt(build_file_context())

        assert "[truncated]" in prompt

    def test_get_json_schema_contains_review_result_shape(self):
        assembler = PromptAssembler()

        schema = assembler.get_json_schema()

        assert schema["title"] == "ReviewResult"
        assert "properties" in schema
        assert schema["properties"]["summary"]["type"] == "string"
        assert schema["properties"]["findings"]["type"] == "array"

    def test_build_system_prompt_includes_response_language_contract(self):
        assembler = PromptAssembler(response_language="zh-CN")
        prompt = assembler.build_system_prompt("python")
        assert "Simplified Chinese" in prompt
        assert "Keep file paths" in prompt

        english = PromptAssembler(response_language="en-US").build_system_prompt("python")
        assert "in English" in english


class TestModelFacingSchema:
    """交给模型的 Schema 不得暴露服务端字段（P6 §2.1）。"""

    def test_schema_hides_server_side_finding_fields(self):
        schema = PromptAssembler().get_json_schema()

        finding_schema = schema["$defs"]["Finding"]
        for field in (
            "sources",
            "evidence",
            "evidence_status",
            "evidence_issues",
            "finding_id",
            "rule_id",
        ):
            assert field not in finding_schema["properties"]
            assert field not in finding_schema["required"]

    def test_schema_keeps_model_facing_fields(self):
        finding_schema = PromptAssembler().get_json_schema()["$defs"]["Finding"]

        for field in (
            "severity",
            "category",
            "file",
            "line_start",
            "line_end",
            "title",
            "problem",
            "suggestion",
            "confidence",
            "code_snippet",
        ):
            assert field in finding_schema["properties"]

    def test_schema_drops_the_unreferenced_evidence_model(self):
        schema = PromptAssembler().get_json_schema()

        assert "Evidence" not in schema["$defs"]
        assert "evidence" not in json.dumps(schema)

    def test_prompts_do_not_leak_server_side_fields(self):
        from ai_pr_review.services.prompt_assembler import SERVER_SIDE_FINDING_FIELDS

        prompts = [
            PromptAssembler().build_system_prompt("python"),
            PromptAssembler().build_cross_file_system_prompt(),
        ]

        for prompt in prompts:
            for field in SERVER_SIDE_FINDING_FIELDS:
                assert f'"{field}"' not in prompt
                assert f"<{field}>" not in prompt


def test_finding_normalizes_human_readable_category_labels() -> None:
    finding = Finding(
        severity="critical",
        category="安全性",
        file="website/index.html",
        line_start=1,
        line_end=1,
        title="credential",
        problem="problem",
        suggestion="suggestion",
        confidence=0.9,
        code_snippet="x",
    )
    assert finding.category == "security"


class TestFindingSources:
    """`sources` 规范化与 `finding_has_source` 判定（P6 §2.3）。"""

    def build(self, sources) -> Finding:
        return Finding(
            severity="high",
            category="security",
            file="src/app.py",
            line_start=1,
            line_end=1,
            title="t",
            problem="p",
            suggestion="s",
            confidence=0.9,
            code_snippet="x",
            sources=sources,
        )

    def test_sources_are_trimmed_and_lowercased(self):
        finding = self.build([" Static_Rule ", "AI_Analysis"])

        assert finding.sources == ["static_rule", "ai_analysis"]

    def test_unknown_sources_are_preserved(self):
        finding = self.build(["Model_Guess"])

        assert finding.sources == ["model_guess"]
        assert finding_has_source(finding, "static_rule") is False

    def test_finding_has_source_ignores_spelling(self):
        assert finding_has_source(self.build(["STATIC_RULE"]), "static_rule") is True
        assert finding_has_source(self.build(["ai_analysis"]), "static_rule") is False
        assert finding_has_source(self.build([]), "static_rule") is False

    def test_default_source_is_ai_analysis(self):
        finding = Finding(
            severity="low",
            category="correctness",
            file="src/app.py",
            line_start=2,
            line_end=2,
            title="t",
            problem="p",
            suggestion="s",
            confidence=0.5,
            code_snippet="x",
        )

        assert finding.sources == ["ai_analysis"]
        assert finding.rule_id == ""
