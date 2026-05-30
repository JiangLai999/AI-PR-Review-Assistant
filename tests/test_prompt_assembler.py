"""Prompt Assembler 模块单元测试。"""

from ai_pr_review.config import PromptAssemblerConfig
from ai_pr_review.services.context_builder import ClassInfo, FileContext, FunctionInfo
from ai_pr_review.services.prompt_assembler import PromptAssembler


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
        assembler = PromptAssembler(
            PromptAssemblerConfig(max_diff_chars=20, max_context_chars=20)
        )

        prompt = assembler.build_user_prompt(build_file_context())

        assert "[truncated]" in prompt

    def test_get_json_schema_contains_review_result_shape(self):
        assembler = PromptAssembler()

        schema = assembler.get_json_schema()

        assert schema["title"] == "ReviewResult"
        assert "properties" in schema
        assert schema["properties"]["summary"]["type"] == "string"
        assert schema["properties"]["findings"]["type"] == "array"
