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
