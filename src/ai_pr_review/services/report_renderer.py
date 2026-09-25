"""Review 报告渲染模块。"""

from __future__ import annotations

import io
import json
import re
from dataclasses import asdict, dataclass
from urllib.parse import quote

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

#: GitHub comment layout (v2). Kept separate from the terminal/markdown
#: renderers so those outputs stay byte-stable.
GITHUB_SEVERITY_ICONS = {
    "critical": "🛑",
    "high": "⚠️",
    "medium": "🔎",
    "low": "ℹ️",
    "info": "📝",
}

#: Chinese chrome for the comment. Model/rule prose is data and is never
#: rewritten; only the surrounding labels follow `GitHubCommentMeta.language`.
GITHUB_SEVERITY_LABELS_ZH = {
    "critical": "严重",
    "high": "高风险",
    "medium": "中风险",
    "low": "低风险",
    "info": "提示",
}
GITHUB_STATS_LABELS_ZH = {
    "critical": "严重",
    "high": "高",
    "medium": "中",
    "low": "低",
    "info": "提示",
}
GITHUB_CATEGORY_LABELS_ZH = {
    "correctness": "正确性",
    "security": "安全",
    "resource": "资源",
    "error_handling": "错误处理",
    "performance": "性能",
    "concurrency": "并发",
    "architecture": "架构",
}
_DEFAULT_GITHUB_TITLE = "AI PR Review Report"
_DEFAULT_GITHUB_TITLE_ZH = "AI PR 审查报告"

#: 证据状态术语的唯一真源（P6 计划 §1）。四个状态的含义固定为「位置与代码片段
#: 自洽」——`FindingValidator` 只证明这一点，所以文案不得写成「证据有效」或
#: 「问题成立」。终端明细行与 GitHub 评论徽章都从这里取词；TUI 侧见
#: `frontend/tui/src/review-ui/helpers.ts`。英文是既有输出，保持不变。
EVIDENCE_STATUS_LABELS: dict[str, tuple[str, str]] = {
    "valid": ("validated", "校验通过"),
    "needs_review": ("needs review", "待人工确认"),
    "invalid": ("invalid", "校验不成立"),
    "unverified": ("unverified", "未校验"),
}
#: 未知/缺失 status 按 `unverified` 处理，与 `FindingValidator` 的默认值一致。
_EVIDENCE_FALLBACK_STATUS = "unverified"


def _evidence_key(status: object) -> str:
    """把任意 status 归一到 `EVIDENCE_STATUS_LABELS` 的四个键之一。"""
    key = str(status or "").strip().lower()
    return key if key in EVIDENCE_STATUS_LABELS else _EVIDENCE_FALLBACK_STATUS


#: 评论徽章的图标；终端只用文字，因此图标单独一张表。
_EVIDENCE_ICONS = {
    "valid": "✅",
    "needs_review": "🔍",
    "invalid": "⛔",
    "unverified": "❔",
}

#: Fence language for the optional code snippet, so GitHub highlights it.
_FENCE_LANGUAGES = {
    "py": "python",
    "js": "javascript",
    "mjs": "javascript",
    "cjs": "javascript",
    "ts": "typescript",
    "tsx": "tsx",
    "jsx": "jsx",
    "sh": "bash",
    "ps1": "powershell",
    "json": "json",
    "yml": "yaml",
    "yaml": "yaml",
    "html": "html",
    "css": "css",
    "scss": "scss",
    "sql": "sql",
    "go": "go",
    "rs": "rust",
    "java": "java",
    "rb": "ruby",
    "php": "php",
    "cs": "csharp",
    "c": "c",
    "h": "c",
    "cpp": "cpp",
    "hpp": "cpp",
}

#: A paragraph inside the model summary that starts with a file path is split
#: out into the collapsible per-file section instead of drowning the top of the
#: comment.
_SUMMARY_FILE_PREFIX = re.compile(
    r"^(?P<path>[\w./\\-]+\.(?:py|js|mjs|cjs|ts|tsx|jsx|java|go|rs|rb|php|cs|kt|swift|c|h|cpp|hpp|"
    r"sh|ps1|sql|html|css|scss|less|json|ya?ml|toml|ini|cfg|md|txt|png|jpg|jpeg|svg|webp|lock))"
    r"\s*[:：]\s*(?P<body>.+)$",
    re.DOTALL,
)

