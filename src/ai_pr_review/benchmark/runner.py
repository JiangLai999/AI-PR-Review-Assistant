"""基准评测执行器：把分析策略的产出与已知缺陷做匹配并统计指标。"""

from __future__ import annotations

from collections.abc import Callable

from ai_pr_review.benchmark.cases import load_cases
from ai_pr_review.benchmark.models import (
    BenchmarkCase,
    BenchmarkReport,
    CaseOutcome,
    ExpectedFinding,
)
from ai_pr_review.models.pr_data import FileDiff, FileStatus
from ai_pr_review.services.analyzers.finding_merge import combine_findings
from ai_pr_review.services.analyzers.python_ast_analyzer import PythonAstAnalyzer
from ai_pr_review.services.analyzers.static_analyzer import StaticAnalyzer
from ai_pr_review.services.context_builder import ContextBuilder
from ai_pr_review.services.prompt_assembler import Finding

Strategy = Callable[[BenchmarkCase], list[Finding]]

# 命中判定允许的行号偏移。规则可能把问题定位到相邻行（例如函数定义行
# 与函数体首行），因此用一个很小的窗口吸收这种差异，同时单独统计严格
# 行号准确率。
LINE_TOLERANCE = 1


def build_changed_file(case: BenchmarkCase) -> tuple[FileDiff, object]:
    """把样例的整段源码构造成“全部为变更行”的文件与上下文。"""
    lines = case.source.splitlines()
    patch = f"@@ -0,0 +1,{len(lines)} @@\n" + "".join(f"+{line}\n" for line in lines)
    file_diff = FileDiff(
        filename=case.filename,
        status=FileStatus.ADDED,
        additions=len(lines),
        deletions=0,
        changes=len(lines),
        patch=patch,
    )
    context = ContextBuilder().build_context(case.filename, patch, case.source)
    return file_diff, context


def strategy_static(case: BenchmarkCase) -> list[Finding]:
    """仅使用逐行静态规则。"""
    if case.language != "python":
        return []
    file_diff, context = build_changed_file(case)
    return StaticAnalyzer().analyze(file_diff, context)


def strategy_ast(case: BenchmarkCase) -> list[Finding]:
    """仅使用 Python AST 规则。"""
    file_diff, context = build_changed_file(case)
    return PythonAstAnalyzer().analyze(file_diff, context)


def strategy_combined(case: BenchmarkCase) -> list[Finding]:
    """逐行规则与 AST 规则合并（对应真实审查链路的默认行为）。"""
    return combine_findings(strategy_static(case), strategy_ast(case))


STRATEGIES: dict[str, Strategy] = {
    "static": strategy_static,
    "ast": strategy_ast,
    "combined": strategy_combined,
}


def _rule_of(finding: Finding) -> str:
    """从标题反查规则名，用于与样例期望对齐。

    Finding 目前只携带标题与来源，不暴露内部规则名，因此这里用标题到
    规则名的稳定映射来匹配。新增规则时需要同步维护该映射。
    """
    return TITLE_TO_RULE.get(finding.title, finding.title)


TITLE_TO_RULE = {
    "Dynamic code execution": "dynamic_execution",
    "Potential HTML injection": "html_injection",
    "Possible hard-coded secret": "hardcoded_secret",
    "Possible hard-coded credential constant": "hardcoded_credential_constant",
    "Possible SQL injection": "sql_interpolation",
    "Unsafe YAML deserialization": "unsafe_yaml_load",
    "TLS certificate verification disabled": "tls_verification_disabled",
    "Debug mode may be enabled in production": "debug_mode_enabled",
    "Mutable default argument": "mutable_default_argument",
    "Bare except swallows every exception": "bare_except",
    "Identity comparison against a literal": "is_literal_comparison",
    "Unsafe deserialization via pickle": "unsafe_deserialization",
    "Unsafe deserialization via dill": "unsafe_deserialization",
    "Unsafe deserialization via marshal": "unsafe_deserialization",
    "Unsafe deserialization via shelve": "unsafe_deserialization",
    "Subprocess executed with shell=True": "subprocess_shell_true",
    "HTTP request without timeout": "http_request_without_timeout",
    "Resource opened without guaranteed cleanup": "unclosed_resource",
    "Exception re-raised without original traceback": "raise_without_from",
    "Input conversion failure raised without context": "uncontextualised_value_error",
    "Weak hash algorithm (md5)": "weak_hash_algorithm",
    "Weak hash algorithm (sha1)": "weak_hash_algorithm",
}


def score_case(case: BenchmarkCase, strategy_name: str, findings: list[Finding]) -> CaseOutcome:
    """把单个样例的发现与期望做贪心匹配。"""
    outcome = CaseOutcome(case_id=case.case_id, strategy=strategy_name)
    remaining = list(findings)
    confidences: list[float] = []

    for expected in case.expected:
        match = _find_match(expected, remaining)
        if match is None:
            outcome.false_negatives += 1
            outcome.missed_rules.append(expected.rule)
            continue
        remaining.remove(match)
        outcome.true_positives += 1
        outcome.matched_rules.append(expected.rule)
        confidences.append(match.confidence)
        if match.line_start == expected.line or match.line_end == expected.line:
            outcome.line_hits += 1

    outcome.false_positives = len(remaining)
    outcome.unexpected_titles = [finding.title for finding in remaining]
    confidences.extend(finding.confidence for finding in remaining)
    outcome.avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    return outcome


def _find_match(expected: ExpectedFinding, candidates: list[Finding]) -> Finding | None:
    for finding in candidates:
        if _rule_of(finding) != expected.rule:
            continue
        if abs(finding.line_start - expected.line) <= LINE_TOLERANCE:
            return finding
    # 规则正确但行号偏差过大时仍计入命中，只是不计入行号准确率。
    for finding in candidates:
        if _rule_of(finding) == expected.rule:
            return finding
    return None


def run_benchmark(
    strategy_name: str = "combined",
    cases: list[BenchmarkCase] | None = None,
) -> BenchmarkReport:
    """对指定策略运行全部样例并返回汇总报告。"""
    if strategy_name not in STRATEGIES:
        raise KeyError(
            f"Unknown strategy: {strategy_name}. Available: {', '.join(sorted(STRATEGIES))}"
        )
    strategy = STRATEGIES[strategy_name]
    selected = cases if cases is not None else load_cases()
    report = BenchmarkReport(strategy=strategy_name)
    for case in selected:
        report.outcomes.append(score_case(case, strategy_name, strategy(case)))
    return report


def run_all_strategies(cases: list[BenchmarkCase] | None = None) -> dict[str, BenchmarkReport]:
    """运行全部策略，便于横向比较。"""
    return {name: run_benchmark(name, cases) for name in STRATEGIES}


__all__ = [
    "LINE_TOLERANCE",
    "STRATEGIES",
    "TITLE_TO_RULE",
    "build_changed_file",
    "run_all_strategies",
    "run_benchmark",
    "score_case",
    "strategy_ast",
    "strategy_combined",
    "strategy_static",
]
