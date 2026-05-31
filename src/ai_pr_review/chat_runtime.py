"""Chat 运行时辅助函数。"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rich.columns import Columns
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Prompt
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


def _pixel_brand_text() -> Text:
    brand = Text()
    brand.append("█▀█ █▀█   █▀█ █▀█ █▀▀ █ █ █ █▀▀ █ █\n", style="bold bright_cyan")
    brand.append("█▀█ █ █   █▀▄ █▀▀ █▀▀ ▀▄▀▄▀ █▀▀ ▀▄▀\n", style="bold bright_cyan")
    brand.append("▀ ▀ ▀▀▀   ▀ ▀ ▀   ▀▀▀  ▀ ▀  ▀▀▀  ▀ ", style="bold bright_cyan")
    return brand


def _render_header(config: AppConfig, restored_count: int) -> Panel:
    """渲染统一 header：品牌横幅 + 命令帮助 + 使用提示。"""
    left = Text()
    left.append_text(_pixel_brand_text())
    left.append("\n\n")
    left.append("terminal workspace", style="dim")
    left.append("  •  ", style="dim")
    left.append(config.provider.display_name or config.ai_client.provider, style="bold green")
    left.append("  •  ", style="dim")
    left.append(config.ai_client.model, style="bold magenta")

    commands = Table.grid(padding=(0, 1))
    commands.add_column(style="bold cyan")
    commands.add_column(style="white")
    commands.add_row("/help", "查看全部命令")
    commands.add_row("/status", "当前会话状态")
    commands.add_row("/usage", "消息/字符统计")
    commands.add_row("/compact", "压缩历史消息")
    commands.add_row("/model <ID>", "切换模型")
    commands.add_row("/review <URL>", "执行 PR 审查")
    commands.add_row("/clear", "清空会话")
    commands.add_row("/exit", "退出")

    right = Text()
    right.append("Tips\n", style="bold yellow")
    right.append("- 直接粘贴 GitHub PR 链接可自动审查\n", style="white")
    right.append("- 输入完整 pr-review 命令也会走本地执行\n", style="white")
    right.append("- Chat 适合追问、复盘和快速 review\n", style="white")
    if restored_count > 0:
        right.append(f"\nRestored {restored_count} messages.", style="yellow")

    body = Columns(
        [
            Panel(left, title="Brand", border_style="bright_blue", padding=(1, 1)),
            Panel(commands, title="Commands", border_style="cyan", padding=(1, 1)),
            Panel(right, title="Hints", border_style="yellow", padding=(1, 1)),
        ],
        expand=True,
        equal=True,
    )
    return Panel(body, border_style="bright_blue", padding=(0, 1))


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
    console.print(_render_header(config, len(messages)))
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
