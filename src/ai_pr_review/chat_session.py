"""Chat 会话持久化辅助函数。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_pr_review.config import resolve_config_path


def chat_session_path(config_path: Path | None) -> Path:
    return resolve_config_path(config_path).parent / "chat_session.json"


def load_chat_session(config_path: Path | None) -> list[dict[str, Any]]:
    session_path = chat_session_path(config_path)
    if not session_path.exists():
        return []
    try:
        payload = json.loads(session_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
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


def save_chat_session(config_path: Path | None, messages: list[dict[str, Any]]) -> None:
    session_path = chat_session_path(config_path)
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_chat_session(config_path: Path | None) -> None:
    session_path = chat_session_path(config_path)
    if session_path.exists():
        session_path.unlink()
