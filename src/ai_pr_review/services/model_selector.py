"""智能模型选择器 - 根据任务复杂度和成本策略选择最优模型。"""

from __future__ import annotations

from enum import Enum
from typing import Any

from ai_pr_review.config import AIClientConfig, AppConfig
from ai_pr_review.services.model_providers.base import BaseModelProvider
from ai_pr_review.services.model_providers.factory import create_model_provider


class TaskComplexity(Enum):
    """任务复杂度等级"""

    TRIVIAL = "trivial"  # 琐碎任务（配置文件、文档）- 本地模型足够
    SIMPLE = "simple"  # 简单任务（工具函数、简单修改）- 本地模型可以
    MODERATE = "moderate"  # 中等任务（业务逻辑）- 需要判断
    COMPLEX = "complex"  # 复杂任务（复杂逻辑、架构）- 远程模型
    CRITICAL = "critical"  # 关键任务（安全、认证、支付）- 必须远程模型


class HybridStrategy(Enum):
    """混合策略"""

    QUALITY_FIRST = "quality_first"  # 质量优先：中等以上用远程
    COST_OPTIMIZED = "cost_optimized"  # 成本优化：只有复杂和关键用远程
    BALANCED = "balanced"  # 平衡：根据上下文智能决策
    LOCAL_ONLY = "local_only"  # 仅本地：全部用本地模型（离线模式）
    REMOTE_ONLY = "remote_only"  # 仅远程：全部用远程模型（质量最大化）


