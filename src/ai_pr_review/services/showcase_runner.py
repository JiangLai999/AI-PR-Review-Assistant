"""Offline showcase payload builder shared by the CLI and the chat backend (§12.3).

`pr-review showcase --json-output` and the backend `showcase` command return the
same object, so the builder lives here and both callers use it.

Strictly offline: the only input is the already-loaded :class:`AppConfig`, and
the readiness flags are computed from local configuration alone. No model call,
no GitHub call, no writes — the steps are a script for the presenter to run,
not something this module executes.
"""

from __future__ import annotations

from typing import Any

from ai_pr_review.config import AppConfig

SHOWCASE_TITLE = "AI PR Review Assistant · Competition Showcase"

#: The recommended competition walkthrough. `dict(...)` copies on read so a
#: caller mutating the payload cannot change what the next caller sees.
SHOWCASE_STEPS: tuple[dict[str, Any], ...] = (
    {"step": 1, "command": "pr-review doctor", "purpose": "检查本地运行环境与凭据状态"},
    {
        "step": 2,
        "command": "pr-review demo --case sql-injection",
        "purpose": "离线展示规则、规划与证据校验",
    },
    {
        "step": 3,
        "command": "pr-review plan <PR_URL>",
        "purpose": "生成真实 PR 审查计划，不调用模型",
    },
    {"step": 4, "command": "pr-review <PR_URL> --verbose", "purpose": "执行完整 AI 审查并落库"},
    {"step": 5, "command": "pr-review history", "purpose": "复盘结果、成本与人工反馈"},
)


def api_key_configured(config: AppConfig) -> bool:
    """Whether the active provider can serve a request without further setup.

    Mirrors `cli._check_config_status(...)["api_key_configured"]`; the CLI's
    `showcase --json-output` bytes are pinned by tests, so the two must stay in
    step. The check lives here as well because importing the CLI from the chat
    backend would drag the whole front-end into the backend process.
    """
    active = config._active_provider_config()
    provider_name = active.name.lower().strip()
    return provider_name in {"ollama", "local"} or bool(active.api_key)


def github_token_configured(config: AppConfig) -> bool:
    resolver = getattr(config, "_resolve_github_token", None)
    return bool(resolver() if callable(resolver) else "")


def real_review_ready(config: AppConfig | None) -> bool:
    """True only when both halves of a real PR review are configured.

    A missing config (`AppConfig.load` failed) reports False rather than
    guessing: the showcase must never promise a real review the machine cannot
    run.
    """
    if config is None:
        return False
    return api_key_configured(config) and github_token_configured(config)


def showcase_payload(config: AppConfig | None = None) -> dict[str, Any]:
    """The object `pr-review showcase --json-output` prints."""
    return {
        "title": SHOWCASE_TITLE,
        "offline_ready": True,
        "real_review_ready": real_review_ready(config),
        "steps": [dict(step) for step in SHOWCASE_STEPS],
    }


def showcase_text(payload: dict[str, Any]) -> str:
    steps = payload.get("steps") if isinstance(payload.get("steps"), list) else []
    readiness = (
        "真实审查凭据已就绪"
        if payload.get("real_review_ready")
        else "真实 PR 步骤前需配置 GitHub + 模型凭据"
    )
    return f"{payload.get('title', SHOWCASE_TITLE)} · {len(steps)} 步 · 离线可用；{readiness}"


def showcase_payload_with_text(config: AppConfig | None = None) -> dict[str, Any]:
    """Backend `showcase` command payload: the CLI object plus a `text` summary."""
    payload = showcase_payload(config)
    return {**payload, "text": showcase_text(payload)}
