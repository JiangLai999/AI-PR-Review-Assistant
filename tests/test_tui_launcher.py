from __future__ import annotations

import subprocess
from pathlib import Path

from ai_pr_review import cli


def _prepare_launcher_tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    project_root = tmp_path / "proj"
    package_root = project_root / "src" / "ai_pr_review"
    dev_root = project_root / "frontend" / "tui"
    static_root = package_root / "tui_static"

    (dev_root / "src").mkdir(parents=True)
    (dev_root / "src" / "main.tsx").write_text("// dev entry\n", encoding="utf-8")
    (dev_root / "node_modules").mkdir()
    static_root.mkdir(parents=True)
    (static_root / "tui.js").write_text("// staged bundle\n", encoding="utf-8")
    (static_root / "pr-review-tui.exe").write_bytes(b"stale-exe")
    return project_root, dev_root, static_root


def _capture_launch(monkeypatch, launched: list[tuple[list[str], Path]]) -> None:
    def fake_run(command, cwd=None, env=None, check=False):
        launched.append((list(command), Path(cwd)))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(cli.subprocess, "run", fake_run)


def test_tui_launcher_prefers_dev_source_then_bundle_then_prebuilt(
    tmp_path: Path, monkeypatch
) -> None:
    project_root, dev_root, static_root = _prepare_launcher_tree(tmp_path)
    package_root = project_root / "src" / "ai_pr_review"
    monkeypatch.setattr(cli, "__file__", str(package_root / "cli.py"))
    monkeypatch.setattr(cli, "_find_bun_runtime", lambda: "bun")
    monkeypatch.delenv("AI_PR_REVIEW_TUI_COMMAND", raising=False)
    launched: list[tuple[list[str], Path]] = []
    _capture_launch(monkeypatch, launched)

    assert cli._open_tui_frontend() is True
    assert launched[-1] == (
        ["bun", "--preload", "@opentui/solid/preload", "src/main.tsx"],
        dev_root,
    )

    # Without the dev toolchain the committed bundle must win over the stale
    # ignored compiled exe.
    (dev_root / "node_modules").rmdir()
    assert cli._open_tui_frontend() is True
    assert launched[-1] == (["bun", str(static_root / "tui.js")], static_root)

    # Only when Bun is unavailable may the compiled fallback be used.
    monkeypatch.setattr(cli, "_find_bun_runtime", lambda: None)
    assert cli._open_tui_frontend() is True
    assert launched[-1] == ([str(static_root / "pr-review-tui.exe")], static_root)


def test_tui_launcher_raw_command_override_wins(tmp_path: Path, monkeypatch) -> None:
    project_root, dev_root, _static_root = _prepare_launcher_tree(tmp_path)
    package_root = project_root / "src" / "ai_pr_review"
    monkeypatch.setattr(cli, "__file__", str(package_root / "cli.py"))
    monkeypatch.setattr(cli, "_find_bun_runtime", lambda: "bun")
    monkeypatch.setenv("AI_PR_REVIEW_TUI_COMMAND", "custom-tui --debug")
    launched: list[tuple[list[str], Path]] = []
    _capture_launch(monkeypatch, launched)

    assert cli._open_tui_frontend() is True
    assert launched[-1] == (["custom-tui", "--debug"], dev_root)
