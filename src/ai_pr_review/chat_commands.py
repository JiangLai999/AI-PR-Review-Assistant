"""Chat slash command 辅助逻辑。"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ai_pr_review.config import AppConfig
from ai_pr_review.services.result_store import ResultStore


def build_chat_help_text() -> str:
    return (
        "/help - 显示可用聊天命令\n"
        "/config - 显示当前会话配置\n"
        "/session - 显示当前 chat 会话信息\n"
        "/history [limit] - 显示最近 N 条审查历史\n"
        "/stats - 显示审查统计\n"
        "/model <模型ID> - 仅本次会话切换模型\n"
        "/review <PR_URL> - 在当前会话中运行 PR 审查\n"
        "/clear - 清空当前会话历史\n"
        "/exit - 退出聊天"
    )


def render_chat_session(config: AppConfig, config_path: Path | None, messages: list[dict[str, Any]], layout: str) -> str:
    return json.dumps(
        {
            "provider": config.ai_client.provider,
            "model": config.ai_client.model,
            "response_language": config.preferences.language,
            "layout": layout,
            "message_count": len(messages),
            "session_path": str(config_path) if config_path is not None else None,
        },
        ensure_ascii=False,
        indent=2,
    )


def render_history_table(runs: list[dict[str, Any]]) -> Table:
    table = Table(box=None, expand=True)
    table.add_column("Run ID", style="cyan")
    table.add_column("PR")
    table.add_column("Model")
    table.add_column("Findings", justify="right")
    for run in runs:
        table.add_row(
            str(run.get("id", ""))[:8],
            str(run.get("pr_url", "")),
            str(run.get("model", "")),
            str(run.get("total_findings", 0)),
        )
    return table


def render_stats_table(stats: dict[str, Any]) -> Table:
    table = Table(box=None, expand=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value")
    for key in ("total_runs", "unique_prs", "total_findings", "total_cost", "latest_run_at"):
        table.add_row(key, str(stats.get(key, "")))
    return table


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
    if command == "/session":
        console.print(
            Panel(
                render_chat_session(config, config_path, messages, layout),
                title="Chat Session",
                border_style="green",
            )
        )
        return True
    if command == "/history":
        if argument:
            try:
                limit = max(1, int(argument))
            except ValueError:
                console.print("Usage: /history [limit]", style="bold red")
                return True
        else:
            limit = 5
        store = ResultStore(config.result_store)
        payload = store.list_runs(limit=limit)
        console.print(
            Panel(render_history_table(payload), title=f"History ({len(payload)})", border_style="green")
        )
        return True
    if command == "/stats":
        store = ResultStore(config.result_store)
        payload = store.get_statistics()
        console.print(
            Panel(render_stats_table(payload), title="Stats", border_style="green")
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