#: Problem/suggestion text longer than this is folded behind `<details>` so the
#: scan path stays one screen per finding.
_GITHUB_FOLD_THRESHOLD = 320


@dataclass(slots=True)
class GitHubCommentMeta:
    """Optional enrichment for the GitHub comment header.

    Everything is optional: without it the comment still renders, it just has
    no model/run/cost line. `language` accepts `zh*` / anything else for English.

    ``from_fork`` exists because the renderer cannot tell on its own: a fork PR
    keeps its head commit outside the base repository, so a
    ``blob/<head_sha>`` link 404s. Callers that fetched the PR can say so, and
    the renderer then falls back to the PR files view.

    ``threshold`` / ``below_threshold`` / ``duplicates`` describe what the
    post-processor did to the model's candidates, so a comment that reports
    "0 findings" can be told apart from a comment whose findings were all
    dropped by the confidence threshold. Each of them is optional and each
    fragment is dropped on its own when its datum is missing: a run that never
    recorded filter statistics gets no audit line, not a fabricated 0.
    """

    language: str = "en"
    run_id: str = ""
    model: str = ""
    duration_seconds: float | None = None
    cost: float | None = None
    head_sha: str = ""
    reviewed_at: str = ""
    files_reviewed: int | None = None
    files_skipped: int | None = None
    from_fork: bool = False
    threshold: float | None = None
    below_threshold: int | None = None
    duplicates: int | None = None


