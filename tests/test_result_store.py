"""Result Store 模块单元测试。"""

from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from ai_pr_review.config import ResultStoreConfig
from ai_pr_review.services.prompt_assembler import Finding, ReviewResult
from ai_pr_review.services.result_store import ResultStore


def build_finding(
    *,
    severity: str = "medium",
    category: str = "correctness",
    file: str = "src/app.py",
    line_start: int = 10,
    line_end: int = 10,
    title: str = "Issue",
    problem: str = "Something is wrong.",
    suggestion: str = "Fix it.",
    confidence: float = 0.8,
    code_snippet: str = "pass",
) -> Finding:
    return Finding(
        severity=severity,
        category=category,
        file=file,
        line_start=line_start,
        line_end=line_end,
        title=title,
        problem=problem,
        suggestion=suggestion,
        confidence=confidence,
        code_snippet=code_snippet,
    )


def build_review_result(
    summary: str = "summary", severities: list[str] | None = None
) -> ReviewResult:
    levels = severities or ["high", "medium"]
    findings = [
        build_finding(
            severity=severity,
            title=f"{severity} issue {index}",
            line_start=index + 1,
            line_end=index + 1,
        )
        for index, severity in enumerate(levels)
    ]
    return ReviewResult(summary=summary, findings=findings)


def test_save_and_get_result_round_trip(tmp_path):
    db_path = tmp_path / "results.db"
    store = ResultStore(ResultStoreConfig(db_path=str(db_path)))
    result = build_review_result(summary="first review", severities=["critical", "low"])

    run_id = store.save_result("https://github.com/test-owner/test-repo/pull/42", result)
    loaded = store.get_result(run_id)

    assert loaded is not None
    assert loaded.model_dump() == result.model_dump()


def test_save_result_populates_run_metadata_from_pr_url(tmp_path):
    db_path = tmp_path / "results.db"
    store = ResultStore(ResultStoreConfig(db_path=str(db_path)))

    run_id = store.save_result(
        "https://github.com/test-owner/test-repo/pull/42/files",
        build_review_result(severities=["critical", "high", "high", "info"]),
    )

    with closing(sqlite3.connect(db_path)) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()

    assert row is not None
    assert row["pr_number"] == 42
    assert row["repo_owner"] == "test-owner"
    assert row["repo_name"] == "test-repo"
    assert row["total_findings"] == 4
    assert row["critical_findings"] == 1
    assert row["high_findings"] == 2
    assert row["info_findings"] == 1


def test_list_runs_returns_newest_first_and_supports_pr_filter(tmp_path):
    db_path = tmp_path / "results.db"
    store = ResultStore(ResultStoreConfig(db_path=str(db_path)))
    pr_one = "https://github.com/test-owner/test-repo/pull/1"
    pr_two = "https://github.com/test-owner/test-repo/pull/2"

    first_id = store.save_result(pr_one, build_review_result(summary="first"))
    second_id = store.save_result(pr_two, build_review_result(summary="second"))
    third_id = store.save_result(pr_one, build_review_result(summary="third"))

    all_runs = store.list_runs(limit=10)
    filtered_runs = store.list_runs(pr_url=pr_one, limit=10)

    assert [run["id"] for run in all_runs] == [third_id, second_id, first_id]
    assert [run["id"] for run in filtered_runs] == [third_id, first_id]
    assert all(run["pr_url"] == pr_one for run in filtered_runs)


def test_get_statistics_returns_aggregated_counts(tmp_path):
    db_path = tmp_path / "results.db"
    store = ResultStore(ResultStoreConfig(db_path=str(db_path)))

    store.save_result(
        "https://github.com/test-owner/test-repo/pull/1",
        build_review_result(severities=["critical", "medium"]),
    )
    store.save_result(
        "https://github.com/test-owner/test-repo/pull/2",
        build_review_result(severities=["high", "high", "info"]),
    )

    stats = store.get_statistics()

    assert stats["total_runs"] == 2
    assert stats["unique_prs"] == 2
    assert stats["total_findings"] == 5
    assert stats["critical_findings"] == 1
    assert stats["high_findings"] == 2
    assert stats["medium_findings"] == 1
    assert stats["low_findings"] == 0
    assert stats["info_findings"] == 1
    assert stats["total_cost"] == 0
    assert stats["latest_run_at"] is not None


def test_max_results_prunes_oldest_runs(tmp_path):
    db_path = tmp_path / "results.db"
    store = ResultStore(ResultStoreConfig(db_path=str(db_path), max_results=2))

    first_id = store.save_result(
        "https://github.com/test-owner/test-repo/pull/1",
        build_review_result(summary="first"),
    )
    second_id = store.save_result(
        "https://github.com/test-owner/test-repo/pull/2",
        build_review_result(summary="second"),
    )
    third_id = store.save_result(
        "https://github.com/test-owner/test-repo/pull/3",
        build_review_result(summary="third"),
    )

    runs = store.list_runs(limit=10)

    assert [run["id"] for run in runs] == [third_id, second_id]
    assert store.get_result(first_id) is None


def test_database_uses_wal_mode(tmp_path):
    db_path = tmp_path / "results.db"
    ResultStore(ResultStoreConfig(db_path=str(db_path)))

    with closing(sqlite3.connect(db_path)) as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

    assert journal_mode.lower() == "wal"


# --------------------------------------------------------------- 追问记录


def _store_with_run(tmp_path, *, max_results: int = 10):
    """建一个带一条 run 的库，返回 (store, run_id)。"""
    store = ResultStore(
        ResultStoreConfig(db_path=str(tmp_path / "results.db"), max_results=max_results)
    )
    run_id = store.save_result(
        "https://github.com/test-owner/test-repo/pull/9",
        build_review_result(summary="chat host"),
    )
    return store, run_id


