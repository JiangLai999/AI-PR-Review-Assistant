"""Tests for the agent planning, deterministic checks, and evidence layer."""

from __future__ import annotations

from ai_pr_review.models.pr_data import FileDiff, FileStatus, PRData
from ai_pr_review.services.agent.planner import ReviewPlanner
from ai_pr_review.services.analyzers.static_analyzer import StaticAnalyzer
from ai_pr_review.services.context_builder import ContextBuilder
from ai_pr_review.services.evidence.finding_validator import FindingValidator
from ai_pr_review.services.filter_pipeline import FilterPipeline


def build_pr(*files: FileDiff) -> PRData:
    return PRData(
        pr_number=1,
        title="Fix authentication API",
        description="Update token handling and API validation.",
        author="tester",
        state="open",
        head_sha="head",
        base_sha="base",
        head_ref="feature",
        base_ref="main",
        files=list(files),
        url="https://github.com/example/repo/pull/1",
        owner="example",
        repo="repo",
    )


def test_review_planner_detects_risk_and_cross_file_scope() -> None:
    files = [
        FileDiff(
            filename="src/auth_service.py",
            status=FileStatus.MODIFIED,
            additions=2,
            changes=2,
            patch="@@ -1 +1,3 @@\n old\n+new\n+new2",
        ),
        FileDiff(
            filename="src/api_router.py",
            status=FileStatus.MODIFIED,
            additions=1,
            changes=1,
            patch="@@ -1 +1,2 @@\n old\n+new",
        ),
    ]
    pr = build_pr(*files)
    _, result = FilterPipeline().filter_pr_data(pr)

    plan = ReviewPlanner().build_plan(pr, result)

    assert plan.risk_level == "high"
    assert "security" in plan.risk_categories
    assert plan.requires_cross_file_analysis is True
    assert "cross_file_impact_review" in plan.strategies


def test_static_finding_is_verified_against_changed_line() -> None:
    file_diff = FileDiff(
        filename="src/auth.py",
        status=FileStatus.MODIFIED,
        additions=1,
        changes=1,
        patch='@@ -1 +1,2 @@\n old\n+query = f"SELECT * FROM users WHERE id={user_id}"',
    )
    content = 'old\nquery = f"SELECT * FROM users WHERE id={user_id}"\n'
    context = ContextBuilder().build_context(file_diff.filename, file_diff.patch or "", content)
    finding = StaticAnalyzer().analyze(file_diff, context)[0]

    evidence = FindingValidator().validate(finding, file_diff, context)
    checked = FindingValidator().annotate(finding, evidence)

    assert evidence.validation_status == "valid"
    assert checked.finding_id
    assert checked.evidence_status == "valid"
    assert checked.evidence[0].changed_line is True


def test_evidence_source_follows_the_shared_source_helper() -> None:
    """来源判定统一走 `finding_has_source`，大小写不再能左右分支（P6 §2.3）。"""
    file_diff = FileDiff(
        filename="src/app.py",
        status=FileStatus.MODIFIED,
        additions=1,
        changes=1,
        patch="@@ -1 +1,2 @@\n old\n+value = eval(user_input)",
    )
    content = "old\nvalue = eval(user_input)\n"
    context = ContextBuilder().build_context(file_diff.filename, file_diff.patch or "", content)
    validator = FindingValidator()

    static_finding = StaticAnalyzer().analyze(file_diff, context)[0]
    model_finding = static_finding.model_copy(
        update={"sources": ["ai_analysis"], "finding_id": "", "rule_id": ""}
    )

    assert validator.validate(static_finding, file_diff, context).source == "static_rule"
    assert validator.validate(model_finding, file_diff, context).source == "ai_analysis"
    assert (
        validator.validate(
            model_finding.model_copy(update={"sources": ["AI_ANALYSIS"]}), file_diff, context
        ).source
        == "ai_analysis"
    )
    assert (
        validator.validate(
            static_finding.model_copy(update={"sources": [" Static_Rule "]}), file_diff, context
        ).source
        == "static_rule"
    )
