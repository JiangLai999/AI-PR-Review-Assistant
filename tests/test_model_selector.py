"""测试双模型协作机制"""

import pytest

from ai_pr_review.config import AIClientConfig, AppConfig, PreferencesConfig
from ai_pr_review.services.model_selector import HybridStrategy, ModelSelector, TaskComplexity


def test_model_selector_evaluates_complexity_correctly():
    """测试文件复杂度评估"""
    config = AppConfig()
    selector = ModelSelector(config)

    # 低风险文件
    assert selector.evaluate_file_complexity("README.md", 10, 5) == TaskComplexity.TRIVIAL
    assert selector.evaluate_file_complexity("config.json", 20, 10) == TaskComplexity.TRIVIAL
    assert selector.evaluate_file_complexity("test_foo.py", 30, 10) == TaskComplexity.TRIVIAL

    # 高风险文件
    assert selector.evaluate_file_complexity("auth.py", 50, 20) == TaskComplexity.CRITICAL
    assert selector.evaluate_file_complexity("payment_handler.py", 100, 50) == TaskComplexity.CRITICAL
    assert selector.evaluate_file_complexity("security/token.py", 80, 30) == TaskComplexity.CRITICAL

    # 简单文件
    assert selector.evaluate_file_complexity("utils.py", 30, 10) == TaskComplexity.SIMPLE

    # 中等复杂度
    assert selector.evaluate_file_complexity("service.py", 150, 50) == TaskComplexity.MODERATE

    # 复杂文件（大量变更）
    assert selector.evaluate_file_complexity("main.py", 600, 200) == TaskComplexity.COMPLEX


def test_model_selector_quality_first_strategy():
    """测试质量优先策略"""
    config = AppConfig()
    config.preferences = PreferencesConfig(hybrid_strategy="quality_first")
    selector = ModelSelector(config)

    # 琐碎任务用本地
    provider, model, is_local = selector.select_model_for_task(
        "file_review", TaskComplexity.TRIVIAL
    )
    assert is_local is True

    # 中等及以上用远程
    provider, model, is_local = selector.select_model_for_task(
        "file_review", TaskComplexity.MODERATE
    )
    assert is_local is False

    provider, model, is_local = selector.select_model_for_task(
        "file_review", TaskComplexity.COMPLEX
    )
    assert is_local is False


def test_model_selector_cost_optimized_strategy():
    """测试成本优化策略"""
    config = AppConfig()
    config.preferences = PreferencesConfig(hybrid_strategy="cost_optimized")
    selector = ModelSelector(config)

    # 简单任务用本地
    provider, model, is_local = selector.select_model_for_task(
        "file_review", TaskComplexity.SIMPLE
    )
    assert is_local is True

    # 中等任务也用本地（成本优先）
    provider, model, is_local = selector.select_model_for_task(
        "file_review", TaskComplexity.MODERATE
    )
    assert is_local is True

    # 只有复杂和关键用远程
    provider, model, is_local = selector.select_model_for_task(
        "file_review", TaskComplexity.COMPLEX
    )
    assert is_local is False

    provider, model, is_local = selector.select_model_for_task(
        "file_review", TaskComplexity.CRITICAL
    )
    assert is_local is False


def test_model_selector_local_only_strategy():
    """测试仅本地策略"""
    config = AppConfig()
    config.preferences = PreferencesConfig(hybrid_strategy="local_only")
    selector = ModelSelector(config)

    # 所有任务都用本地
    for complexity in TaskComplexity:
        provider, model, is_local = selector.select_model_for_task(
            "file_review", complexity
        )
        # 如果本地模型可用，应该是 True
        if selector.local_provider:
            assert is_local is True


def test_model_selector_remote_only_strategy():
    """测试仅远程策略"""
    config = AppConfig()
    config.preferences = PreferencesConfig(hybrid_strategy="remote_only")
    selector = ModelSelector(config)

    # 所有任务都用远程
    for complexity in TaskComplexity:
        provider, model, is_local = selector.select_model_for_task(
            "file_review", complexity
        )
        assert is_local is False


def test_model_selector_tracks_statistics():
    """测试统计追踪"""
    config = AppConfig()
    selector = ModelSelector(config)

    # 调用几次
    selector.select_model_for_task("file_review", TaskComplexity.TRIVIAL)
    selector.select_model_for_task("file_review", TaskComplexity.COMPLEX)
    selector.select_model_for_task("file_review", TaskComplexity.SIMPLE)

    stats = selector.get_statistics()
    assert stats["total_calls"] == 3
    assert stats["local_calls"] + stats["remote_calls"] == 3
    assert 0 <= stats["local_percentage"] <= 100
    assert 0 <= stats["remote_percentage"] <= 100


def test_model_selector_cost_tracking():
    """测试成本追踪"""
    config = AppConfig()
    selector = ModelSelector(config)

    selector.record_cost(0.05)
    selector.record_cost(0.10)
    selector.record_cost(0.03)

    stats = selector.get_statistics()
    assert stats["total_cost"] == pytest.approx(0.18, abs=0.01)


def test_model_selector_should_use_remote_for_high_risk():
    """测试高风险上下文使用远程模型"""
    config = AppConfig()
    config.preferences = PreferencesConfig(hybrid_strategy="balanced")
    selector = ModelSelector(config)

    # 高风险等级
    context = {"risk_level": "high"}
    assert selector._should_use_remote(context) is True

    # 高风险文件路径
    context = {"file_path": "src/auth/login.py"}
    assert selector._should_use_remote(context) is True

    # 大变更
    context = {"additions": 400, "deletions": 100}
    assert selector._should_use_remote(context) is True


def test_model_selector_respects_cost_budget():
    """测试成本预算限制"""
    config = AppConfig()
    config.preferences = PreferencesConfig(hybrid_strategy="balanced", max_cost_per_review=0.10)
    config.ai_client = AIClientConfig()
    config.ai_client.max_cost_per_review = 0.10
    selector = ModelSelector(config)

    # 消耗预算
    selector.record_cost(0.12)  # 超过预算

    # 即使是中等复杂度，也应该用本地（预算耗尽）
    context = {"risk_level": "low"}
    assert selector._should_use_remote(context) is False
