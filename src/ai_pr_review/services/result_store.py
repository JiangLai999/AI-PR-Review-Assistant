"""Review 结果存储模块。

使用 SQLite 持久化审查结果和运行历史，支持按 PR 查询和统计。
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import uuid
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ai_pr_review.config import ResultStoreConfig, _default_result_store_path
from ai_pr_review.services.prompt_assembler import ReviewResult
from ai_pr_review.utils.github_url_parser import parse_pr_url

# 严重级别字段列表，用于统计
SEVERITY_FIELDS = ("critical", "high", "medium", "low", "info")


class ResultStore:
    """使用 SQLite 持久化 ReviewResult 和运行历史。"""

    def __init__(self, config: ResultStoreConfig):
        """初始化存储层，创建数据库目录和表结构。"""
        self._config = config
        self._db_path = self._resolve_db_path(config.db_path)
        self._using_fallback_path = self._db_path != Path(config.db_path).expanduser()
        self._initialize_database()

    @property
    def using_fallback_path(self) -> bool:
        """是否因为配置路径不可写而改道到了备用库。

        调用方可以据此提示用户，避免"历史记录看起来丢了"这类误判。
        """
        return self._using_fallback_path

    @property
    def db_path(self) -> Path:
        """实际使用的数据库文件路径。"""
        return self._db_path

    @staticmethod
    def _resolve_db_path(configured_path: str) -> Path:
        """解析数据库路径，并在配置路径不可写时退回到工作目录。

        退回是为了让受限运行环境（HOME 只读、沙箱）仍能启动服务。但它会改变
        实际读写位置，因此必须让调用方能够发现：`using_fallback_path` 会变为
        True，并额外发出 RuntimeWarning。否则用户会以为历史记录丢失了。
        """
        requested = Path(configured_path).expanduser()
        try:
            requested.parent.mkdir(parents=True, exist_ok=True)
            # A fixed `.write-probe` falsely reports unwritable when a process
            # crashes before unlink or two checks overlap. Unique temp files
            # avoid both collisions and leave no probe after normal exit.
            with tempfile.NamedTemporaryFile(
                dir=requested.parent, prefix=".write-probe-", delete=True
            ):
                pass
            return requested
        except OSError as exc:
            # The platform default may be unavailable in a restricted runtime (for
            # example a sandbox). We still fall back so the CLI can start, but the
            # redirect must never be silent: a moved history database reads as
            # "my past reviews disappeared".
            default_path = _default_result_store_path()
            is_platform_default = requested == default_path
            # The legacy tilde spelling can also be an explicitly chosen
            # location. It is not safe to silently redirect it to CWD.
            if not is_platform_default:
                # An explicit/workspace-derived history location is a data
                # boundary. Never silently redirect it into an unrelated CWD.
                raise OSError(
                    f"历史数据库路径不可写：{requested}。请检查目录权限，或在配置中指定可写的 result_store.db_path。"
                ) from exc
            fallback = Path.cwd() / ".ai_pr_review" / "results.db"
            fallback.parent.mkdir(parents=True, exist_ok=True)
            warnings.warn(
                f"Result store path is not writable: {requested}; using fallback: {fallback}. "
                "History will be stored at the fallback path.",
                RuntimeWarning,
                stacklevel=2,
            )
            return fallback

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
        metadata: dict | None = None,
    ) -> str:
        """保存 Review 结果，返回 run_id。"""
        run_id = str(uuid.uuid4())
        parsed_url = self._parse_pr_url(pr_url)
        counts = self._count_findings(result)
        payload = result.model_dump_json()
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)

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
                    result_json,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    metadata_json,
                ),
            )
            self._prune_old_results(connection)

        return run_id

    def get_run_metadata(self, run_id: str) -> dict:
        """Return persisted plan and execution metadata for a run."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT metadata_json FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        if row is None or not row["metadata_json"]:
            return {}
        try:
            value = json.loads(row["metadata_json"])
        except (TypeError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def save_feedback(
        self,
        run_id: str,
        finding_id: str,
        status: str,
        note: str = "",
    ) -> None:
        """Persist a user's decision about a finding."""
        allowed = {"accepted", "rejected", "fixed", "needs_review"}
        if status not in allowed:
            raise ValueError(f"Unsupported feedback status: {status}")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO finding_feedback (run_id, finding_id, status, note)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, finding_id, status, note),
            )

    def list_feedback(self, run_id: str) -> list[dict]:
        """Return feedback decisions for a review run."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT run_id, finding_id, status, note, created_at
                FROM finding_feedback
                WHERE run_id = ?
                ORDER BY datetime(created_at) ASC, rowid ASC
                """,
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_run_summary(self, run_id: str) -> dict | None:
        """Return persisted PR/run fields and metadata needed to rebuild a report."""
        with self._connect() as connection:
            row = connection.execute(
                """SELECT id, pr_url, pr_number, repo_owner, repo_name, head_sha,
                          total_files, included_files, excluded_files, created_at,
                          model, duration_seconds, total_cost, metadata_json
                   FROM runs WHERE id = ?""",
                (run_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    # ------------------------------------------------------------------
    # 追问记录（`/api/chat` 的落库侧）
    #
    # 只服务**绑定了 run** 的追问：未绑定 run 的普通对话没有可归属的记录，
    # 前端仍按"挂载期内内存"处理，这里不造一个 run_id='' 的伪记录。
    # ------------------------------------------------------------------

    def save_chat_turn(
        self,
        run_id: str,
        *,
        role: str,
        content: str,
        model: str = "",
        usage: dict | None = None,
        context_meta: dict | None = None,
        duration_ms: int | None = None,
    ) -> dict:
        """追加一条追问记录，返回落库后的行（含 `turn_id` / `turn_index` / `created_at`）。

        `turn_index` 由库侧自增（同一 run 内 MAX+1），调用方不需要自己维护计数——
        并发写同一 run 时也不会串号。
        """
        if role not in {"user", "assistant"}:
            raise ValueError(f"Unsupported chat role: {role}")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(turn_index), 0) + 1 AS next_index FROM chat_turns WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            turn_index = int(row["next_index"])
            cursor = connection.execute(
                """
                INSERT INTO chat_turns (
                    run_id, turn_index, role, content, model,
                    usage_json, context_meta_json, duration_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    turn_index,
                    role,
                    content,
                    model,
                    json.dumps(usage or {}, ensure_ascii=False),
                    json.dumps(context_meta or {}, ensure_ascii=False),
                    duration_ms,
                ),
            )
            saved = connection.execute(
                """SELECT id, run_id, turn_index, role, content, model,
                          usage_json, context_meta_json, duration_ms, created_at
                   FROM chat_turns WHERE id = ?""",
                (cursor.lastrowid,),
            ).fetchone()
        return self._chat_turn_payload(saved)

    def list_chat_turns(self, run_id: str, limit: int = 200) -> list[dict]:
        """按时间顺序返回某次审查的追问记录（最早在前，便于前端直接追加渲染）。"""
        normalized_limit = max(0, limit)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, run_id, turn_index, role, content, model,
                       usage_json, context_meta_json, duration_ms, created_at
                FROM chat_turns
                WHERE run_id = ?
                ORDER BY turn_index ASC
                LIMIT ?
                """,
                (run_id, normalized_limit),
            ).fetchall()
        return [self._chat_turn_payload(row) for row in rows]

    def clear_chat_turns(self, run_id: str) -> int:
        """删除某次审查的全部追问记录，返回删除条数。"""
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM chat_turns WHERE run_id = ?", (run_id,))
        return int(cursor.rowcount or 0)

    @staticmethod
    def _chat_turn_payload(row: sqlite3.Row | None) -> dict:
        """把一行 chat_turns 转成前端契约形状（JSON 列解回 dict）。"""
        if row is None:  # pragma: no cover - 只在并发删除时可能出现
            return {}
        payload = dict(row)
        for column, target in (
            ("usage_json", "usage"),
            ("context_meta_json", "context_meta"),
        ):
            raw = payload.pop(column, "")
            try:
                value = json.loads(raw) if raw else {}
            except (TypeError, json.JSONDecodeError):
                value = {}
            payload[target] = value if isinstance(value, dict) else {}
        turn_id = payload.pop("id", None)
        payload["turn_id"] = turn_id
        return payload

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
            row = connection.execute(
                """
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
                """
            ).fetchone()

        return dict(row)

    def _initialize_database(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
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
                    result_json TEXT,
                    metadata_json TEXT
                )
                """
            )

            self._migrate_runs_metadata_column(connection)

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS finding_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    finding_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    note TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (run_id) REFERENCES runs(id)
                )
                """
            )

            # 追问记录：同一次审查可多轮，`turn_index` 是库侧自增的稳定顺序。
            # 不加 FOREIGN KEY：run 被清理后追问记录按同样的清理策略处理，
            # 但历史库里可能存在"先写追问、后补 run"的极端顺序（导入/迁移）。
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    turn_index INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    model TEXT DEFAULT '',
                    usage_json TEXT DEFAULT '',
                    context_meta_json TEXT DEFAULT '',
                    duration_ms INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chat_turns_run
                ON chat_turns (run_id, turn_index)
                """
            )

    @staticmethod
    def _migrate_runs_metadata_column(connection: sqlite3.Connection) -> None:
        """Add metadata_json to databases created before the column existed."""
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(runs)").fetchall()}
        if "metadata_json" not in columns:
            connection.execute("ALTER TABLE runs ADD COLUMN metadata_json TEXT")

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
            connection.execute("DELETE FROM chat_turns")
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
        # 追问记录跟着它所属的 run 一起清：孤儿行只会白占空间，且删掉的 run
        # 已经无法再从历史里打开，留着这些记录没有任何入口能看到它们。
        connection.execute("DELETE FROM chat_turns WHERE run_id NOT IN (SELECT id FROM runs)")
