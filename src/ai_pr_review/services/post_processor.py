"""Review 结果后处理模块。"""

from __future__ import annotations

from collections.abc import Hashable

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
        findings = self.filter_by_confidence(
            result.findings,
            threshold=self._config.confidence_threshold,
        )
        findings = self.deduplicate(findings)
        findings = self.sort_by_severity(findings)
        payload = result.model_dump()
        payload["findings"] = [finding.model_dump() for finding in findings]
        return ReviewResult.model_validate(payload)

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
        return (
            finding.file,
            finding.category,
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