#: GitHub rejects comment bodies above 65,536 characters. Stay well below that
#: and truncate loudly instead of failing the whole publish.
_GITHUB_SOFT_LIMIT = 24_000
_GITHUB_COMPACT_FINDINGS_PER_SEVERITY = 6


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
        # Render into an in-memory stream. Console(record=True) alone still
        # writes every console.print() call to stdout, and the exported text
        # would then be printed a second time by the CLI adapter.
        console = Console(record=True, file=io.StringIO())
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
            # Same normalization as the comment renderer: a value outside the
            # four states counts as `unverified` instead of raising KeyError.
            evidence_counts[_evidence_key(finding.get("evidence_status"))] += 1

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
        # The summary row spells the states out in full (§1): an abbreviated
        # 「无效」 next to a full 「校验不成立」 reads as two different states.
        summary_table.add_row(
            labels["evidence"],
            " · ".join(
                f"{EVIDENCE_STATUS_LABELS[key][1]} {evidence_counts[key]}"
                for key in ("valid", "needs_review", "invalid", "unverified")
            ),
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
            # Same words as the GitHub comment badge and the TUI (§1): the
            # status only says the location and snippet are self-consistent.
            status_label = EVIDENCE_STATUS_LABELS[_evidence_key(status)][1]
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

    def render_markdown(
        self,
        result: ReviewResult,
        pr_data: PRData,
        *,
        files_changed: int | None = None,
    ) -> str:
        """渲染 Markdown 报告。"""
        context = self._build_context(
            result,
            pr_data,
            include_code_snippets=True,
            files_changed=files_changed,
        )
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

    def render_github_comment(
        self,
        result: ReviewResult,
        pr_data: PRData,
        *,
        meta: GitHubCommentMeta | None = None,
    ) -> str:
        """Render the GitHub PR comment (v2 layout).

        Optimised for a reviewer who opens the comment once: target and stats
        first, a ranked "fix these first" shortlist, one collapsible block per
        severity, clickable `file:line` links, an evidence badge on every
        finding, and the long per-file model summary folded away at the bottom.
        """
        context = self._build_context(
            result,
            pr_data,
            include_code_snippets=self._config.include_code_snippets_in_github_comment,
        )
        if self._config.github_comment_template is not None:
            return self._config.github_comment_template.format_map(asdict(context))

        options = meta or GitHubCommentMeta()
        return self._render_github_comment_v2(result, pr_data, context, options)

    # ------------------------------------------------------------------
    # GitHub comment v2 building blocks
    # ------------------------------------------------------------------
    def _render_github_comment_v2(
        self,
        result: ReviewResult,
        pr_data: PRData,
        context: RenderedReportContext,
        meta: GitHubCommentMeta,
    ) -> str:
        zh = str(meta.language or "").lower().startswith("zh")
        grouped = self._group_findings(result.findings)
        ranked = [
            finding
            for severity in SEVERITY_ORDER
            for finding in sorted(grouped[severity], key=lambda item: item.confidence, reverse=True)
        ]
        evidence_counts = self._github_evidence_counts(result.findings)

        title = context.title
        if zh and title == _DEFAULT_GITHUB_TITLE:
            title = _DEFAULT_GITHUB_TITLE_ZH
        lines = [f"## 🤖 {title}", ""]
        lines.extend([self._github_target_line(context, meta, zh), ""])

        # One blockquote block: stats, evidence, provenance, and — closing it —
        # what the post-processor filtered out. Every line but the last gets an
        # explicit hard break so no renderer can join them.
        quote_lines = list(self._github_stats_line(context, evidence_counts, zh))
        meta_line = self._github_meta_line(meta, zh)
        if meta_line:
            quote_lines.append(meta_line)
        audit_line = self._github_audit_line(context, meta, zh)
        if audit_line:
            quote_lines.append(audit_line)
        lines.extend(
            [
                "> " + "  \n> ".join(quote_lines),
                "",
            ]
        )

        if not ranked:
            lines.extend(
                [
                    "### ✅ " + ("未发现问题" if zh else "No findings"),
                    "",
                    (
                        "本次审查在变更范围内未发现需要修复的问题。"
                        if zh
                        else "This review found nothing that needs fixing in the changed files."
                    ),
                    "",
                ]
            )
        else:
            lines.extend(self._github_top_findings(ranked, pr_data, meta, zh))
            lines.extend(self._github_severity_sections(grouped, pr_data, meta, zh))

        summary_block = self._github_summary_block(context.summary, zh)
        lines.extend(summary_block)

        lines.extend(["---", "*Generated by AI PR Review Assistant*"])
        footer = self._github_footer(meta, evidence_counts, context, zh)
        if footer:
            lines.append(footer)

        body = "\n".join(lines)
        if len(body) <= _GITHUB_SOFT_LIMIT:
            return body

        # Too long for one comment: first drop the per-file prose, then shorten
        # each severity block, and finally cut with an explicit marker. Never
        # silently publish a truncated report.
        head: list[str] = [
            f"## 🤖 {title}",
            "",
            self._github_target_line(context, meta, zh),
            "",
            "> " + "  \n> ".join(quote_lines),
            "",
        ]
        if ranked:
            head.extend(self._github_top_findings(ranked, pr_data, meta, zh))
        note = "> ⚠️ " + (
            f"评论超过 {_GITHUB_SOFT_LIMIT} 字符，逐文件摘要已省略，低优先级条目已折叠为计数。"
            if zh
            else f"Comment exceeded {_GITHUB_SOFT_LIMIT} characters: per-file prose omitted, lower-priority entries kept as counts."
        )
        closing = ["", "---", "*Generated by AI PR Review Assistant*"]
        footer = self._github_footer(meta, evidence_counts, context, zh)
        if footer:
            closing.append(footer)

        # Reserve room for the head, the degradation note, the closing block and
        # the truncation marker *before* laying out severity sections. The old
        # prefix cut could slice the note off, which hid the reason the report
        # was shortened.
        marker = (
            f"\n\n> ⛔ 评论过长已截断（>{_GITHUB_SOFT_LIMIT} 字符）；完整报告请运行 "
            f"`pr-review history {meta.run_id[:8] or '<run>'}`。\n"
            if zh
            else f"\n\n> ⛔ Comment truncated (over {_GITHUB_SOFT_LIMIT} chars); run "
            f"`pr-review history {meta.run_id[:8] or '<run>'}` for the full report.\n"
        )
        chunks = (
            self._github_severity_chunks(
                grouped,
                pr_data,
                meta,
                zh,
                max_per_severity=_GITHUB_COMPACT_FINDINGS_PER_SEVERITY,
            )
            if ranked
            else []
        )
        base = "\n".join([*head, note, *closing])
        def lay_out(budget: int) -> list[str]:
            taken: list[str] = []
            used = 0
            for chunk in chunks:
                if used + len(chunk) + 1 > budget:
                    break
                taken.append(chunk)
                used += len(chunk) + 1
            return taken

        # Pass 1: everything fits without a truncation notice -> nothing is
        # silently missing, so no notice is needed.
        kept = lay_out(_GITHUB_SOFT_LIMIT - len(base) - 2)
        if len(kept) == len(chunks):
            return "\n".join([*head, note, *kept, *closing])

        # Pass 2: something has to be dropped, so the notice is mandatory and
        # gets budget reserved before the sections are laid out again.
        kept = lay_out(_GITHUB_SOFT_LIMIT - len(base) - len(marker) - 2)
        compact_body = "\n".join([*head, note, *kept, *closing])
        if len(compact_body) + len(marker) <= _GITHUB_SOFT_LIMIT:
            return compact_body + marker
        # Unreachable for real reports (the head is bounded by the shortlist),
        # but never let the note or the marker be the thing that gets cut.
        head_text = "\n".join(head)
        reserve = len(note) + len(marker) + 2
        return head_text[: max(0, _GITHUB_SOFT_LIMIT - reserve)] + f"\n{note}{marker}"

    def _github_severity_sections(
        self,
        grouped: dict[str, list[Finding]],
        pr_data: PRData,
        meta: GitHubCommentMeta,
        zh: bool,
        *,
        max_per_severity: int | None = None,
    ) -> list[str]:
        lines: list[str] = []
        for chunk in self._github_severity_chunks(
            grouped, pr_data, meta, zh, max_per_severity=max_per_severity
        ):
            # `split("\n")`, not `splitlines()`: severity blocks end with a blank
            # line and the loose form would silently drop it, changing the normal
            # path output by a few bytes.
            lines.extend(chunk.split("\n"))
        return lines

    def _github_severity_chunks(
        self,
        grouped: dict[str, list[Finding]],
        pr_data: PRData,
        meta: GitHubCommentMeta,
        zh: bool,
        *,
        max_per_severity: int | None = None,
    ) -> list[str]:
        """One string per severity block, in `SEVERITY_ORDER`.

        The compact path needs whole blocks so it can drop them one by one while
        keeping the degradation note and the truncation marker intact.
        """
        chunks: list[str] = []
        for severity in SEVERITY_ORDER:
            findings = sorted(grouped[severity], key=lambda item: item.confidence, reverse=True)
            if not findings:
                continue
            shown = findings if max_per_severity is None else findings[:max_per_severity]
            section = self._github_severity_block(
                severity,
                shown,
                pr_data,
                meta,
                zh,
                include_code_snippet=self._config.include_code_snippets_in_github_comment,
            )
            if len(shown) < len(findings):
                hidden = len(findings) - len(shown)
                section.insert(
                    -2,
                    (
                        f"> … 另有 {hidden} 条同类问题未展开（见 `pr-review history {meta.run_id[:8]}`）"
                        if zh
                        else f"> … {hidden} more in this severity (see `pr-review history {meta.run_id[:8]}`)"
                    ),
                )
                section.insert(-1, "")
            chunks.append("\n".join(section))
        return chunks

    def _github_target_line(
        self, context: RenderedReportContext, meta: GitHubCommentMeta, zh: bool
    ) -> str:
        pr_ref = f"PR #{context.pr_number}"
        if context.pr_url:
            pr_ref = f"[{pr_ref}]({context.pr_url})"
        files_label = (
            f"{context.files_changed} 个变更文件"
            if zh
            else f"{context.files_changed} files changed"
        )
        target = f"**{self._github_code_span(context.repository)}** · {pr_ref}"
        if context.pr_title:
            target += f" · {self._github_escape_prose(context.pr_title)}"
        elif zh:
            target += " · （未记录标题）"
        if context.author and context.author != "unknown":
            target += f" · @{self._github_escape_prose(context.author)}"
        coverage = ""
        reviewed = meta.files_reviewed
        skipped = meta.files_skipped or 0
        if reviewed is not None:
            if zh:
                coverage = f" · 已审查 {reviewed}/{context.files_changed} 个文件"
                coverage += f"（跳过 {skipped}）" if skipped else ""
            else:
                coverage = f" · reviewed {reviewed}/{context.files_changed} files"
                coverage += f" (skipped {skipped})" if skipped else ""
        return f"{target} · {files_label}{coverage}"

    @staticmethod
    def _github_evidence_counts(findings: list[Finding]) -> dict[str, int]:
        counts = {"valid": 0, "needs_review": 0, "invalid": 0, "unverified": 0}
        for finding in findings:
            status = str(finding.evidence_status or "unverified").strip().lower()
            counts[status if status in counts else "unverified"] += 1
        return counts

    @staticmethod
    def _github_evidence_badge(status: str, zh: bool) -> str:
        """Describe the *validation* result, not the truth of the finding.

        `FindingValidator` only checks that the quoted file/lines/snippet are
        self-consistent with the diff. Saying「证据有效」for that over-claims, so
        the badges spell out what was validated.
        """
        key = _evidence_key(status)
        english, chinese = EVIDENCE_STATUS_LABELS[key]
        return f"{_EVIDENCE_ICONS[key]} {chinese if zh else english}"

    def _github_stats_line(
        self,
        context: RenderedReportContext,
        evidence: dict[str, int],
        zh: bool,
    ) -> list[str]:
        """Findings-distribution line plus the evidence-validation line."""
        counts = {
            "critical": context.critical_count,
            "high": context.high_count,
            "medium": context.medium_count,
            "low": context.low_count,
            "info": context.info_count,
        }
        severity_bits = []
        for severity in SEVERITY_ORDER:
            if counts[severity] <= 0:
                continue
            label = (
                GITHUB_STATS_LABELS_ZH[severity]
                if zh
                else SEVERITY_LABELS[severity].lower()
            )
            severity_bits.append(f"{GITHUB_SEVERITY_ICONS[severity]} {counts[severity]} {label}")
        total_label = "个问题" if zh else "findings"
        head = f"**{context.total_findings} {total_label}**"
        if severity_bits:
            head += " · " + " · ".join(severity_bits)
        evidence_label = "证据校验（位置与片段自洽）" if zh else "evidence (location + snippet)"
        evidence_bits = " · ".join(
            f"{self._github_evidence_badge(key, zh)} {evidence[key]}"
            for key in ("valid", "needs_review", "invalid", "unverified")
        )
        return [head, f"**{evidence_label}** {evidence_bits}"]

    @staticmethod
    def _github_audit_line(
        context: RenderedReportContext, meta: GitHubCommentMeta, zh: bool
    ) -> str:
        """Closing line of the stats block: what the filter did to the findings.

        The user story behind it: the same PR showed "2 findings" and then
        "0 findings", and nothing told the reader whether the second one was the
        model's verdict or a threshold swallowing every candidate. This line
        separates the two cases out loud — e.g.
        ``已审查 2/2 个文件 · 置信度门槛 0.60 · 低于门槛过滤 1 条 · 去重 0 条``.

        Each fragment stands on its own datum and is dropped alone when that
        datum is missing (an unknown threshold is never rendered as 0). A run
        with no recorded filter statistics at all gets no line: its coverage is
        already carried by the target line, and inventing the rest would be
        worse than saying nothing.
        """
        if meta.threshold is None and meta.below_threshold is None and meta.duplicates is None:
            return ""
        bits: list[str] = []
        if meta.files_reviewed is not None:
            bits.append(
                f"已审查 {meta.files_reviewed}/{context.files_changed} 个文件"
                if zh
                else f"reviewed {meta.files_reviewed}/{context.files_changed} files"
            )
        if meta.threshold is not None:
            bits.append(
                f"置信度门槛 {meta.threshold:.2f}"
                if zh
                else f"confidence threshold {meta.threshold:.2f}"
            )
        if meta.below_threshold is not None:
            bits.append(
                f"低于门槛过滤 {meta.below_threshold} 条"
                if zh
                else f"filtered {meta.below_threshold} below threshold"
            )
        if meta.duplicates is not None:
            bits.append(f"去重 {meta.duplicates} 条" if zh else f"{meta.duplicates} duplicates")
        return " · ".join(bits)

    @staticmethod
    def _github_meta_line(meta: GitHubCommentMeta, zh: bool) -> str:
        bits: list[str] = []
        if meta.reviewed_at:
            bits.append(f"{'审查于' if zh else 'reviewed'} {meta.reviewed_at}")
        if meta.model:
            bits.append(f"模型 `{meta.model}`" if zh else f"model `{meta.model}`")
        if meta.run_id:
            bits.append(f"run `{meta.run_id[:8]}`")
        if meta.duration_seconds is not None:
            bits.append(
                f"耗时 {meta.duration_seconds:.1f}s" if zh else f"{meta.duration_seconds:.1f}s"
            )
        if meta.cost is not None:
            # Local token×price estimate, not a bill: mark it as such.
            if meta.cost <= 0:
                bits.append("成本未记录" if zh else "cost not recorded")
            else:
                bits.append(f"≈ ${meta.cost:.4f}")
        return " · ".join(bits)

    @staticmethod
    def _github_blob_link(finding: Finding, pr_data: PRData, head_sha: str) -> str | None:
        """`file:line` deep link, when the commit is known.

        Only a missing sha is handled here. A fork PR has a non-empty sha whose
        commit lives in the fork, so callers that know the PR is from a fork must
        set `GitHubCommentMeta.from_fork` — the renderer then links the PR files
        view instead of a blob URL that would 404.
        """
        sha = (head_sha or "").strip()
        if not sha:
            return None
        path = quote(str(finding.file or ""), safe="/")
        if not path:
            return None
        url = f"https://github.com/{pr_data.owner}/{pr_data.repo}/blob/{sha}/{path}"
        if finding.line_start:
            url += f"#L{finding.line_start}"
            if finding.line_end and finding.line_end != finding.line_start:
                url += f"-L{finding.line_end}"
        return url

    def _github_location(
        self, finding: Finding, pr_data: PRData, meta: GitHubCommentMeta
    ) -> str:
        label = f"{finding.file}:{finding.line_start}"
        if finding.line_end and finding.line_end != finding.line_start:
            label = f"{finding.file}:{finding.line_start}-{finding.line_end}"
        link = None
        if meta.from_fork:
            # The head commit is not in the base repository, so a blob URL would
            # 404; the PR files view always exists.
            files_url = f"https://github.com/{pr_data.owner}/{pr_data.repo}/pull/{pr_data.pr_number}/files"
            link = files_url
        else:
            link = self._github_blob_link(finding, pr_data, meta.head_sha)
        span = self._github_code_span(label)
        return f"[{span}]({link})" if link else span

    def _github_top_findings(
        self,
        ranked: list[Finding],
        pr_data: PRData,
        meta: GitHubCommentMeta,
        zh: bool,
    ) -> list[str]:
        limit = 3
        heading = "🎯 优先修复" if zh else "🎯 Fix first"
        lines = [f"### {heading}（Top {min(limit, len(ranked))}）" if zh else f"### {heading} (top {min(limit, len(ranked))})", ""]
        for index, finding in enumerate(ranked[:limit], start=1):
            confidence = f"{finding.confidence * 100:.0f}%"
            lines.append(
                f"{index}. {GITHUB_SEVERITY_ICONS[finding.severity]} "
                f"**{self._github_escape_prose(finding.title)}** · "
                f"{self._github_location(finding, pr_data, meta)} · {confidence} · "
                f"{self._github_evidence_badge(finding.evidence_status, zh)}"
            )
        lines.append("")
        return lines

    def _github_severity_block(
        self,
        severity: str,
        findings: list[Finding],
        pr_data: PRData,
        meta: GitHubCommentMeta,
        zh: bool,
        *,
        include_code_snippet: bool,
    ) -> list[str]:
        if zh:
            title = f"{GITHUB_SEVERITY_ICONS[severity]} {GITHUB_SEVERITY_LABELS_ZH[severity]} · {len(findings)} 条"
        else:
            title = f"{GITHUB_SEVERITY_ICONS[severity]} {SEVERITY_LABELS[severity]} · {len(findings)}"
        # Only the most severe block is expanded: the shortlist above already
        # carries the headline items, so everything else stays one click away.
        opening = "<details open>" if severity == "critical" else "<details>"
        lines = [opening, f"<summary><b>{title}</b></summary>", ""]
        for index, finding in enumerate(findings, start=1):
            lines.extend(
                self._github_finding_card(
                    finding,
                    index,
                    pr_data,
                    meta,
                    zh,
                    include_code_snippet=include_code_snippet,
                )
            )
        lines.extend(["</details>", ""])
        return lines

    def _github_finding_card(
        self,
        finding: Finding,
        index: int,
        pr_data: PRData,
        meta: GitHubCommentMeta,
        zh: bool,
        *,
        include_code_snippet: bool,
    ) -> list[str]:
        confidence = f"{finding.confidence * 100:.0f}%"
        sources = ", ".join(f"`{source}`" for source in (finding.sources or []))
        detail_bits = [
            self._github_location(finding, pr_data, meta),
            (f"置信度 {confidence}" if zh else f"confidence {confidence}"),
            self._github_evidence_badge(finding.evidence_status, zh),
        ]
        if finding.category:
            category = (
                GITHUB_CATEGORY_LABELS_ZH.get(finding.category, finding.category)
                if zh
                else finding.category
            )
            detail_bits.append(f"`{category}`")
        if sources:
            detail_bits.append(sources)

        lines = [
            f"#### {index}. {GITHUB_SEVERITY_ICONS[finding.severity]} "
            f"{self._github_escape_prose(finding.title)}",
            " · ".join(detail_bits),
            "",
        ]
        if finding.evidence_issues:
            escaped_issues = [self._github_escape_prose(issue) for issue in finding.evidence_issues]
            issues = "；".join(escaped_issues) if zh else "; ".join(escaped_issues)
            lines.extend([f"> ⚠️ {'证据疑点' if zh else 'evidence issues'}：{issues}", ""])

        problem_label = "问题" if zh else "Problem"
        suggestion_label = "建议" if zh else "Suggestion"
        code_label = "代码" if zh else "Code"
        fence = self._github_fence_language(finding.file)
        problem = self._github_escape_prose(finding.problem)
        suggestion = self._github_escape_prose(finding.suggestion)
        fold = len(problem) + len(suggestion) > _GITHUB_FOLD_THRESHOLD
        if fold:
            lines.extend(
                [
                    "<details>",
                    f"<summary>{problem_label} / {suggestion_label}</summary>",
                    "",
                    f"**{problem_label}**：{problem}",
                    "",
                    f"**{suggestion_label}**：{suggestion}",
                    "",
                ]
            )
            if include_code_snippet and finding.code_snippet:
                lines.extend(self._github_code_block(finding.code_snippet, fence, code_label))
            lines.extend(["</details>", ""])
            return lines

        lines.extend([f"**{problem_label}**：{problem}", "", f"**{suggestion_label}**：{suggestion}", ""])
        if include_code_snippet and finding.code_snippet:
            lines.extend(self._github_code_block(finding.code_snippet, fence, code_label))
        return lines

    @staticmethod
    def _github_code_block(snippet: str, fence: str, label: str) -> list[str]:
        """Fence the snippet with a delimiter the snippet itself cannot close."""
        body = str(snippet or "")
        longest = max((len(run) for run in re.findall(r"`+", body)), default=0)
        delimiter = "`" * max(3, longest + 1)
        return [f"**{label}**：", f"{delimiter}{fence}", body, delimiter, ""]

    @staticmethod
    def _github_fence_language(filename: str) -> str:
        suffix = str(filename or "").rsplit(".", 1)[-1].lower() if "." in str(filename or "") else ""
        return _FENCE_LANGUAGES.get(suffix, "")

    @staticmethod
    def _github_escape_prose(text: object) -> str:
        """Escape model/rule prose so GitHub renders it literally.

        GitHub strips unknown HTML tags: a model sentence containing `<head>` or
        `target="_blank"` would silently lose those words. Escaping the angle
        brackets keeps the reviewer's evidence intact, and a leading `#` is
        neutralised so prose cannot inject a heading.
        """
        value = str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        value = " ".join(value.split())
        return re.sub(r"^(#{1,6})(\s)", r"\\\1\2", value)

    @staticmethod
    def _github_code_span(text: object) -> str:
        """Backtick span that survives a backtick inside the value."""
        value = str(text or "").strip()
        if "`" in value:
            return f"`` {value} ``"
        return f"`{value}`"

    def _github_summary_block(self, summary: str, zh: bool) -> list[str]:
        """Split the model summary so file-by-file prose stops dominating.

        Anything before the first `path:` paragraph stays visible as the review
        conclusion; the per-file paragraphs move into a collapsed block.
        """
        text = str(summary or "").strip()
        if not text:
            return []

        overview: list[str] = []
        per_file: list[tuple[str, str]] = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            match = _SUMMARY_FILE_PREFIX.match(line)
            if match:
                per_file.append((match.group("path"), match.group("body").strip()))
            elif per_file:
                path, body = per_file[-1]
                per_file[-1] = (path, f"{body} {line}".strip())
            else:
                overview.append(line)

        lines: list[str] = []
        if overview:
            heading = "### 📌 结论摘要" if zh else "### 📌 Review summary"
            lines.extend(
                [heading, "", self._github_escape_prose(" ".join(overview)), ""]
            )
        if per_file:
            heading = (
                f"📄 模型摘要覆盖的 {len(per_file)} 个文件"
                if zh
                else f"📄 Model summary by file ({len(per_file)} files)"
            )
            lines.extend(["<details>", f"<summary><b>{heading}</b></summary>", ""])
            for path, body in per_file:
                lines.extend(
                    [
                        f"**{self._github_code_span(path)}**",
                        "",
                        f"> {self._github_escape_prose(body)}",
                        "",
                    ]
                )
            lines.extend(["</details>", ""])
        return lines

    def _github_footer(
        self,
        meta: GitHubCommentMeta,
        evidence: dict[str, int],
        context: RenderedReportContext,
        zh: bool,
    ) -> str:
        bits: list[str] = []
        if zh:
            bits.append(
                f"证据优先 · 位置与片段校验通过 {evidence['valid']}/{context.total_findings}"
            )
        else:
            bits.append(
                f"evidence-first · {evidence['valid']}/{context.total_findings} locations and snippets validated"
            )
        if meta.model:
            bits.append(f"{'模型' if zh else 'model'} `{meta.model}`")
        if meta.run_id:
            bits.append(f"run `{meta.run_id[:8]}`")
        if meta.head_sha:
            bits.append(f"{'提交' if zh else 'commit'} `{meta.head_sha[:7]}`")
        return f"<sub>{' · '.join(bits)}</sub>"

    def _build_payload(
        self,
        result: ReviewResult,
        pr_data: PRData,
        *,
        files_changed: int | None = None,
    ) -> dict:
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
                # Rendered from history the per-file list is gone, so callers may
                # pass the persisted count instead of reporting a misleading 0.
                "files_changed": (
                    pr_data.changed_files_count if files_changed is None else files_changed
                ),
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
        files_changed: int | None = None,
    ) -> RenderedReportContext:
        payload = self._build_payload(result, pr_data, files_changed=files_changed)
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
