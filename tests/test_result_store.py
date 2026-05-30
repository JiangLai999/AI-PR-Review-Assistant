"""Result Store 模块单元测试。"""

from __future__ import annotations

import sqlite3
from contextlib import closing

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
