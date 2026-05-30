"""Post-Processor 模块单元测试。"""

from ai_pr_review.config import PostProcessorConfig
from ai_pr_review.services.post_processor import PostProcessor
from ai_pr_review.services.prompt_assembler import Finding, ReviewResult


def build_finding(
    *,
    severity: str = "medium",
    category: str = "correctness",
    file: str = "src/app.py",
    line_start: int = 10,
    line_end: int = 10,
    title: str = "Issue",
    problem: str = "Something is wrong.",
    suggestion: str = "Fix it.",
    confidence: float = 0.8,
    code_snippet: str = "pass",
) -> Finding:
    return Finding(
        severity=severity,
        category=category,
        file=file,
        line_start=line_start,
        line_end=line_end,
        title=title,
        problem=problem,
        suggestion=suggestion,
        confidence=confidence,
        code_snippet=code_snippet,
    )


class TestPostProcessor:
    def test_filter_by_confidence_drops_low_confidence_findings(self):
        processor = PostProcessor()
        findings = [
            build_finding(title="keep", confidence=0.6),
            build_finding(title="drop", confidence=0.59),
        ]

        result = processor.filter_by_confidence(findings, threshold=0.6)

        assert [finding.title for finding in result] == ["keep"]

    def test_deduplicate_uses_default_same_file_category_and_line_bucket_rule(self):
        processor = PostProcessor()
        findings = [
            build_finding(
                severity="medium",
                category="security",
                file="src/app.py",
                line_start=12,
                line_end=13,
                title="lower confidence",
                confidence=0.7,
            ),
            build_finding(
                severity="high",
                category="security",
                file="src/app.py",
                line_start=18,
                line_end=19,
                title="higher severity",
                confidence=0.65,
            ),
            build_finding(
                severity="high",
                category="security",
                file="src/app.py",
                line_start=25,
                line_end=26,
                title="different bucket",
                confidence=0.9,
            ),
        ]

        result = processor.deduplicate(findings)

        assert len(result) == 2
        assert {finding.title for finding in result} == {"higher severity", "different bucket"}

    def test_deduplicate_supports_custom_rule(self):
        processor = PostProcessor(
            PostProcessorConfig(deduplication_rule=lambda finding: finding.file)
        )
        findings = [
            build_finding(file="src/a.py", title="A1", confidence=0.7),
            build_finding(file="src/a.py", title="A2", confidence=0.9),
            build_finding(file="src/b.py", title="B1", confidence=0.8),
        ]

        result = processor.deduplicate(findings)

        assert len(result) == 2
        assert {finding.title for finding in result} == {"A2", "B1"}

    def test_sort_by_severity_orders_from_critical_to_info(self):
        processor = PostProcessor()
        findings = [
            build_finding(severity="low", title="low"),
            build_finding(severity="critical", title="critical"),
            build_finding(severity="info", title="info"),
            build_finding(severity="high", title="high"),
            build_finding(severity="medium", title="medium"),
        ]

        result = processor.sort_by_severity(findings)

        assert [finding.title for finding in result] == [
            "critical",
            "high",
            "medium",
            "low",
            "info",
        ]

    def test_process_applies_filter_dedup_and_sort_and_returns_valid_result(self):
        processor = PostProcessor(PostProcessorConfig(confidence_threshold=0.75))
        review_result = ReviewResult(
            summary="raw summary",
            findings=[
                build_finding(
                    severity="low",
                    category="security",
                    file="src/app.py",
                    line_start=12,
                    line_end=12,
                    title="duplicate low",
                    confidence=0.8,
                ),
                build_finding(
                    severity="high",
                    category="security",
                    file="src/app.py",
                    line_start=15,
                    line_end=16,
                    title="duplicate high",
                    confidence=0.85,
                ),
                build_finding(
                    severity="critical",
                    file="src/db.py",
                    line_start=30,
                    line_end=33,
                    title="critical issue",
                    confidence=0.95,
                ),
                build_finding(
                    severity="medium",
                    file="src/skip.py",
                    line_start=40,
                    line_end=40,
                    title="too uncertain",
                    confidence=0.5,
                ),
            ],
        )

        result = processor.process(review_result)

        assert result.summary == "raw summary"
        assert [finding.title for finding in result.findings] == [
            "critical issue",
            "duplicate high",
        ]
