"""`repo_context`：预取顺序、截断、缓存、降级、预算与相对导入。"""

from __future__ import annotations

from ai_pr_review.services.repo_context import (
    IMPORT_INIT_MAX_LINES,
    TEST_MAX_LINES,
    RepoContextProvider,
    RelatedFile,
    render_pr_file_list,
    render_repo_tree,
)


class DictCache:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.get_calls = 0
        self.put_calls = 0

    def get(self, key: str) -> str | None:
        self.get_calls += 1
        return self.store.get(key)

    def put(self, key: str, content: str) -> None:
        self.put_calls += 1
        self.store[key] = content


class CountingReader:
    def __init__(self, files: dict[str, str], *, fail_on: set[str] | None = None) -> None:
        self.files = files
        self.fail_on = fail_on or set()
        self.calls: list[str] = []

    def __call__(self, path: str) -> str | None:
        self.calls.append(path)
        if path in self.fail_on:
            raise RuntimeError(f"read failed: {path}")
        return self.files.get(path)


def make_file(path: str, reason: str) -> RelatedFile:
    return RelatedFile(path=path, reason=reason, content="", truncated=False, from_cache=False)


class TestCollectionOrderAndLimits:
    def test_test_file_comes_first_then_import_then_init(self):
        files = {
            "pkg/mod.py": "from .dep import x\n",
            "pkg/test_mod.py": "def test_x():\n    pass\n",
            "pkg/dep.py": "def helper():\n    pass\n",
            "pkg/__init__.py": "VALUE = 1\n",
        }
        provider = RepoContextProvider(read_file=CountingReader(files))

        result = provider.collect_for_file("pkg/mod.py")

        assert [item.path for item in result] == [
            "pkg/test_mod.py",
            "pkg/dep.py",
            "pkg/__init__.py",
        ]
        assert [item.reason for item in result] == ["test", "import", "init"]

    def test_test_candidates_prefer_same_dir_over_tests_root(self):
        files = {
            "pkg/mod.py": "",
            "pkg/test_mod.py": "same dir\n",
            "tests/test_mod.py": "tests root\n",
        }
        provider = RepoContextProvider(read_file=CountingReader(files))

        result = provider.collect_for_file("pkg/mod.py")

        assert [item.path for item in result] == ["pkg/test_mod.py"]
        assert result[0].content == "same dir\n"

    def test_falls_back_to_tests_root_when_same_dir_missing(self):
        files = {
            "pkg/mod.py": "",
            "tests/test_mod.py": "tests root\n",
        }
        provider = RepoContextProvider(read_file=CountingReader(files))

        result = provider.collect_for_file("pkg/mod.py")

        assert [item.path for item in result] == ["tests/test_mod.py"]

    def test_dedupes_paths_appearing_in_multiple_strategies(self):
        files = {
            "pkg/mod.py": "from .test_mod import x\n",
            "pkg/test_mod.py": "def t():\n    pass\n",
        }
        provider = RepoContextProvider(read_file=CountingReader(files))

        result = provider.collect_for_file("pkg/mod.py")

        paths = [item.path for item in result]
        assert paths == ["pkg/test_mod.py"]
        assert paths.count("pkg/test_mod.py") == 1

    def test_max_files_caps_collection(self):
        files = {
            "pkg/mod.py": "from .a import x\nfrom .b import y\n",
            "pkg/test_mod.py": "def t():\n    pass\n",
            "pkg/a.py": "A = 1\n",
            "pkg/b.py": "B = 2\n",
            "pkg/__init__.py": "I = 3\n",
        }
        provider = RepoContextProvider(read_file=CountingReader(files), max_files=2)

        result = provider.collect_for_file("pkg/mod.py")

        assert [item.path for item in result] == ["pkg/test_mod.py", "pkg/a.py"]

    def test_max_files_zero_returns_empty(self):
        files = {"pkg/mod.py": "from .a import x\n", "pkg/test_mod.py": "T = 1\n"}
        provider = RepoContextProvider(read_file=CountingReader(files), max_files=0)

        assert provider.collect_for_file("pkg/mod.py") == []

    def test_non_source_extension_returns_empty(self):
        reader = CountingReader({"docs/readme.md": "hi\n", "docs/test_readme.md": "x\n"})
        provider = RepoContextProvider(read_file=reader)

        assert provider.collect_for_file("docs/readme.md") == []
        assert reader.calls == []


