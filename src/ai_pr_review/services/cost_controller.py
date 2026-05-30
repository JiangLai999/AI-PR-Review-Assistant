"""AI 成本控制模块。"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from ai_pr_review.config import CostControllerConfig


MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-20250514": (3.0, 15.0),
    "claude-sonnet": (3.0, 15.0),
}


@dataclass(slots=True)
class UsageRecord:
    timestamp: float
    cost: float
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


class CostController:
    """跟踪单次运行和滑动窗口成本。"""

    def __init__(self, config: CostControllerConfig, time_fn: Callable[[], float] | None = None):
        self._config = config
        self._time_fn = time_fn or time.time
        self._usage_history: deque[UsageRecord] = deque()
        self._run_total_cost = 0.0

    def check_budget(self, estimated_cost: float) -> bool:
        """检查是否有足够预算。"""
        self._prune_usage_history()
        projected_run_total = self._run_total_cost + estimated_cost
        projected_daily_total = self.get_daily_cost() + estimated_cost
        return (
            projected_run_total <= self._config.max_cost_per_run
            and projected_daily_total <= self._config.max_cost_per_24h
        )

    def record_usage(self, input_tokens: int, output_tokens: int, model: str) -> float:
        """记录 API 使用量并返回本次成本。"""
        self._prune_usage_history()
        cost = self.calculate_cost(input_tokens, output_tokens, model)
        record = UsageRecord(
            timestamp=self._time_fn(),
            cost=cost,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
        )
        self._usage_history.append(record)
        self._run_total_cost += cost
        return cost

    def calculate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        """按模型价格计算成本。"""
        input_price, output_price = self._get_model_pricing(model)
        input_cost = (input_tokens / 1_000_000) * input_price
        output_cost = (output_tokens / 1_000_000) * output_price
        return input_cost + output_cost

    def get_total_cost(self) -> float:
        """获取当前运行累计成本。"""
        return self._run_total_cost

    def get_daily_cost(self) -> float:
        """获取 24h 滑动窗口累计成本。"""
        self._prune_usage_history()
        return sum(record.cost for record in self._usage_history)

    def is_near_limit(self, estimated_cost: float = 0.0) -> bool:
        """判断追加指定成本后是否接近预算上限。"""
        self._prune_usage_history()
        run_ratio = (self._run_total_cost + estimated_cost) / self._config.max_cost_per_run
        daily_ratio = (self.get_daily_cost() + estimated_cost) / self._config.max_cost_per_24h
        return max(run_ratio, daily_ratio) >= self._config.warning_threshold

    def reset(self):
        """重置当前运行计数器。"""
        self._run_total_cost = 0.0
        self._usage_history.clear()

    def _get_model_pricing(self, model: str) -> tuple[float, float]:
        configured_pricing = (
            self._config.input_cost_per_million,
            self._config.output_cost_per_million,
        )
        if model in MODEL_PRICING:
            default_pricing = MODEL_PRICING[model]
            if configured_pricing != default_pricing:
                return configured_pricing
            return default_pricing

        if "sonnet" in model:
            default_pricing = MODEL_PRICING["claude-sonnet"]
            if configured_pricing != default_pricing:
                return configured_pricing
            return default_pricing

        return configured_pricing

    def _prune_usage_history(self) -> None:
        cutoff = self._time_fn() - (self._config.sliding_window_hours * 3600)
        while self._usage_history and self._usage_history[0].timestamp < cutoff:
            self._usage_history.popleft()
