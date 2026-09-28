"""Report Renderer 模块单元测试。"""

from __future__ import annotations

import json

import pytest

from ai_pr_review.config import ReportRendererConfig
from ai_pr_review.models.pr_data import FileDiff, FileStatus, PRData
from ai_pr_review.services.prompt_assembler import Finding, ReviewResult
from ai_pr_review.services.report_renderer import (
    EVIDENCE_STATUS_LABELS,
    GitHubCommentMeta,
    ReportRenderer,
)


def build_pr_data() -> PRData:
    return PRData(
        pr_number=123,
        title="Add user authentication",
        description="desc",
        author="alice",
        state="open",
        head_sha="head123",
        base_sha="base123",
        head_ref="feature/auth",
        base_ref="main",
        diff="diff --git a/src/services/user.py b/src/services/user.py",
        files=[
            FileDiff(
                filename="src/services/user.py",
                status=FileStatus.MODIFIED,
                additions=10,
                deletions=2,
                changes=12,
                patch="@@ -45,2 +45,2 @@",
            )
        ],
        url="https://github.com/owner/repo/pull/123",
        merged=False,
        owner="owner",
        repo="repo",
    )


def build_review_result() -> ReviewResult:
    return ReviewResult(
        summary="Potential security and reliability issues found.",
        findings=[
            Finding(
                severity="critical",
                category="security",
                file="src/services/user.py",
                line_start=45,
                line_end=52,
                title="SQL Injection in user query",
                problem="User input is directly concatenated into SQL query.",
                suggestion="Use parameterized query instead of f-string.",
                confidence=0.95,
                code_snippet='query = f"SELECT * FROM users WHERE id = {user_id}"',
            ),
            Finding(
                severity="high",
                category="error_handling",
                file="src/services/user.py",
                line_start=23,
                line_end=28,
                title="Missing error handling",
                problem="The database call can raise without being handled.",
                suggestion="Wrap the call and convert failures into a safe response.",
                confidence=0.88,
                code_snippet="await db.fetch_one(query)",
            ),
        ],
    )


def test_render_terminal_outputs_summary_and_findings():
    renderer = ReportRenderer()

    output = renderer.render_terminal(build_review_result(), build_pr_data())

    assert "AI PR Review Report" in output
    assert "PR: #123 - Add user authentication" in output
    assert "Total Findings: 2" in output
    assert "Critical: 1" in output
    assert "High: 1" in output
    assert "SQL Injection in user query" in output
    assert "Missing error handling" in output


def test_render_terminal_uses_the_shared_evidence_vocabulary():
    """P6 §1：终端中文证据文案与词汇表逐字一致，且不得写成「证据有效」。"""
    result = build_review_result()
    result.findings[0].evidence_status = "valid"
    result.findings[1].evidence_status = "invalid"

    output = ReportRenderer().render_terminal(result, build_pr_data(), language="zh-CN")

    # 汇总行
    assert "校验通过 1 · 待人工确认 0 · 校验不成立 1 · 未校验 0" in output
    # 明细行
    assert "校验通过 · 来源：ai_analysis" in output
    assert "校验不成立 · 来源：ai_analysis" in output
    # 「证据有效 / 证据不成立」把「位置与片段自洽」说成了「问题成立」。
    assert "证据有效" not in output
    assert "证据不成立" not in output
    assert "有效 1" not in output


@pytest.mark.parametrize(
    ("status", "badge", "chinese"),
    [
        ("valid", "✅", "校验通过"),
        ("needs_review", "🔍", "待人工确认"),
        ("invalid", "⛔", "校验不成立"),
        ("unverified", "❔", "未校验"),
    ],
)
def test_terminal_and_comment_agree_on_the_chinese_evidence_word(status, badge, chinese):
    """同一个 status 在终端与评论里必须是同一个中文词（P6 §6 的比对口径）。"""
    assert EVIDENCE_STATUS_LABELS[status][1] == chinese

    result = build_review_result()
    for finding in result.findings:
        finding.evidence_status = status

    terminal = ReportRenderer().render_terminal(result, build_pr_data(), language="zh-CN")
    comment = ReportRenderer().render_github_comment(
        result, build_pr_data(), meta=GitHubCommentMeta(language="zh-CN", head_sha="head123")
    )

    assert f"{chinese} · 来源：ai_analysis" in terminal
    assert f"{chinese} 2" in terminal  # 汇总行：两个 finding 同一个状态
    assert f"{badge} {chinese}" in comment


def test_render_terminal_falls_back_for_an_unknown_evidence_status():
    """词汇表外的 status 与评论徽章一样回退到「未校验」，而不是抛 KeyError。"""
    result = build_review_result()
    result.findings[0].evidence_status = "not-a-status"

    terminal = ReportRenderer().render_terminal(result, build_pr_data(), language="zh-CN")
    comment = ReportRenderer().render_github_comment(
        result, build_pr_data(), meta=GitHubCommentMeta(language="zh-CN")
    )

    assert "未校验 · 来源" in terminal
    assert "未校验 2" in terminal
    assert "not-a-status" not in terminal
    assert "❔ 未校验 2" in comment


