from __future__ import annotations

from typing import Any

from ai_pr_review.demo_fixtures import get_demo_case, list_demo_cases
from ai_pr_review.services.agent.planner import ReviewPlanner
from ai_pr_review.services.analyzers.static_analyzer import StaticAnalyzer
from ai_pr_review.services.context_builder import ContextBuilder
from ai_pr_review.services.evidence.finding_validator import FindingValidator
from ai_pr_review.services.filter_pipeline import FilterPipeline


def demo_cases_payload() -> list[dict[str, str]]:
    return [
        {"key": case.key, "title": case.title, "description": case.description}
        for case in list_demo_cases()
    ]


def run_demo_case(case_key: str) -> dict[str, Any]:
    case = get_demo_case(case_key)
    pr_data = case.pr_data
    _, filter_result = FilterPipeline().filter_pr_data(pr_data)
    plan = ReviewPlanner().build_plan(pr_data, filter_result)
    context_builder = ContextBuilder()
    analyzer = StaticAnalyzer()
    validator = FindingValidator()
    checked = []
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
    return {
        "case": {"key": case.key, "title": case.title, "description": case.description},
        "pr": pr_data.model_dump(mode="json"),
        "filter": filter_result.to_dict(),
        "plan": plan.model_dump(mode="json"),
        "findings": [finding.model_dump(mode="json") for finding in checked],
        "summary": {
            "risk_level": plan.risk_level,
            "finding_count": len(checked),
            "evidence_validated": sum(
                1 for finding in checked if finding.evidence_status == "valid"
            ),
            "cost": 0.0,
        },
    }