class TestTruncation:
    def test_long_test_file_truncated_around_definition(self):
        lines = ["# filler\n"] * 50 + ["def target():\n", "    return 1\n"] + ["# tail\n"] * 80
        files = {
            "pkg/mod.py": "",
            "pkg/test_mod.py": "".join(lines),
        }
        provider = RepoContextProvider(read_file=CountingReader(files))

        result = provider.collect_for_file("pkg/mod.py")

        assert len(result) == 1
        assert result[0].truncated is True
        assert "def target():" in result[0].content
        assert len(result[0].content.splitlines()) <= TEST_MAX_LINES

    def test_long_import_file_truncated_around_definition(self):
        lines = ["# filler\n"] * 30 + ["class Widget:\n", "    pass\n"] + ["# tail\n"] * 80
        files = {
            "pkg/mod.py": "from .dep import x\n",
            "pkg/dep.py": "".join(lines),
        }
        provider = RepoContextProvider(read_file=CountingReader(files))

        result = provider.collect_for_file("pkg/mod.py")

        assert result[0].reason == "import"
        assert result[0].truncated is True
        assert "class Widget:" in result[0].content
        assert len(result[0].content.splitlines()) <= IMPORT_INIT_MAX_LINES + 1

    def test_long_file_without_definition_keeps_head(self):
        files = {
            "pkg/mod.py": "",
            "pkg/test_mod.py": "".join(f"line {i}\n" for i in range(1, 201)),
        }
        provider = RepoContextProvider(read_file=CountingReader(files))

        result = provider.collect_for_file("pkg/mod.py")

        assert result[0].truncated is True
        assert result[0].content.startswith("line 1\n")
        assert len(result[0].content.splitlines()) == TEST_MAX_LINES

    def test_short_file_not_truncated(self):
        files = {"pkg/mod.py": "", "pkg/test_mod.py": "def t():\n    pass\n"}
        provider = RepoContextProvider(read_file=CountingReader(files))

        result = provider.collect_for_file("pkg/mod.py")

        assert result[0].truncated is False
        assert result[0].content == "def t():\n    pass\n"


class TestCache:
    def test_cache_hit_sets_from_cache_and_skips_read_file(self):
        files = {
            "pkg/mod.py": "",
            "pkg/test_mod.py": "def t():\n    pass\n",
            "pkg/__init__.py": "INIT = 1\n",
        }
        cache = DictCache()
        reader = CountingReader(files)
        provider = RepoContextProvider(read_file=reader, cache=cache)

        first = provider.collect_for_file("pkg/mod.py")
        calls_after_first = len(reader.calls)

        second = provider.collect_for_file("pkg/mod.py")

        assert first[0].from_cache is False
        assert second[0].from_cache is True
        assert len(reader.calls) == calls_after_first
        assert "pkg/test_mod.py" in cache.store

    def test_cache_hit_still_applies_truncation(self):
        long_body = "".join(f"line {i}\n" for i in range(1, 300))
        files = {"pkg/mod.py": "", "pkg/test_mod.py": long_body}
        cache = DictCache()
        provider = RepoContextProvider(read_file=CountingReader(files), cache=cache)

        first = provider.collect_for_file("pkg/mod.py")
        second = provider.collect_for_file("pkg/mod.py")

        assert first[0].truncated is True
        assert second[0].from_cache is True
        assert second[0].truncated is True
        assert second[0].content == first[0].content


