"""Context Builder 模块单元测试。"""

from ai_pr_review.config import ContextBuilderConfig
from ai_pr_review.services.context_builder import ContextBuilder

PYTHON_CONTENT = """import os
from typing import Any


class Service(BaseService):
    def __init__(self, repo):
        self.repo = repo

    async def run(self, item: str) -> dict[str, Any]:
        return await self.repo.fetch(item)


def helper(value: int) -> int:
    return value + 1
"""


PYTHON_DIFF = """@@ -4,6 +4,7 @@
 class Service(BaseService):
     def __init__(self, repo):
         self.repo = repo

+    async def run(self, item: str) -> dict[str, Any]:
         return await self.repo.fetch(item)
"""


TS_CONTENT = """import { http } from './http';

export class ApiClient extends BaseClient {
  async request(path: string): Promise<Response> {
    return http(path);
  }
}

export const loadUser = async (id: string): Promise<User> => {
  return fetchUser(id);
};
"""


class TestContextBuilder:
    """Context Builder 测试。"""

    def test_build_context_extracts_python_context(self):
        builder = ContextBuilder(ContextBuilderConfig(context_lines=2))

        result = builder.build_context("src/service.py", PYTHON_DIFF, PYTHON_CONTENT)

        assert result.file_path == "src/service.py"
        assert result.language == "python"
        assert result.parse_mode == "regex"
        assert result.imports == ["import os", "from typing import Any"]
        assert [function.name for function in result.functions] == ["__init__", "run", "helper"]
        assert result.functions[1].is_async is True
        assert result.functions[1].parameters == ["self", "item: str"]
        assert result.functions[1].return_type == "dict[str, Any]"
        assert len(result.classes) == 1
        assert result.classes[0].name == "Service"
        assert result.classes[0].methods == ["__init__", "run"]
        assert result.classes[0].parent_classes == ["BaseService"]
        assert "@@ context" in result.diff_with_context
        assert ">   7:         self.repo = repo" in result.diff_with_context
        assert (
            "    9:     async def run(self, item: str) -> dict[str, Any]:"
            in result.diff_with_context
        )

    def test_extract_ast_context_extracts_typescript_symbols(self):
        builder = ContextBuilder(ContextBuilderConfig(enable_tree_sitter=False))

        result = builder.extract_ast_context("src/client.ts", TS_CONTENT, "typescript")

        assert result.parse_mode == "regex"
        assert result.imports == ["import { http } from './http';"]
        assert [function.name for function in result.functions] == ["request", "loadUser"]
        assert result.functions[0].is_async is True
        assert result.functions[1].return_type == "Promise<User>"
        assert len(result.classes) == 1
        assert result.classes[0].name == "ApiClient"
        assert result.classes[0].methods == ["request"]
        assert result.classes[0].parent_classes == ["BaseClient"]

    def test_unknown_language_falls_back_to_diff_only(self):
        builder = ContextBuilder(ContextBuilderConfig(enable_tree_sitter=False))

        result = builder.build_context(
            "docs/readme.txt",
            "@@ -1 +1 @@\n-old\n+new",
            "new\nsecond line",
        )

        assert result.language == "text"
        assert result.parse_mode == "fallback"
        assert result.imports == []
        assert result.functions == []
        assert result.classes == []
        assert ">   1: new" in result.diff_with_context

    def test_tree_sitter_failure_uses_regex_fallback(self):
        builder = ContextBuilder(ContextBuilderConfig(enable_tree_sitter=True))

        result = builder.extract_ast_context("src/service.py", PYTHON_CONTENT, "python")

        assert result.parse_mode == "regex"
        assert [function.name for function in result.functions] == ["__init__", "run", "helper"]

    def test_diff_context_merges_overlapping_windows(self):
        builder = ContextBuilder(ContextBuilderConfig(context_lines=1, enable_tree_sitter=False))
        diff = """@@ -2,3 +2,3 @@
 line2
-line3
+line3 changed
 line4
@@ -4,3 +4,3 @@
 line4
-line5
+line5 changed
 line6
"""
        content = "line1\nline2\nline3 changed\nline4\nline5 changed\nline6\nline7"

        result = builder.extract_diff_context(diff, content)

        assert result.count("@@ context") == 1
        assert ">   3: line3 changed" in result
        assert ">   5: line5 changed" in result
