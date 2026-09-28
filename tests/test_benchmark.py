"""基准评测体系的测试。"""

from __future__ import annotations

from ai_pr_review.benchmark.cases import BENCHMARK_CASES, get_case, load_cases
from ai_pr_review.benchmark.models import BenchmarkCase, CaseOutcome, ExpectedFinding
from ai_pr_review.benchmark.runner import (
    STRATEGIES,
    TITLE_TO_RULE,
    build_changed_file,
    run_all_strategies,
    run_benchmark,
    score_case,
)
from ai_pr_review.services.prompt_assembler import Finding


def make_finding(rule_title: str, line: int, category: str = "security", confidence: float = 0.9):
    return Finding(
        severity="high",
        category=category,
        file="src/sample.py",
        line_start=line,
        line_end=line,
        title=rule_title,
        problem="p",
        suggestion="s",
        confidence=confidence,
        code_snippet="x",
        sources=["static_rule"],
    )


class TestCaseLibrary:
    def test_cases_have_unique_ids(self):
        ids = [case.case_id for case in BENCHMARK_CASES]

        assert len(ids) == len(set(ids))

    def test_load_cases_returns_independent_copy(self):
        first = load_cases()
        first.clear()

        assert len(load_cases()) == len(BENCHMARK_CASES)

    def test_expected_lines_are_inside_source(self):
        for case in BENCHMARK_CASES:
            line_count = len(case.source.splitlines())
            for expected in case.expected:
                assert 1 <= expected.line <= line_count, (
                    f"{case.case_id}/{expected.rule} points to line {expected.line} "
                    f"but the sample only has {line_count} lines"
                )

    def test_every_expected_rule_is_mapped(self):
        for case in BENCHMARK_CASES:
            for expected in case.expected:
                assert expected.rule in set(
                    TITLE_TO_RULE.values()
                ), f"{case.case_id} expects rule {expected.rule} which no analyzer reports"

    def test_get_case_raises_for_unknown_id(self):
        try:
            get_case("does-not-exist")
        except KeyError:
            return
        raise AssertionError("expected KeyError for an unknown case id")

    def test_there_is_a_negative_control_case(self):
        assert any(case.expected == [] for case in BENCHMARK_CASES)

    def test_changed_file_covers_all_lines(self):
        case = get_case("correctness-python-01")

        file_diff, context = build_changed_file(case)

        assert file_diff.filename == case.filename
        assert file_diff.additions == len(case.source.splitlines())
        assert context.language == case.language


class TestMetrics:
    def test_all_metrics_when_everything_matches(self):
        outcome = CaseOutcome(case_id="c", strategy="s", true_positives=4)

        assert outcome.precision == 1.0
        assert outcome.recall == 1.0
        assert outcome.f1 == 1.0
        assert outcome.false_positive_rate == 0.0

    def test_metrics_are_zero_without_predictions(self):
        outcome = CaseOutcome(case_id="c", strategy="s")

        assert outcome.precision == 0.0
        assert outcome.recall == 0.0
        assert outcome.f1 == 0.0

    def test_false_positive_rate_reflects_noise(self):
        outcome = CaseOutcome(case_id="c", strategy="s", true_positives=1, false_positives=3)

        assert outcome.precision == 0.25
        assert outcome.false_positive_rate == 0.75

    def test_line_accuracy_requires_exact_line(self):
        outcome = CaseOutcome(case_id="c", strategy="s", true_positives=4, line_hits=2)

        assert outcome.line_accuracy == 0.5


