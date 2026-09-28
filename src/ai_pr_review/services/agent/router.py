"""Chat intent routing for the local Agent Copilot."""

from __future__ import annotations

import json
import re
from typing import Any

from ai_pr_review.services.agent.actions import ChatAction
from ai_pr_review.services.agent.context import ChatContext
from ai_pr_review.services.model_providers.base import BaseModelProvider

_PR_URL_RE = re.compile(r"https?://github\.com/[^\s]+/[^\s]+/pull/\d+", re.I)


class ChatActionRouter:
    """Use deterministic routing first and the local model only when needed."""

    def __init__(self, provider: BaseModelProvider, *, model_name: str) -> None:
        self.provider = provider
        self.model_name = model_name

    async def route(self, text: str, context: ChatContext) -> ChatAction:
        deterministic = self._deterministic_route(text, context)
        if deterministic is not None:
            return deterministic
        return await self._model_route(text, context)

    def _deterministic_route(self, text: str, context: ChatContext) -> ChatAction | None:
        normalized = text.strip().lower()
        if not normalized:
            return ChatAction(action="chat", source="deterministic")
        if normalized in {"停止", "取消", "stop", "cancel", "/cancel"}:
            return ChatAction(
                action="cancel_review", requires_confirmation=False, source="deterministic"
            )

        action: str | None = None

        # Configuration actions
        if any(
            keyword in normalized
            for keyword in ["开始配置", "配置模型", "配置供应商", "configure provider", "setup"]
        ):
            action = "configure_provider"
        elif any(
            keyword in normalized for keyword in ["配置 github", "github token", "configure github"]
        ):
            action = "configure_github"
        # Analysis actions
        elif any(
            keyword in normalized
            for keyword in ["历史分析", "分析历史", "趋势分析", "analyze history", "history trend"]
        ):
            action = "analyze_history"
        # Review actions
        elif (
            "生成审查计划" in normalized or "只看计划" in normalized or "review plan" in normalized
        ):
            action = "create_review_plan"
        elif "解释" in normalized and ("问题" in normalized or "finding" in normalized):
            action = "explain_finding"
        elif "历史" in normalized or "上一次审查" in normalized or "审查记录" in normalized:
            action = "list_history"
        elif (
            "环境" in normalized
            or "配置状态" in normalized
            or "模型状态" in normalized
            or "检查环境" in normalized
        ):
            action = "check_environment"
        else:
            action = (
                "start_review" if _PR_URL_RE.search(text) or "审查这个 pr" in normalized else None
            )

        if action is None:
            return None

        args: dict[str, Any] = {}
        match = _PR_URL_RE.search(text)
        if match:
            args["pr_url"] = match.group(0).rstrip(".,)>")
        if context.current_run_id:
            args["run_id"] = context.current_run_id

        return ChatAction(
            action=action,
            arguments=args,
            requires_confirmation=action
            in {"start_review", "create_review_plan", "configure_provider", "configure_github"},
            risk_level=(
                "high"
                if action in {"start_review", "configure_provider", "configure_github"}
                else "low"
            ),
            source="deterministic",
        )

    async def _model_route(self, text: str, context: ChatContext) -> ChatAction:
        prompt = {
            "task": "Classify the user's intent into exactly one action.",
            "allowed_actions": [
                "chat",
                "start_review",
                "create_review_plan",
                "explain_finding",
                "list_history",
                "analyze_history",
                "check_environment",
                "cancel_review",
                "configure_provider",
                "configure_github",
            ],
            "user_text": text,
            "current_run_id": context.current_run_id,
            "output_schema": {
                "action": "string",
                "arguments": "object",
                "requires_confirmation": "boolean",
                "risk_level": "low|medium|high",
            },
        }
        try:
            response = await _run_provider_chat(
                self.provider,
                [{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
                model_name=self.model_name,
            )
            payload = json.loads(response)
            if not isinstance(payload, dict):
                raise ValueError("router response must be an object")
            allowed = {
                "chat",
                "start_review",
                "create_review_plan",
                "explain_finding",
                "list_history",
                "analyze_history",
                "check_environment",
                "cancel_review",
                "configure_provider",
                "configure_github",
            }
            action = str(payload.get("action", "chat"))
            if action not in allowed:
                action = "chat"
            arguments = payload.get("arguments", {})
            return ChatAction(
                action=action,
                arguments=arguments if isinstance(arguments, dict) else {},
                requires_confirmation=bool(payload.get("requires_confirmation", False)),
                risk_level=str(payload.get("risk_level", "low")),
                source="local_model",
            )
        except (ValueError, TypeError, json.JSONDecodeError):
            return ChatAction(action="chat", source="local_model_fallback")


async def _run_provider_chat(
    provider: BaseModelProvider, messages: list[dict[str, Any]], *, model_name: str
) -> str:
    response = await provider.chat(
        messages,
        max_tokens=1536,
        timeout_seconds=30,
        structured_output=True,
        model=model_name,
    )
    return response.text
