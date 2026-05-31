"""Chat 运行时辅助函数。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from ai_pr_review.config import AppConfig


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
    send_message: Callable[[list[dict[str, Any]], str], None],
) -> None:
    messages = load_session(config_path)
    console.print(Panel("输入 /exit 退出。", title=chat_title(config), border_style="cyan"))
    if messages:
        console.print(f"Restored {len(messages)} messages from the previous chat session.")

    def send_once(user_text: str) -> None:
        messages.append({"role": "user", "content": user_text})
        print_chat_message(console, "You", user_text)
        answer = send_message(messages, user_text)
        if answer is None:
            messages.pop()
            return
        messages.append({"role": "assistant", "content": answer})
        save_session(config_path, messages)
        print_chat_message(console, "Assistant", answer)

    if message is not None:
        send_once(message)
        return

    while True:
        user_text = Prompt.ask("You", console=console).strip()
        if user_text.lower() in {"/exit", "exit", "quit", "q"}:
            break
        if not user_text:
            continue
        if user_text.startswith("/") and slash_handler(
            console, config, config_path, messages, user_text, active_layout
        ):
            continue
        send_once(user_text)
