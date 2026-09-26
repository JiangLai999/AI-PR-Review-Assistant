"""L2 符号定位：命中/上限/排除/缓存/降级/集成触发条件。"""

from __future__ import annotations

import warnings

import pytest

from ai_pr_review.config import (
    DEFAULT_SYMBOL_LOCATE,
    PreferencesConfig,
    normalize_symbol_locate,
)
from ai_pr_review.models.pr_data import FileDiff, FileStatus, PRData
from ai_pr_review.services.analyzers.symbol_index import SymbolIndex
from ai_pr_review.services.context_builder import ContextBuilder
from ai_pr_review.services.review_orchestrator import ReviewOrchestrator
from ai_pr_review.services.symbol_locator import (
    RepoSymbolLocator,
    SymbolLocation,
    changed_symbols_from_impacts,
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
    def __init__(
        self,
        files: dict[str, str],
        *,
        fail_on: set[str] | None = None,
    ) -> None:
        self.files = files
        self.fail_on = fail_on or set()
        self.calls: list[str] = []

    def __call__(self, path: str) -> str | None:
        self.calls.append(path)
        if path in self.fail_on:
            raise RuntimeError(f"read failed: {path}")
        return self.files.get(path)


def make_locator(
    files: dict[str, str],
    *,
    tree: list[str] | None = None,
    cache: DictCache | None = None,
    fail_on: set[str] | None = None,
    max_requests: int = 15,
    max_results_per_symbol: int = 5,
    read_tree=None,
) -> tuple[RepoSymbolLocator, CountingReader]:
    reader = CountingReader(files, fail_on=fail_on)
    if read_tree is None:
        paths = tree if tree is not None else list(files.keys())
        read_tree = lambda: paths  # noqa: E731
    locator = RepoSymbolLocator(
        read_tree=read_tree,
        read_file=reader,
        cache=cache,
        max_requests=max_requests,
        max_results_per_symbol=max_results_per_symbol,
    )
    return locator, reader


class TestLocateBasics:
    def test_hit_returns_path_line_and_snippet(self):
        files = {
            "src/a.py": "def helper():\n    return 1\n",
            "src/b.py": "from a import helper\n\nhelper()\n",
        }
        locator, reader = make_locator(files)

        results = locator.locate("helper", exclude_paths={"src/a.py"})

        assert [
            SymbolLocation(path="src/b.py", line=1, snippet="from a import helper", source="repo"),
            SymbolLocation(path="src/b.py", line=3, snippet="helper()", source="repo"),
        ] == results
        assert reader.calls == ["src/b.py"]

    def test_miss_returns_empty_without_extra_reads(self):
        files = {"src/a.py": "VALUE = 1\n", "src/b.py": "OTHER = 2\n"}
        locator, reader = make_locator(files)

        assert locator.locate("missing_symbol") == []
        assert len(reader.calls) == 2

    def test_identifier_boundary_avoids_partial_match(self):
        files = {"src/a.py": "my_helper = 1\nhelper_value = 2\nx = helper\n"}
        locator, _ = make_locator(files)

        results = locator.locate("helper")

        assert [(item.path, item.line) for item in results] == [("src/a.py", 3)]

    def test_skips_non_source_extensions(self):
        files = {
            "docs/readme.md": "helper\n",
            "src/a.py": "helper = 1\n",
        }
        locator, reader = make_locator(files)

        results = locator.locate("helper")

        assert [item.path for item in results] == ["src/a.py"]
        assert reader.calls == ["src/a.py"]

    def test_long_line_snippet_is_truncated(self):
        long_line = "x = " + "helper" + " + " + "y" * 400
        files = {"src/a.py": long_line + "\n"}
        locator, _ = make_locator(files)

        results = locator.locate("helper")

        assert len(results) == 1
        assert len(results[0].snippet) <= 200
        assert results[0].snippet.endswith("…")

    def test_empty_symbol_returns_empty(self):
        locator, reader = make_locator({"src/a.py": "helper = 1\n"})
        assert locator.locate("") == []
        assert reader.calls == []


class TestLimits:
    def test_max_requests_caps_file_reads(self):
        files = {
            f"src/f{i}.py": f"v{i} = {i}\n" for i in range(10)
        }
        # 只有最后一个文件含符号；上限 3 次读取时永远到不了它。
        files["src/f9.py"] = "target = 1\n"
        locator, reader = make_locator(files, max_requests=3)

        results = locator.locate("target")

        assert results == []
        assert len(reader.calls) == 3

    def test_max_results_per_symbol_stops_early(self):
        files = {f"src/f{i}.py": "target = 1\ntarget = 2\n" for i in range(4)}
        locator, reader = make_locator(files, max_results_per_symbol=3)

        results = locator.locate("target")

        assert len(results) == 3
        # 命中满额后不再继续读文件。
        assert len(reader.calls) < 4

    def test_zero_max_requests_returns_empty(self):
        locator, reader = make_locator({"src/a.py": "target = 1\n"}, max_requests=0)
        assert locator.locate("target") == []
        assert reader.calls == []


class TestExcludeAndCache:
    def test_exclude_paths_skips_changed_files(self):
        files = {
            "src/changed.py": "target = 1\n",
            "src/other.py": "target = 2\n",
        }
        locator, reader = make_locator(files)

        results = locator.locate("target", exclude_paths={"src/changed.py"})

        assert [item.path for item in results] == ["src/other.py"]
        assert reader.calls == ["src/other.py"]

    def test_cache_hit_does_not_count_as_read_request(self):
        cache = DictCache()
        cache.store["src/a.py"] = "target = 1\n"
        cache.store["src/b.py"] = "target = 2\n"
        locator, reader = make_locator(
            {"src/a.py": "target = 1\n", "src/b.py": "target = 2\n"},
            cache=cache,
            max_requests=1,
        )

        results = locator.locate("target")

        assert len(results) == 2
        # 两文件都命中缓存，read_file 一次也没调用。
        assert reader.calls == []
        assert cache.get_calls >= 2

    def test_cache_miss_reads_then_writes_back(self):
        cache = DictCache()
        locator, reader = make_locator(
            {"src/a.py": "target = 1\n"}, cache=cache
        )

        results = locator.locate("target")

        assert len(results) == 1
        assert reader.calls == ["src/a.py"]
        assert cache.put_calls == 1
        assert cache.store["src/a.py"] == "target = 1\n"


class TestDegradation:
    def test_read_tree_error_returns_empty(self):
        def boom() -> list[str]:
            raise RuntimeError("tree down")

        locator, reader = make_locator({"src/a.py": "target = 1\n"}, read_tree=boom)

        assert locator.locate("target") == []
        assert reader.calls == []

    def test_read_file_error_skips_file_and_continues(self):
        files = {
            "src/broken.py": "target = 1\n",
            "src/ok.py": "target = 2\n",
        }
        locator, _ = make_locator(files, fail_on={"src/broken.py"})

        results = locator.locate("target")

        assert [item.path for item in results] == ["src/ok.py"]

    def test_read_file_error_on_all_files_returns_empty(self):
        files = {"src/a.py": "target = 1\n", "src/b.py": "target = 2\n"}
        locator, _ = make_locator(
            files, fail_on={"src/a.py", "src/b.py"}
        )

        assert locator.locate("target") == []

    def test_cache_error_does_not_break_locate(self):
        class BrokenCache:
            def get(self, key: str) -> str | None:
                raise RuntimeError("cache get")

            def put(self, key: str, content: str) -> None:
                raise RuntimeError("cache put")

        locator, reader = make_locator(
            {"src/a.py": "target = 1\n"}, cache=BrokenCache()
        )

        results = locator.locate("target")

        assert len(results) == 1
        assert reader.calls == ["src/a.py"]


class TestChangedSymbolsFromImpacts:
    def test_extracts_unique_symbol_names_in_order(self):
        class Change:
            def __init__(self, symbol: str) -> None:
                self.symbol = symbol

        class Impact:
            def __init__(self, symbol: str) -> None:
                self.change = Change(symbol)

        assert changed_symbols_from_impacts(
            [Impact("alpha"), Impact("beta"), Impact("alpha")]
        ) == ["alpha", "beta"]

    def test_empty_when_no_impacts(self):
        assert changed_symbols_from_impacts([]) == []
        assert changed_symbols_from_impacts(None) == []  # type: ignore[arg-type]


SERVICE_BEFORE = "def fetch_user(user_id):\n    return user_id\n"
SERVICE_AFTER = "def fetch_user(user_id, include_roles=False):\n    return user_id\n"
CALLER_OUTSIDE_PR = "def handler(request):\n    return fetch_user(request.user_id)\n"


def _build_context(filename: str, content: str):
    lines = content.splitlines()
    patch = f"@@ -0,0 +1,{len(lines)} @@\n" + "".join(f"+{line}\n" for line in lines)
    file_diff = FileDiff(
        filename=filename,
        status=FileStatus.MODIFIED,
        additions=len(lines),
        changes=len(lines),
        patch=patch,
    )
    return file_diff, ContextBuilder().build_context(filename, patch, content)


class TestSignatureChangeTrigger:
    """集成路径：有签名变化才触发定位。"""

    def test_signature_change_yields_symbols(self):
        contexts = [_build_context("src/service.py", SERVICE_AFTER)]
        base = SymbolIndex([_build_context("src/service.py", SERVICE_BEFORE)]).signature_map()

        changes = SymbolIndex(contexts).compare_with(base)

        assert [change.symbol for change in changes] == ["fetch_user"]
        assert changed_symbols_from_impacts(changes) == ["fetch_user"]

    def test_no_signature_change_yields_no_symbols(self):
        contexts = [_build_context("src/service.py", SERVICE_AFTER)]
        base = SymbolIndex([_build_context("src/service.py", SERVICE_AFTER)]).signature_map()

        assert SymbolIndex(contexts).compare_with(base) == []
        assert changed_symbols_from_impacts([]) == []

    def test_no_base_signatures_yields_no_symbols(self):
        contexts = [_build_context("src/service.py", SERVICE_AFTER)]
        assert SymbolIndex(contexts).compare_with({}) == []

    def test_orchestrator_skips_locate_when_no_signature_change(self):
        orchestrator = ReviewOrchestrator.__new__(ReviewOrchestrator)
        orchestrator._config = type(
            "Cfg", (), {"preferences": PreferencesConfig(symbol_locate=True)}
        )()
        called: list[str] = []

        class SpyLocator:
            def __init__(self, *args, **kwargs) -> None:
                called.append("init")

            def locate(self, symbol: str, **kwargs):
                called.append(symbol)
                return []

        import ai_pr_review.services.review_orchestrator as ro

        original = ro.RepoSymbolLocator
        ro.RepoSymbolLocator = SpyLocator  # type: ignore[assignment]
        try:
            result = orchestrator._locate_changed_symbols(
                _pr_data_with("src/service.py"),
                [],
                exclude_paths={"src/service.py"},
            )
        finally:
            ro.RepoSymbolLocator = original

        assert result == {}
        assert called == []

    def test_orchestrator_locates_only_on_signature_change(self, monkeypatch):
        import ai_pr_review.services.review_orchestrator as ro

        stub_cache = DictCache()
        monkeypatch.setattr(
            ro, "FileSystemRepoCache", lambda *args, **kwargs: stub_cache
        )
        orchestrator = ReviewOrchestrator.__new__(ReviewOrchestrator)
        orchestrator._config = type(
            "Cfg", (), {"preferences": PreferencesConfig(symbol_locate=True)}
        )()
        pr_data = _pr_data_with("src/service.py")

        def fake_tree(owner: str, repo: str, ref: str) -> list[str]:
            return ["src/service.py", "src/caller.py"]

        def fake_read(owner: str, repo: str, path: str, ref: str) -> str | None:
            return {
                "src/service.py": SERVICE_AFTER,
                "src/caller.py": CALLER_OUTSIDE_PR,
            }.get(path)

        orchestrator._list_repo_tree_paths = fake_tree  # type: ignore[method-assign]
        orchestrator._pr_fetcher = type(
            "Fetcher", (), {"fetch_file_content": staticmethod(fake_read)}
        )()

        contexts = [_build_context("src/service.py", SERVICE_AFTER)]
        base = SymbolIndex([_build_context("src/service.py", SERVICE_BEFORE)]).signature_map()
        impacts = [
            type(
                "Impact",
                (),
                {
                    "change": change,
                    "references": [],
                    "affected_files": [],
                },
            )()
            for change in SymbolIndex(contexts).compare_with(base)
        ]

        result = orchestrator._locate_changed_symbols(
            pr_data, impacts, exclude_paths={"src/service.py"}
        )

        assert "fetch_user" in result
        assert result["fetch_user"] == ["src/caller.py:2"]
        # 定位到的引用并入 CrossFileReference 列表。
        assert len(impacts[0].references) == 1
        assert impacts[0].references[0].referencing_file == "src/caller.py"
        assert impacts[0].affected_files == ["src/caller.py"]

    def test_orchestrator_respects_symbol_locate_off(self):
        orchestrator = ReviewOrchestrator.__new__(ReviewOrchestrator)
        orchestrator._config = type(
            "Cfg", (), {"preferences": PreferencesConfig(symbol_locate=False)}
        )()
        called: list[str] = []

        class SpyLocator:
            def __init__(self, *args, **kwargs) -> None:
                called.append("init")

            def locate(self, symbol: str, **kwargs):
                called.append(symbol)
                return []

        import ai_pr_review.services.review_orchestrator as ro

        original = ro.RepoSymbolLocator
        ro.RepoSymbolLocator = SpyLocator  # type: ignore[assignment]
        try:
            impacts = [
                type(
                    "Impact",
                    (),
                    {
                        "change": type("C", (), {"symbol": "fetch_user", "file": "s.py"})(),
                        "references": [],
                        "affected_files": [],
                    },
                )()
            ]
            result = orchestrator._locate_changed_symbols(
                _pr_data_with("src/service.py"),
                impacts,
                exclude_paths=set(),
            )
        finally:
            ro.RepoSymbolLocator = original

        assert result == {}
        assert called == []

    def test_empty_locate_result_is_omitted(self):
        locator, _ = make_locator({"src/a.py": "nothing_here = 1\n"})
        assert locator.locate("fetch_user") == []


def _pr_data_with(filename: str) -> PRData:
    return PRData(
        pr_number=1,
        title="t",
        description="",
        author="a",
        state="open",
        head_sha="head",
        base_sha="base",
        head_ref="feature",
        base_ref="main",
        diff="",
        files=[
            FileDiff(
                filename=filename,
                status=FileStatus.MODIFIED,
                additions=1,
                changes=1,
                patch="@@ -1 +1 @@\n-x\n+y",
            )
        ],
        url="https://example.com/pr/1",
        merged=False,
        owner="owner",
        repo="repo",
    )


class TestSymbolLocatePreference:
    def test_default_is_true(self):
        assert DEFAULT_SYMBOL_LOCATE is True
        assert PreferencesConfig().symbol_locate is True

    @pytest.mark.parametrize("value", [True, False, 0, 1, "true", "false", "on", "off"])
    def test_normalize_accepts_common_forms(self, value):
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            normalized = normalize_symbol_locate(value)
        assert isinstance(normalized, bool)
        assert [item for item in recorded if "symbol_locate" in str(item.message)] == []

    @pytest.mark.parametrize("raw", ["maybe", 2, object()])
    def test_invalid_value_falls_back_with_warning(self, raw):
        with pytest.warns(RuntimeWarning, match="symbol_locate"):
            assert normalize_symbol_locate(raw) is True

    def test_legacy_config_without_field_stays_enabled(self):
        # 字段缺失时 PreferencesConfig 默认开启，不告警。
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            preferences = PreferencesConfig()
        assert preferences.symbol_locate is True
        assert [item for item in recorded if "symbol_locate" in str(item.message)] == []