class TestDegradation:
    def test_exception_on_one_candidate_continues_with_others(self):
        reader = CountingReader(
            {
                "pkg/mod.py": "from .dep import x\nfrom .other import y\n",
                "pkg/dep.py": "D = 1\n",
                "pkg/other.py": "O = 2\n",
                "pkg/__init__.py": "I = 3\n",
            },
            fail_on={"pkg/dep.py"},
        )
        provider = RepoContextProvider(read_file=reader)

        result = provider.collect_for_file("pkg/mod.py")

        paths = [item.path for item in result]
        assert "pkg/dep.py" not in paths
        assert paths == ["pkg/other.py", "pkg/__init__.py"]

    def test_exception_on_test_candidate_falls_through_to_next(self):
        reader = CountingReader(
            {
                "pkg/mod.py": "",
                "pkg/test_mod.py": "same dir\n",
                "tests/test_mod.py": "tests root\n",
            },
            fail_on={"pkg/test_mod.py"},
        )
        provider = RepoContextProvider(read_file=reader)

        result = provider.collect_for_file("pkg/mod.py")

        assert [item.path for item in result] == ["tests/test_mod.py"]

    def test_missing_file_is_skipped_without_error(self):
        provider = RepoContextProvider(read_file=CountingReader({"pkg/mod.py": ""}))

        assert provider.collect_for_file("pkg/mod.py") == []


class TestBudget:
    def test_drops_low_priority_when_over_budget(self):
        # 预算 400 字符 = 100 tokens；init 与 import 较大，test 最小但优先级最高
        files = {
            "pkg/mod.py": "from .a import x\n",
            "pkg/test_mod.py": "T = 1\n",  # 7 chars
            "pkg/a.py": "A = 1\n" + "#" * 300,  # ~307
            "pkg/__init__.py": "I = 1\n" + "#" * 300,  # ~307
        }
        provider = RepoContextProvider(
            read_file=CountingReader(files),
            max_files=3,
            budget_tokens=100,
        )

        result = provider.collect_for_file("pkg/mod.py")

        paths = [item.path for item in result]
        assert "pkg/__init__.py" not in paths  # 优先级最低，先被丢弃
        assert paths[0] == "pkg/test_mod.py"

    def test_keeps_at_least_one_when_some_file_fits(self):
        files = {
            "pkg/mod.py": "from .a import x\n",
            "pkg/test_mod.py": "T = 1\n",
            "pkg/a.py": "A = 1\n" + "#" * 5000,
        }
        # 预算 20 字符：仅 test 文件能放下
        provider = RepoContextProvider(
            read_file=CountingReader(files),
            max_files=3,
            budget_tokens=5,
        )

        result = provider.collect_for_file("pkg/mod.py")

        assert len(result) == 1
        assert result[0].path == "pkg/test_mod.py"

    def test_budget_covers_truncated_content_size(self):
        lines = ["# filler\n"] * 200
        files = {
            "pkg/mod.py": "",
            "pkg/test_mod.py": "".join(lines),
        }
        # 截断后约 120 行 * 9 字符；给刚好放下截断结果的预算
        provider = RepoContextProvider(
            read_file=CountingReader(files),
            budget_tokens=300,  # 1200 chars
        )

        result = provider.collect_for_file("pkg/mod.py")

        assert len(result) == 1
        assert result[0].truncated is True
        assert len(result[0].content) <= 1200