def test_render_markdown_outputs_expected_sections():
    renderer = ReportRenderer()

    output = renderer.render_markdown(build_review_result(), build_pr_data())

    assert "# AI PR Review Report" in output
    assert "## Summary" in output
    assert "- **PR**: #123 - Add user authentication" in output
    assert "## Critical Findings" in output
    assert "### SQL Injection in user query" in output
    assert "- **Severity**: Critical" in output
    assert "```python" in output
    assert "**Suggestion**: Use parameterized query instead of f-string." in output


def test_render_json_outputs_structured_payload():
    renderer = ReportRenderer()

    output = renderer.render_json(build_review_result(), build_pr_data())
    payload = json.loads(output)

    assert payload["pr"]["number"] == 123
    assert payload["pr"]["repository"] == "owner/repo"
    assert payload["counts"]["total_findings"] == 2
    assert payload["counts"]["by_severity"]["critical"] == 1
    assert payload["findings"][0]["title"] == "SQL Injection in user query"


def test_render_github_comment_outputs_target_stats_and_footer():
    renderer = ReportRenderer()

    output = renderer.render_github_comment(build_review_result(), build_pr_data())

    assert "## 🤖 AI PR Review Report" in output
    assert (
        "**`owner/repo`** · [PR #123](https://github.com/owner/repo/pull/123) · "
        "Add user authentication · @alice · 1 files changed"
    ) in output
    assert "> **2 findings** · 🛑 1 critical · ⚠️ 1 high" in output
    assert "**evidence (location + snippet)**" in output
    assert "### 🎯 Fix first (top 2)" in output
    assert "<summary><b>🛑 Critical · 1</b></summary>" in output
    assert "#### 1. 🛑 SQL Injection in user query" in output
    assert "*Generated by AI PR Review Assistant*" in output
    assert "```python" not in output


def test_render_github_comment_links_lines_and_needs_metadata_for_it():
    """`file:line` becomes a blob link only when the commit is known."""
    without_sha = ReportRenderer().render_github_comment(build_review_result(), build_pr_data())
    assert "https://github.com/owner/repo/blob/" not in without_sha
    assert "`src/services/user.py:45-52`" in without_sha

    with_sha = ReportRenderer().render_github_comment(
        build_review_result(),
        build_pr_data(),
        meta=GitHubCommentMeta(head_sha="head123", run_id="run-12345678", model="deepseek-flash"),
    )
    assert (
        "[`src/services/user.py:45-52`]"
        "(https://github.com/owner/repo/blob/head123/src/services/user.py#L45-L52)"
    ) in with_sha
    assert "模型 `deepseek-flash`" not in with_sha  # default language is English
    assert "model `deepseek-flash` · run `run-1234`" in with_sha


def test_render_github_comment_localizes_for_chinese():
    output = ReportRenderer().render_github_comment(
        build_review_result(),
        build_pr_data(),
        meta=GitHubCommentMeta(language="zh-CN", head_sha="head123", run_id="run-12345678"),
    )

    assert "## 🤖 AI PR 审查报告" in output
    assert "个变更文件" in output
    assert "> **2 个问题** · 🛑 1 严重 · ⚠️ 1 高" in output
    assert "证据校验（位置与片段自洽）" in output
    assert "❔ 未校验 2" in output
    assert "### 🎯 优先修复（Top 2）" in output
    assert "<summary><b>🛑 严重 · 1 条</b></summary>" in output
    assert "置信度 95%" in output
    assert "**问题**：" in output and "**建议**：" in output
    assert "<sub>证据优先 · 位置与片段校验通过 0/2" in output


def test_render_github_comment_folds_per_file_summary_and_long_details():
    result = build_review_result()
    result.summary = (
        "整体结论：两处问题需要修复。\n" "src/a.py: 文件 A 的结论。\n" "src/b.py: 文件 B 的结论。"
    )
    result.findings[0].problem = "P" * 400
    result.findings[0].suggestion = "S" * 20

    output = ReportRenderer().render_github_comment(result, build_pr_data())

    assert "### 📌 Review summary" in output
    assert "整体结论：两处问题需要修复。" in output
    assert "<summary><b>📄 Model summary by file (2 files)</b></summary>" in output
    assert "**`src/a.py`**" in output and "**`src/b.py`**" in output
    # The 400-char problem is folded instead of flooding the scan path.
    assert "<summary>Problem / Suggestion</summary>" in output


def test_render_github_comment_without_findings_is_short():
    result = build_review_result()
    result.findings = []

    output = ReportRenderer().render_github_comment(result, build_pr_data())

    assert "### ✅ No findings" in output
    assert "<details" not in output
    assert "Fix first" not in output


def test_render_github_comment_escapes_prose_so_github_keeps_it():
    """GitHub strips unknown tags: quoted evidence must survive verbatim."""
    result = build_review_result()
    finding = result.findings[0]
    finding.title = "Unescaped <script> in head"
    finding.problem = 'The template ends with </head> and uses target="_blank" without rel.'
    finding.suggestion = "# Wrap it"
    finding.evidence_issues = ["missing <meta> tag"]

    output = ReportRenderer().render_github_comment(result, build_pr_data())

    assert "&#96;" not in output
    assert "<script>" not in output
    assert "&lt;script&gt;" in output
    assert "&lt;/head&gt;" in output
    assert 'target="_blank"' in output  # quotes are safe; only angle brackets escaped
    assert "\\# Wrap it" in output
    assert "missing &lt;meta&gt; tag" in output


