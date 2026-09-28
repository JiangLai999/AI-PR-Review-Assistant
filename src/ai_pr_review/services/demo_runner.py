"""Offline demo payload builder shared by the CLI and the chat backend (§12.3).

`pr-review demo --case <key> --json-output` and the backend `demo` command must
return one and the same object, so the builder lives here and both callers use
it. Nothing in this module talks to a model, to GitHub, or to the result store:
the demo runs the deterministic filter/plan/static-rule/validator pipeline over
the embedded fixtures and nothing else.

The payload is a stable, published contract — the CLI hashes are pinned by
`tests/test_cli.py`, so key names and ordering are part of the interface.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ai_pr_review.demo_fixtures import get_demo_case, list_demo_cases
from ai_pr_review.models.review_plan import ReviewPlan
from ai_pr_review.services.agent.planner import ReviewPlanner
from ai_pr_review.services.analyzers.static_analyzer import StaticAnalyzer
from ai_pr_review.services.context_builder import ContextBuilder
from ai_pr_review.services.evidence.finding_validator import FindingValidator
from ai_pr_review.services.filter_pipeline import FilterPipeline
from ai_pr_review.services.prompt_assembler import Finding

#: The case `pr-review demo` runs when no `--case` is given.
DEFAULT_DEMO_CASE = "sql-injection"


class UnknownDemoCase(LookupError):
    """Raised for a case key the fixtures do not define; lists the valid keys."""

    def __init__(self, case_key: str, available: Sequence[str]) -> None:
        self.case_key = case_key
        self.available = list(available)
        super().__init__(f"未知的 Demo 用例：{case_key}。可用用例：" + ", ".join(self.available))


@dataclass(frozen=True)
class DemoRun:
    """One executed demo case: the rendered payload plus the objects behind it."""

    case_key: str
    title: str
    description: str
    plan: ReviewPlan
    findings: list[Finding]
    payload: dict[str, Any]

    @property
    def risk_level(self) -> str:
        return self.plan.risk_level

    @property
    def priority_files(self) -> int:
        return len(self.plan.priority_files)

    @property
    def valid_count(self) -> int:
        return sum(1 for finding in self.findings if finding.evidence_status == "valid")


def case_keys() -> list[str]:
    return [case.key for case in list_demo_cases()]


def demo_cases() -> list[dict[str, str]]:
    return [
        {"key": case.key, "title": case.title, "description": case.description}
        for case in list_demo_cases()
    ]


def run_demo(case_key: str = DEFAULT_DEMO_CASE, *, language: str = "en") -> DemoRun:
    """Run one demo case offline and return its payload.

    Raises:
        UnknownDemoCase: the key is not one of the embedded fixtures.

    `language` 默认 **en**（而不是 `i18n_text` 的"拿不到就中文"）：demo 的 JSON 是
    `pr-review demo --json-output` 的**冻结契约**，字节级被 SHA256 黄金表锁住
    （tests/test_cli.py 的 DEMO_JSON_SHA256），改默认语言等于毁掉那个契约。
    需要本地化时由调用方显式传语言（Web 的 `/api/demo/run` 就是这么做的）。
    """
    try:
        case = get_demo_case(case_key)
    except ValueError as exc:
        raise UnknownDemoCase(case_key, case_keys()) from exc

    pr_data = case.pr_data
    _, filter_result = FilterPipeline().filter_pr_data(pr_data)
    plan = ReviewPlanner().build_plan(pr_data, filter_result, language=language)
    context_builder = ContextBuilder()
    analyzer = StaticAnalyzer()
    validator = FindingValidator()
    checked: list[Finding] = []
    for file_diff in pr_data.files:
        context = context_builder.build_context(
            file_diff.filename,
            file_diff.patch or "",
            case.file_contents.get(file_diff.filename, ""),
        )
        checked.extend(
            validator.annotate(finding, validator.validate(finding, file_diff, context))
            for finding in analyzer.analyze(file_diff, context)
        )

    payload = {
        "case": {"key": case.key, "title": case.title, "description": case.description},
        "plan": plan.model_dump(mode="json"),
        "findings": [finding.model_dump(mode="json") for finding in checked],
    }
    return DemoRun(
        case_key=case.key,
        title=case.title,
        description=case.description,
        plan=plan,
        findings=checked,
        payload=payload,
    )


def demo_case_payload(case_key: str = DEFAULT_DEMO_CASE) -> dict[str, Any]:
    """The object `pr-review demo --case <key> --json-output` prints."""
    return run_demo(case_key).payload


def demo_list_payload() -> dict[str, Any]:
    """The object the backend `demo list` command returns."""
    return {"cases": demo_cases()}


def _case_text(run: DemoRun) -> str:
    return (
        f"离线 Demo：{run.title}\n"
        f"风险等级：{run.risk_level} · 优先文件：{run.priority_files} · "
        f"Findings：{len(run.findings)} · 证据通过：{run.valid_count}/{len(run.findings)}"
    )


def _list_text(cases: list[dict[str, str]]) -> str:
    lines = [f"可用离线 Demo 用例（{len(cases)} 个）："]
    lines.extend(f"- {case['key']}：{case['title']} — {case['description']}" for case in cases)
    lines.append(f"用法：/demo <case_key>，默认 {DEFAULT_DEMO_CASE}。")
    return "\n".join(lines)


def demo_payload(args: Sequence[Any] = ()) -> dict[str, Any]:
    """Backend `demo` command payload: the CLI object plus a `text` summary.

    `demo list` lists the cases; `demo <case_key>` runs one (default
    `sql-injection`). The extra `text` key is appended last so the JSON body
    stays byte-identical to the CLI output.
    """
    tokens = [str(item).strip() for item in args if str(item).strip()]
    if tokens and tokens[0].lower() == "list":
        payload = demo_list_payload()
        return {**payload, "text": _list_text(payload["cases"])}
    case_key = tokens[0] if tokens else DEFAULT_DEMO_CASE
    run = run_demo(case_key)
    return {**run.payload, "text": _case_text(run)}
