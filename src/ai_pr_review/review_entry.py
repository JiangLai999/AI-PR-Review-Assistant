"""Review 命令入口辅助函数。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from rich.console import Console

from ai_pr_review.config import AppConfig
from ai_pr_review.review_commands import (
    build_fetch_only_payload,
    build_filter_only_payload,
    render_selected_report,
    write_report_output,
)
from ai_pr_review.services.review_orchestrator import ReviewOrchestrator


def execute_review_flow(
    console: Console,
    *,
    pr_url: str,
    model: str | None,
    app_config: AppConfig,
    effective_format: str,
    output: Path | None,
    publish_comment: bool,
    dry_run: bool,
    only_fetch: bool,
    only_filter: bool,
    show_filter_reasons: bool,
    run_review,
    render_markdown_report,
    render_json_report,
    render_terminal_report,
    render_github_comment_report,
    maybe_publish_comment,
) -> None:
    selected_modes = sum(bool(flag) for flag in (dry_run, only_fetch, only_filter))
    if selected_modes > 1:
        raise ValueError("--dry-run、--only-fetch 和 --only-filter 不能同时使用。")

    if only_fetch:
        orchestrator = ReviewOrchestrator(app_config)
        artifacts = asyncio.run(orchestrator.fetch_only(pr_url))
        click_payload = build_fetch_only_payload(artifacts)
        console.print_json(data=click_payload)
        return

    if only_filter or dry_run:
        orchestrator = ReviewOrchestrator(app_config)
        artifacts = asyncio.run(orchestrator.filter_only(pr_url))
        click_payload = build_filter_only_payload(
            artifacts,
            dry_run=dry_run,
            show_filter_reasons=show_filter_reasons,
        )
        console.print_json(data=click_payload)
        return

    artifacts = asyncio.run(run_review(pr_url, model=model, verbose=False, config=app_config))
    rendered = render_selected_report(
        artifacts,
        app_config,
        effective_format=effective_format,
        render_markdown_report=render_markdown_report,
        render_json_report=render_json_report,
    )

    if effective_format == "terminal":
        render_terminal_report(console, artifacts, app_config)
    elif output is None:
        assert rendered is not None
        console.print(rendered, end="")

    if output is not None:
        write_report_output(
            output,
            rendered=rendered,
            artifacts=artifacts,
            app_config=app_config,
            render_terminal_report=render_terminal_report,
        )
        console.print(f"Report written to {output}")

    if publish_comment:
        comment_report = render_github_comment_report(artifacts, app_config)
        maybe_publish_comment(artifacts, comment_report, app_config)
        console.print("Published review comment to GitHub PR.")

    console.print(
        f"Saved run {artifacts.run_id} | cost=${artifacts.total_cost:.4f} | duration={artifacts.duration_seconds:.2f}s"
    )
