"""Chat 帮助文本 ↔ 命令实现 一致性测试。

事实基线全部从**源码**里 grep 出来，而不是手写清单：

- 后端：`src/ai_pr_review/backend/jsonl_server.py` 的 `command.execute` 分支里
  `if/elif command == "..."` 的集合；
- CLI：`chat_commands.handle_basic_chat_slash_command` 与 `cli._handle_chat_slash_command`
  里的 `command == "/..."`，再加 `chat_runtime` 认识的 `/exit`；
- 帮助文本：`build_chat_help_text()` 的返回值，以及后端 `/help` 分支真正返回的字符串。

任一方向漂移（帮助少一条命令、或残留已删除命令）都会失败。
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from ai_pr_review.backend.jsonl_server import JsonlBackend
from ai_pr_review.chat_commands import build_chat_help_text

REPO_ROOT = Path(__file__).resolve().parents[1]
JSONL_SERVER_PATH = REPO_ROOT / "src" / "ai_pr_review" / "backend" / "jsonl_server.py"
CHAT_COMMANDS_PATH = REPO_ROOT / "src" / "ai_pr_review" / "chat_commands.py"
CLI_PATH = REPO_ROOT / "src" / "ai_pr_review" / "cli.py"
CHAT_RUNTIME_PATH = REPO_ROOT / "src" / "ai_pr_review" / "chat_runtime.py"
README_PATH = REPO_ROOT / "README.md"
APP_TSX_PATH = REPO_ROOT / "frontend" / "tui" / "src" / "app.tsx"

# TUI 前端本地截获、不进后端分发，但同样是用户可用的现行命令（后端 /help 也要列出）。
TUI_LOCAL_COMMANDS = frozenset({"retry", "workbench", "sessions", "rename"})

# 已删除/从未实现的命令：任何一份帮助文本里都不允许再出现。
# 注意：`sessions` 已于 A-P2 重新实现（TUI 前端 `/sessions` + `Alt+S`），故不在此列。
REMOVED_COMMANDS = frozenset(
    {
        "ask",
        "debug",
        "kill",
        "lang",
        "load",
        "mode",
        "prompt",
        "quit",
        "redo",
        "reset",
        "run",
        "save",
        "stop",
        "theme",
        "token",
        "tokens",
        "trace",
        "undo",
    }
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _command_execute_source() -> str:
    """`command.execute` 分支的源码切片（避免抓到别的方法里的同名判断）。"""
    source = _read(JSONL_SERVER_PATH)
    start = source.index('elif method == "command.execute":')
    end = source.find("def write_event(", start)
    return source[start:] if end == -1 else source[start:end]


def backend_dispatched_commands() -> set[str]:
    """grep 出的后端命令分发集合：`if/elif command == "..."`。"""
    return set(re.findall(r'(?:el)?if command == "([a-z_]+)"', _command_execute_source()))


def cli_implemented_commands() -> set[str]:
    """grep 出的 CLI chat（`pr-review chat`）本地实现的命令集合。"""
    found = set(re.findall(r'command == "(/[a-z]+)"', _read(CHAT_COMMANDS_PATH)))
    found |= set(re.findall(r'command == "(/[a-z]+)"', _read(CLI_PATH)))
    exit_set = re.search(r"user_text\.lower\(\) in \{([^}]*)\}", _read(CHAT_RUNTIME_PATH))
    if exit_set is not None:
        found |= {f"/{name}" for name in re.findall(r'"/([a-z]+)"', exit_set.group(1))}
    return {token.lstrip("/") for token in found}


def tui_frontend_local_commands() -> set[str]:
    """grep 出 TUI 前端本地截获（`text === "/x"` / `text.startsWith("/x ")`）的命令。"""
    source = _read(APP_TSX_PATH)
    found = set(re.findall(r'text(?:\.toLowerCase\(\))?\s*===\s*"(/[a-z]+)"', source))
    found |= set(re.findall(r'text(?:\.toLowerCase\(\))?\.startsWith\("(/[a-z]+)', source))
    return {token.lstrip("/") for token in found}


def readme_chat_table() -> dict[str, set[str]]:
    """README「### 斜杠命令」表的 ``命令 -> 标注的可用界面``（tui / cli）。"""
    section = _read(README_PATH).split("### 斜杠命令", 1)[1].split("\n## ", 1)[0]
    table: dict[str, set[str]] = {}
    for line in section.splitlines():
        match = re.match(r"\|\s*`(/[a-z]+)", line)
        if not match:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        surface = cells[-1]
        marks: set[str] = set()
        if "TUI" in surface:
            marks.add("tui")
        if "CLI" in surface:
            marks.add("cli")
        table[match.group(1).lstrip("/")] = marks
    return table