def test_render_github_comment_handles_backticks_in_paths():
    result = build_review_result()
    result.findings[0].file = "docs/we`ird name.md"

    output = ReportRenderer().render_github_comment(result, build_pr_data())

    assert "`` docs/we`ird name.md:45-52 ``" in output


def test_render_github_comment_falls_back_to_pr_files_for_forks():
    """A fork head commit is not in the base repo, so do not link the blob."""
    output = ReportRenderer().render_github_comment(
        build_review_result(),
        build_pr_data(),
        meta=GitHubCommentMeta(head_sha="fork-sha", from_fork=True),
    )

    assert "https://github.com/owner/repo/blob/fork-sha" not in output
    assert "https://github.com/owner/repo/pull/123/files" in output


def test_render_github_comment_reports_coverage_time_and_estimated_cost():
    output = ReportRenderer().render_github_comment(
        build_review_result(),
        build_pr_data(),
        meta=GitHubCommentMeta(
            language="zh-CN",
            head_sha="head123",
            run_id="run-12345678",
            model="deepseek-flash",
            reviewed_at="2026-09-20 09:12 UTC",
            files_reviewed=1,
            files_skipped=0,
            duration_seconds=66.1,
            cost=0.0021,
        ),
    )

    assert "已审查 1/1 个文件" in output
    assert "（跳过 0）" not in output
    pr_two_files = build_pr_data()
    pr_two_files.files = pr_two_files.files + [
        FileDiff(
            filename="src/services/other.py",
            status=FileStatus.MODIFIED,
            additions=1,
            deletions=1,
            changes=2,
            patch="@@ -1 +1 @@",
        )
    ]
    skipped = ReportRenderer().render_github_comment(
        build_review_result(),
        pr_two_files,
        meta=GitHubCommentMeta(language="zh-CN", files_reviewed=1, files_skipped=1),
    )
    assert "已审查 1/2 个文件（跳过 1）" in skipped
    assert "审查于 2026-09-20 09:12 UTC" in output
    assert "耗时 66.1s" in output
    assert "≈ $0.0021" in output

    unrecorded = ReportRenderer().render_github_comment(
        build_review_result(),
        build_pr_data(),
        meta=GitHubCommentMeta(language="zh-CN", cost=0.0),
    )
    assert "成本未记录" in unrecorded
    assert "$0.0000" not in unrecorded


def test_render_github_comment_caps_a_runaway_comment():
    result = build_review_result()
    template = result.findings[0]
    result.findings = []
    for index in range(120):
        clone = template.model_copy(deep=True)
        clone.title = f"Finding {index} " + "T" * 40
        clone.problem = "P" * 400
        clone.suggestion = "S" * 400
        result.findings.append(clone)

    output = ReportRenderer().render_github_comment(
        result,
        build_pr_data(),
        meta=GitHubCommentMeta(run_id="run-12345678", head_sha="head123"),
    )

    assert len(output) <= 24_000
    assert "per-file prose omitted" in output
    assert "more in this severity" in output
    # Every severity bucket past the visible ones is still accounted for.
    assert "120" not in output or "more in this severity" in output


def test_render_github_comment_fence_grows_past_snippet_backticks():
    result = build_review_result()
    result.findings[0].code_snippet = "print('```')\nmore\n```"

    output = ReportRenderer(
        ReportRendererConfig(include_code_snippets_in_github_comment=True)
    ).render_github_comment(result, build_pr_data())

    assert "````python" in output
    assert "````" in output.split("````python", 1)[1]


def test_render_github_comment_evidence_badges_do_not_overclaim():
    result = build_review_result()
    result.findings[0].evidence_status = "valid"
    result.findings[1].evidence_status = "needs_review"

    chinese = ReportRenderer().render_github_comment(
        result, build_pr_data(), meta=GitHubCommentMeta(language="zh-CN")
    )
    english = ReportRenderer().render_github_comment(result, build_pr_data())

    assert "✅ 校验通过" in chinese and "🔍 待人工确认" in chinese
    assert "证据有效" not in chinese
    assert "✅ validated" in english and "🔍 needs review" in english


def test_render_markdown_supports_custom_template():
    renderer = ReportRenderer(
        ReportRendererConfig(
            markdown_template="# {title}\n\nPR: #{pr_number}\n\n{findings_markdown}"
        )
    )

    output = renderer.render_markdown(build_review_result(), build_pr_data())

    assert output.startswith("# AI PR Review Report")
    assert "PR: #123" in output
    assert "## Critical Findings" in output


def test_render_github_comment_can_include_code_snippets_when_enabled():
    renderer = ReportRenderer(ReportRendererConfig(include_code_snippets_in_github_comment=True))

    output = renderer.render_github_comment(build_review_result(), build_pr_data())

    assert "```python" in output
    assert 'query = f"SELECT * FROM users WHERE id = {user_id}"' in output


