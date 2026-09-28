"""agent_bridge 协作总线的加固回归测试（Claude 审计 F5 / F6 / F12）。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def bridge(tmp_path: Path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "agent_bridge_under_test", ROOT / "scripts" / "agent_bridge.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    bus = tmp_path / ".agent-bus"
    monkeypatch.setattr(module, "BUS", bus)
    monkeypatch.setattr(module, "TASKS", bus / "tasks")
    monkeypatch.setattr(module, "REPORTS", bus / "reports")
    monkeypatch.setattr(module, "LOCKS", bus / "locks")
    return module


def test_bus_gitignore_keeps_runs_ignored(bridge) -> None:
    """`ensure_bus()` 不得把 `runs/` 那行删掉。

    历史 bug：常量漏了 `runs/`，而 `ensure_bus()` 一旦发现文件内容与常量不同就重写，
    于是**每条总线命令都会删一次**，headless 调度器的 agent 日志（`runs/*.log`）
    随即暴露成待提交文件，仓库里反复出现这条噪声 diff。
    """
    bridge.ensure_bus()

    first = (bridge.BUS / ".gitignore").read_text(encoding="utf-8")
    assert "runs/" in first
    assert "tasks/" in first and "reports/" in first and "locks/" in first

    # 幂等：再跑一次内容不变（否则 mtime 抖动会一直产生假 diff）。
    bridge.ensure_bus()
    assert (bridge.BUS / ".gitignore").read_text(encoding="utf-8") == first


def test_task_id_cannot_escape_the_bus(bridge) -> None:
    for bad in ("../../evil", "a/b", "..", "", "x" * 65, "a b"):
        with pytest.raises(SystemExit, match="invalid task id"):
            bridge.validate_task_id(bad)
    assert bridge.validate_task_id("claude-backend-audit_2") == "claude-backend-audit_2"


def test_active_lock_blocks_a_second_claimant(bridge) -> None:
    bridge.dispatch("claude", "task-a", "objective", [], "prompt")
    bridge.claim("claude", "task-a")
    with pytest.raises(SystemExit, match="already claimed"):
        bridge.claim("claude", "task-a")


def test_stale_lock_can_be_reclaimed(bridge) -> None:
    bridge.dispatch("claude", "task-a", "objective", [], "prompt")
    bridge.write_json(
        bridge.lock_path("task-a"),
        {
            "task_id": "task-a",
            "agent": "claude",
            "host": "somewhere",
            "claimed_at": "2000-01-01T00:00:00+00:00",
        },
        exclusive=True,
    )

    bridge.claim("claude", "task-a")  # 过期锁必须可回收，否则崩溃即永久死锁

    task = json.loads(bridge.task_path("task-a").read_text(encoding="utf-8"))
    assert task["status"] == "claimed"
    assert task["claimed_at"] != "2000-01-01T00:00:00+00:00"


def test_release_unblocks_a_dead_claim(bridge) -> None:
    bridge.dispatch("claude", "task-a", "objective", [], "prompt")
    bridge.claim("claude", "task-a")

    bridge.release("claude", "task-a")

    assert not bridge.lock_path("task-a").exists()
    task = json.loads(bridge.task_path("task-a").read_text(encoding="utf-8"))
    assert task["status"] == "pending"
    bridge.claim("claude", "task-a")  # 释放后必须能重新认领


def test_report_enforces_status_machine(bridge) -> None:
    bridge.dispatch("claude", "task-a", "objective", [], "prompt")
    with pytest.raises(SystemExit, match="must be claimed"):
        bridge.report("claude", "task-a", "completed", "done", [], [])

    bridge.claim("claude", "task-a")
    bridge.report("claude", "task-a", "completed", "done", ["evidence"], [])

    with pytest.raises(SystemExit, match="already completed"):
        bridge.report("claude", "task-a", "blocked", "rolled back", [], [])


def test_corrupt_task_file_reports_an_actionable_error(bridge) -> None:
    bridge.ensure_bus()
    bridge.task_path("task-a").write_text('{"task_id": "task-a",', encoding="utf-8")

    with pytest.raises(SystemExit, match="corrupt"):
        bridge.claim("claude", "task-a")


def test_state_writes_leave_no_temporary_files_behind(bridge) -> None:
    bridge.dispatch("claude", "task-a", "objective", [], "prompt")
    bridge.claim("claude", "task-a")
    bridge.report("claude", "task-a", "needs-review", "summary", [], [])

    leftovers = [
        path.name
        for directory in (bridge.TASKS, bridge.REPORTS, bridge.LOCKS)
        for path in directory.iterdir()
        if path.name.startswith(".")
    ]
    assert leftovers == []
