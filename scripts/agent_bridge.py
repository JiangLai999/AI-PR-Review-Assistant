"""Small file-based collaboration bus for local coding agents.

The bus deliberately does not transmit credentials or start arbitrary commands. Agents
claim a task by atomically creating a lock, read the immutable task JSON, and write a
structured report to the matching reports directory. Codex remains the integration
owner.

Hardening notes (see docs/claude-tui-audit.md F5/F6/F12):

* every state file is written with ``tempfile`` + ``os.replace`` + ``fsync``;
* locks carry ``claimed_at`` and are reclaimable after ``LOCK_TTL_SECONDS``;
* ``report`` enforces a status machine instead of allowing silent rollbacks;
* ``task_id`` is restricted to ``[A-Za-z0-9_-]{1,64}`` so it cannot escape the bus.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BUS = ROOT / ".agent-bus"
TASKS = BUS / "tasks"
REPORTS = BUS / "reports"
LOCKS = BUS / "locks"
SCHEMA_VERSION = 1

TASK_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
LOCK_TTL_SECONDS = 6 * 60 * 60
TERMINAL_STATUSES = frozenset({"completed", "blocked", "needs-review"})
# A report may be re-sent while the task is still open, but never once it is done.
REPORTABLE_STATUSES = frozenset({"claimed", "blocked", "needs-review"})
_GITIGNORE = "tasks/\nreports/\nlocks/\n"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def validate_task_id(task_id: str) -> str:
    if not TASK_ID_PATTERN.fullmatch(task_id or ""):
        raise SystemExit("invalid task id: use 1-64 characters from A-Z, a-z, 0-9, '_' and '-'")
    return task_id


def task_path(task_id: str) -> Path:
    return TASKS / f"{task_id}.json"


def report_path(task_id: str) -> Path:
    return REPORTS / f"{task_id}.json"


def lock_path(task_id: str) -> Path:
    return LOCKS / f"{task_id}.lock"


def ensure_bus() -> None:
    for path in (TASKS, REPORTS, LOCKS):
        path.mkdir(parents=True, exist_ok=True)
    gitignore = BUS / ".gitignore"
    try:
        current = gitignore.read_text(encoding="utf-8")
    except OSError:
        current = ""
    # Idempotent: rewriting on every command churned mtime for no reason.
    if current != _GITIGNORE:
        gitignore.write_text(_GITIGNORE, encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any], *, exclusive: bool = False) -> None:
    """Write JSON atomically.

    ``exclusive=True`` claims a name that must not exist yet (a lock), so it keeps
    ``O_CREAT | O_EXCL``: two agents can never both win the same lock. Everything
    else goes through a temp file + ``os.replace`` so a crash cannot leave half a
    JSON document behind for the next reader to trip over.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if exclusive:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        return
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def read_json(path: Path, *, kind: str) -> dict[str, Any]:
    """Read a JSON object, turning every failure into an actionable message."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SystemExit(f"{kind} not found: {path}") from exc
    except OSError as exc:
        raise SystemExit(f"{kind} unreadable ({path}): {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{kind} is corrupt ({path}): {exc}. Delete the file to recover.") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"{kind} must be a JSON object: {path}")
    return payload


def read_lock(path: Path) -> dict[str, Any] | None:
    """Return the lock payload, or ``None`` when it is missing or unreadable."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def lock_is_stale(lock: dict[str, Any]) -> bool:
    claimed_at = parse_timestamp(str(lock.get("claimed_at", "")))
    if claimed_at is None:
        return True
    return datetime.now(timezone.utc) - claimed_at > timedelta(seconds=LOCK_TTL_SECONDS)


def dispatch(agent: str, task_id: str, objective: str, scope: list[str], prompt: str) -> None:
    ensure_bus()
    validate_task_id(task_id)
    task = {
        "schema": SCHEMA_VERSION,
        "task_id": task_id,
        "agent": agent,
        "status": "pending",
        "created_at": now(),
        "created_by": "codex",
        "objective": objective,
        "write_scope": scope,
        "prompt": prompt,
        "constraints": [
            "Do not read, print, transmit, or modify credentials or private session logs.",
            "Do not reset, clean, commit, or push the repository.",
            "Do not edit files outside write_scope; read-only audits must not edit source.",
            "Report exact commands, paths, evidence, and unresolved uncertainty.",
        ],
    }
    path = task_path(task_id)
    try:
        write_json(path, task, exclusive=True)
    except FileExistsError as exc:
        raise SystemExit(f"task already exists: {task_id}") from exc
    print(json.dumps({"task_id": task_id, "path": str(path)}, ensure_ascii=False))