# --- Fold policy (P6 comment freeze): critical expanded, the rest collapsed ---

_SEVERITY_ICONS = {
    "critical": "🛑",
    "high": "⚠️",
    "medium": "🔎",
    "low": "ℹ️",
    "info": "📝",
}


def _severity_block_openings(output: str) -> list[tuple[str, str]]:
    """Return (severity, opening_tag) for each severity block, in document order.

    Only the severity headers look like ``<summary><b>{icon} {label} · N…</b></summary>``;
    nested problem/suggestion folds and the per-file summary use other icons/labels.
    """
    openings: list[tuple[str, str]] = []
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("<summary><b>"):
            continue
        body = line[len("<summary><b>") : -len("</b></summary>")]
        for severity, icon in _SEVERITY_ICONS.items():
            if body.startswith(f"{icon} "):
                openings.append((severity, lines[index - 1]))
                break
    return openings


def _build_finding(severity: str, index: int) -> Finding:
    return Finding(
        severity=severity,
        category="correctness",
        file="src/services/user.py",
        line_start=10 + index,
        line_end=10 + index,
        title=f"{severity} finding {index}",
        problem="Short problem text.",
        suggestion="Short suggestion text.",
        confidence=0.9,
        code_snippet="pass",
    )


def test_render_github_comment_folds_only_critical_open_across_severities():
    """折叠策略：critical 块 open，其余严重级块折叠，顺序 critical→high→medium→low→info。"""
    result = build_review_result()
    result.findings = [
        _build_finding(severity, index)
        for index, severity in enumerate(["critical", "high", "medium", "low", "info"])
    ]

    output = ReportRenderer().render_github_comment(result, build_pr_data())
    openings = _severity_block_openings(output)

    assert [severity for severity, _ in openings] == [
        "critical",
        "high",
        "medium",
        "low",
        "info",
    ]
    by_severity = dict(openings)
    assert by_severity["critical"] == "<details open>"
    for severity in ("high", "medium", "low", "info"):
        assert by_severity[severity] == "<details>", severity
        assert "open" not in by_severity[severity]


def test_render_github_comment_opens_the_only_critical_block():
    """仅有 critical 时仍应是 details open，且不得出现其它严重级块。"""
    result = build_review_result()
    result.findings = [_build_finding("critical", 0)]

    output = ReportRenderer().render_github_comment(result, build_pr_data())
    openings = _severity_block_openings(output)

    assert openings == [("critical", "<details open>")]
    assert output.count("<details open>") == 1
    assert output.count("<summary><b>") == 1  # 只有 critical 一个严重级块


# --- Freeze the remaining §13.4 layout elements (mimo-p6-freeze-pin-rest) ---


def test_render_github_comment_keeps_a_blank_line_between_severity_blocks():
    """A compact-path refactor once dropped the trailing blank line of every
    severity block (`splitlines()` vs `split("\\n")`), which silently changed the
    normal path output. Pin the separation so it cannot happen again."""
    result = build_review_result()
    result.findings = [
        _titled_finding("critical", 0.9, "top issue"),
        _titled_finding("high", 0.8, "second issue"),
    ]

    output = ReportRenderer().render_github_comment(result, build_pr_data())

    assert "</details>\n\n<details" in output
    # A blank line still separates the body from the generated-by footer.
    assert "\n\n---\n*Generated by AI PR Review Assistant*" in output


def _shortlist_rows(output: str) -> list[str]:
    """Numbered `Fix first` rows, in document order."""
    lines = output.splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith("### 🎯"))
    rows: list[str] = []
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if not stripped:
            if rows:
                break
            continue
        if stripped[0].isdigit() and ". " in stripped[:4]:
            rows.append(stripped)
        elif rows:
            break
    return rows


def _comment_footer(output: str) -> str:
    """The `<sub>…</sub>` line that follows the generated-by marker."""
    tail = output.split("*Generated by AI PR Review Assistant*", 1)[1]
    return next(line for line in tail.splitlines() if line.startswith("<sub>"))


def _titled_finding(severity: str, confidence: float, title: str) -> Finding:
    finding = _build_finding(severity, 0)
    finding.confidence = confidence
    finding.title = title
    return finding


def test_render_github_comment_shortlists_at_most_three_by_severity_then_confidence():
    """§13.4 #4：>3 条 critical/high 时短名单恰好 3 条，严重级优先、同级置信度降序。"""
    result = build_review_result()
    result.findings = [
        _titled_finding("high", 0.60, "high-low"),
        _titled_finding("critical", 0.70, "crit-low"),
        _titled_finding("high", 0.95, "high-top"),
        _titled_finding("high", 0.80, "high-mid"),
        _titled_finding("critical", 0.90, "crit-high"),
    ]

    output = ReportRenderer().render_github_comment(result, build_pr_data())
    rows = _shortlist_rows(output)

    assert "### 🎯 Fix first (top 3)" in output
    assert len(rows) == 3
    assert [row.split("**")[1] for row in rows] == ["crit-high", "crit-low", "high-top"]


