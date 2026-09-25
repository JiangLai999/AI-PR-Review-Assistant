"""`repo_context`：预取顺序、截断、缓存、降级、预算与相对导入。"""

from __future__ import annotations

from ai_pr_review.services.repo_context import (
    IMPORT_INIT_MAX_LINES,
    TEST_MAX_LINES,
    RepoContextProvider,
    RelatedFile,
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
