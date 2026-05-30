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

    def render_terminal(self, result: ReviewResult, pr_data: PRData) -> str:
        """渲染终端输出（Rich 格式）。"""
        console = Console(record=True)
        payload = self._build_payload(result, pr_data)
        pr = payload["pr"]
        counts = payload["counts"]

        summary_table = Table.grid(expand=True)
        summary_table.add_row(f"PR: #{pr['number']} - {pr['title']}")
        summary_table.add_row(f"Files Changed: {pr['files_changed']}")
        summary_table.add_row(f"Total Findings: {counts['total_findings']}")
        summary_table.add_row(
            " | ".join(
                f"{SEVERITY_LABELS[severity]}: {counts['by_severity'][severity]}"
                for severity in SEVERITY_ORDER
            )
        )

        console.print(Panel(summary_table, title=self._config.title, expand=False))
        if payload["summary"]:
            console.print(f"Summary: {payload['summary']}")

        if not payload["findings"]:
            console.print("No findings.")
            return console.export_text()

        for severity in SEVERITY_ORDER:
            findings = [item for item in payload["findings"] if item["severity"] == severity]
            if not findings:
                continue

            console.print()
            console.print(f"{SEVERITY_LABELS[severity]} Findings:", style=SEVERITY_STYLES[severity])
            for finding in findings:
                console.print(
                    f"{SEVERITY_ICONS[severity]} {finding['title']}",
                    style=SEVERITY_STYLES[severity],
                )
                console.print(
                    f"  File: {finding['file']}:{finding['line_start']}-{finding['line_end']}"
                )
                console.print(f"  Problem: {finding['problem']}")
                console.print(f"  Confidence: {finding['confidence']:.2f}")
                if finding["code_snippet"]:
                    console.print("  Code:")
                    console.print(Panel(finding["code_snippet"], expand=False))
                console.print(f"  Suggestion: {finding['suggestion']}")

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
            lines.extend(["### Findings", "", "No findings.", "", "---", "*Generated by AI PR Review Assistant*"])
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
