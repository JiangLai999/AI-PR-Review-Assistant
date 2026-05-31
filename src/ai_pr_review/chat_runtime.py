"""Chat 运行时辅助函数。"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from ai_pr_review.config import AppConfig


def _render_status_bar(config: AppConfig, message_count: int, session_path: str | None) -> Panel:
    """渲染底部状态栏，显示 provider、model、消息数和会话路径。"""
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan", ratio=0)
    table.add_column(style="white", ratio=1)
    table.add_column(style="bold green", ratio=0)
    table.add_column(style="white", ratio=1)
    table.add_column(style="bold yellow", ratio=0)
    table.add_column(style="white", ratio=1)

    provider = config.provider.display_name or config.ai_client.provider
    model = config.ai_client.model
    path_display = session_path if session_path else "memory"

    table.add_row(
        "Provider",
        provider,
        "Model",
        model,
        "Messages",
        str(message_count),
    )

    return Panel(
        table,
        title="[bold white]Session Info[/bold white]",
        border_style="dim",
        padding=(0, 1),
    )


def _render_welcome(config: AppConfig, restored_count: int) -> Panel:
    """渲染欢迎面板，显示帮助提示和可用命令概览。"""
    help_text = Text()
    help_text.append("可用命令：\n", style="bold white")
    help_text.append("  /help", style="bold cyan")
    help_text.append("       显示所有聊天命令\n")
    help_text.append("  /status", style="bold cyan")
    help_text.append("      显示当前会话状态\n")
    help_text.append("  /usage", style="bold cyan")
    help_text.append("       显示 token 使用统计\n")
    help_text.append("  /compact", style="bold cyan")
    help_text.append("      压缩会话历史\n")
    help_text.append("  /review <URL>", style="bold cyan")
    help_text.append("  执行 PR 审查\n")
    help_text.append("  /model <ID>", style="bold cyan")
    help_text.append("    切换模型\n")
    help_text.append("  /clear", style="bold cyan")
    help_text.append("      清空会话\n")
    help_text.append("  /exit", style="bold cyan")
    help_text.append("       退出聊天\n")
    help_text.append("\n")
    help_text.append("直接输入 PR URL 也会自动触发审查。", style="dim")

    if restored_count > 0:
        help_text.append(f"\n\n已恢复 {restored_count} 条历史消息。", style="yellow")

    return Panel(
        help_text,
        title=f"[bold cyan]{config.provider.display_name} / {config.ai_client.model}[/bold cyan]",
        border_style="bright_blue",
        padding=(1, 2),
    )


def _spinner_frame(elapsed: float) -> str:
    """根据经过时间返回 spinner 帧。"""
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    idx = int(elapsed * 8) % len(frames)
    return frames[idx]


def run_chat_session(
    console: Console,
    *,
    config: AppConfig,
    config_path: Path | None,
    active_layout: str,
    message: str | None,
    load_session: Callable[[Path | None], list[dict[str, Any]]],
    save_session: Callable[[Path | None, list[dict[str, Any]]], None],
    chat_title: Callable[[AppConfig], str],
    print_chat_message: Callable[[Console, str, str], None],
    slash_handler: Callable[
        [Console, AppConfig, Path | None, list[dict[str, Any]], str, str], bool
    ],
    raw_command_handler: Callable[[str], bool],
    send_message: Callable[[list[dict[str, Any]], str], str],
) -> None:
    messages = load_session(config_path)
    session_path = str(config_path) if config_path is not None else None

    console.print()
    console.print(_render_welcome(config, len(messages)))
    console.print(_render_status_bar(config, len(messages), session_path))
    console.print()

    def send_once(user_text: str) -> None:
        messages.append({"role": "user", "content": user_text})
        print_chat_message(console, "You", user_text)

        start_time = time.time()
        answer = None
        try:
            with Live(
                console=console,
                refresh_per_second=12,
                transient=True,
            ) as live:
                while True:
                    elapsed = time.time() - start_time
                    spinner = _spinner_frame(elapsed)
                    live.update(Text(f"  {spinner} 正在思考... ({elapsed:.1f}s)", style="yellow"))
                    if elapsed > 0.3:
                        break
                answer = send_message(messages, user_text)
        except Exception:
            answer = send_message(messages, user_text)

        if not answer:
            messages.pop()
            console.print("  [dim](无回复)[/dim]")
            return

        messages.append({"role": "assistant", "content": answer})
        save_session(config_path, messages)
        print_chat_message(console, "Assistant", answer)
        console.print()
        console.print(_render_status_bar(config, len(messages), session_path))
        console.print()

    if message is not None:
        send_once(message)
        return

    while True:
        try:
            user_text = Prompt.ask("[bold green]You[/bold green]", console=console).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]退出聊天。[/dim]")
            break

        if user_text.lower() in {"/exit", "exit", "quit", "q"}:
            console.print("[dim]退出聊天。[/dim]")
            break
        if not user_text:
            continue
        if raw_command_handler(user_text):
            continue
        if user_text.startswith("/") and slash_handler(
            console, config, config_path, messages, user_text, active_layout
        ):
            continue
        send_once(user_text)
