"""Review 报告渲染模块。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ai_pr_review.config import ReportRendererConfig
from ai_pr_review.models.pr_data import PRData
from ai_pr_review.services.prompt_assembler import Finding, ReviewResult

SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]
SEVERITY_STYLES = {
    "critical": "bold red",
    "high": "yellow",
    "medium": "cyan",
    "low": "green",
    "info": "dim",
}
SEVERITY_LABELS = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "info": "Info",
}
SEVERITY_ICONS = {
    "critical": "[CRITICAL]",
    "high": "[HIGH]",
    "medium": "[MEDIUM]",
    "low": "[LOW]",
    "info": "[INFO]",
}
MARKDOWN_HEADING_ICONS = {
    "critical": "❌",
    "high": "⚠️",
    "medium": "🔎",
    "low": "ℹ️",
    "info": "📝",
}


@dataclass(slots=True)
class RenderedReportContext:
    title: str
    pr_number: int
    pr_title: str
    pr_url: str
    repository: str
    author: str
    files_changed: int
    total_findings: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    info_count: int
    summary: str
    findings_markdown: str


class ReportRenderer:
    """将 ReviewResult 渲染为多种报告格式。"""

    def __init__(self, config: ReportRendererConfig | None = None):
        self._config = config or ReportRendererConfig()

    def render_terminal(
        self, result: ReviewResult, pr_data: PRData, *, language: str = "en-US"
    ) -> str:
        """Render a summary-first terminal report in the selected UI language."""
        console = Console(record=True)
        payload = self._build_payload(result, pr_data)
        pr = payload["pr"]
        counts = payload["counts"]
        findings = payload["findings"]
        is_zh = language.lower().startswith("zh")
        labels = {
            "review_target": "审查对象" if is_zh else "Pull Request",
            "repository": "仓库" if is_zh else "Repository",
            "files_changed": "变更文件" if is_zh else "Files Changed",
            "total_findings": "问题总数" if is_zh else "Total Findings",
            "risk": "风险分布" if is_zh else "Risk",
            "evidence": "证据状态" if is_zh else "Evidence",
            "summary": "结论摘要" if is_zh else "Summary",
            "list": "问题列表（按风险等级排序）" if is_zh else "Findings (grouped by severity)",
            "location": "位置" if is_zh else "Location",
            "evidence_item": "证据" if is_zh else "Evidence",
            "confidence": "置信度" if is_zh else "Confidence",
            "problem": "问题" if is_zh else "Problem",
            "suggestion": "建议" if is_zh else "Suggestion",
            "code": "代码" if is_zh else "Code",
            "next": "下一步" if is_zh else "Next Steps",
        }
        evidence_counts = {"valid": 0, "needs_review": 0, "invalid": 0, "unverified": 0}
        for finding in findings:
            evidence_counts[finding.get("evidence_status") or "unverified"] += 1

        summary_table = Table.grid(expand=True, padding=(0, 1))
        # Keep one compact row per metric; the English labels are stable for
        # scripts and existing integrations, while the surrounding panels are
        # localized for human readers.
        if is_zh:
            summary_table.add_row(labels["review_target"], f"PR #{pr['number']} · {pr['title']}")
            summary_table.add_row(labels["repository"], pr.get("repository") or "-")
            summary_table.add_row(labels["files_changed"], str(pr["files_changed"]))
            summary_table.add_row(labels["total_findings"], str(counts["total_findings"]))
        else:
            summary_table.add_row("PR", f"PR: #{pr['number']} - {pr['title']}")
            summary_table.add_row("Files Changed", f"Files Changed: {pr['files_changed']}")
            summary_table.add_row("Total Findings", f"Total Findings: {counts['total_findings']}")
        severity_distribution = " | ".join(
            f"{SEVERITY_LABELS[severity]}: {counts['by_severity'][severity]}"
            for severity in SEVERITY_ORDER
        )
        summary_table.add_row(labels["risk"], severity_distribution)
        summary_table.add_row(
            labels["evidence"],
            f"有效 {evidence_counts['valid']} · 待确认 {evidence_counts['needs_review']} · "
            f"无效 {evidence_counts['invalid']} · 未校验 {evidence_counts['unverified']}",
        )
        console.print(Panel(summary_table, title=f"{self._config.title} · 审查结果", expand=False))

        if not findings:
            if payload["summary"]:
                console.print(
                    Panel(payload["summary"], title=labels["summary"], border_style="blue")
                )
            console.print(Panel("未发现需要处理的问题。", title="结果", border_style="green"))
            return console.export_text()

        # Multi-file summaries repeat the detailed Finding cards below. Keep a
        # concise, non-duplicating overview in terminal output; full summaries
        # remain available in Markdown/JSON reports and history metadata.
        console.print(
            Panel(
                (
                    f"已分析 {pr['files_changed']} 个变更文件，识别出 {counts['total_findings']} 项需要关注的问题。\n"
                    "下方按风险等级列出详细 Finding、证据状态与修复建议。"
                    if is_zh
                    else f"Analyzed {pr['files_changed']} changed files and identified {counts['total_findings']} findings.\n"
                    "Details are grouped below by severity with evidence and remediation guidance."
                ),
                title=labels["summary"],
                border_style="blue",
            )
        )

        console.print(f"\n{labels['list']}", style="bold cyan")
        for index, finding in enumerate(findings, start=1):
            severity = finding["severity"]
            status = finding.get("evidence_status") or "unverified"
            status_label = {
                "valid": "证据有效",
                "needs_review": "待人工确认",
                "invalid": "证据不成立",
                "unverified": "未校验",
            }.get(status, status)
            status_style = {
                "valid": "green",
                "needs_review": "yellow",
                "invalid": "red",
                "unverified": "dim",
            }.get(status, "white")
            source_text = "、".join(finding.get("sources") or []) or "未标注"
            location = f"{finding['file']}:{finding['line_start']}-{finding['line_end']}"
            body = Table.grid(expand=True, padding=(0, 1))
            body.add_row("位置", location)
            body.add_row(
                "证据", f"[{status_style}]{status_label}[/{status_style}] · 来源：{source_text}"
            )
            body.add_row("置信度", f"{finding['confidence']:.2f}")
            body.add_row("问题", finding["problem"])
            body.add_row("建议", finding["suggestion"])
            if finding.get("code_snippet"):
                body.add_row("代码", finding["code_snippet"])
            console.print(
                Panel(
                    body,
                    title=f"#{index:02d} {SEVERITY_ICONS[severity]} {finding['title']}",
                    border_style=SEVERITY_STYLES[severity].replace("bold ", ""),
                    expand=False,
                )
            )

        console.print(
            Panel(
                "建议先处理 Critical / High，再逐项确认黄色证据。\n"
                "查看历史：pr-review history\n"
                "解释本次运行：pr-review explain <RUN_ID>",
                title=labels["next"],
                border_style="dim",
                expand=False,
            )
        )
        return console.export_text()

    def render_markdown(self, result: ReviewResult, pr_data: PRData) -> str:
        """渲染 Markdown 报告。"""
        context = self._build_context(result, pr_data, include_code_snippets=True)
        if self._config.markdown_template is not None:
            return self._config.markdown_template.format_map(asdict(context))

        lines = [
            f"# {context.title}",
            "",
            "## Summary",
            f"- **PR**: #{context.pr_number} - {context.pr_title}",
            f"- **Repository**: {context.repository}",
            f"- **Author**: {context.author}",
            f"- **Files Changed**: {context.files_changed}",
            f"- **Total Findings**: {context.total_findings}",
            (
                f"- **Critical**: {context.critical_count} | **High**: {context.high_count} | "
                f"**Medium**: {context.medium_count} | **Low**: {context.low_count} | "
                f"**Info**: {context.info_count}"
            ),
            "",
        ]

        if context.summary:
            lines.extend([context.summary, ""])

        findings_by_severity = self._group_findings(result.findings)
        if not any(findings_by_severity.values()):
            lines.extend(["## Findings", "", "No findings."])
            return "\n".join(lines)

        for severity in SEVERITY_ORDER:
            findings = findings_by_severity[severity]
            if not findings:
                continue

            lines.extend([f"## {SEVERITY_LABELS[severity]} Findings", ""])
            for finding in findings:
                lines.extend(self._render_markdown_finding(finding, include_code_snippet=True))

        return "\n".join(lines)

    def render_json(self, result: ReviewResult, pr_data: PRData) -> str:
        """渲染 JSON 报告。"""
        return json.dumps(
            self._build_payload(result, pr_data),
            ensure_ascii=False,
            indent=self._config.json_indent,
        )

    def render_github_comment(self, result: ReviewResult, pr_data: PRData) -> str:
        """渲染 GitHub PR Comment。"""
        context = self._build_context(
            result,
            pr_data,
            include_code_snippets=self._config.include_code_snippets_in_github_comment,
        )
        if self._config.github_comment_template is not None:
            return self._config.github_comment_template.format_map(asdict(context))

        lines = [
            f"## 🤖 {context.title}",
            "",
            "### Summary",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Files Changed | {context.files_changed} |",
            f"| Total Findings | {context.total_findings} |",
            f"| Critical | {context.critical_count} |",
            f"| High | {context.high_count} |",
            f"| Medium | {context.medium_count} |",
            f"| Low | {context.low_count} |",
            f"| Info | {context.info_count} |",
            "",
        ]

        if context.summary:
            lines.extend(["**Summary**: " + context.summary, ""])

        findings_by_severity = self._group_findings(result.findings)
        if not any(findings_by_severity.values()):
            lines.extend(
                [
                    "### Findings",
                    "",
                    "No findings.",
                    "",
                    "---",
                    "*Generated by AI PR Review Assistant*",
                ]
            )
            return "\n".join(lines)

        for severity in SEVERITY_ORDER:
            findings = findings_by_severity[severity]
            if not findings:
                continue

            lines.extend([f"### {SEVERITY_LABELS[severity]} Findings", ""])
            for finding in findings:
                lines.extend(
                    self._render_github_finding(
                        finding,
                        include_code_snippet=self._config.include_code_snippets_in_github_comment,
                    )
                )

        lines.extend(["---", "*Generated by AI PR Review Assistant*"])
        return "\n".join(lines)

    def _build_payload(self, result: ReviewResult, pr_data: PRData) -> dict:
        severity_counts = {severity: 0 for severity in SEVERITY_ORDER}
        for finding in result.findings:
            severity_counts[finding.severity] += 1

        return {
            "pr": {
                "number": pr_data.pr_number,
                "title": pr_data.title,
                "url": pr_data.url,
                "repository": pr_data.repo_full_name,
                "author": pr_data.author,
                "files_changed": pr_data.changed_files_count,
            },
            "summary": result.summary,
            "findings": [finding.model_dump() for finding in result.findings],
            "counts": {
                "total_findings": len(result.findings),
                "by_severity": severity_counts,
            },
        }

    def _build_context(
        self,
        result: ReviewResult,
        pr_data: PRData,
        *,
        include_code_snippets: bool,
    ) -> RenderedReportContext:
        payload = self._build_payload(result, pr_data)
        pr = payload["pr"]
        counts = payload["counts"]
        findings_markdown = self._render_findings_markdown(
            result.findings,
            include_code_snippet=include_code_snippets,
        )
        return RenderedReportContext(
            title=self._config.title,
            pr_number=pr["number"],
            pr_title=pr["title"],
            pr_url=pr["url"],
            repository=pr["repository"],
            author=pr["author"],
            files_changed=pr["files_changed"],
            total_findings=counts["total_findings"],
            critical_count=counts["by_severity"]["critical"],
            high_count=counts["by_severity"]["high"],
            medium_count=counts["by_severity"]["medium"],
            low_count=counts["by_severity"]["low"],
            info_count=counts["by_severity"]["info"],
            summary=payload["summary"],
            findings_markdown=findings_markdown,
        )

    def _group_findings(self, findings: list[Finding]) -> dict[str, list[Finding]]:
        grouped = {severity: [] for severity in SEVERITY_ORDER}
        for finding in findings:
            grouped[finding.severity].append(finding)
        return grouped

    def _render_findings_markdown(
        self,
        findings: list[Finding],
        *,
        include_code_snippet: bool,
    ) -> str:
        lines: list[str] = []
        for severity in SEVERITY_ORDER:
            severity_findings = [finding for finding in findings if finding.severity == severity]
            if not severity_findings:
                continue

            lines.extend([f"## {SEVERITY_LABELS[severity]} Findings", ""])
            for finding in severity_findings:
                lines.extend(
                    self._render_markdown_finding(
                        finding,
                        include_code_snippet=include_code_snippet,
                    )
                )

        return "\n".join(lines).rstrip()

    def _render_markdown_finding(
        self,
        finding: Finding,
        *,
        include_code_snippet: bool,
    ) -> list[str]:
        lines = [
            f"### {finding.title}",
            f"- **File**: `{finding.file}:{finding.line_start}-{finding.line_end}`",
            f"- **Confidence**: {finding.confidence:.2f}",
            f"- **Severity**: {SEVERITY_LABELS[finding.severity]}",
            "",
            f"**Problem**: {finding.problem}",
            "",
        ]

        if include_code_snippet and finding.code_snippet:
            lines.extend(["**Code**:", "```python", finding.code_snippet, "```", ""])

        lines.extend([f"**Suggestion**: {finding.suggestion}", ""])
        return lines

    def _render_github_finding(
        self,
        finding: Finding,
        *,
        include_code_snippet: bool,
    ) -> list[str]:
        lines = [
            f"#### {MARKDOWN_HEADING_ICONS[finding.severity]} {finding.title}",
            f"**File**: `{finding.file}:{finding.line_start}-{finding.line_end}`  ",
            f"**Confidence**: {finding.confidence:.2f}",
            "",
            f"**Problem**: {finding.problem}",
            "",
        ]

        if include_code_snippet and finding.code_snippet:
            lines.extend(["**Code**:", "```python", finding.code_snippet, "```", ""])

        lines.extend([f"**Suggestion**: {finding.suggestion}", ""])
        return lines