def commands_in_help_text(text: str) -> set[str]:
    """按行取行首的 `/<command>`；说明正文里的路径/URL 不算命令。"""
    found: set[str] = set()
    for line in text.splitlines():
        match = re.match(r"\s*/([a-z][a-z0-9_-]*)", line)
        if match:
            found.add(match.group(1))
    return found


def backend_help_text(tmp_path: Path) -> str:
    """调用真实后端拿 `/help` 返回值（不解析源码里的字面量）。"""
    backend = JsonlBackend(tmp_path / "config.json")
    events = asyncio.run(
        backend.handle(
            {
                "id": "1",
                "method": "command.execute",
                "params": {"name": "help", "args": [], "session_id": "help-session"},
            }
        )
    )
    assert events[0]["ok"] is True, events[0]
    text = events[0]["result"].get("text", "")
    assert isinstance(text, str) and text
    return text


DISPATCHED = backend_dispatched_commands()
CLI_IMPLEMENTED = cli_implemented_commands()


def test_command_sets_discovered_from_source() -> None:
    """基线自检：grep 结果必须包含现行命令，否则后面的对照等于没跑。"""
    assert "help" in DISPATCHED
    assert {"think", "compact", "history", "context", "new", "model"} <= DISPATCHED
    assert "help" in CLI_IMPLEMENTED
    assert {"review", "exit", "usage", "clear"} <= CLI_IMPLEMENTED


@pytest.mark.parametrize("command", sorted(DISPATCHED))
def test_backend_help_lists_every_dispatched_command(command: str, tmp_path: Path) -> None:
    assert f"/{command}" in backend_help_text(tmp_path)


def test_backend_help_matches_dispatch_set(tmp_path: Path) -> None:
    """后端 /help 的命令表 = 分发集合 ∪ TUI 本地命令，一条不多、一条不少。"""
    listed = commands_in_help_text(backend_help_text(tmp_path))
    assert listed == DISPATCHED | set(TUI_LOCAL_COMMANDS)


def test_backend_help_has_no_removed_commands(tmp_path: Path) -> None:
    listed = commands_in_help_text(backend_help_text(tmp_path))
    assert not listed & REMOVED_COMMANDS


@pytest.mark.parametrize("command", sorted(CLI_IMPLEMENTED))
def test_cli_help_lists_every_implemented_command(command: str) -> None:
    assert f"/{command}" in build_chat_help_text()


def test_cli_help_matches_implementation_set() -> None:
    listed = commands_in_help_text(build_chat_help_text())
    assert listed == CLI_IMPLEMENTED


def test_cli_help_has_no_removed_commands() -> None:
    listed = commands_in_help_text(build_chat_help_text())
    assert not listed & REMOVED_COMMANDS


def test_help_texts_cover_the_commands_they_share(tmp_path: Path) -> None:
    """两份帮助文本都必须逐行列出同名命令（不能一份有、一份没有）。"""
    backend_lines = backend_help_text(tmp_path).splitlines()
    cli_lines = build_chat_help_text().splitlines()
    shared = {f"/{name}" for name in DISPATCHED & CLI_IMPLEMENTED}
    for command in sorted(shared):
        assert any(line.strip().startswith(command) for line in backend_lines), command
        assert any(line.strip().startswith(command) for line in cli_lines), command


def test_readme_chat_table_is_discovered() -> None:
    """基线自检：README 斜杠命令表必须能被解析出来，否则后面的对照等于没跑。"""
    table = readme_chat_table()
    assert {"help", "review", "usage", "think", "sessions"} <= set(table)


def test_readme_chat_table_matches_implementation_surfaces() -> None:
    """README 斜杠命令表 = 两套界面的实现集合，且逐条标注正确的可用界面。

    回归点（2026-09-28 官网核查）：README 的「斜杠命令」表同时混入了 TUI 与 CLI 的
    命令，既没有标注「仅 CLI / 仅 TUI」，还漏掉了 `/sessions`、`/rename`、`/think`
    等 TUI 命令；官网「Chat 工作区」标签页直接渲染这张表，于是把只存在于纯文本
    CLI 的 `/usage`、`/exit` 等展示成通用命令。这里用源码集合锁住两边。
    """
    table = readme_chat_table()
    tui_available = DISPATCHED | set(TUI_LOCAL_COMMANDS) | tui_frontend_local_commands()
    cli_available = CLI_IMPLEMENTED

    expected: dict[str, set[str]] = {}
    for name in tui_available | cli_available:
        marks: set[str] = set()
        if name in tui_available:
            marks.add("tui")
        if name in cli_available:
            marks.add("cli")
        expected[name] = marks

    only_doc = sorted(set(table) - set(expected))
    only_code = sorted(set(expected) - set(table))
    wrong_surface = sorted(
        name for name in set(table) & set(expected) if table[name] != expected[name]
    )
    assert table == expected, (
        "README 斜杠命令表与实现不一致："
        f"仅文档有 {only_doc}；仅实现有 {only_code}；界面标注错误 {wrong_surface}"
    )
