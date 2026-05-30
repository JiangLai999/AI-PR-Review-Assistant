"""Chat slash command 辅助逻辑。"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel

from ai_pr_review.config import AppConfig
from ai_pr_review.services.result_store import ResultStore


def build_chat_help_text() -> str:
    return (
        "/help - 显示可用聊天命令\n"
        "/config - 显示当前会话配置\n"
        "/history - 显示最近 5 条审查历史\n"
        "/stats - 显示审查统计\n"
        "/model <模型ID> - 仅本次会话切换模型\n"
        "/review <PR_URL> - 在当前会话中运行 PR 审查\n"
        "/clear - 清空当前会话历史\n"
        "/exit - 退出聊天"
    )


def render_chat_config(config: AppConfig, layout: str) -> str:
    return json.dumps(
        {
            "provider": config.ai_client.provider,
            "model": config.ai_client.model,
            "base_url": config.ai_client.base_url,
            "response_language": config.preferences.language,
            "layout": layout,
        },
        ensure_ascii=False,
        indent=2,
    )


def handle_basic_chat_slash_command(
    console: Console,
    config: AppConfig,
    config_path: Path | None,
    messages: list[dict[str, Any]],
    command_text: str,
    layout: str,
    *,
    clear_session: Callable[[Path | None], None],
    set_active_model: Callable[[AppConfig, str], None],
) -> bool:
    parts = command_text.split(maxsplit=1)
    command = parts[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else ""

    if command == "/help":
        console.print(Panel(build_chat_help_text(), title="Chat Commands", border_style="cyan"))
        return True
    if command == "/config":
        console.print(Panel(render_chat_config(config, layout), title="Chat Config", border_style="green"))
        return True
    if command == "/history":
        store = ResultStore(config.result_store)
        payload = {"runs": store.list_runs(limit=5)}
        console.print(
            Panel(json.dumps(payload, ensure_ascii=False, indent=2), title="History", border_style="green")
        )
        return True
    if command == "/stats":
        store = ResultStore(config.result_store)
        payload = store.get_statistics()
        console.print(
            Panel(json.dumps(payload, ensure_ascii=False, indent=2), title="Stats", border_style="green")
        )
        return True
    if command == "/clear":
        messages.clear()
        clear_session(config_path)
        console.print("Conversation cleared.")
        return True
    if command == "/model":
        if not argument:
            console.print("Usage: /model <模型ID>", style="bold red")
            return True
        set_active_model(config, argument)
        console.print(f"Active model set to: {config.ai_client.model}")
        return True
    return False
