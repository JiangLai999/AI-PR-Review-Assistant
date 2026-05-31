"""Chat 运行时辅助函数。"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from ai_pr_review.config import AppConfig


def _render_status_bar(config: AppConfig, message_count: int, session_path: str | None) -> Panel:
    """渲染更紧凑的状态栏，参考 opencode 的底部信息结构。"""
    provider = config.provider.display_name or config.ai_client.provider
    model = config.ai_client.model
    layout = (
        config.preferences.chat_layout if hasattr(config.preferences, "chat_layout") else "split"
    )
    path_display = session_path if session_path else "memory"

    status = Text()
    status.append(" ● ", style="bold green")
    status.append("CONNECTED", style="bold green")
    status.append("   ")
    status.append("Provider", style="bold cyan")
    status.append(f" {provider}", style="white")
    status.append("   ")
    status.append("Model", style="bold magenta")
    status.append(f" {model}", style="white")
    status.append("   ")
    status.append("Layout", style="bold yellow")
    status.append(f" {layout}", style="white")
    status.append("   ")
    status.append("Messages", style="bold bright_blue")
    status.append(f" {message_count}", style="white")
    status.append("   ")
    status.append("Session", style="bold white")
    status.append(f" {path_display}", style="dim")

    return Panel(status, border_style="dim", padding=(0, 1))


def _render_brand_banner() -> Panel:
    """渲染顶部品牌横幅，增强产品感。"""
    banner = Text()
    banner.append("AI PR REVIEW", style="bold bright_cyan")
    banner.append("  terminal workspace", style="dim")
    banner.append("\n")
    banner.append("Code review  ", style="green")
    banner.append("|  ", style="dim")
    banner.append("Chat workspace  ", style="cyan")
    banner.append("|  ", style="dim")
    banner.append("Multi-provider", style="magenta")
    return Panel(banner, border_style="bright_blue", padding=(0, 2))


def _render_welcome(config: AppConfig, restored_count: int) -> Panel:
    """渲染欢迎面板，显示帮助提示和可用命令概览。"""
    help_text = Text()
    help_text.append("Quick actions\n", style="bold white")
    help_text.append("  /help", style="bold cyan")
    help_text.append("  /status", style="bold cyan")
    help_text.append("  /usage", style="bold cyan")
    help_text.append("  /compact", style="bold cyan")
    help_text.append("  /model <ID>", style="bold cyan")
    help_text.append("  /review <URL>", style="bold cyan")
    help_text.append("  /clear", style="bold cyan")
    help_text.append("  /exit", style="bold cyan")
    help_text.append("\n\n")
    help_text.append("Tip: ", style="bold yellow")
    help_text.append(
        "直接粘贴 GitHub PR 链接，或输入完整 pr-review 命令，即可触发本地审查。", style="dim"
    )

    if restored_count > 0:
        help_text.append(
            f"\n\nRestored {restored_count} messages from previous session.", style="yellow"
        )

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
    console.print(_render_brand_banner())
    console.print(Rule(style="dim"))
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
                    live.update(
                        Panel(
                            Text(f"{spinner} Thinking... {elapsed:.1f}s", style="bold yellow"),
                            border_style="yellow",
                            padding=(0, 1),
                        )
                    )
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
