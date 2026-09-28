"""确定性分析结果的合并与去重。

逐行规则和 AST 规则会独立命中同一处缺陷（例如同一行的硬编码密钥既被
逐行规则匹配、又被 AST 规则匹配）。把这些结果合并时按
`(文件, 行, 类别)` 去重，避免同一问题在报告里出现多次。
"""

from __future__ import annotations

from collections.abc import Iterable

from ai_pr_review.services.prompt_assembler import Finding

# 同一处缺陷在不同规则下可能体现为不同标题，这里给出等价组，
# 便于在判定重复时把它们视为同一个问题。
_EQUIVALENT_TITLES = (
    frozenset(
        {
            "Possible hard-coded secret",
            "Possible hard-coded credential constant",
        }
    ),
    frozenset(
        {
            "TLS certificate verification disabled",
        }
    ),
)


def _equivalence_key(title: str) -> str:
    for group in _EQUIVALENT_TITLES:
        if title in group:
            return "|".join(sorted(group))
    return title


def _deduplication_key(finding: Finding) -> tuple[str, int, str, str]:
    return (
        finding.file,
        finding.line_start,
        finding.category,
        _equivalence_key(finding.title),
    )


def combine_findings(*groups: Iterable[Finding]) -> list[Finding]:
    """合并多组确定性发现并按位置去重。

    去重保留置信度更高的那条；置信度相同时保留先出现的（顺序稳定）。
    """
    best: dict[tuple[str, int, str, str], Finding] = {}
    for group in groups:
        for finding in group:
            key = _deduplication_key(finding)
            existing = best.get(key)
            if existing is None or finding.confidence > existing.confidence:
                best[key] = finding
    return list(best.values())


__all__ = ["combine_findings"]
