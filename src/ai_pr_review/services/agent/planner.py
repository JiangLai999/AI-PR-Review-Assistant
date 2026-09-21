"""Deterministic review planning before AI analysis."""

from __future__ import annotations

import re
from collections.abc import Iterable

from ai_pr_review.models.pr_data import FileDiff, PRData
from ai_pr_review.models.review_plan import ReviewPlan
from ai_pr_review.services.filter_pipeline import FilterPipelineResult


class ReviewPlanner:
    """Build a transparent, deterministic plan from PR metadata and files."""

    _RISK_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("security", ("auth", "login", "permission", "token", "secret", "password", "crypto")),
        ("resource", ("db", "database", "cache", "queue", "connection", "file", "stream")),
        ("concurrency", ("async", "thread", "lock", "worker", "queue", "concurrent")),
        ("correctness", ("api", "service", "controller", "router", "model", "schema")),
        ("performance", ("query", "search", "batch", "loop", "index")),
    )
    _HIGH_RISK_TERMS = ("security", "auth", "login", "permission", "payment", "database", "token")

    def build_plan(self, pr_data: PRData, filter_result: FilterPipelineResult) -> ReviewPlan:
        included = filter_result.included_files
        searchable_text = " ".join(
            [pr_data.title, pr_data.description or "", *(file.filename for file in pr_data.files)]
        ).lower()
        categories = self._detect_categories(searchable_text, included)
        high_risk = any(term in searchable_text for term in self._HIGH_RISK_TERMS)
        risk_level = "high" if high_risk else ("medium" if categories else "low")
        if any(file.changes > 250 for file in included):
            risk_level = "high" if risk_level == "medium" else risk_level

        priority_files = sorted(
            (file.filename for file in included),
            key=lambda filename: self._priority_key(filename, categories),
        )
        strategies = ["changed_line_review", "evidence_validation"]
        rationale = ["Review scope is derived from the PR metadata and included file set."]
        if categories:
            strategies.append("risk_category_review")
            rationale.append(f"Detected risk categories: {', '.join(categories)}.")
        requires_cross_file = len(included) > 1 or any(
            token in searchable_text for token in ("api", "refactor", "rename", "schema", "config")
        )
        if requires_cross_file:
            strategies.append("cross_file_impact_review")
            rationale.append(
                "Multiple files or interface-sensitive terms require a cross-file pass."
            )

        return ReviewPlan(
            intent=self._infer_intent(pr_data.title, pr_data.description),
            risk_level=risk_level,
            risk_categories=categories,
            priority_files=priority_files,
            skipped_files=[file.filename for file in filter_result.excluded_files],
            strategies=strategies,
            requires_cross_file_analysis=requires_cross_file,
            estimated_file_reviews=len(included),
            rationale=rationale,
        )

    def _detect_categories(self, text: str, files: Iterable[FileDiff]) -> list[str]:
        file_text = " ".join(file.filename.lower() for file in files)
        combined = f"{text} {file_text}"
        categories = [
            category
            for category, terms in self._RISK_PATTERNS
            if any(re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", combined) for term in terms)
        ]
        return categories or ["correctness", "error_handling"]

    def _priority_key(self, filename: str, categories: list[str]) -> tuple[int, str]:
        lowered = filename.lower()
        priority_terms = {
            "security": ("auth", "login", "permission", "token", "secret"),
            "resource": ("db", "database", "connection", "cache"),
            "correctness": ("api", "service", "controller", "router"),
        }
        score = min(
            (
                index
                for index, category in enumerate(categories)
                for term in priority_terms.get(category, ())
                if term in lowered
            ),
            default=99,
        )
        return score, filename

    def _infer_intent(self, title: str, description: str | None) -> str:
        text = " ".join(value.strip() for value in (title, description or "") if value.strip())
        return text or "Review the pull request for correctness and security risks."