def claim(agent: str, task_id: str) -> None:
    ensure_bus()
    validate_task_id(task_id)
    path = task_path(task_id)
    task = read_json(path, kind="task")
    owner = str(task.get("agent", ""))
    if owner != agent:
        raise SystemExit(f"task belongs to {owner}, not {agent}")
    if str(task.get("status", "")) == "completed":
        raise SystemExit(f"task already completed: {task_id}")

    lock_file = lock_path(task_id)
    if lock_file.exists():
        existing = read_lock(lock_file)
        holder = str(existing.get("agent", "?")) if existing is not None else "unknown"
        if existing is not None and not lock_is_stale(existing):
            raise SystemExit(
                f"task already claimed by {holder} at {existing.get('claimed_at')}; "
                f"use `release` if the holder is gone, or wait for the {LOCK_TTL_SECONDS}s TTL"
            )
        print(
            f"reclaiming stale lock for {task_id} (previous holder: {holder})",
            file=sys.stderr,
        )
        lock_file.unlink(missing_ok=True)

    lock = {
        "task_id": task_id,
        "agent": agent,
        "host": socket.gethostname(),
        "claimed_at": now(),
    }
    try:
        write_json(lock_file, lock, exclusive=True)
    except FileExistsError as exc:
        raise SystemExit(f"task already claimed: {task_id}") from exc
    task["status"] = "claimed"
    task["agent"] = agent
    task["claimed_at"] = lock["claimed_at"]
    write_json(path, task)
    print(json.dumps(task, ensure_ascii=False, indent=2))


def release(agent: str, task_id: str, *, force: bool = False) -> None:
    """Drop a lock so a crashed claim cannot block the task forever."""
    ensure_bus()
    validate_task_id(task_id)
    path = task_path(task_id)
    task = read_json(path, kind="task")
    lock_file = lock_path(task_id)
    lock = read_lock(lock_file)
    holder = str(lock.get("agent", "")) if lock is not None else ""
    if lock_file.exists() and holder and holder != agent and not force:
        raise SystemExit(f"lock is held by {holder}; pass --force to release it anyway")
    lock_file.unlink(missing_ok=True)
    if str(task.get("status", "")) == "claimed":
        task["status"] = "pending"
        task["released_at"] = now()
        write_json(path, task)
    print(
        json.dumps(
            {"task_id": task_id, "released": True, "status": task.get("status", "")},
            ensure_ascii=False,
        )
    )


def report(
    agent: str,
    task_id: str,
    status: str,
    summary: str,
    evidence: list[str],
    blockers: list[str],
) -> None:
    ensure_bus()
    validate_task_id(task_id)
    if status not in TERMINAL_STATUSES:
        raise SystemExit(f"unsupported status: {status}")
    path = task_path(task_id)
    task = read_json(path, kind="task")
    if str(task.get("agent", "")) != agent:
        raise SystemExit("agent does not own this task")
    current = str(task.get("status", ""))
    if current == "completed":
        raise SystemExit(f"task already completed; refusing to rewrite it as {status}")
    if current not in REPORTABLE_STATUSES:
        raise SystemExit(
            f"task must be claimed before reporting (current status: {current or 'unknown'})"
        )
    payload = {
        "schema": SCHEMA_VERSION,
        "task_id": task_id,
        "agent": agent,
        "status": status,
        "reported_at": now(),
        "summary": summary,
        "evidence": evidence,
        "blockers": blockers,
    }
    write_json(report_path(task_id), payload)
    task["status"] = status
    task["reported_at"] = payload["reported_at"]
    write_json(path, task)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> int:
    # Windows consoles default to GBK; task JSON and summaries carry Chinese.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # pragma: no cover - best effort on odd streams
        pass
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    d = sub.add_parser("dispatch")
    # 协作执行器：claude / mimo / codex(GLM) / opencode(MiMo-V2.6-Flash-Free) /
    # workbuddy（WorkBuddy 自带 codebuddy headless CLI；模型走账号默认，可用
    # WORKBUDDY_MODEL 环境变量覆盖）
    d.add_argument(
        "--agent",
        choices=("claude", "mimo", "codex", "opencode", "workbuddy"),
        required=True,
    )
    d.add_argument("--task-id", default=None)
    d.add_argument("--objective", required=True)
    d.add_argument("--scope", action="append", default=[])
    d.add_argument("--prompt", required=True)
    c = sub.add_parser("claim")
    c.add_argument("--agent", required=True)
    c.add_argument("task_id")
    rel = sub.add_parser("release")
    rel.add_argument("--agent", required=True)
    rel.add_argument("--force", action="store_true")
    rel.add_argument("task_id")
    r = sub.add_parser("report")
    r.add_argument("--agent", required=True)
    r.add_argument("--status", choices=sorted(TERMINAL_STATUSES), required=True)
    r.add_argument("--summary", required=True)
    r.add_argument("--evidence", action="append", default=[])
    r.add_argument("--blocker", dest="blockers", action="append", default=[])
    r.add_argument("task_id")
    args = parser.parse_args()
    if args.command == "init":
        ensure_bus()
        print(BUS)
    elif args.command == "dispatch":
        dispatch(
            args.agent,
            args.task_id or f"{args.agent}-{uuid.uuid4().hex[:10]}",
            args.objective,
            args.scope,
            args.prompt,
        )
    elif args.command == "claim":
        claim(args.agent, args.task_id)
    elif args.command == "release":
        release(args.agent, args.task_id, force=args.force)
    else:
        report(args.agent, args.task_id, args.status, args.summary, args.evidence, args.blockers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
