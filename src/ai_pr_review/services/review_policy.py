"""Build provider-neutral policies for structured review requests."""

from __future__ import annotations

from typing import Any

from ai_pr_review.services.model_capabilities import get_model_capabilities


def structured_review_params(provider: str, model: str) -> dict[str, Any]:
    """Return only capabilities supported by the selected provider family."""
    profile = get_model_capabilities(provider, model)
    params: dict[str, Any] = {}
    if profile.supports_json_object:
        params["response_format"] = {"type": "json_object"}
    if profile.supports_thinking_disable:
        params["thinking"] = {"type": "disabled"}
    return params