class ModelSelector:
    """智能模型选择器 - 实现双模型协作的核心决策逻辑"""

    # 高风险文件模式
    HIGH_RISK_PATTERNS = [
        "auth",
        "login",
        "password",
        "credential",
        "secret",
        "token",
        "payment",
        "transaction",
        "security",
        "crypto",
        "sign",
        "verify",
    ]

    # 低风险文件模式
    LOW_RISK_PATTERNS = [
        ".md",
        ".txt",
        ".json",
        ".yml",
        ".yaml",
        ".toml",
        ".ini",
        ".cfg",
        "test_",
        "_test.",
        ".test.",
        ".spec.",
        "readme",
        "changelog",
        "license",
    ]

    def __init__(self, config: AppConfig):
        self.config = config
        self.ai_config = config.ai_client

        # 创建本地模型 provider
        try:
            from ai_pr_review.config import ModelProviderConfig

            local_config = ModelProviderConfig.from_name("ollama")
            self.local_provider = create_model_provider(local_config)
            self.local_model = getattr(self.ai_config, "local_model", "qwen3.5:4b")
        except Exception:
            self.local_provider = None
            self.local_model = None

        # 创建远程模型 provider
        self.remote_provider = create_model_provider(self.ai_config.model_provider)
        self.remote_model = self.ai_config.model

        # 获取策略
        self.strategy = self._get_strategy()

        # 成本追踪
        self.total_cost = 0.0
        self.local_calls = 0
        self.remote_calls = 0

    def _get_strategy(self) -> HybridStrategy:
        """获取混合策略"""
        # 从配置读取，默认为 balanced
        strategy_name = getattr(
            getattr(self.config, "preferences", None), "hybrid_strategy", "balanced"
        )

        try:
            return HybridStrategy(strategy_name)
        except ValueError:
            return HybridStrategy.BALANCED

    def select_model_for_task(
        self,
        task_type: str,
        complexity: TaskComplexity,
        context: dict[str, Any] | None = None,
    ) -> tuple[BaseModelProvider, str, bool]:
        """为任务选择合适的模型

        Args:
            task_type: 任务类型（如 "file_review", "chat", "formatting"）
            complexity: 任务复杂度
            context: 上下文信息（文件路径、风险等级、当前成本等）

        Returns:
            (provider, model_name, is_local) 元组
        """
        context = context or {}

        # 1. 检查强制策略
        if self.strategy == HybridStrategy.LOCAL_ONLY:
            if self.local_provider:
                self.local_calls += 1
                return self.local_provider, self.local_model, True
            # 如果本地不可用，降级到远程
            self.remote_calls += 1
            return self.remote_provider, self.remote_model, False

        if self.strategy == HybridStrategy.REMOTE_ONLY:
            self.remote_calls += 1
            return self.remote_provider, self.remote_model, False

        # 2. 检查是否本地模型不可用
        if not self.local_provider:
            self.remote_calls += 1
            return self.remote_provider, self.remote_model, False

        # 3. 检查任务类型是否明确归属本地
        local_tasks = {
            "intent_recognition",
            "action_routing",
            "result_formatting",
            "simple_classification",
            "template_generation",
        }
        if task_type in local_tasks:
            self.local_calls += 1
            return self.local_provider, self.local_model, True

        # 4. 检查任务类型是否明确归属远程
        remote_tasks = {
            "deep_code_analysis",
            "security_analysis",
            "cross_file_reasoning",
            "complex_recommendation",
        }
        if task_type in remote_tasks:
            self.remote_calls += 1
            return self.remote_provider, self.remote_model, False

        # 5. 根据复杂度和策略决策
        if self.strategy == HybridStrategy.QUALITY_FIRST:
            # 质量优先：中等以上用远程
            if complexity in {TaskComplexity.MODERATE, TaskComplexity.COMPLEX, TaskComplexity.CRITICAL}:
                self.remote_calls += 1
                return self.remote_provider, self.remote_model, False
            self.local_calls += 1
            return self.local_provider, self.local_model, True

        elif self.strategy == HybridStrategy.COST_OPTIMIZED:
            # 成本优化：只有复杂和关键用远程
            if complexity in {TaskComplexity.COMPLEX, TaskComplexity.CRITICAL}:
                self.remote_calls += 1
                return self.remote_provider, self.remote_model, False
            self.local_calls += 1
            return self.local_provider, self.local_model, True

        else:  # BALANCED
            # 平衡策略：智能决策
            # 琐碎和简单：用本地
            if complexity in {TaskComplexity.TRIVIAL, TaskComplexity.SIMPLE}:
                self.local_calls += 1
                return self.local_provider, self.local_model, True

            # 关键：必须远程
            if complexity == TaskComplexity.CRITICAL:
                self.remote_calls += 1
                return self.remote_provider, self.remote_model, False

            # 中等和复杂：看上下文
            if self._should_use_remote(context):
                self.remote_calls += 1
                return self.remote_provider, self.remote_model, False

            self.local_calls += 1
            return self.local_provider, self.local_model, True

    def _should_use_remote(self, context: dict[str, Any]) -> bool:
        """判断是否应该使用远程模型（平衡策略下的智能决策）"""

        # 1. 检查风险等级
        risk_level = context.get("risk_level", "low")
        if risk_level in {"high", "critical"}:
            return True

        # 2. 检查成本预算
        max_cost = getattr(self.ai_config, "max_cost_per_review", 0.5)
        if self.total_cost >= max_cost:
            return False  # 预算用完，用本地

        # 3. 检查文件路径
        file_path = context.get("file_path", "").lower()
        if any(pattern in file_path for pattern in self.HIGH_RISK_PATTERNS):
            return True

        # 4. 检查是否有静态规则命中高危问题
        static_findings = context.get("static_findings", [])
        if static_findings:
            critical_findings = [
                f for f in static_findings if getattr(f, "severity", "low") in {"high", "critical"}
            ]
            if critical_findings:
                return True

        # 5. 检查变更量
        additions = context.get("additions", 0)
        deletions = context.get("deletions", 0)
        total_changes = additions + deletions
        if total_changes > 300:  # 大变更用远程
            return True

        # 默认用本地
        return False

    def evaluate_file_complexity(
        self,
        file_path: str,
        additions: int = 0,
        deletions: int = 0,
        static_findings: list[Any] | None = None,
    ) -> TaskComplexity:
        """评估文件复杂度

        Args:
            file_path: 文件路径
            additions: 新增行数
            deletions: 删除行数
            static_findings: 静态规则发现的问题列表

        Returns:
            TaskComplexity 复杂度等级
        """
        file_lower = file_path.lower()

        # 1. 检查是否低风险文件类型
        if any(pattern in file_lower for pattern in self.LOW_RISK_PATTERNS):
            return TaskComplexity.TRIVIAL

        # 2. 检查是否高风险文件
        if any(pattern in file_lower for pattern in self.HIGH_RISK_PATTERNS):
            return TaskComplexity.CRITICAL

        # 3. 检查变更量
        total_changes = additions + deletions
        if total_changes > 500:
            return TaskComplexity.COMPLEX
        if total_changes > 200:
            return TaskComplexity.MODERATE

        # 4. 检查静态规则命中情况
        if static_findings:
            critical_count = sum(
                1 for f in static_findings if getattr(f, "severity", "low") in {"critical", "high"}
            )
            if critical_count > 0:
                return TaskComplexity.COMPLEX
            if len(static_findings) > 3:
                return TaskComplexity.MODERATE

        # 5. 默认为简单
        if total_changes < 50:
            return TaskComplexity.SIMPLE

        return TaskComplexity.MODERATE

    def get_statistics(self) -> dict[str, Any]:
        """获取使用统计"""
        total_calls = self.local_calls + self.remote_calls
        local_percentage = (self.local_calls / total_calls * 100) if total_calls > 0 else 0
        remote_percentage = (self.remote_calls / total_calls * 100) if total_calls > 0 else 0

        return {
            "total_calls": total_calls,
            "local_calls": self.local_calls,
            "remote_calls": self.remote_calls,
            "local_percentage": round(local_percentage, 1),
            "remote_percentage": round(remote_percentage, 1),
            "total_cost": round(self.total_cost, 4),
            "strategy": self.strategy.value,
        }

    def record_cost(self, cost: float) -> None:
        """记录单次调用成本"""
        self.total_cost += cost
