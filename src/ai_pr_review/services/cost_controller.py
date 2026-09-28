"""AI 成本控制模块。"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

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


@dataclass(slots=True)
class CostLedger:
    """可被**多个 CostController 共享**的累计账本。

    为什么需要它：hybrid 编排器为 local / remote 各建一个 AIClient，各自持有
    CostController；预算判定读的是"本 controller 累计"，于是两个槽位各花一半
    就能分别绕过 `max_cost_per_run`（run 级预算被按槽位数稀释）。
    让它们共用同一个 ledger，累计值与 24h 窗口就统一了。

    为什么不让两个客户端**共用一个 CostController**：`_get_model_pricing()` 对未知
    模型（本地 qwen 之类）会退回 **controller 自己的 config 价目**；共用后本地调用
    会被按云端价计费 —— 正是 `hybrid_orchestrator._client_config_for` 注释里记录过的
    「local_only 却报 $0.0311」事故。ledger 只管累计、不管价目，两个诉求互不干扰。
    """

    run_total: float = 0.0
    usage_history: deque[UsageRecord] = field(default_factory=deque)


class CostController:
    """跟踪单次运行和滑动窗口成本。"""

    def __init__(
        self,
        config: CostControllerConfig,
        time_fn: Callable[[], float] | None = None,
        ledger: CostLedger | None = None,
    ):
        self._config = config
        self._time_fn = time_fn or time.time
        # 不传 ledger 就自建一个 ⇒ 行为与改造前逐字相同（既有调用方零改动）。
        self._ledger = ledger if ledger is not None else CostLedger()
        # `_usage_history` 保持指向**同一个 deque**：`tests/test_ai_client.py` 会直接
        # 往 `client._usage_history` 里 append 记录来构造 24h 窗口场景。
        self._usage_history: deque[UsageRecord] = self._ledger.usage_history

    @property
    def ledger(self) -> CostLedger:
        """当前生效的账本（共享时即调用方传入的那一个）。"""
        return self._ledger

    def check_budget(self, estimated_cost: float) -> bool:
        """检查是否有足够预算。"""
        self._prune_usage_history()
        projected_run_total = self._ledger.run_total + estimated_cost
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
        self._ledger.run_total += cost
        return cost

    def calculate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        """按模型价格计算成本。"""
        input_price, output_price = self._get_model_pricing(model)
        input_cost = (input_tokens / 1_000_000) * input_price
        output_cost = (output_tokens / 1_000_000) * output_price
        return input_cost + output_cost

    def get_total_cost(self) -> float:
        """获取当前运行累计成本。"""
        return self._ledger.run_total

    def get_daily_cost(self) -> float:
        """获取 24h 滑动窗口累计成本。"""
        self._prune_usage_history()
        return sum(record.cost for record in self._usage_history)

    def is_near_limit(self, estimated_cost: float = 0.0) -> bool:
        """判断追加指定成本后是否接近预算上限。"""
        self._prune_usage_history()
        run_ratio = (self._ledger.run_total + estimated_cost) / self._config.max_cost_per_run
        daily_ratio = (self.get_daily_cost() + estimated_cost) / self._config.max_cost_per_24h
        return max(run_ratio, daily_ratio) >= self._config.warning_threshold

    def reset(self):
        """重置当前运行计数器（共享账本时，所有共用它的 controller 一起归零）。"""
        self._ledger.run_total = 0.0
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