def test_render_github_comment_card_detail_line_carries_category_and_sources():
    """§13.4 #5b：明细行同时含 category 与 sources；zh 下 category 走中文映射，sources 原样。"""
    result = build_review_result()
    result.findings[0].category = "security"
    result.findings[0].sources = ["static_rule", "ai_analysis"]

    zh = ReportRenderer().render_github_comment(
        result, build_pr_data(), meta=GitHubCommentMeta(language="zh-CN")
    )
    en = ReportRenderer().render_github_comment(result, build_pr_data())

    assert "`安全` · `static_rule`, `ai_analysis`" in zh
    assert "`security` · `static_rule`, `ai_analysis`" in en
    # sources 是数据，不被界面语言改写
    assert "`static_rule`" in zh and "`ai_analysis`" in zh


def test_render_github_comment_footer_carries_evidence_ratio_model_run_commit():
    """§13.4 #7：footer 五片段齐全——证据比例 + 模型/run/提交（en 对应形态）。"""
    zh = ReportRenderer().render_github_comment(
        build_review_result(),
        build_pr_data(),
        meta=GitHubCommentMeta(
            language="zh-CN",
            head_sha="cafe1234567890",
            run_id="run-12345678",
            model="deepseek-flash",
        ),
    )
    zh_footer = _comment_footer(zh)
    assert zh_footer.startswith("<sub>") and zh_footer.endswith("</sub>")
    assert "证据优先" in zh_footer
    assert "位置与片段校验通过 0/2" in zh_footer
    assert "模型 `deepseek-flash`" in zh_footer
    assert "run `run-1234`" in zh_footer
    assert "提交 `cafe123`" in zh_footer

    en = ReportRenderer().render_github_comment(
        build_review_result(),
        build_pr_data(),
        meta=GitHubCommentMeta(
            head_sha="cafe1234567890",
            run_id="run-12345678",
            model="deepseek-flash",
        ),
    )
    en_footer = _comment_footer(en)
    assert "evidence-first" in en_footer
    assert "0/2 locations and snippets validated" in en_footer
    assert "model `deepseek-flash`" in en_footer
    assert "run `run-1234`" in en_footer
    assert "commit `cafe123`" in en_footer


def test_render_github_comment_footer_omits_missing_model_run_commit():
    """§13.4 #7：只给 model 或只给 run 时，缺失项不得臆造。"""
    only_model = _comment_footer(
        ReportRenderer().render_github_comment(
            build_review_result(),
            build_pr_data(),
            meta=GitHubCommentMeta(model="deepseek-flash"),
        )
    )
    assert "model `deepseek-flash`" in only_model
    assert "run `" not in only_model
    assert "commit `" not in only_model

    only_run = _comment_footer(
        ReportRenderer().render_github_comment(
            build_review_result(),
            build_pr_data(),
            meta=GitHubCommentMeta(run_id="run-12345678"),
        )
    )
    assert "run `run-1234`" in only_run
    assert "model `" not in only_run
    assert "commit `" not in only_run

    zh_only_model = _comment_footer(
        ReportRenderer().render_github_comment(
            build_review_result(),
            build_pr_data(),
            meta=GitHubCommentMeta(language="zh-CN", model="deepseek-flash"),
        )
    )
    assert "模型 `deepseek-flash`" in zh_only_model
    assert "run `" not in zh_only_model
    assert "提交 `" not in zh_only_model


def test_render_github_comment_compact_drops_per_file_then_counts_within_soft_limit():
    """§13.4 超大评论：先省略逐文件摘要并提示，再折叠为 more-in-severity 计数，且不超 soft limit。"""
    from ai_pr_review.services.report_renderer import _GITHUB_SOFT_LIMIT

    result = build_review_result()
    result.summary = (
        "Overall conclusion.\n" "src/a.py: file A conclusion.\n" "src/b.py: file B conclusion."
    )
    template = result.findings[0]
    result.findings = []
    for index in range(120):
        clone = template.model_copy(deep=True)
        clone.title = f"Finding {index} " + "T" * 40
        clone.problem = "P" * 400
        clone.suggestion = "S" * 400
        result.findings.append(clone)

    output = ReportRenderer().render_github_comment(
        result,
        build_pr_data(),
        meta=GitHubCommentMeta(run_id="run-12345678", head_sha="head123"),
    )

    # 步骤 1：逐文件摘要整段省略，并显式提示
    assert "Model summary by file" not in output
    assert "per-file prose omitted" in output
    # 步骤 2：每级只留可见卡片，其余折叠为计数
    assert "more in this severity" in output
    # compact 之后已回到 soft limit 内：不得动用最后一刀
    assert len(output) <= _GITHUB_SOFT_LIMIT
    assert "Comment truncated" not in output


