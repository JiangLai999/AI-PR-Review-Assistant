"""Chat 会话持久化辅助函数。

两种存储并存（docs/session-and-compaction-plan.md §A2）：

- **多会话（新，TUI 后端）**：``<config 同目录>/sessions/index.json``（索引）+
  ``sessions/<id>.json``（每个会话的完整消息），由下面的 ``ChatSessionStore`` 拥有；
- **单会话（旧，CLI ``pr-review chat``）**：``chat_session.json``，即本模块顶部的
  ``load_chat_session`` / ``save_chat_session`` / ``clear_chat_session``。

旧文件在 TUI 后端首次启动时**迁移**为 legacy 会话（见 ``ChatSessionStore.migrate_legacy``），
迁移只读不改：CLI 仍按原样使用它。代价是迁移之后两边各写各的（CLI 写旧文件、TUI 写
``sessions/``），互相看不到对方的**新**对话——见 docs/claude-sessions-compaction.md §5.8。
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_pr_review.config import resolve_config_path

# 多会话存储（契约 v1）。目录名/id 前缀都是**对外可见**的（用户手册与验收脚本都按它们写），
# 改动等于改协议。
SESSIONS_DIRNAME = "sessions"
SESSIONS_INDEX_NAME = "index.json"
SESSION_ID_PREFIX = "s"
# 会话 id 只允许 ASCII 单调短码（`s1`、`s2`…）：与 bus 的 `[A-Za-z0-9_-]` 同口径，
# 不把 UUID 暴露给用户；显示一律用标题。
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
# 标题默认 = 首条用户消息截断 40 字（契约 v1）。
SESSION_TITLE_LIMIT = 40
# 迁移过来的旧会话标题（opencode 的用户手册按这个名字写）。
LEGACY_SESSION_TITLE = "legacy"
# 标题来源：auto = 由首条用户消息生成；user = 用户 rename 过（此后不再被自动覆盖）。
TITLE_SOURCE_AUTO = "auto"
TITLE_SOURCE_USER = "user"


def chat_session_path(config_path: Path | None) -> Path:
    return resolve_config_path(config_path).parent / "chat_session.json"


def sessions_dir(config_path: Path | None) -> Path:
    """多会话目录（``<config 同目录>/sessions``）。"""
    return resolve_config_path(config_path).parent / SESSIONS_DIRNAME


def sessions_index_path(config_path: Path | None) -> Path:
    return sessions_dir(config_path) / SESSIONS_INDEX_NAME


def session_file_path(config_path: Path | None, session_id: str) -> Path:
    """某个会话的消息文件。id 来自索引/扫描，仍先过一遍白名单再拼路径。

    id 是会被写进磁盘文件名的字符串；一旦上游（手改的 index.json）塞进 ``../``
    这类片段，拼路径就等于让配置文件决定往哪儿写。非法 id 一律拒绝。
    """
    if not SESSION_ID_PATTERN.match(session_id):
        raise ValueError(f"Invalid session id: {session_id!r}")
    return sessions_dir(config_path) / f"{session_id}.json"


def chat_context_path(config_path: Path | None) -> Path:
    """ChatContext 持久化路径"""
    return resolve_config_path(config_path).parent / "chat_context.json"


def _sanitize_messages(payload: object) -> list[dict[str, Any]]:
    """把任意 JSON 载荷归一成消息列表（不认识的东西**丢掉**，不抛）。

    格式：`[{"role", "content", "timestamp"[, "duration_seconds"]}, …]`；角色不做白名单，
    因为存量文件里出现过 `system`（压缩摘要）这类角色，过滤掉它们等于静默丢历史。
    """
    if not isinstance(payload, list):
        return []
    messages: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if isinstance(role, str) and isinstance(content, str):
            message: dict[str, Any] = {"role": role, "content": content}
            timestamp = item.get("timestamp")
            duration_seconds = item.get("duration_seconds")
            if isinstance(timestamp, str):
                message["timestamp"] = timestamp
            if isinstance(duration_seconds, (int, float)):
                message["duration_seconds"] = float(duration_seconds)
            messages.append(message)
    return messages


def load_chat_session(config_path: Path | None) -> list[dict[str, Any]]:
    """读取落盘的对话历史；读不到/读坏了都返回 `[]`（绝不抛）。

    格式：`[{"role", "content", "timestamp"[, "duration_seconds"]}, …]`。CLI 的
    `pr-review chat` 与 TUI 后端（`JsonlBackend`）共用这一份文件，因此两边的消息
    形状必须一致：新增字段只能加可选字段，且必须容忍旧文件缺字段。
    """
    session_path = chat_session_path(config_path)
    if not session_path.exists():
        return []
    try:
        payload = json.loads(session_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # 坏文件/读不动都当作"没有历史"：恢复会话失败不该让调用方（聊天循环、
        # 后端启动路径）跟着失败，更不该把半截历史喂给模型。
        return []
    return _sanitize_messages(payload)


def save_chat_session(config_path: Path | None, messages: list[dict[str, Any]]) -> None:
    session_path = chat_session_path(config_path)
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_chat_session(config_path: Path | None) -> None:
    session_path = chat_session_path(config_path)
    if session_path.exists():
        session_path.unlink()


def load_chat_context(config_path: Path | None) -> dict[str, Any] | None:
    """加载 ChatContext"""
    context_path = chat_context_path(config_path)
    if not context_path.exists():
        return None
    try:
        payload = json.loads(context_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except (json.JSONDecodeError, OSError):
        pass
    return None


def save_chat_context(config_path: Path | None, context: dict[str, Any]) -> None:
    """保存 ChatContext"""
    context_path = chat_context_path(config_path)
    context_path.parent.mkdir(parents=True, exist_ok=True)

    # 添加保存时间戳
    context_with_meta = dict(context)
    context_with_meta["_saved_at"] = datetime.now().isoformat()

    context_path.write_text(
        json.dumps(context_with_meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def clear_chat_context(config_path: Path | None) -> None:
    """清除 ChatContext"""
    context_path = chat_context_path(config_path)
    if context_path.exists():
        context_path.unlink()


# ---------------------------------------------------------------------------
# 多会话存储（契约 v1 §A）
# ---------------------------------------------------------------------------


def _session_now() -> str:
    """会话时间戳：ISO-8601 UTC（秒精度）。

    秒精度是**有意的**：`updated_at` 既给用户看也用于排序，同一秒内建的多个会话靠
    id 序号做次级键（见 `ChatSessionStore._sorted`），不会因为浮点/时区写法漂移。
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _session_order(session_id: str) -> int:
    """id 里的序号（`s12` → 12）；不认识的形态返回 0（只影响同秒排序）。"""
    match = re.search(r"(\d+)$", session_id or "")
    return int(match.group(1)) if match else 0


