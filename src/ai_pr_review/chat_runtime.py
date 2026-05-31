"""Chat runtime helpers - Premium TUI design.

Inspired by OpenCode, Claude Code, and OpenClaw.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.align import Align
from rich.box import DOUBLE, HEAVY, ROUNDED, SQUARE
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax
from rich.text import Text

from ai_pr_review.config import AppConfig

CODE_BLOCK_RE = re.compile(r"```(?P<lang>[\w+-]*)\n(?P<code>.*?)```", re.DOTALL)


def _pixel_brand() -> Text:
    """大像素品牌横幅 - PR REVIEW."""
    lines = [
        "██████  ██████      ██████  ███████ ██    ██ ██ ███████ ██  ██",
        "██   ██ ██   ██     ██   ██ ██      ██    ██ ██ ██      ██  ██",
        "██████  ██████      ██████  █████   ██    ██ ██ █████   ██████",
        "██      ██   ██     ██   ██ ██       ██  ██  ██ ██      ██  ██",
        "██      ██   ██     ██   ██ ███████   ████   ██ ███████ ██  ██",
    ]

    brand = Text()
    for line in lines:
        brand.append(" " + line + "\n", style="grey35")
    for line in lines:
        brand.append(line + "\n", style="bold white")
    return brand


def _render_header(config: AppConfig) -> Panel:
    """品牌头部 - 大像素横幅 + 副标题."""
    subtitle = Text()
    subtitle.append("AI-Powered Pull Request Review", style="grey70")
    subtitle.append("  ·  ", style="dim")
    subtitle.append("Terminal Workspace", style="grey50")

    content = Group(
        Text(""),
        Align.center(_pixel_brand()),
        Text(""),
        Align.center(subtitle),
        Text(""),
    )

    inner = Panel(
        content,
        border_style="grey58",
        padding=(0, 2),
        style="white on black",
        box=DOUBLE,
    )
    return Panel(
        inner,
        border_style="grey35",
        padding=(0, 1),
        style="white on black",
        box=SQUARE,
    )


def _render_status_bar(config: AppConfig, message_count: int) -> Text:
    """状态栏 - 极简连接信息."""
    provider = config.provider.display_name or config.ai_client.provider
    model = config.ai_client.model

    status = Text()
    status.append("  ● ", style="bold green")
    status.append(provider, style="bold white")
    status.append(" / ", style="dim")
    status.append(model, style="grey70")
    status.append("    ", style="dim")
    status.append(f"{message_count} messages", style="grey70")
    status.append("    ", style="dim")
    status.append(datetime.now().strftime("%Y-%m-%d %H:%M"), style="grey62")
    status.append("\n")
    return status


def _render_assistant_content(text: str) -> Any:
    """渲染 assistant 消息内容，支持 Markdown 和代码高亮."""
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
        parts.append(Syntax(code, lang, theme="monokai", word_wrap=True, line_numbers=False))
        cursor = end

    tail = text[cursor:].strip()
    if tail:
        parts.append(Markdown(tail))

    if not parts:
        return Text(text, style="white")
    if len(parts) == 1:
        return parts[0]
    return Group(*parts)


def _render_user_message(text: str, timestamp: str) -> Panel:
    """渲染用户消息 - 简洁淡色边框."""
    header = Text()
    header.append(" ▶ ", style="bold cyan")
    header.append("YOU", style="bold cyan")
    header.append(f"  ·  {timestamp}", style="dim")

    return Panel(
        Text(text, style="white"),
        title=header,
        title_align="left",
        border_style="grey42",
        padding=(0, 2),
        style="white on black",
        box=ROUNDED,
    )


def _render_assistant_message(
    text: str, timestamp: str, duration_seconds: float | None = None
) -> Panel:
    """渲染助手消息 - 高亮边框."""
    header = Text()
    header.append(" ⏺ ", style="bold green")
    header.append("ASSISTANT", style="bold green")
    header.append(f"  ·  {timestamp}", style="dim")

    body: Any = _render_assistant_content(text)
    if duration_seconds is not None:
        footer = Text()
        footer.append("\n")
        footer.append("Completed in ", style="grey62")
        footer.append(f"{duration_seconds:.1f}s", style="bold green")
        body = Group(body, footer)

    inner = Panel(
        body,
        title=header,
        title_align="left",
        border_style="grey70",
        padding=(0, 2),
        style="white on black",
        box=HEAVY,
    )
    return Panel(
        inner,
        border_style="grey35",
        padding=(0, 1),
        style="white on black",
        box=SQUARE,
    )


def _render_message(
    role: str, text: str, timestamp: str | None = None, duration_seconds: float | None = None
) -> Panel:
    """渲染消息 - 根据角色选择不同样式."""
    time_str = timestamp or datetime.now().strftime("%H:%M")

    if role == "user":
        return _render_user_message(text, time_str)
    else:
        return _render_assistant_message(text, time_str, duration_seconds)


def _render_welcome() -> Panel:
    """欢迎消息 - 引导用户开始使用."""
    welcome = Text()
    welcome.append("\n")
    welcome.append("  Welcome to AI PR Review", style="bold white")
    welcome.append("\n\n")
    welcome.append("  ", style="grey70")
    welcome.append("▶", style="green")
    welcome.append("  Paste a ", style="grey70")
    welcome.append("GitHub PR URL", style="bold cyan")
    welcome.append(" to auto-review code\n", style="grey70")
    welcome.append("  ", style="grey70")
    welcome.append("▶", style="green")
    welcome.append("  Type ", style="grey70")
    welcome.append("/", style="bold cyan")
    welcome.append(" to see available commands\n", style="grey70")
    welcome.append("  ", style="grey70")
    welcome.append("▶", style="green")
    welcome.append("  Type ", style="grey70")
    welcome.append("/help", style="bold cyan")
    welcome.append(" for full help\n", style="grey70")
    welcome.append("  ", style="grey70")
    welcome.append("▶", style="green")
    welcome.append("  Type ", style="grey70")
    welcome.append("/exit", style="bold cyan")
    welcome.append(" to quit\n", style="grey70")
    welcome.append("\n")

    return Panel(
        welcome,
        title=" Welcome ",
        title_align="left",
        border_style="grey42",
        padding=(0, 2),
        style="white on black",
        box=ROUNDED,
    )


def _render_transcript(messages: list[dict[str, Any]]) -> Panel:
    """渲染消息历史."""
    if not messages:
        return _render_welcome()

    recent = messages[-12:]
    renderables: list[Any] = []
    for i, message in enumerate(recent):
        role = str(message.get("role", "assistant")).lower()
        content = str(message.get("content", ""))
        timestamp = str(message.get("timestamp", ""))
        duration_seconds = message.get("duration_seconds")
        duration = float(duration_seconds) if isinstance(duration_seconds, (int, float)) else None
        renderables.append(
            _render_message(role, content, timestamp if timestamp else None, duration)
        )
        if i < len(recent) - 1:
            renderables.append(Text(""))

    return Panel(
        Group(*renderables),
        title=" Transcript ",
        title_align="left",
        border_style="grey58",
        padding=(1, 1),
        style="white on black",
        box=SQUARE,
    )


def _render_input_area(current_input: str = "") -> Panel:
    """渲染输入区 - 用户输入在上，提示文字在下."""
    content = Text()
    if current_input:
        content.append(f"  {current_input}\n", style="bold white")
    content.append("  ▶ ", style="bold green")
    content.append("Type your message or paste a PR URL...", style="grey50")
    return Panel(
        content,
        border_style="grey42",
        padding=(0, 1),
        style="white on black",
        box=ROUNDED,
    )


def _render_workspace(
    config: AppConfig,
    messages: list[dict[str, Any]],
    session_path: str | None,
) -> Group:
    """渲染完整工作区."""
    return Group(
        _render_header(config),
        _render_status_bar(config, len(messages)),
        _render_transcript(messages),
    )


# 多样化思考阶段 - 借鉴 Claude Code 的多阶段思考
THINKING_STAGES = [
    (0.0, "▰▱▱▱▱", "Connecting"),
    (1.0, "▰▰▱▱▱", "Analyzing"),
    (3.0, "▰▰▰▱▱", "Generating"),
    (6.0, "▰▰▰▰▱", "Crafting"),
    (12.0, "▰▰▰▰▰", "Finishing"),
]


def _thinking_animation(elapsed: float) -> tuple[str, str, str]:
    """返回 (spinner, progress, message) 多阶段动画."""
    spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    spinner = spinner_frames[int(elapsed * 10) % len(spinner_frames)]

    stage = THINKING_STAGES[0]
    for s in THINKING_STAGES:
        if elapsed >= s[0]:
            stage = s
        else:
            break

    return spinner, stage[1], stage[2]


def _render_thinking(elapsed: float) -> Panel:
    """渲染思考状态 - 多样化进度显示."""
    spinner, progress, message = _thinking_animation(elapsed)

    content = Text()
    content.append(f"  {spinner}  ", style="bold cyan")
    content.append(progress, style="bold cyan")
    content.append("  ", style="white")
    content.append(message, style="bold white")
    content.append("...", style="dim")
    content.append(f"   {elapsed:.1f}s", style="dim")

    inner = Panel(
        content,
        title=" Thinking ",
        title_align="left",
        border_style="cyan",
        padding=(0, 1),
        style="white on black",
        box=ROUNDED,
    )
    return Panel(
        inner,
        border_style="grey35",
        padding=(0, 1),
        style="white on black",
        box=SQUARE,
    )


def _run_message_in_background(
    send_message: Callable[[list[dict[str, Any]], str], str],
    messages: list[dict[str, Any]],
    user_text: str,
) -> tuple[threading.Thread, dict[str, Any]]:
    result: dict[str, Any] = {"answer": None, "error": None}

    def target() -> None:
        try:
            result["answer"] = send_message(messages, user_text)
        except Exception as exc:  # pragma: no cover - surfaced to caller
            result["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, result


def _build_prompt_session() -> Any | None:
    """构建 prompt_toolkit 会话."""
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
                "  <style fg='#444444'>│</style>"
                "  <b><style fg='#888888'> Tab </style></b>"
                " <style fg='#555555'>complete</style>"
                "  <style fg='#444444'>│</style>"
                "  <b><style fg='#888888'> / </style></b>"
                " <style fg='#555555'>commands</style>"
                "  <style fg='#444444'>│</style>"
                "  <b><style fg='#888888'> Ctrl+C </style></b>"
                " <style fg='#555555'>exit</style>"
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
    """运行聊天会话主循环."""
    messages: list[dict[str, Any]] = []
    session_path = str(config_path) if config_path is not None else None
    prompt_session = _build_prompt_session()

    def rerender_workspace() -> None:
        console.clear()
        console.print()
        console.print(_render_workspace(config, messages, session_path))
        console.print(_render_input_area())
        console.print()

    rerender_workspace()

    def send_once(user_text: str) -> None:
        timestamp = datetime.now().strftime("%H:%M")
        messages.append({"role": "user", "content": user_text, "timestamp": timestamp})
        rerender_workspace()

        start_time = time.time()
        thread, result = _run_message_in_background(send_message, messages, user_text)
        with Live(console=console, refresh_per_second=12, transient=True) as live:
            while thread.is_alive():
                elapsed = time.time() - start_time
                live.update(_render_thinking(elapsed))
                time.sleep(0.08)

        if result["error"] is not None:
            messages.pop()
            rerender_workspace()
            raise result["error"]

        answer = result["answer"]

        if not answer:
            messages.pop()
            rerender_workspace()
            console.print("[dim]No response returned.[/dim]")
            return

        timestamp = datetime.now().strftime("%H:%M")
        elapsed = time.time() - start_time
        messages.append(
            {
                "role": "assistant",
                "content": answer,
                "timestamp": timestamp,
                "duration_seconds": round(elapsed, 3),
            }
        )
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
                    HTML("<b><style fg='#4ade80'>▶</style></b> ")
                ).strip()
            else:
                user_text = Prompt.ask("[bold green]▶[/bold green]", console=console).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Exiting chat.[/dim]")
            break

        if user_text.lower() in {"/exit", "exit", "quit", "q"}:
            console.print("[dim]Exiting chat.[/dim]")
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