def test_render_github_comment_compact_cut_marker_is_the_last_resort_and_last_segment():
    """compact 仍超限时才出现显式截断标记，且标记是正文最后一段。"""
    from ai_pr_review.services.report_renderer import _GITHUB_SOFT_LIMIT

    result = build_review_result()
    result.summary = (
        "Overall conclusion.\n" "src/a.py: file A conclusion.\n" "src/b.py: file B conclusion."
    )
    result.findings = []
    for severity in ("critical", "high", "medium", "low", "info"):
        for index in range(10):
            finding = _build_finding(severity, index)
            finding.title = f"{severity} huge {index}"
            finding.problem = "P" * 2500
            finding.suggestion = "S" * 2500
            result.findings.append(finding)

    output = ReportRenderer().render_github_comment(
        result,
        build_pr_data(),
        meta=GitHubCommentMeta(run_id="run-12345678", head_sha="head123"),
    )

    # 省略逐文件摘要这一步仍然生效；降级提示与截断标记都不允许被最后一刀切掉
    assert "Model summary by file" not in output
    assert "per-file prose omitted" in output
    assert len(output) <= _GITHUB_SOFT_LIMIT
    # 最后一刀：显式标记，且只出现在正文末尾
    assert "Comment truncated" in output
    assert "⛔ Comment truncated" in output
    assert output.index("per-file prose omitted") < output.index("⛔ Comment truncated")
    assert output.endswith("for the full report.\n")


# --- Filter disclosure: the audit line closing the stats block ---
# (claude-p6-comment-filter-line) The v2 layout's one deliberate extension: a
# reader who sees "0 findings" must be able to tell the model's verdict from a
# confidence threshold that swallowed every candidate.


def _pr_data_with_two_files() -> PRData:
    pr_data = build_pr_data()
    pr_data.files = pr_data.files + [
        FileDiff(
            filename="src/services/other.py",
            status=FileStatus.MODIFIED,
            additions=1,
            deletions=1,
            changes=2,
            patch="@@ -1 +1 @@",
        )
    ]
    return pr_data


def _quote_lines(output: str) -> list[str]:
    """The stats blockquote's lines, in document order."""
    return [line for line in output.splitlines() if line.startswith("> ")]


def test_render_github_comment_closes_the_stats_block_with_the_filter_audit():
    """有 findings 时：覆盖率/门槛/过滤条数组成 stats 块的最后一行。"""
    output = ReportRenderer().render_github_comment(
        build_review_result(),
        _pr_data_with_two_files(),
        meta=GitHubCommentMeta(
            language="zh-CN",
            files_reviewed=2,
            threshold=0.6,
            below_threshold=1,
            duplicates=0,
        ),
    )

    assert "已审查 2/2 个文件 · 置信度门槛 0.60 · 低于门槛过滤 1 条 · 去重 0 条" in output
    # 该行是引用块的最后一行：块内每条非末行都以硬换行结尾，末行没有。
    assert (
        _quote_lines(output)[-1]
        == "> 已审查 2/2 个文件 · 置信度门槛 0.60 · 低于门槛过滤 1 条 · 去重 0 条"
    )
    assert output.split("已审查 2/2 个文件 · 置信度门槛 0.60 · 低于门槛过滤 1 条 · 去重 0 条")[
        1
    ].startswith("\n\n### 🎯")


def test_render_github_comment_shows_the_filter_audit_without_findings_too():
    """无 findings 分支同样要有这一行：这正是「0 个问题」需要被解释的场景。"""
    result = build_review_result()
    result.findings = []

    output = ReportRenderer().render_github_comment(
        result,
        _pr_data_with_two_files(),
        meta=GitHubCommentMeta(
            language="zh-CN",
            files_reviewed=2,
            threshold=0.6,
            below_threshold=3,
            duplicates=0,
        ),
    )

    assert "### ✅ 未发现问题" in output
    assert "**0 个问题**" in output
    assert (
        _quote_lines(output)[-1]
        == "> 已审查 2/2 个文件 · 置信度门槛 0.60 · 低于门槛过滤 3 条 · 去重 0 条"
    )


def test_render_github_comment_omits_the_audit_line_without_filter_data():
    """没有过滤数据就整行省略：覆盖率已由目标行承担，其余不得臆造。"""
    for meta in (
        GitHubCommentMeta(language="zh-CN"),
        GitHubCommentMeta(language="zh-CN", files_reviewed=1, files_skipped=0),
        GitHubCommentMeta(files_reviewed=1, head_sha="head123"),
    ):
        output = ReportRenderer().render_github_comment(
            build_review_result(), build_pr_data(), meta=meta
        )

        assert "置信度门槛" not in output
        assert "低于门槛过滤" not in output
        assert "去重" not in output
        assert "confidence threshold" not in output
        # 整行都不存在：引用块仍只有「严重级计数」与「证据校验」两行，覆盖率
        # 只在目标行里说一次（否则没有过滤数据的 Run 也会多出一行重复的覆盖度）。
        assert len(_quote_lines(output)) == 2
        assert not any("已审查" in line or "reviewed " in line for line in _quote_lines(output))


