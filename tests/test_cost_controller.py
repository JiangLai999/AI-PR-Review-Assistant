"""Cost Controller 模块单元测试。"""

from __future__ import annotations

import pytest

from ai_pr_review.config import CostControllerConfig
from ai_pr_review.services.cost_controller import CostController


def test_record_usage_updates_run_and_daily_costs():
    controller = CostController(CostControllerConfig(), time_fn=lambda: 1_000.0)

    cost = controller.record_usage(1_000_000, 1_000_000, "claude-sonnet-4-20250514")

    assert cost == pytest.approx(18.0)
    assert controller.get_total_cost() == pytest.approx(18.0)
    assert controller.get_daily_cost() == pytest.approx(18.0)


def test_check_budget_uses_current_run_total():
    controller = CostController(CostControllerConfig(run_limit=5.0), time_fn=lambda: 1_000.0)
    controller.record_usage(1_000_000, 0, "claude-sonnet-4-20250514")

    assert controller.check_budget(1.9) is True
    assert controller.check_budget(2.1) is False


def test_check_budget_uses_24h_sliding_window():
    current_time = 90_000.0
    controller = CostController(
        CostControllerConfig(run_limit=100.0, daily_limit=50.0),
        time_fn=lambda: current_time,
    )
    controller.record_usage(1_000_000, 1_000_000, "claude-sonnet-4-20250514")
    controller.record_usage(1_000_000, 1_000_000, "claude-sonnet-4-20250514")

    assert controller.get_daily_cost() == pytest.approx(36.0)
    assert controller.check_budget(2.0) is True
    assert controller.check_budget(14.1) is False


def test_get_daily_cost_prunes_expired_records():
    current_time = 10.0
    controller = CostController(
        CostControllerConfig(run_limit=100.0, daily_limit=100.0),
        time_fn=lambda: current_time,
    )
    controller.record_usage(1_000_000, 0, "claude-sonnet-4-20250514")
    current_time = 20.0
    controller.record_usage(1_000_000, 1_000_000, "claude-sonnet-4-20250514")
    current_time = 90_000.0

    assert controller.get_daily_cost() == pytest.approx(0.0)
    assert controller.get_total_cost() == pytest.approx(21.0)


def test_is_near_limit_uses_warning_threshold():
    controller = CostController(
        CostControllerConfig(run_limit=10.0, daily_limit=100.0, warning_threshold=0.8),
        time_fn=lambda: 1_000.0,
    )
    controller.record_usage(1_000_000, 0, "claude-sonnet-4-20250514")
    controller.record_usage(1_000_000, 0, "claude-sonnet-4-20250514")

    assert controller.is_near_limit(1.9) is False
    assert controller.is_near_limit(2.0) is True


def test_reset_clears_usage_state():
    controller = CostController(CostControllerConfig(), time_fn=lambda: 1_000.0)
    controller.record_usage(1_000_000, 1_000_000, "claude-sonnet-4-20250514")

    controller.reset()

    assert controller.get_total_cost() == 0.0
    assert controller.get_daily_cost() == 0.0


# ---------------------------------------------------------------------------
# 共享账本（跨槽位预算闭环，2026-09-28）
#
# hybrid 编排器为 local / remote 各建一个 AIClient。若两者各持一份累计账本，
# `max_cost_per_run` / 24h 预算会被按槽位数稀释 —— 各花一半即可分别绕过。
# 修法是让它们共享 **CostLedger**（只共享累计，不共享价目）。
# ---------------------------------------------------------------------------


def test_shared_ledger_accumulates_across_controllers():
    """两个 controller 共享账本时，任一方都能看到对方花掉的钱。"""
    from ai_pr_review.services.cost_controller import CostLedger

    ledger = CostLedger()
    remote = CostController(
        CostControllerConfig(run_limit=0.5), time_fn=lambda: 1_000.0, ledger=ledger
    )
    local = CostController(
        CostControllerConfig(run_limit=0.5), time_fn=lambda: 1_000.0, ledger=ledger
    )

    remote.record_usage(100_000, 0, "claude-sonnet-4-20250514")  # 0.3
    assert local.get_total_cost() == pytest.approx(0.3)
    local.record_usage(100_000, 0, "claude-sonnet-4-20250514")  # 0.3
    assert remote.get_total_cost() == pytest.approx(0.6)

    # 关键：预算判定看的是**合计** 0.6 —— 不共享时两边各 0.3，都会放行
    assert remote.check_budget(0.0) is False
    assert local.check_budget(0.0) is False


def test_shared_ledger_keeps_each_controllers_pricing():
    """反向锁死：共享的只能是**账本**，不能是 controller —— 否则本地调用按云端价计费。

    真实事故：`_client_config_for` 的注释记录过 local_only 却报 $0.0311，
    根因就是本地模型（不在 MODEL_PRICING 表里）退回了 controller 自己的价目。
    """
    from ai_pr_review.services.cost_controller import CostLedger

    ledger = CostLedger()
    cloud_priced = CostController(
        CostControllerConfig(input_cost_per_million=3.0, output_cost_per_million=15.0),
        time_fn=lambda: 1_000.0,
        ledger=ledger,
    )
    local_priced = CostController(
        CostControllerConfig(input_cost_per_million=0.0, output_cost_per_million=0.0),
        time_fn=lambda: 1_000.0,
        ledger=ledger,
    )

    assert cloud_priced.record_usage(1_000_000, 0, "some-cloud-model") == pytest.approx(3.0)
    assert local_priced.record_usage(1_000_000, 0, "qwen3.5:4b") == pytest.approx(0.0)
    # 本地那次没有被按点价：合计仍是 3.0（若共用一个 controller 会变成 6.0）
    assert ledger.run_total == pytest.approx(3.0)


def test_shared_ledger_shares_the_24h_window_and_reset():
    """24h 滑动窗口同属账本；reset 会清空所有共用它的 controller。"""
    from ai_pr_review.services.cost_controller import CostLedger

    ledger = CostLedger()
    a = CostController(CostControllerConfig(), time_fn=lambda: 1_000.0, ledger=ledger)
    b = CostController(CostControllerConfig(), time_fn=lambda: 1_000.0, ledger=ledger)

    a.record_usage(1_000_000, 0, "claude-sonnet-4-20250514")  # 3.0
    assert b.get_daily_cost() == pytest.approx(3.0)

    b.reset()
    assert a.get_total_cost() == 0.0
    assert a.get_daily_cost() == 0.0
    assert b.get_daily_cost() == 0.0


def test_ledger_is_optional_and_defaults_to_private_accounting():
    """不传 ledger 时行为与改造前一致：各 controller 各算各的。"""
    a = CostController(CostControllerConfig(), time_fn=lambda: 1_000.0)
    b = CostController(CostControllerConfig(), time_fn=lambda: 1_000.0)

    a.record_usage(1_000_000, 0, "claude-sonnet-4-20250514")

    assert a.get_total_cost() == pytest.approx(3.0)
    assert b.get_total_cost() == 0.0
    assert a.ledger is not b.ledger
