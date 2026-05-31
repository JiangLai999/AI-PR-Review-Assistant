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
        "/help      - 显示可用聊天命令\n"
        "/status    - 显示当前会话状态\n"
        "/usage     - 显示 token 使用统计\n"
        "/compact   - 压缩会话历史\n"
        "/restore   - 恢复之前的会话记录\n"
        "/config    - 显示当前会话配置\n"
        "/session   - 显示当前 chat 会话信息\n"
        "/history [limit] - 显示最近 N 条审查历史\n"
        "/stats     - 显示审查统计\n"
        "/model <模型ID> - 仅本次会话切换模型\n"
        "/review <PR_URL> - 在当前会话中运行 PR 审查\n"
        "/clear     - 清空当前会话历史\n"
        "/exit      - 退出聊天"
    )


def render_chat_session(
    config: AppConfig, config_path: Path | None, messages: list[dict[str, Any]], layout: str
) -> str:
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
    load_session: Callable[[Path | None], list[dict[str, Any]]],
    set_active_model: Callable[[AppConfig, str], None],
) -> bool:
    parts = command_text.split(maxsplit=1)
    command = parts[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else ""

    if command == "/help":
        console.print(Panel(build_chat_help_text(), title="Chat Commands", border_style="cyan"))
        return True
    if command == "/config":
        console.print(
            Panel(render_chat_config(config, layout), title="Chat Config", border_style="green")
        )
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
            Panel(
                render_history_table(payload),
                title=f"History ({len(payload)})",
                border_style="green",
            )
        )
        return True
    if command == "/stats":
        store = ResultStore(config.result_store)
        stats_payload: dict[str, Any] = store.get_statistics()
        console.print(Panel(render_stats_table(stats_payload), title="Stats", border_style="green"))
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
    if command == "/status":
        table = Table(box=None, expand=True, show_header=False)
        table.add_column("Key", style="bold cyan", width=16)
        table.add_column("Value")
        table.add_row("Provider", config.provider.display_name or config.ai_client.provider)
        table.add_row("Model", config.ai_client.model)
        table.add_row("Base URL", config.ai_client.base_url or "default")
        table.add_row("Language", config.preferences.language)
        table.add_row("Messages", str(len(messages)))
        table.add_row("Session", str(config_path) if config_path else "memory")
        console.print(Panel(table, title="Session Status", border_style="cyan"))
        return True
    if command == "/usage":
        total_chars = sum(len(m.get("content", "")) for m in messages)
        user_msgs = sum(1 for m in messages if m.get("role") == "user")
        assistant_msgs = sum(1 for m in messages if m.get("role") == "assistant")
        table = Table(box=None, expand=True, show_header=False)
        table.add_column("Metric", style="bold cyan", width=16)
        table.add_column("Value")
        table.add_row("Total Messages", str(len(messages)))
        table.add_row("User Messages", str(user_msgs))
        table.add_row("Assistant Messages", str(assistant_msgs))
        table.add_row("Total Characters", str(total_chars))
        console.print(Panel(table, title="Usage Statistics", border_style="green"))
        return True
    if command == "/compact":
        if len(messages) <= 2:
            console.print("会话历史已经很短，无需压缩。", style="yellow")
            return True
        original_count = len(messages)
        first_msg = messages[0] if messages else None
        last_msgs = messages[-4:] if len(messages) >= 4 else messages
        messages.clear()
        if first_msg:
            messages.append(first_msg)
        messages.extend(last_msgs)
        removed = original_count - len(messages)
        console.print(
            f"已压缩会话：移除 {removed} 条消息，保留 {len(messages)} 条。", style="green"
        )
        return True
    if command == "/restore":
        loaded = load_session(config_path)
        if not loaded:
            console.print("没有找到历史会话记录。", style="yellow")
            return True
        messages.clear()
        messages.extend(loaded)
        console.print(f"已恢复 {len(messages)} 条历史消息。", style="green")
        return True
    return False