def test_render_github_comment_audit_line_keeps_only_the_fragments_it_has():
    """部分字段：只显示已有片段，缺的那段不显示也不填 0。"""
    only_below = ReportRenderer().render_github_comment(
        build_review_result(),
        build_pr_data(),
        meta=GitHubCommentMeta(language="zh-CN", below_threshold=1),
    )
    assert _quote_lines(only_below)[-1] == "> 低于门槛过滤 1 条"
    assert "置信度门槛" not in only_below
    assert "去重" not in only_below
    # 没有覆盖度数据时不伪造「已审查 x/y 个文件」（目标行也没有覆盖率后缀）
    assert "已审查" not in only_below

    without_below = ReportRenderer().render_github_comment(
        build_review_result(),
        _pr_data_with_two_files(),
        meta=GitHubCommentMeta(language="zh-CN", files_reviewed=2, threshold=0.75, duplicates=2),
    )
    assert _quote_lines(without_below)[-1] == "> 已审查 2/2 个文件 · 置信度门槛 0.75 · 去重 2 条"
    assert "低于门槛过滤" not in without_below

    # 0 是真实测得的计数，必须显示；缺数据才是省略的理由。
    zeroes = ReportRenderer().render_github_comment(
        build_review_result(),
        build_pr_data(),
        meta=GitHubCommentMeta(language="zh-CN", below_threshold=0, duplicates=0),
    )
    assert _quote_lines(zeroes)[-1] == "> 低于门槛过滤 0 条 · 去重 0 条"


def test_render_github_comment_audit_line_follows_the_interface_language():
    """英文界面用同一组片段的英文措辞，数字口径一致。"""
    english = ReportRenderer().render_github_comment(
        build_review_result(),
        _pr_data_with_two_files(),
        meta=GitHubCommentMeta(
            files_reviewed=2,
            threshold=0.6,
            below_threshold=1,
            duplicates=0,
        ),
    )
    assert (
        _quote_lines(english)[-1]
        == "> reviewed 2/2 files · confidence threshold 0.60 · filtered 1 below threshold"
        " · 0 duplicates"
    )


def test_cli_comment_report_reads_the_filter_audit_from_the_run_artifacts():
    """CLI 的 `--publish-comment` 路径：计数取自 artifacts.filtered_findings，
    门槛取本次进程生效的配置值。"""
    from ai_pr_review.cli import render_github_comment_report
    from ai_pr_review.config import AIClientConfig, AppConfig, PostProcessorConfig, PRFetcherConfig
    from ai_pr_review.services.filter_pipeline import FilterPipelineResult, FilterResult
    from ai_pr_review.services.review_orchestrator import ReviewArtifacts

    pr_data = _pr_data_with_two_files()
    artifacts = ReviewArtifacts(
        pr_data=pr_data,
        filter_result=FilterPipelineResult(
            results=[FilterResult(file=file, included=True) for file in pr_data.files]
        ),
        review_result=build_review_result(),
        filtered_findings={
            "before": 3,
            "after": 2,
            "below_threshold": 1,
            "duplicates": 0,
            "severity_sorted": True,
        },
    )
    # 内存配置：不读磁盘上的用户配置，也不让两个 token 字段去读环境变量。
    config = AppConfig(
        ai_client=AIClientConfig(api_key=""),
        github_token="",
        pr_fetcher=PRFetcherConfig(github_token=""),
    )
    config.post_processor = PostProcessorConfig(confidence_threshold=0.6)

    body = render_github_comment_report(artifacts, config)

    assert "已审查 2/2 个文件 · 置信度门槛 0.60 · 低于门槛过滤 1 条 · 去重 0 条" in body


# --- Follow-up Q&A section (p5b): optional, appended last, questions never lose
# their verbatim Markdown because the report is the only place a run's follow-ups
# are archived alongside the review they belong to. ---

_CHAT_TURNS = [
    {
        "turn_id": 1,
        "turn_index": 1,
        "role": "user",
        "content": "第 45 行的注入是真的吗？",
        "model": "",
        "usage": {},
        "context_meta": {},
        "duration_ms": None,
        "created_at": "2026-09-20 09:12:03",
    },
    {
        "turn_id": 2,
        "turn_index": 2,
        "role": "assistant",
        "content": "是真的，**user_id** 直接拼进了 SQL。",
        "model": "deepseek-flash",
        "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
        "context_meta": {"bound_run": "run-12345678"},
        "duration_ms": 1820,
        "created_at": "2026-09-20 09:12:05",
    },
    {
        "turn_id": 3,
        "turn_index": 3,
        "role": "user",
        "content": "那第二个问题呢？",
        "model": "",
        "usage": {},
        "context_meta": {},
        "duration_ms": None,
        "created_at": "2026-09-20 09:13:01",
    },
    {
        "turn_id": 4,
        "turn_index": 4,
        "role": "assistant",
        "content": "错误处理缺失是次要问题。",
        "model": "deepseek-flash",
        "usage": {"prompt_tokens": 90, "completion_tokens": 12},
        "context_meta": {},
        "duration_ms": 640,
        "created_at": "2026-09-20 09:13:02",
    },
]


def test_render_markdown_omits_the_follow_up_section_by_default():
    """回归保护：默认调用不传 chat_turns，报告里不得凭空出现追问小节。"""
    output = ReportRenderer().render_markdown(build_review_result(), build_pr_data())

    assert "Follow-up Q&A" not in output
    assert "追问记录" not in output
    assert "Q1." not in output
    assert output == ReportRenderer().render_markdown(
        build_review_result(), build_pr_data(), chat_turns=[]
    )