class TestScoreCase:
    def _case(self) -> BenchmarkCase:
        return BenchmarkCase(
            case_id="unit-case",
            filename="src/sample.py",
            language="python",
            source="a = 1\nb = 2\nc = 3\n",
            expected=[
                ExpectedFinding(
                    rule="sql_interpolation", line=1, severity="high", category="security"
                ),
                ExpectedFinding(
                    rule="bare_except", line=3, severity="medium", category="error_handling"
                ),
            ],
        )

    def test_counts_true_positives_and_hits(self):
        findings = [
            make_finding("Possible SQL injection", 1),
            make_finding("Bare except swallows every exception", 3, category="error_handling"),
        ]

        outcome = score_case(self._case(), "unit", findings)

        assert outcome.true_positives == 2
        assert outcome.false_negatives == 0
        assert outcome.false_positives == 0
        assert outcome.line_hits == 2

    def test_counts_missed_rules(self):
        outcome = score_case(self._case(), "unit", [make_finding("Possible SQL injection", 1)])

        assert outcome.true_positives == 1
        assert outcome.false_negatives == 1
        assert outcome.missed_rules == ["bare_except"]

    def test_counts_unexpected_findings(self):
        findings = [
            make_finding("Possible SQL injection", 1),
            make_finding("Bare except swallows every exception", 3, category="error_handling"),
            make_finding("Debug mode may be enabled in production", 2),
        ]

        outcome = score_case(self._case(), "unit", findings)

        assert outcome.false_positives == 1
        assert outcome.unexpected_titles == ["Debug mode may be enabled in production"]

    def test_tolerates_off_by_one_line(self):
        findings = [make_finding("Possible SQL injection", 2)]

        outcome = score_case(self._case(), "unit", findings)

        assert outcome.true_positives == 1
        # 行号偏差在容差内视为命中，但不计入严格行号准确率。
        assert outcome.line_hits == 0

    def test_rule_with_large_line_offset_still_counts_as_hit(self):
        findings = [make_finding("Possible SQL injection", 99)]

        outcome = score_case(self._case(), "unit", findings)

        assert outcome.true_positives == 1
        assert outcome.line_hits == 0

    def test_duplicate_findings_are_consumed_once(self):
        findings = [
            make_finding("Possible SQL injection", 1),
            make_finding("Possible SQL injection", 1),
            make_finding("Bare except swallows every exception", 3, category="error_handling"),
        ]

        outcome = score_case(self._case(), "unit", findings)

        assert outcome.true_positives == 2
        assert outcome.false_positives == 1


class TestRunBenchmark:
    def test_unknown_strategy_raises(self):
        try:
            run_benchmark("nope")
        except KeyError:
            return
        raise AssertionError("expected KeyError for an unknown strategy")

    def test_all_strategies_run(self):
        reports = run_all_strategies()

        assert set(reports) == set(STRATEGIES)
        for report in reports.values():
            assert len(report.outcomes) == len(BENCHMARK_CASES)

    def test_combined_strategy_matches_every_expected_finding(self):
        """合并策略应覆盖样例库中的全部已知缺陷（回归保护）。"""
        report = run_benchmark("combined")

        assert report.false_negatives == 0
        assert report.recall == 1.0

    def test_combined_strategy_produces_no_noise(self):
        report = run_benchmark("combined")

        assert report.false_positives == 0
        assert report.precision == 1.0

    def test_negative_control_case_stays_silent(self):
        report = run_benchmark("combined")
        control = next(o for o in report.outcomes if o.case_id == "clean-python-01")

        assert control.true_positives == 0
        assert control.false_positives == 0
        assert control.unexpected_titles == []

    def test_ast_strategy_beats_static_on_recall(self):
        static_report = run_benchmark("static")
        ast_report = run_benchmark("ast")

        assert ast_report.recall > static_report.recall

    def test_report_serialises_to_dict(self):
        payload = run_benchmark("combined").to_dict()

        assert payload["strategy"] == "combined"
        assert payload["case_count"] == len(BENCHMARK_CASES)
        assert len(payload["cases"]) == len(BENCHMARK_CASES)
        assert 0.0 <= payload["f1"] <= 1.0

    def test_report_renders_text(self):
        text = run_benchmark("combined").render_text()

        assert "Benchmark strategy: combined" in text
        assert "Precision:" in text
        assert "TOTAL" in text