class TestRelativeImports:
    def test_single_dot_resolves_sibling_module(self):
        files = {
            "pkg/mod.py": "from .dep import x\n",
            "pkg/dep.py": "def helper():\n    pass\n",
        }
        provider = RepoContextProvider(read_file=CountingReader(files), max_files=1)

        result = provider.collect_for_file("pkg/mod.py")

        assert result[0].path == "pkg/dep.py"
        assert result[0].reason == "import"

    def test_two_dots_resolves_parent_package_module(self):
        files = {
            "pkg/sub/mod.py": "from ..utils import y\n",
            "pkg/utils.py": "Y = 1\n",
        }
        provider = RepoContextProvider(read_file=CountingReader(files), max_files=1)

        result = provider.collect_for_file("pkg/sub/mod.py")

        assert result[0].path == "pkg/utils.py"

    def test_two_dots_with_dotted_module(self):
        files = {
            "pkg/sub/mod.py": "from ..X.Y import z\n",
            "pkg/X/Y.py": "Z = 1\n",
        }
        provider = RepoContextProvider(read_file=CountingReader(files), max_files=1)

        result = provider.collect_for_file("pkg/sub/mod.py")

        assert result[0].path == "pkg/X/Y.py"

    def test_prefers_module_py_over_package_init(self):
        files = {
            "pkg/mod.py": "from .dep import x\n",
            "pkg/dep.py": "PY = 1\n",
            "pkg/dep/__init__.py": "INIT = 1\n",
        }
        provider = RepoContextProvider(read_file=CountingReader(files), max_files=1)

        result = provider.collect_for_file("pkg/mod.py")

        assert result[0].path == "pkg/dep.py"

    def test_falls_back_to_package_init(self):
        files = {
            "pkg/mod.py": "from .dep import x\n",
            "pkg/dep/__init__.py": "INIT = 1\n",
        }
        provider = RepoContextProvider(read_file=CountingReader(files), max_files=1)

        result = provider.collect_for_file("pkg/mod.py")

        assert result[0].path == "pkg/dep/__init__.py"

    def test_from_dot_import_name(self):
        files = {
            "pkg/mod.py": "from . import dep\n",
            "pkg/dep.py": "D = 1\n",
        }
        provider = RepoContextProvider(read_file=CountingReader(files), max_files=1)

        result = provider.collect_for_file("pkg/mod.py")

        assert result[0].path == "pkg/dep.py"
        assert result[0].reason == "import"

    def test_relative_import_skipped_for_non_python(self):
        files = {
            "pkg/mod.ts": "from './dep' // not parsed\n",
            "pkg/dep.ts": "export const x = 1\n",
        }
        provider = RepoContextProvider(read_file=CountingReader(files), max_files=3)

        result = provider.collect_for_file("pkg/mod.ts")

        assert all(item.reason != "import" for item in result)


class TestRelatedFileShape:
    def test_related_file_fields(self):
        files = {"pkg/mod.py": "", "pkg/test_mod.py": "def t():\n    pass\n"}
        provider = RepoContextProvider(read_file=CountingReader(files))

        item = provider.collect_for_file("pkg/mod.py")[0]

        assert isinstance(item, RelatedFile)
        assert item.path == "pkg/test_mod.py"
        assert item.reason == "test"
        assert item.content == "def t():\n    pass\n"
        assert item.truncated is False
        assert item.from_cache is False


class TestRenderPrFileList:
    """B（docs/claude-repo-structure-context.md）：PR 变更清单的注入格式。"""

    def test_header_counts_paths_and_review_skips(self):
        text = render_pr_file_list(["src/a.py", "src/b.ts"], skipped=4)

        assert text.splitlines()[0] == "## 本次 PR 变更文件（共 2 个，另有 4 个被本次审查跳过）"
        assert "- src/a.py" in text
        assert "- src/b.ts" in text
        assert "不得臆测" in text

    def test_skip_clause_is_omitted_when_unknown_or_zero(self):
        assert "## 本次 PR 变更文件（共 2 个）" in render_pr_file_list(["a.py", "b.py"])
        assert "## 本次 PR 变更文件（共 2 个）" in render_pr_file_list(
            ["a.py", "b.py"], skipped=0
        )
        assert "跳过" not in render_pr_file_list(["a.py"], skipped=0)

    def test_truncates_over_the_limit_and_says_how_many_are_hidden(self):
        paths = [f"src/f{index:03d}.py" for index in range(60)]

        text = render_pr_file_list(paths, limit=50)

        assert "- src/f049.py" in text
        assert "- src/f050.py" not in text
        assert "…（另有 10 个未列出，仅列出前 50 个）" in text

    def test_unavailable_renders_the_reason_without_inventing_paths(self):
        text = render_pr_file_list(None, unavailable="RuntimeError")

        assert text == "## 本次 PR 变更文件\n（未能读取变更文件清单：RuntimeError）"

    def test_paths_with_control_characters_are_dropped(self):
        text = render_pr_file_list(["src/ok.py", "src/evil\n- 注入行.py", "src/tab\t.py"])

        assert "（共 1 个）" in text
        assert "注入行" not in text
        assert "- src/ok.py" in text