def test_render_markdown_appends_one_section_per_run_with_role_prefixes():
    output = ReportRenderer().render_markdown(
        build_review_result(), build_pr_data(), chat_turns=_CHAT_TURNS
    )

    assert "## Follow-up Q&A" in output
    assert "**Q1.** Question" in output and "**A1.** Answer" in output
    assert "第 45 行的注入是真的吗？" in output
    assert "是真的，**user_id** 直接拼进了 SQL。" in output
    assert "**Q2.** Question" in output and "**A2.** Answer" in output
    assert "错误处理缺失是次要问题。" in output
    # 小节在报告末尾，且一轮与下一轮之间用 `---` 分隔。
    assert output.index("## Follow-up Q&A") > output.index("## High Findings")
    assert output.index("---") > output.index("## Follow-up Q&A")
    assert output.rstrip().endswith("错误处理缺失是次要问题。")


def test_render_markdown_chat_meta_line_carries_turn_model_duration_tokens_and_time():
    output = ReportRenderer().render_markdown(
        build_review_result(), build_pr_data(), chat_turns=_CHAT_TURNS
    )

    assert (
        "- **Turn 1** · **Model** `deepseek-flash` · **Duration** 1.82s · "
        "**Tokens** 150 · **Asked at** 2026-09-20 09:12:05"
    ) in output
    # 没有 total_tokens 时用 prompt+completion 求和，而不是显示空括号。
    assert (
        "- **Turn 2** · **Model** `deepseek-flash` · **Duration** 0.64s · **Tokens** 102" in output
    )


def test_render_markdown_chat_meta_line_omits_every_absent_field():
    """缺 duration_ms / usage 的轮次不崩、不填 0，也不留下空括号。"""
    output = ReportRenderer().render_markdown(
        build_review_result(),
        build_pr_data(),
        chat_turns=[{"role": "assistant", "content": "没有元信息的回答。"}],
    )

    assert "- **Turn 1**" in output
    assert "Duration" not in output
    assert "Tokens" not in output
    assert "Asked at" not in output
    assert "0.00s" not in output
    assert "()" not in output
    assert "没有元信息的回答。" in output


def test_render_markdown_skips_turns_whose_content_is_empty():
    output = ReportRenderer().render_markdown(
        build_review_result(),
        build_pr_data(),
        chat_turns=[
            {"role": "user", "content": "有效提问", "model": "deepseek-flash"},
            {"role": "assistant", "content": "   "},
            {"role": "assistant", "content": "有效回答。"},
        ],
    )

    assert "**Q1.** Question" in output and "**A1.** Answer" in output
    assert "Q2." not in output
    assert "## Follow-up Q&A" in output


def test_render_markdown_omits_the_follow_up_section_when_every_turn_is_empty():
    output = ReportRenderer().render_markdown(
        build_review_result(),
        build_pr_data(),
        chat_turns=[{"role": "user", "content": ""}, {"role": "assistant", "content": ""}],
    )

    assert "Follow-up Q&A" not in output
    assert "追问记录" not in output


def test_render_markdown_follow_up_section_follows_the_interface_language():
    output = ReportRenderer().render_markdown(
        build_review_result(),
        build_pr_data(),
        chat_turns=_CHAT_TURNS,
        language="zh-CN",
    )

    assert "## 追问记录" in output
    assert "Follow-up Q&A" not in output
    assert "**Q1.** 问题" in output and "**A1.** 回答" in output
    assert (
        "- **轮次 1** · **模型** `deepseek-flash` · **耗时** 1.82s · "
        "**Token** 150 · **时间** 2026-09-20 09:12:05"
    ) in output


def test_render_markdown_keeps_answer_markdown_verbatim():
    answer = '改法：\n\n```python\nquery = "..."\n```\n\n- [x] 加上 `**` 转义检查\n- 1. 重跑'
    output = ReportRenderer().render_markdown(
        build_review_result(),
        build_pr_data(),
        chat_turns=[{"role": "assistant", "content": answer}],
    )

    assert answer in output
    assert "\\*\\*" not in output
    assert "```python" in output


def test_render_markdown_keeps_the_follow_up_section_when_there_are_no_findings():
    result = build_review_result()
    result.findings = []

    output = ReportRenderer().render_markdown(result, build_pr_data(), chat_turns=_CHAT_TURNS)

    assert "## Findings\n\nNo findings." in output
    assert "## Follow-up Q&A" in output
    assert output.index("## Follow-up Q&A") > output.index("No findings.")


def test_render_markdown_template_path_ignores_follow_up_turns():
    """自定义模板代表整份报告，配置了它就不追加追问小节（避免模板被截断）。"""
    renderer = ReportRenderer(
        ReportRendererConfig(markdown_template="# {title}\n\n{findings_markdown}")
    )

    output = renderer.render_markdown(
        build_review_result(), build_pr_data(), chat_turns=_CHAT_TURNS
    )

    assert output == renderer.render_markdown(build_review_result(), build_pr_data())
    assert "Follow-up Q&A" not in output
    assert "追问记录" not in output
