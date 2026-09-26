"""Review 结果后处理模块。"""

from __future__ import annotations

from collections.abc import Hashable
from typing import Any

from ai_pr_review.config import PostProcessorConfig
from ai_pr_review.services.prompt_assembler import Finding, ReviewResult

SEVERITY_ORDER = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "info": 4,
}


class PostProcessor:
    """对 AI 审查结果执行统一后处理。"""

    def __init__(self, config: PostProcessorConfig | None = None):
        self._config = config or PostProcessorConfig()

    def process(self, result: ReviewResult) -> ReviewResult:
        """后处理 Review 结果。"""
        return self.process_with_stats(result)[0]

    def process_with_stats(self, result: ReviewResult) -> tuple[ReviewResult, dict[str, Any]]:
        """后处理 Review 结果，并返回本次后处理的计数。

        这是「按用户配置的门槛丢噪音 → 去重 → 按严重程度排序」的唯一实现：
        `process()` 委托给它，标准编排器与 hybrid 编排器因此共用同一套行为与
        同一份 `app_config.post_processor`。

        返回的 `stats` 只陈述事实，不估算，可直接落进 run metadata：

        | 键 | 含义 |
        |---|---|
        | `before` | 进入后处理的 finding 条数 |
        | `after` | 后处理之后剩下的条数 |
        | `below_threshold` | 因 `confidence_threshold` 被丢弃的条数 |
        | `duplicates` | 被去重规则合并掉的条数 |
        | `threshold` | 本次实际使用的置信度门槛（历史 Run 复现时据此披露，而不是读当前配置） |
        | `severity_sorted` | 返回的 finding 确实按严重程度有序（对结果的自检） |
        """
        above_threshold = self.filter_by_confidence(
            result.findings,
            threshold=self._config.confidence_threshold,
        )
        deduplicated = self.deduplicate(above_threshold)
        findings = self.sort_by_severity(deduplicated)

        payload = result.model_dump()
        payload["findings"] = [finding.model_dump() for finding in findings]
        processed = ReviewResult.model_validate(payload)

        severity_ranks = [SEVERITY_ORDER[finding.severity] for finding in findings]
        return processed, {
            "before": len(result.findings),
            "after": len(findings),
            "below_threshold": len(result.findings) - len(above_threshold),
            "duplicates": len(above_threshold) - len(deduplicated),
            # Store the threshold that was actually applied: republishing an old
            # run must not claim today's setting was used back then.
            "threshold": float(self._config.confidence_threshold),
            "severity_sorted": severity_ranks == sorted(severity_ranks),
        }

    def filter_by_confidence(self, findings: list[Finding], threshold: float) -> list[Finding]:
        """按置信度过滤。"""
        return [finding for finding in findings if finding.confidence >= threshold]

    def deduplicate(self, findings: list[Finding]) -> list[Finding]:
        """按配置规则去重。"""
        deduplication_rule = self._config.deduplication_rule or self._default_deduplication_rule
        best_by_key: dict[Hashable, Finding] = {}

        for finding in findings:
            key = deduplication_rule(finding)
            existing = best_by_key.get(key)
            if existing is None or self._is_better_finding(finding, existing):
                best_by_key[key] = finding

        return list(best_by_key.values())

    def sort_by_severity(self, findings: list[Finding]) -> list[Finding]:
        """按严重程度排序。"""
        return sorted(
            findings,
            key=lambda finding: (
                SEVERITY_ORDER[finding.severity],
                -finding.confidence,
                finding.file,
                finding.line_start,
                finding.line_end,
                finding.title,
            ),
        )

    def _default_deduplication_rule(self, finding: Finding) -> Hashable:
        # 同一文件、同一 10 行桶内视为重复：**刻意不按 category 分桶**。
        # 实测（PR #31 真实 run）：`website/js/main.js:86` 被写成两条
        # （high 94% 与 high 80%），只因分类不同就没被合并，报告里看着像
        # 两个独立缺陷。同位置的两条只会保留更强的那条（见 _is_better_finding）。
        return (
            finding.file,
            finding.line_start // 10,
        )

    def _is_better_finding(self, candidate: Finding, current: Finding) -> bool:
        candidate_rank = (
            -SEVERITY_ORDER[candidate.severity],
            candidate.confidence,
            -(candidate.line_end - candidate.line_start),
        )
        current_rank = (
            -SEVERITY_ORDER[current.severity],
            current.confidence,
            -(current.line_end - current.line_start),
        )
        return candidate_rank > current_rank
