"""Review 结果存储模块。

使用 SQLite 持久化审查结果和运行历史，支持按 PR 查询和统计。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ai_pr_review.config import ResultStoreConfig
from ai_pr_review.services.prompt_assembler import ReviewResult
from ai_pr_review.utils.github_url_parser import parse_pr_url

# 严重级别字段列表，用于统计
SEVERITY_FIELDS = ("critical", "high", "medium", "low", "info")


class ResultStore:
    """使用 SQLite 持久化 ReviewResult 和运行历史。"""

    def __init__(self, config: ResultStoreConfig):
        """初始化存储层，创建数据库目录和表结构。"""
        self._config = config
        self._db_path = Path(config.db_path).expanduser()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_database()

    def save_result(
        self,
        pr_url: str,
        result: ReviewResult,
        *,
        head_sha: str | None = None,
        total_files: int | None = None,
        included_files: int | None = None,
        excluded_files: int | None = None,
        total_cost: float | None = None,
        duration_seconds: float | None = None,
        model: str | None = None,
    ) -> str:
        """保存 Review 结果，返回 run_id。"""
        run_id = str(uuid.uuid4())
        parsed_url = self._parse_pr_url(pr_url)
        counts = self._count_findings(result)
        payload = result.model_dump_json()

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    id,
                    pr_url,
                    pr_number,
                    repo_owner,
                    repo_name,
                    head_sha,
                    total_files,
                    included_files,
                    excluded_files,
                    total_findings,
                    critical_findings,
                    high_findings,
                    medium_findings,
                    low_findings,
                    info_findings,
                    total_cost,
                    duration_seconds,
                    model,
                    result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    pr_url,
                    parsed_url["pr_number"],
                    parsed_url["repo_owner"],
                    parsed_url["repo_name"],
                    head_sha,
                    total_files,
                    included_files,
                    excluded_files,
                    counts["total_findings"],
                    counts["critical_findings"],
                    counts["high_findings"],
                    counts["medium_findings"],
                    counts["low_findings"],
                    counts["info_findings"],
                    total_cost,
                    duration_seconds,
                    model,
                    payload,
                ),
            )
            self._prune_old_results(connection)

        return run_id

    def get_result(self, run_id: str) -> ReviewResult | None:
        """获取 Review 结果。"""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT result_json FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()

        if row is None:
            return None

        return ReviewResult.model_validate_json(row["result_json"])

    def list_runs(self, pr_url: str | None = None, limit: int = 10) -> list[dict]:
        """列出历史运行。"""
        normalized_limit = max(0, limit)
        query = """
            SELECT
                id,
                pr_url,
                pr_number,
                repo_owner,
                repo_name,
                head_sha,
                total_files,
                included_files,
                excluded_files,
                total_findings,
                critical_findings,
                high_findings,
                medium_findings,
                low_findings,
                info_findings,
                total_cost,
                duration_seconds,
                model,
                created_at
            FROM runs
        """
        parameters: tuple[object, ...]

        if pr_url is not None:
            query += " WHERE pr_url = ?"
            parameters = (pr_url, normalized_limit)
        else:
            parameters = (normalized_limit,)

        query += " ORDER BY datetime(created_at) DESC, rowid DESC LIMIT ?"

        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()

        return [dict(row) for row in rows]

    def get_statistics(self) -> dict:
        """获取统计信息。"""
        with self._connect() as connection:
            row = connection.execute("""
                SELECT
                    COUNT(*) AS total_runs,
                    COUNT(DISTINCT pr_url) AS unique_prs,
                    COALESCE(SUM(total_findings), 0) AS total_findings,
                    COALESCE(SUM(critical_findings), 0) AS critical_findings,
                    COALESCE(SUM(high_findings), 0) AS high_findings,
                    COALESCE(SUM(medium_findings), 0) AS medium_findings,
                    COALESCE(SUM(low_findings), 0) AS low_findings,
                    COALESCE(SUM(info_findings), 0) AS info_findings,
                    COALESCE(SUM(total_cost), 0) AS total_cost,
                    MAX(created_at) AS latest_run_at
                FROM runs
                """).fetchone()

        return dict(row)

    def _initialize_database(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    pr_url TEXT NOT NULL,
                    pr_number INTEGER,
                    repo_owner TEXT,
                    repo_name TEXT,
                    head_sha TEXT,
                    total_files INTEGER,
                    included_files INTEGER,
                    excluded_files INTEGER,
                    total_findings INTEGER,
                    critical_findings INTEGER,
                    high_findings INTEGER,
                    medium_findings INTEGER,
                    low_findings INTEGER,
                    info_findings INTEGER,
                    total_cost REAL,
                    duration_seconds REAL,
                    model TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    result_json TEXT
                )
                """)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _count_findings(self, result: ReviewResult) -> dict[str, int]:
        counts = {f"{severity}_findings": 0 for severity in SEVERITY_FIELDS}

        for finding in result.findings:
            counts[f"{finding.severity}_findings"] += 1

        counts["total_findings"] = len(result.findings)
        return counts

    def _parse_pr_url(self, pr_url: str) -> dict[str, int | str | None]:
        try:
            parsed = parse_pr_url(pr_url)
        except Exception:
            return {
                "pr_number": None,
                "repo_owner": None,
                "repo_name": None,
            }

        return {
            "pr_number": parsed.pr_number,
            "repo_owner": parsed.owner,
            "repo_name": parsed.repo,
        }

    def _prune_old_results(self, connection: sqlite3.Connection) -> None:
        if self._config.max_results <= 0:
            connection.execute("DELETE FROM runs")
            return

        connection.execute(
            """
            DELETE FROM runs
            WHERE id IN (
                SELECT id
                FROM runs
                ORDER BY datetime(created_at) DESC, rowid DESC
                LIMIT -1 OFFSET ?
            )
            """,
            (self._config.max_results,),
        )
