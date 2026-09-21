"""基准测试子系统。

用于量化审查策略的实际效果：精确率、召回率、误报率、行号准确率。
"""

from ai_pr_review.benchmark.cases import BENCHMARK_CASES, get_case, load_cases
from ai_pr_review.benchmark.models import (
    BenchmarkCase,
    BenchmarkReport,
    CaseOutcome,
    ExpectedFinding,
)
from ai_pr_review.benchmark.runner import (
    STRATEGIES,
    run_all_strategies,
    run_benchmark,
)

__all__ = [
    "BENCHMARK_CASES",
    "STRATEGIES",
    "BenchmarkCase",
    "BenchmarkReport",
    "CaseOutcome",
    "ExpectedFinding",
    "get_case",
    "load_cases",
    "run_all_strategies",
    "run_benchmark",
]
