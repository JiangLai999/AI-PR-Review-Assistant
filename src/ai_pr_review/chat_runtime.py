"""Chat 运行时辅助函数。"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rich.columns import Columns
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
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
    status.append(" ● ", style="bold white")
    status.append("CONNECTED", style="bold white")
    status.append("   ")
    status.append("Provider", style="bold white")
    status.append(f" {provider}", style="grey82")
    status.append("   ")
    status.append("Model", style="bold white")
    status.append(f" {model}", style="grey82")
    status.append("   ")
    status.append("Layout", style="bold white")
    status.append(f" {layout}", style="grey82")
    status.append("   ")
    status.append("Messages", style="bold white")
    status.append(f" {message_count}", style="grey82")
    status.append("   ")
    status.append("Session", style="bold white")
    status.append(f" {path_display}", style="dim")

    return Panel(status, border_style="grey27", padding=(0, 1), style="white on black")


def _pixel_brand_text() -> Text:
    brand = Text()
    brand.append("█▀█ █ █   █▀█ █▀█   █▀█ █▀▀ █ █ █ █▀▀ █ █\n", style="bold white")
    brand.append("█▀█ █ █   █▀▀ █▀▄   █▀▄ █▀▀ ▀▄▀▄▀ █▀▀ ▀▄▀\n", style="bold white")
    brand.append("▀ ▀ ▀▀▀   ▀   ▀ ▀   ▀ ▀ ▀▀▀  ▀ ▀  ▀▀▀  ▀ ", style="bold white")
    return brand


def _render_header(config: AppConfig, restored_count: int) -> Panel:
    """渲染统一 header：品牌横幅 + 命令帮助 + 使用提示。"""
    left = Text()
    left.append_text(_pixel_brand_text())
    left.append("\n\n")
    left.append("terminal workspace", style="grey62")
    left.append("  •  ", style="dim")
    left.append(config.provider.display_name or config.ai_client.provider, style="bold white")
    left.append("  •  ", style="dim")
    left.append(config.ai_client.model, style="grey82")

    commands = Table.grid(padding=(0, 1))
    commands.add_column(style="bold white")
    commands.add_column(style="grey82")
    commands.add_row("/help", "查看全部命令")
    commands.add_row("/status", "当前会话状态")
    commands.add_row("/usage", "消息/字符统计")
    commands.add_row("/compact", "压缩历史消息")
    commands.add_row("/model <ID>", "切换模型")
    commands.add_row("/review <URL>", "执行 PR 审查")
    commands.add_row("/clear", "清空会话")
    commands.add_row("/exit", "退出")

    right = Text()
    right.append("Hints\n", style="bold white")
    right.append("- 直接粘贴 GitHub PR 链接可自动审查\n", style="grey82")
    right.append("- 输入完整 pr-review 命令也会走本地执行\n", style="grey82")
    right.append("- Chat 适合追问、复盘和快速 review\n", style="grey82")
    if restored_count > 0:
        right.append(f"\nRestored {restored_count} messages.", style="white")

    body = Columns(
        [
            Panel(
                left, title="Brand", border_style="grey35", padding=(1, 1), style="white on black"
            ),
            Panel(
                commands,
                title="Commands",
                border_style="grey35",
                padding=(1, 1),
                style="white on black",
            ),
            Panel(
                right, title="Hints", border_style="grey35", padding=(1, 1), style="white on black"
            ),
        ],
        expand=True,
        equal=True,
    )
    return Panel(body, border_style="white", padding=(0, 1), style="white on black")


def _render_message(role: str, text: str) -> Panel:
    renderable: Any
    if role == "user":
        renderable = Text(text, style="white")
        title = " YOU "
        subtitle = "input"
        border_style = "grey35"
    else:
        renderable = Markdown(text)
        title = " ASSISTANT "
        subtitle = "response"
        border_style = "white"
    return Panel(
        renderable,
        title=title,
        subtitle=f"[dim]{subtitle}[/dim]",
        border_style=border_style,
        padding=(0, 1),
        style="white on black",
    )


def _render_transcript(messages: list[dict[str, Any]]) -> Panel:
    if not messages:
        empty = Text(
            "No messages yet. Start by typing a prompt, a PR URL, or a full pr-review command.",
            style="grey70",
        )
        return Panel(
            empty,
            title=" Transcript ",
            border_style="grey35",
            padding=(1, 2),
            style="white on black",
        )

    renderables = []
    for message in messages[-12:]:
        role = str(message.get("role", "assistant")).lower()
        content = str(message.get("content", ""))
        renderables.append(_render_message(role, content))
    return Panel(
        Group(*renderables),
        title=" Transcript ",
        border_style="grey35",
        padding=(1, 1),
        style="white on black",
    )


def _render_input_bar() -> Panel:
    input_text = Text()
    input_text.append("Input", style="bold white")
    input_text.append("  >  ", style="dim")
    input_text.append("输入问题、/命令、GitHub PR URL 或完整 pr-review 命令", style="grey70")
    return Panel(input_text, border_style="grey35", padding=(0, 1), style="white on black")


def _render_workspace(
    config: AppConfig,
    messages: list[dict[str, Any]],
    session_path: str | None,
    restored_count: int,
) -> Group:
    return Group(
        _render_header(config, restored_count),
        _render_status_bar(config, len(messages), session_path),
        _render_transcript(messages),
        _render_input_bar(),
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

    def rerender_workspace() -> None:
        console.clear()
        console.print()
        console.print(_render_workspace(config, messages, session_path, len(messages)))
        console.print()

    rerender_workspace()

    def send_once(user_text: str) -> None:
        messages.append({"role": "user", "content": user_text})
        rerender_workspace()

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
                            Text(f"{spinner} Thinking... {elapsed:.1f}s", style="bold white"),
                            border_style="grey35",
                            padding=(0, 1),
                            style="white on black",
                        )
                    )
                    if elapsed > 0.3:
                        break
                answer = send_message(messages, user_text)
        except Exception:
            answer = send_message(messages, user_text)

        if not answer:
            messages.pop()
            rerender_workspace()
            console.print("[dim]No response returned.[/dim]")
            return

        messages.append({"role": "assistant", "content": answer})
        save_session(config_path, messages)
        rerender_workspace()

    if message is not None:
        send_once(message)
        return

    while True:
        try:
            user_text = Prompt.ask("[bold white]You[/bold white]", console=console).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]退出聊天。[/dim]")
            break

        if user_text.lower() in {"/exit", "exit", "quit", "q"}:
            console.print("[dim]退出聊天。[/dim]")
            break
        if not user_text:
            continue
        if raw_command_handler(user_text):
            rerender_workspace()
            continue
        if user_text.startswith("/") and slash_handler(
            console, config, config_path, messages, user_text, active_layout
        ):
            rerender_workspace()
            continue
        send_once(user_text)