class TestRenderRepoTree:
    """C（docs/claude-repo-structure-context.md）：目录树的注入格式与三种折叠。"""

    def test_renders_directories_first_then_files(self):
        text = render_repo_tree(["src/app.py", "src/pkg/mod.py", "README.md"])

        assert text.splitlines()[0].startswith("## 仓库目录树（head 提交")
        # 第 3 行起是树本体，最后一行是规则
        assert text.splitlines()[2:-1] == [
            "src/",
            "  pkg/",
            "    mod.py",
            "  app.py",
            "README.md",
        ]

    def test_sha_is_trimmed_into_the_header(self):
        text = render_repo_tree(["a.py"], sha="b" * 40)

        assert "## 仓库目录树（head 提交 bbbbbbbb · 深度 ≤3 · 最多 200 行）" in text

    def test_directory_beyond_max_depth_is_folded_with_a_count(self):
        text = render_repo_tree(["a/b/c/d/e.py"], max_depth=3)

        assert "    c/ …（2 项未展开）" in text

    def test_siblings_share_the_line_budget(self):
        paths = [f"big/f{index:03d}.py" for index in range(120)] + [
            "small/a.py",
            "small/b.py",
        ]

        text = render_repo_tree(paths, max_entries=30, max_children=25)

        # 大目录吃不到小目录的份额：两个都露面，小的完整、大的折叠
        assert "small/" in text
        assert "  b.py" in text
        assert "…（另有" in text

    def test_per_directory_child_cap_folds_the_rest(self):
        paths = [f"src/f{index:03d}.py" for index in range(40)]

        text = render_repo_tree(paths, max_children=10, max_entries=200)

        assert "  f009.py" in text
        assert "f010.py" not in text
        assert "…（另有 30 项未列出）" in text

    def test_noise_directories_and_files_are_excluded(self):
        paths = [
            "src/app.py",
            "node_modules/pkg/index.js",
            "src/__pycache__/app.pyc",
            ".venv313/lib/site.py",
            "docs/.DS_Store",
            "web/dist/bundle.js",
            "pkg.egg-info/PKG-INFO",
            ".github/workflows/ci.yml",
        ]

        text = render_repo_tree(paths)

        # 只看树本体：第 2 行的说明里本来就写着"已排除 node_modules 等"，不能拿全文判
        body = "\n".join(text.splitlines()[2:-1])
        for noise in ("node_modules", "__pycache__", ".venv313", ".DS_Store", "dist", "egg-info"):
            assert noise not in body, f"{noise} 是噪声，不该进注入"
        # 点目录只放行少数几个（.github 在）
        assert ".github/" in body
        assert "ci.yml" in body
        assert "src/" in body and "app.py" in body

    def test_empty_and_unavailable_trees_are_distinct(self):
        empty = render_repo_tree([])
        missing = render_repo_tree(None, unavailable="NetworkError")

        assert "（该提交下没有可列出的文件）" in empty
        assert missing == "## 仓库目录树\n（未能读取仓库目录树：NetworkError）"
        assert "NetworkError" not in empty
