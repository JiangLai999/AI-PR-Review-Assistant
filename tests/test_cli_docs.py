"""CLI 文档与官网命令入口的防漂移守卫。

真源是 ``ai_pr_review.cli.main`` 里实际注册的命令。这里锁住三件事：

1. ``docs/API.md`` 覆盖所有可见顶层命令与 ``config`` 子命令；
2. 官网首页展示当前可用的离线体检、Demo、Web 工作台入口；
3. 生成后的 ``docs-data.js`` 确实包含完整 CLI 命令速查。
"""

from __future__ import annotations

from pathlib import Path

from ai_pr_review.cli import main

ROOT = Path(__file__).resolve().parents[1]
API_DOC = ROOT / "docs" / "API.md"
WEBSITE_INDEX = ROOT / "website" / "index.html"
WEBSITE_DATA = ROOT / "website" / "assets" / "docs-data.js"


def _visible_top_level_commands() -> list[str]:
    return [name for name, command in main.commands.items() if not command.hidden]


def test_api_doc_covers_every_visible_top_level_command() -> None:
    doc = API_DOC.read_text(encoding="utf-8")
    missing = [name for name in _visible_top_level_commands() if f"`pr-review {name}" not in doc]
    assert not missing, (
        "docs/API.md 缺少以下顶层命令：" f"{missing}；CLI 新增或改名后必须同步命令参考。"
    )


def test_api_doc_covers_every_config_subcommand() -> None:
    doc = API_DOC.read_text(encoding="utf-8")
    config_commands = main.commands["config"].commands
    missing = [name for name in config_commands if f"`pr-review config {name}" not in doc]
    assert not missing, (
        "docs/API.md 缺少以下 config 子命令：" f"{missing}；配置命令变更后必须同步命令参考。"
    )


def test_website_homepage_mentions_current_entry_points() -> None:
    html = WEBSITE_INDEX.read_text(encoding="utf-8")
    for command in (
        "pr-review doctor",
        "pr-review demo",
        "pr-review serve",
        "pr-review config health --probe",
    ):
        assert command in html, f"官网首页缺少当前命令入口：{command}"

    assert "Web 服务、React 前端和更完整的平台化形态仍属于规划方向" not in html
    assert "当前不是。" not in html


def test_generated_website_data_exposes_cli_command_reference() -> None:
    data = WEBSITE_DATA.read_text(encoding="utf-8")
    for command in (
        "pr-review doctor",
        "pr-review demo",
        "pr-review serve",
        "pr-review showcase",
        "pr-review preferences",
        "pr-review local-model check",
        "pr-review export-run",
    ):
        assert command in data, f"官网文档中心缺少命令：{command}"