def test_chat_turns_round_trip_and_index(tmp_path):
    store, run_id = _store_with_run(tmp_path)

    question = store.save_chat_turn(run_id, role="user", content="这次审查有几个问题？")
    answer = store.save_chat_turn(
        run_id,
        role="assistant",
        content="两个：一个中风险，一个低风险。",
        model="deepseek-flash",
        usage={"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
        context_meta={"bound_run": run_id, "sections": ["run_summary"]},
        duration_ms=1820,
    )

    assert (question["turn_index"], answer["turn_index"]) == (1, 2)
    assert question["turn_id"] != answer["turn_index"]
    assert answer["usage"]["total_tokens"] == 150
    assert answer["context_meta"]["bound_run"] == run_id
    assert answer["duration_ms"] == 1820
    assert answer["created_at"]

    turns = store.list_chat_turns(run_id)
    assert [turn["role"] for turn in turns] == ["user", "assistant"]
    assert [turn["turn_index"] for turn in turns] == [1, 2]
    assert turns[1]["content"].startswith("两个")


def test_chat_turns_are_scoped_per_run_and_by_limit(tmp_path):
    store, run_id = _store_with_run(tmp_path)
    other_id = store.save_result(
        "https://github.com/test-owner/test-repo/pull/10",
        build_review_result(summary="other"),
    )
    store.save_chat_turn(run_id, role="user", content="A")
    store.save_chat_turn(other_id, role="user", content="B")
    store.save_chat_turn(run_id, role="user", content="C")

    assert [turn["content"] for turn in store.list_chat_turns(run_id)] == ["A", "C"]
    assert [turn["content"] for turn in store.list_chat_turns(other_id)] == ["B"]
    # limit 取最早的 N 条（顺序契约：turn_index ASC）。
    assert [turn["content"] for turn in store.list_chat_turns(run_id, limit=1)] == ["A"]
    assert store.list_chat_turns("no-such-run") == []


def test_chat_turn_rejects_unknown_role(tmp_path):
    store, run_id = _store_with_run(tmp_path)

    with pytest.raises(ValueError, match="Unsupported chat role"):
        store.save_chat_turn(run_id, role="system", content="nope")


def test_chat_turn_payload_tolerates_broken_json(tmp_path):
    """导入/迁移进来的脏行不能让整页追问炸掉：解不开就当空 dict。"""
    store, run_id = _store_with_run(tmp_path)
    store.save_chat_turn(run_id, role="assistant", content="hi", usage={"a": 1})

    with closing(sqlite3.connect(store.db_path)) as connection:
        connection.execute("UPDATE chat_turns SET usage_json = 'not json'")
        connection.commit()

    turn = store.list_chat_turns(run_id)[0]
    assert turn["usage"] == {}
    assert turn["model"] == ""


def test_clear_chat_turns_removes_only_that_run(tmp_path):
    store, run_id = _store_with_run(tmp_path)
    other_id = store.save_result(
        "https://github.com/test-owner/test-repo/pull/11",
        build_review_result(summary="keep"),
    )
    store.save_chat_turn(run_id, role="user", content="A")
    store.save_chat_turn(run_id, role="user", content="B")
    store.save_chat_turn(other_id, role="user", content="keep me")

    assert store.clear_chat_turns(run_id) == 2
    assert store.list_chat_turns(run_id) == []
    assert len(store.list_chat_turns(other_id)) == 1
    # 再清一次是幂等的 0，不是抛错。
    assert store.clear_chat_turns(run_id) == 0


def test_pruning_runs_also_prunes_their_chat_turns(tmp_path):
    """追问记录跟着 run 一起清：删掉的 run 已经没有任何入口能打开它。"""
    db_path = tmp_path / "results.db"
    store = ResultStore(ResultStoreConfig(db_path=str(db_path), max_results=1))
    old_id = store.save_result(
        "https://github.com/test-owner/test-repo/pull/1",
        build_review_result(summary="old"),
    )
    store.save_chat_turn(old_id, role="user", content="会被清掉的追问")

    new_id = store.save_result(
        "https://github.com/test-owner/test-repo/pull/2",
        build_review_result(summary="new"),
    )
    store.save_chat_turn(new_id, role="user", content="保留的追问")

    assert store.list_chat_turns(old_id) == []
    assert len(store.list_chat_turns(new_id)) == 1
    with closing(sqlite3.connect(db_path)) as connection:
        orphans = connection.execute(
            "SELECT COUNT(*) FROM chat_turns WHERE run_id NOT IN (SELECT id FROM runs)"
        ).fetchone()[0]
    assert orphans == 0


def test_chat_turns_table_is_created_on_legacy_database(tmp_path):
    """老库（只有 runs/finding_feedback）打开后必须自动补出 chat_turns 表。"""
    db_path = tmp_path / "legacy.db"
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            """
            CREATE TABLE runs (
                id TEXT PRIMARY KEY, pr_url TEXT NOT NULL, pr_number INTEGER,
                repo_owner TEXT, repo_name TEXT, head_sha TEXT,
                total_files INTEGER, included_files INTEGER, excluded_files INTEGER,
                total_findings INTEGER, critical_findings INTEGER, high_findings INTEGER,
                medium_findings INTEGER, low_findings INTEGER, info_findings INTEGER,
                total_cost REAL, duration_seconds REAL, model TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                result_json TEXT, metadata_json TEXT
            )
            """
        )
        connection.commit()

    store = ResultStore(ResultStoreConfig(db_path=str(db_path)))
    store.save_chat_turn("legacy-run", role="user", content="hi")

    assert [turn["content"] for turn in store.list_chat_turns("legacy-run")] == ["hi"]