def default_session_title(messages: list[dict[str, Any]]) -> str:
    """契约 v1：标题默认 = **首条用户消息**截断 40 字。

    空白折叠后再截断（消息里带换行时列表会被撑成多行）；没有用户消息时返回空串，
    由协议层决定占位文案。
    """
    for message in messages:
        if str(message.get("role", "")) != "user":
            continue
        content = " ".join(str(message.get("content", "")).split())
        if content:
            return content[:SESSION_TITLE_LIMIT]
    return ""


def placeholder_session_title() -> str:
    """新建会话的**占位标题**（本地时间）：此时还没有用户消息可摘要。

    2026-09-27 用户实测反馈：新建后标题为空，会话列表里是一整片空白行——
    看起来像"没有会话/没有命名"。给一个带时间的占位，`save()` 在首条用户消息
    出现后会把它替换成消息摘要（`title_source` 保持 `auto`，用户 rename 的不动）。
    """
    return f"新会话 · {datetime.now().strftime('%H:%M')}"


def _atomic_write_json(path: Path, payload: Any) -> None:
    """tempfile + fsync + `os.replace` 原子写（沿用 `AppConfig.save` 的模式）。

    直接 `write_text` 在断电/被中断时会留下半截 JSON；索引坏掉还能靠目录扫描自愈，
    会话文件坏了就是真丢历史。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        # 失败的临时文件必须清掉：`sessions/` 目录会被扫描，留下垃圾会被当成会话。
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _warn(message: str) -> None:
    """会话层的告警一律走 stderr——stdout 是 JSONL 协议通道，不能混进任何一行。"""
    print(message, file=sys.stderr, flush=True)


class ChatSessionStore:
    """`sessions/index.json` + `sessions/<id>.json` 的读写。

    设计要点（docs/claude-sessions-compaction.md §1）：

    - **单一真源**：会话文件是真相，索引只是缓存。写入顺序永远是"先会话文件、后索引"，
      因此索引**可能落后**；落后的部分由下一轮 `_load_records` 按目录扫描补齐（自愈）。
    - **删除类操作先读后写**：索引写失败不影响已落盘的会话文件，最多是索引滞后。
    - **读路径绝不抛**：坏文件 = 那一条被剔除（并告警），其它会话照常可用。
    """

    def __init__(self, config_path: Path | None) -> None:
        self.config_path = config_path

    # -- 路径 ---------------------------------------------------------------

    @property
    def directory(self) -> Path:
        return sessions_dir(self.config_path)

    @property
    def index_path(self) -> Path:
        return sessions_index_path(self.config_path)

    # -- 索引读写 -----------------------------------------------------------

    def _read_index(self) -> dict[str, Any]:
        """读索引；缺失/坏掉/形状不对都返回 `{}`（随后由扫描自愈）。"""
        path = self.index_path
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            _warn(f"chat sessions index unreadable ({exc.__class__.__name__}: {exc}); rescanning")
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_index(
        self,
        records: list[dict[str, Any]],
        *,
        current: str,
        counter: int,
        legacy_imported: bool,
    ) -> None:
        """写索引；失败只告警（会话文件已经落盘，下一轮扫描会把索引补齐）。"""
        payload = {
            "version": 1,
            "current": current,
            "counter": counter,
            "legacy_imported": legacy_imported,
            "sessions": [
                {
                    "id": record["id"],
                    "title": record["title"],
                    "title_source": record["title_source"],
                    "created_at": record["created_at"],
                    "updated_at": record["updated_at"],
                    "message_count": record["message_count"],
                    "source": record["source"],
                }
                for record in records
            ],
        }
        try:
            _atomic_write_json(self.index_path, payload)
        except OSError as exc:
            _warn(
                f"chat sessions index save failed ({exc.__class__.__name__}: {exc}); "
                "it will be rebuilt from the sessions directory next time"
            )

    def _record_from_file(self, path: Path) -> dict[str, Any] | None:
        """从会话文件重建一条索引记录；读不动返回 `None`（调用方剔除）。"""
        session_id = path.stem
        if not SESSION_ID_PATTERN.match(session_id):
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            _warn(
                f"chat session file unreadable ({path.name}: {exc.__class__.__name__}); "
                "dropping it from the session list"
            )
            return None
        if not isinstance(payload, dict):
            return None
        messages = _sanitize_messages(payload.get("messages"))
        title = str(payload.get("title", "") or "")
        created_at = str(payload.get("created_at", "") or "") or _session_now()
        updated_at = str(payload.get("updated_at", "") or "") or created_at
        run_id = payload.get("current_run_id")
        return {
            "id": session_id,
            "title": title,
            "title_source": str(payload.get("title_source", "") or TITLE_SOURCE_AUTO),
            "created_at": created_at,
            "updated_at": updated_at,
            "message_count": len(messages),
            "current_run_id": str(run_id) if run_id else None,
            "source": str(payload.get("source", "") or "new"),
        }

    def _refresh_record(
        self, records: list[dict[str, Any]], session_id: str
    ) -> list[dict[str, Any]]:
        """写盘之后把这条会话的索引记录从**文件**重读一遍（其余记录原样）。

        索引是缓存、文件是真相（见类文档），但 `_load_records` 只对"索引里没有的会话文件"
        做扫描：一条**已在索引里**的会话改了标题/消息数之后，不重读就还是旧值——于是
        `_write_index(records)` 会把刚写进文件的标题又按旧索引覆盖回去，`session.list`
        永远看不到新标题与新消息数。修法是写完之后按 id 换掉这一条。
        """
        fresh = self._record_from_file(session_file_path(self.config_path, session_id))
        if fresh is None:
            return records
        return [fresh if record["id"] == session_id else record for record in records]

    @staticmethod
    def _sorted(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """契约 v1：`updated_at` 降序；同一秒再按 id 序号降序（新建的排前面）。"""
        return sorted(
            records,
            key=lambda record: (record["updated_at"], _session_order(record["id"])),
            reverse=True,
        )

    def _load_records(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """索引 ∪ 目录扫描 → 有效记录（降序）+ 索引元信息；顺带自愈。

        自愈的三条分支（codex 验收用例 3）：
        1. 索引缺失/损坏 → 全量扫描重建；
        2. 索引落后（有会话文件不在索引里）→ 补进来；
        3. 索引超前（引用的会话文件已被删）→ 剔除该条，并把它从 `current` 上摘掉。
        """
        index = self._read_index()
        records: dict[str, dict[str, Any]] = {}
        repaired = not index
        raw_sessions = index.get("sessions")
        if isinstance(raw_sessions, list):
            for item in raw_sessions:
                if not isinstance(item, dict):
                    continue
                session_id = str(item.get("id", "") or "")
                if not SESSION_ID_PATTERN.match(session_id):
                    continue
                try:
                    path = session_file_path(self.config_path, session_id)
                except ValueError:
                    continue
                if not path.exists():
                    # 索引超前：文件没了 → 剔除（用例 3 的"被剔除"分支）。
                    _warn(f"chat session {session_id} referenced by the index is missing")
                    repaired = True
                    continue
                records[session_id] = {
                    "id": session_id,
                    "title": str(item.get("title", "") or ""),
                    "title_source": str(item.get("title_source", "") or TITLE_SOURCE_AUTO),
                    "created_at": str(item.get("created_at", "") or ""),
                    "updated_at": str(item.get("updated_at", "") or ""),
                    "message_count": int(item.get("message_count") or 0),
                    "current_run_id": item.get("current_run_id") or None,
                    "source": str(item.get("source", "") or "new"),
                }
        for path in sorted(self.directory.glob("*.json")) if self.directory.exists() else []:
            if path.name == SESSIONS_INDEX_NAME:
                continue
            session_id = path.stem
            if session_id in records:
                continue
            if not SESSION_ID_PATTERN.match(session_id):
                continue
            # 索引落后：目录里有、索引里没有 → 从文件补齐（用例 3 的"扫描修复"分支）。
            record = self._record_from_file(path)
            if record is None:
                repaired = True
                continue
            records[session_id] = record
            repaired = True
        ordered = self._sorted(list(records.values()))
        current = str(index.get("current", "") or "")
        if current and current not in records:
            # 当前会话被删/文件丢失：切到最近一个（没有就置空），绝不留下悬空 id。
            current = ordered[0]["id"] if ordered else ""
            repaired = True
        elif not current and ordered:
            # 索引整个丢了（被手删/写坏）后重建：没有"当前会话"的记忆可用，按同一条规则
            # 指向最近的会话。留空会让 TUI 起来后没有活动会话，而用户明明有历史。
            current = ordered[0]["id"]
            repaired = True
        counter = index.get("counter")
        counter = int(counter) if isinstance(counter, int) and counter >= 0 else 0
        counter = max([counter, *(_session_order(record["id"]) for record in ordered)], default=0)
        legacy_imported = bool(index.get("legacy_imported", False))
        if repaired:
            self._write_index(
                ordered,
                current=current,
                counter=counter,
                legacy_imported=legacy_imported,
            )
        return ordered, {
            "current": current,
            "counter": counter,
            "legacy_imported": legacy_imported,
        }

    # -- 对外读接口 ---------------------------------------------------------

    def records(self) -> list[dict[str, Any]]:
        return self._load_records()[0]

    def current_id(self) -> str:
        return str(self._load_records()[1]["current"])

    def get(self, session_id: str) -> dict[str, Any] | None:
        """完整会话载荷（含 messages）；不存在/读不动返回 `None`。"""
        try:
            path = session_file_path(self.config_path, session_id)
        except ValueError:
            return None
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(payload, dict):
            return None
        record = self._record_from_file(path)
        if record is None:
            return None
        return {**record, "messages": _sanitize_messages(payload.get("messages"))}

    # -- 写接口 -------------------------------------------------------------

    def _write_session(self, payload: dict[str, Any]) -> None:
        _atomic_write_json(session_file_path(self.config_path, str(payload["id"])), payload)

    def create(
        self,
        *,
        title: str = "",
        title_source: str = TITLE_SOURCE_AUTO,
        source: str = "new",
        messages: list[dict[str, Any]] | None = None,
        run_id: str | None = None,
        make_current: bool = True,
    ) -> dict[str, Any]:
        """新建会话并（默认）切换过去；返回完整载荷。"""
        records, meta = self._load_records()
        used = {_session_order(record["id"]) for record in records}
        counter = int(meta["counter"])
        while True:
            counter += 1
            if counter not in used:
                break
        session_id = f"{SESSION_ID_PREFIX}{counter}"
        messages = messages or []
        now = _session_now()
        payload = {
            "id": session_id,
            "title": title or default_session_title(messages) or placeholder_session_title(),
            "title_source": title_source,
            "created_at": now,
            "updated_at": now,
            "message_count": len(messages),
            "current_run_id": run_id,
            "source": source,
            "messages": messages,
        }
        self._write_session(payload)
        updated = [*records, payload]
        self._write_index(
            self._sorted(updated),
            current=session_id if make_current else meta["current"],
            counter=counter,
            legacy_imported=bool(meta["legacy_imported"]),
        )
        return payload

    def switch(self, session_id: str) -> dict[str, Any] | None:
        """把 `current` 指向目标会话；返回完整载荷（不存在返回 `None`）。"""
        payload = self.get(session_id)
        if payload is None:
            return None
        records, meta = self._load_records()
        self._write_index(
            records,
            current=session_id,
            counter=int(meta["counter"]),
            legacy_imported=bool(meta["legacy_imported"]),
        )
        return payload

    def rename(self, session_id: str, title: str) -> dict[str, Any] | None:
        """改标题。改过之后 `title_source` 变成 user，自动生成不再覆盖它。"""
        payload = self.get(session_id)
        if payload is None:
            return None
        payload["title"] = title
        payload["title_source"] = TITLE_SOURCE_USER
        payload["updated_at"] = _session_now()
        self._write_session(payload)
        records, meta = self._load_records()
        self._write_index(
            self._sorted(self._refresh_record(records, session_id)),
            current=str(meta["current"]),
            counter=int(meta["counter"]),
            legacy_imported=bool(meta["legacy_imported"]),
        )
        return {"id": session_id, "title": title}

    def delete(self, session_id: str) -> tuple[str, str | None] | None:
        """删除会话，返回 `(被删 id, 新的 current)`；不存在返回 `None`。

        删当前会话时**自动切到最近一个**（契约 v1）：否则全链路会进入"无会话"态——
        `chat.send` 全部 not_found，而界面上什么提示都没有。
        """
        try:
            path = session_file_path(self.config_path, session_id)
        except ValueError:
            # 非法 id（`../x` 之类）与"不存在"对外同义：都不是可删的会话。
            # 与 `get()` 同一口径——不能让协议层看到一个内部 ValueError。
            return None
        records, meta = self._load_records()
        if session_id not in {record["id"] for record in records}:
            return None
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            _warn(f"chat session delete failed ({exc.__class__.__name__}: {exc})")
            return None
        remaining = [record for record in records if record["id"] != session_id]
        current = str(meta["current"])
        if current == session_id:
            current = remaining[0]["id"] if remaining else ""
        self._write_index(
            remaining,
            current=current,
            counter=int(meta["counter"]),
            legacy_imported=bool(meta["legacy_imported"]),
        )
        return session_id, (current or None)

    def save(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        *,
        run_id: str | None = None,
    ) -> dict[str, Any] | None:
        """落盘某个会话的消息（每轮 chat 之后调用）。

        索引里的标题只在"还没有标题"时按首条用户消息补一次；用户 rename 过的标题
        （`title_source=user`）永不被覆盖。
        """
        payload = self.get(session_id)
        if payload is None:
            return None
        title = str(payload.get("title", "") or "")
        title_source = str(payload.get("title_source", "") or TITLE_SOURCE_AUTO)
        if title_source != TITLE_SOURCE_USER:
            # auto 来源：首条用户消息出现后用消息摘要**覆盖占位标题**
            # （`placeholder_session_title` 的"新会话 · HH:MM"）；后续轮次重算为同值。
            # 用户 rename 过的（`title_source=user`）永不动。
            auto_title = default_session_title(messages)
            if auto_title:
                title = auto_title
        payload.update(
            {
                "title": title,
                "title_source": title_source,
                "updated_at": _session_now(),
                "message_count": len(messages),
                "current_run_id": run_id,
                "messages": messages,
            }
        )
        self._write_session(payload)
        records, meta = self._load_records()
        self._write_index(
            self._sorted(self._refresh_record(records, session_id)),
            current=str(meta["current"] or session_id),
            counter=int(meta["counter"]),
            legacy_imported=bool(meta["legacy_imported"]),
        )
        return payload

    def migrate_legacy(self) -> dict[str, Any] | None:
        """把旧 `chat_session.json` 迁移成 legacy 会话（只读旧文件，绝不改它）。

        三种情况直接跳过：文件不存在/读不出消息、索引里已经有一条 legacy 会话、
        索引标记过 `legacy_imported`（用户可能已把那条会话删了，不该再长回来）。
        任何异常都只告警——**迁移失败不能挡启动**（方案 §A6）。
        """
        try:
            legacy_path = chat_session_path(self.config_path)
            if not legacy_path.exists():
                return None
            try:
                payload = json.loads(legacy_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                _warn(
                    f"legacy chat session migration skipped " f"({exc.__class__.__name__}: {exc})"
                )
                return None
            messages = _sanitize_messages(payload)
            if not messages:
                return None
            records, meta = self._load_records()
            if meta["legacy_imported"] or any(record["source"] == "legacy" for record in records):
                return None
            now = _session_now()
            created = self.create(
                title=LEGACY_SESSION_TITLE,
                title_source=TITLE_SOURCE_USER,
                source="legacy",
                messages=messages,
                make_current=not meta["current"],
            )
            records, meta = self._load_records()
            self._write_index(
                records,
                current=str(meta["current"]),
                counter=int(meta["counter"]),
                legacy_imported=True,
            )
            _warn(
                f"legacy chat session migrated to {created['id']} "
                f"({len(messages)} messages, {now})"
            )
            return created
        except Exception as exc:  # 迁移失败绝不阻塞启动
            _warn(f"legacy chat session migration failed ({exc.__class__.__name__}: {exc})")
            return None
