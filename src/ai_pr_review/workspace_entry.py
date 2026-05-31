"""Workspace 命令入口辅助函数。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ai_pr_review.config import AppConfig


def build_history_output(config: AppConfig, *, pr_url: str | None, limit: int) -> dict:
    from ai_pr_review.services.result_store import ResultStore

    store = ResultStore(config.result_store)
    return {
        "runs": store.list_runs(pr_url=pr_url, limit=limit),
        "statistics": store.get_statistics(),
    }


def build_stats_output(config: AppConfig) -> dict:
    from ai_pr_review.services.result_store import ResultStore

    store = ResultStore(config.result_store)
    return store.get_statistics()


def apply_workspace_preferences(
    config: AppConfig,
    *,
    config_path: Path | None,
    ui_language: str | None,
    response_language: str | None,
    chat_layout: str | None,
    output_format: str | None,
    save_key_checker: Callable[[Path | None], bool],
) -> dict:
    changed = False
    if ui_language is not None:
        config.preferences.ui_language = ui_language
        changed = True
    if response_language is not None:
        config.preferences.language = response_language
        changed = True
    if chat_layout is not None:
        config.preferences.chat_layout = chat_layout
        changed = True
    if output_format is not None:
        config.preferences.output_format = output_format
        changed = True
    if changed:
        config.save(config_path, save_key=save_key_checker(config_path))
    return {
        "ui_language": config.preferences.ui_language,
        "language": config.preferences.language,
        "chat_layout": config.preferences.chat_layout,
        "output_format": config.preferences.output_format,
        "auto_publish_comment": config.preferences.auto_publish_comment,
    }
