"""Chat 运行时辅助函数。"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.box import ASCII
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from ai_pr_review.config import AppConfig

CODE_BLOCK_RE = __import__("re").compile(
    r"```(?P<lang>[\w+-]*)\n(?P<code>.*?)```", __import__("re").DOTALL
)


def _render_status_bar(config: AppConfig, message_count: int) -> Panel:
    """简洁的状态栏。"""
    provider = config.provider.display_name or config.ai_client.provider
    model = config.ai_client.model

    status = Text()
    status.append(" * ", style="bold green")
    status.append("CONNECTED", style="bold green")
    status.append("  |  ", style="dim")
    status.append(provider, style="bold white")
    status.append(" / ", style="dim")
    status.append(model, style="grey70")
    status.append("  |  ", style="dim")
    status.append(f"{message_count} messages", style="grey70")

    return Panel(status, border_style="dim", padding=(0, 1), style="white on black", box=ASCII)


def _render_header(config: AppConfig) -> Panel:
    """简洁的品牌头部。"""
    brand = Text()
    brand.append("  +------------------------------------------------------------+\n", style="dim")
    brand.append("  |                                                            |\n", style="dim")
    brand.append("  |   ", style="dim")
    brand.append("AI PR Review", style="bold white")
    brand.append("  -  ", style="dim")
    brand.append("Terminal Workspace", style="grey62")
    brand.append("                          |\n", style="dim")
    brand.append("  |                                                            |\n", style="dim")
    brand.append("  +------------------------------------------------------------+\n", style="dim")

    return Panel(brand, border_style="dim", padding=(0, 0), style="white on black", box=ASCII)


def _render_welcome() -> Panel:
    """欢迎消息面板。"""
    welcome = Text()
    welcome.append("  Welcome to ", style="grey70")
    welcome.append("AI PR Review Chat", style="bold white")
    welcome.append("!\n\n", style="grey70")
    welcome.append("  ", style="grey70")
    welcome.append(">", style="green")
    welcome.append("  Paste GitHub PR URL to auto-review\n", style="grey70")
    welcome.append("  ", style="grey70")
    welcome.append(">", style="green")
    welcome.append("  Type ", style="grey70")
    welcome.append("/help", style="bold cyan")
    welcome.append(" to see all commands\n", style="grey70")
    welcome.append("  ", style="grey70")
    welcome.append(">", style="green")
    welcome.append("  Type ", style="grey70")
    welcome.append("/exit", style="bold cyan")
    welcome.append(" to quit\n", style="grey70")
    welcome.append("  ", style="grey70")
    welcome.append(">", style="green")
    welcome.append("  Supports Markdown and code highlighting\n", style="grey70")

    return Panel(welcome, border_style="dim", padding=(1, 1), style="white on black", box=ASCII)


def _render_assistant_content(text: str) -> Any:
    """渲染 assistant 消息内容，支持 Markdown 和代码高亮。"""
    parts: list[Any] = []
    cursor = 0
    for match in CODE_BLOCK_RE.finditer(text):
        start, end = match.span()
        if start > cursor:
            prose = text[cursor:start].strip()
            if prose:
                parts.append(Markdown(prose))
        lang = (match.group("lang") or "text").strip() or "text"
        code = match.group("code").rstrip()
        parts.append(Syntax(code, lang, theme="github-dark", word_wrap=True, line_numbers=False))
        cursor = end

    tail = text[cursor:].strip()
    if tail:
        parts.append(Markdown(tail))

    if not parts:
        return Text(text, style="white")
    if len(parts) == 1:
        return parts[0]
    return Group(*parts)


def _render_message(role: str, text: str, timestamp: str | None = None) -> Panel:
    """渲染单条消息，带时间戳和更好的样式。"""
    time_str = timestamp or datetime.now().strftime("%H:%M")

    if role == "user":
        header = Text()
        header.append(" > ", style="bold cyan")
        header.append("YOU", style="bold cyan")
        header.append(f"  {time_str}", style="dim")
        renderable: Any = Text(text, style="white")
        border_style = "dim"
    else:
        header = Text()
        header.append(" * ", style="bold green")
        header.append("ASSISTANT", style="bold green")
        header.append(f"  {time_str}", style="dim")
        renderable = _render_assistant_content(text)
        border_style = "grey70"

    return Panel(
        renderable,
        title=header,
        border_style=border_style,
        padding=(0, 1),
        style="white on black",
        box=ASCII,
    )


def _render_transcript(messages: list[dict[str, Any]]) -> Panel:
    """渲染消息历史。"""
    if not messages:
        return _render_welcome()

    renderables = []
    for message in messages[-12:]:
        role = str(message.get("role", "assistant")).lower()
        content = str(message.get("content", ""))
        timestamp = str(message.get("timestamp", ""))
        renderables.append(_render_message(role, content, timestamp if timestamp else None))

    return Panel(
        Group(*renderables),
        title=" Transcript ",
        border_style="dim",
        padding=(1, 1),
        style="white on black",
        box=ASCII,
    )


def _render_input_hint() -> Panel:
    """简洁的输入提示。"""
    input_text = Text()
    input_text.append(" >", style="bold white")
    input_text.append(" ", style="white")
    return Panel(input_text, border_style="dim", padding=(0, 1), style="white on black", box=ASCII)


def _render_workspace(
    config: AppConfig,
    messages: list[dict[str, Any]],
    session_path: str | None,
) -> Group:
    """渲染完整工作区。"""
    return Group(
        _render_header(config),
        _render_status_bar(config, len(messages)),
        _render_transcript(messages),
        _render_input_hint(),
    )


def _spinner_frame(elapsed: float) -> str:
    """旋转动画帧。"""
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    idx = int(elapsed * 10) % len(frames)
    return frames[idx]


def _thinking_stage(elapsed: float) -> str:
    """根据时间返回思考阶段文字。"""
    if elapsed < 0.5:
        return "Analyzing input..."
    elif elapsed < 1.0:
        return "Building context..."
    elif elapsed < 2.0:
        return "Calling AI model..."
    elif elapsed < 5.0:
        return "Processing response..."
    else:
        return "Still working..."


def _build_prompt_session() -> Any | None:
    """构建 prompt_toolkit 会话。"""
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import WordCompleter
        from prompt_toolkit.formatted_text import HTML
        from prompt_toolkit.history import InMemoryHistory
    except ModuleNotFoundError:
        return None

    try:
        history = InMemoryHistory()
        slash_commands = [
            "/help",
            "/status",
            "/usage",
            "/compact",
            "/restore",
            "/config",
            "/session",
            "/history",
            "/stats",
            "/model",
            "/review",
            "/clear",
            "/exit",
        ]
        completer = WordCompleter(slash_commands, ignore_case=True)
        return PromptSession(
            history=history,
            completer=completer,
            bottom_toolbar=HTML(
                "<b><style fg='#888888'> Enter </style></b>"
                " <style fg='#555555'>send</style>"
                "  <style fg='#444444'>|</style>"
                "  <b><style fg='#888888'> Tab </style></b>"
                " <style fg='#555555'>complete</style>"
                "  <style fg='#444444'>|</style>"
                "  <b><style fg='#888888'> / </style></b>"
                " <style fg='#555555'>commands</style>"
            ),
            multiline=False,
        )
    except Exception:
        return None


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
    """运行聊天会话主循环。"""
    messages: list[dict[str, Any]] = []
    session_path = str(config_path) if config_path is not None else None
    prompt_session = _build_prompt_session()

    def rerender_workspace() -> None:
        console.clear()
        console.print()
        console.print(_render_workspace(config, messages, session_path))
        console.print()

    rerender_workspace()

    def send_once(user_text: str) -> None:
        timestamp = datetime.now().strftime("%H:%M")
        messages.append({"role": "user", "content": user_text, "timestamp": timestamp})
        rerender_workspace()

        start_time = time.time()
        answer = None
        try:
            with Live(console=console, refresh_per_second=12, transient=True) as live:
                while True:
                    elapsed = time.time() - start_time
                    spinner = _spinner_frame(elapsed)
                    stage = _thinking_stage(elapsed)
                    live.update(
                        Panel(
                            Text(f" {spinner} {stage} ({elapsed:.1f}s)", style="bold white"),
                            border_style="dim",
                            padding=(0, 1),
                            style="white on black",
                            box=ASCII,
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

        timestamp = datetime.now().strftime("%H:%M")
        messages.append({"role": "assistant", "content": answer, "timestamp": timestamp})
        save_session(config_path, messages)
        rerender_workspace()

    if message is not None:
        send_once(message)
        return

    while True:
        try:
            if prompt_session is not None:
                from prompt_toolkit.formatted_text import HTML

                user_text = prompt_session.prompt(
                    HTML("<b><style fg='#ffffff'>> </style></b>")
                ).strip()
            else:
                user_text = Prompt.ask("[bold white]>[/bold white]", console=console).strip()
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
