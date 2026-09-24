"""结果库路径解析的测试。

覆盖 `ResultStore._resolve_db_path` 的两种分支：配置路径可写时原样使用，
不可写时改道到工作目录 —— 且改道必须可被发现，否则客户端口会
"看起来像丢了历史记录"。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_pr_review.config import ResultStoreConfig
from ai_pr_review.services.result_store import ResultStore


class TestDefaultPath:
    def test_writable_path_is_used_as_is(self, tmp_path: Path):
        target = tmp_path / "results.db"

        store = ResultStore(ResultStoreConfig(db_path=str(target)))

        assert store.db_path == target
        assert store.using_fallback_path is False

    def test_parent_directories_are_created(self, tmp_path: Path):
        target = tmp_path / "nested" / "deeper" / "results.db"

        store = ResultStore(ResultStoreConfig(db_path=str(target)))

        assert target.parent.is_dir()
        assert store.using_fallback_path is False

    def test_explicit_path_failure_is_not_swallowed(self, monkeypatch, tmp_path: Path):
        """非 `~` 开头的显式路径不可写时必须抛错，而不是悄悄换地方。"""
        boom = tmp_path / "results.db"

        def refuse(self: Path, *args, **kwargs):
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "mkdir", refuse)

        with pytest.raises(OSError, match="历史数据库路径不可写") as raised:
            ResultStore(ResultStoreConfig(db_path=str(boom)))
        assert str(boom) in str(raised.value)
        assert "result_store.db_path" in str(raised.value)


class TestFallbackPath:
    @staticmethod
    def _block_home_dir(monkeypatch, blocked: Path):
        """只让「主目录下的配置路径」创建失败，备用目录照常可建。"""
        real_mkdir = Path.mkdir

        def guarded(self: Path, *args, **kwargs):
            if self == blocked:
                raise OSError("home is read-only")
            return real_mkdir(self, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", guarded)

    def test_home_path_falls_back_and_warns(self, monkeypatch, tmp_path: Path):
        fallback_dir = tmp_path / "cwd"
        fallback_dir.mkdir()
        monkeypatch.chdir(fallback_dir)
        blocked = tmp_path / "blocked-default"
        self._block_home_dir(monkeypatch, blocked)
        monkeypatch.setattr(
            "ai_pr_review.services.result_store._default_result_store_path",
            lambda: blocked / "results.db",
        )

        with pytest.warns(RuntimeWarning, match="Result store path is not writable"):
            store = ResultStore(ResultStoreConfig(db_path=str(blocked / "results.db")))

        assert store.using_fallback_path is True
        assert store.db_path == fallback_dir / ".ai_pr_review" / "results.db"

    def test_fallback_store_is_usable(self, monkeypatch, tmp_path: Path):
        from ai_pr_review.services.prompt_assembler import Finding, ReviewResult

        monkeypatch.chdir(tmp_path)
        blocked = tmp_path / "blocked-default"
        self._block_home_dir(monkeypatch, blocked)
        monkeypatch.setattr(
            "ai_pr_review.services.result_store._default_result_store_path",
            lambda: blocked / "results.db",
        )

        with pytest.warns(RuntimeWarning):
            store = ResultStore(ResultStoreConfig(db_path=str(blocked / "results.db")))

        run_id = store.save_result(
            "https://github.com/owner/repo/pull/1",
            ReviewResult(
                summary="s",
                findings=[
                    Finding(
                        severity="low",
                        category="correctness",
                        file="a.py",
                        line_start=1,
                        line_end=1,
                        title="t",
                        problem="p",
                        suggestion="s",
                        confidence=0.9,
                        code_snippet="x",
                    )
                ],
            ),
        )

        assert store.get_result(run_id) is not None
        assert store.get_statistics()["total_runs"] == 1


def test_stale_fixed_probe_does_not_force_fallback(tmp_path: Path) -> None:
    (tmp_path / ".write-probe").write_text("leftover", encoding="utf-8")
    store = ResultStore(ResultStoreConfig(db_path=str(tmp_path / "history.db")))
    assert store.db_path == tmp_path / "history.db"
    assert store.using_fallback_path is False


def test_explicit_legacy_tilde_path_failure_never_redirects(monkeypatch, tmp_path: Path) -> None:
    requested = Path("~/.ai_pr_review/results.db").expanduser()
    real_mkdir = Path.mkdir

    def guarded(self: Path, *args, **kwargs):
        if self == requested.parent:
            raise OSError("blocked for test")
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", guarded)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(OSError, match="历史数据库路径不可写"):
        ResultStore(ResultStoreConfig(db_path="~/.ai_pr_review/results.db"))
    assert not (tmp_path / ".ai_pr_review" / "results.db").exists()
