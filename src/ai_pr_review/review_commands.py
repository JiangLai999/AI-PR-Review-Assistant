"""Review 命令辅助函数。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_pr_review.config import AppConfig
from ai_pr_review.services.review_orchestrator import ReviewArtifacts


def build_fetch_only_payload(artifacts: ReviewArtifacts) -> dict[str, Any]:
    return {
        "pr": artifacts.pr_data.model_dump(mode="json"),
        "run": {"duration_seconds": artifacts.duration_seconds},
    }


def build_filter_only_payload(
    artifacts: ReviewArtifacts, *, dry_run: bool, show_filter_reasons: bool
) -> dict[str, Any]:
    payload = {
        "pr": {
            "number": artifacts.pr_data.pr_number,
            "title": artifacts.pr_data.title,
            "url": artifacts.pr_data.url,
            "repository": artifacts.pr_data.repo_full_name,
            "files_changed": artifacts.pr_data.changed_files_count,
        },
        "filter": artifacts.filter_result.to_dict(),
        "run": {
            "dry_run": dry_run,
            "duration_seconds": artifacts.duration_seconds,
        },
    }
    if not show_filter_reasons:
        for result in payload["filter"]["results"]:
            result.pop("reasons", None)
    return payload


def render_selected_report(
    artifacts: ReviewArtifacts,
    app_config: AppConfig,
    *,
    effective_format: str,
    render_markdown_report,
    render_json_report,
) -> str | None:
    if effective_format == "markdown":
        return render_markdown_report(artifacts, app_config)
    if effective_format == "json":
        return render_json_report(artifacts, app_config)
    return None


def write_report_output(
    output: Path,
    *,
    rendered: str | None,
    artifacts: ReviewArtifacts,
    app_config: AppConfig,
    render_terminal_report,
) -> None:
    content = rendered
    if content is None:
        from rich.console import Console

        terminal_console = Console(record=True)
        render_terminal_report(terminal_console, artifacts, app_config)
        content = terminal_console.export_text()
    output.write_text(content, encoding="utf-8")
