"""Anthropic provider implementation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ai_pr_review.config import ModelProviderConfig
from ai_pr_review.services.exceptions import AIServiceError
from ai_pr_review.services.model_providers.base import BaseModelProvider, ProviderResponse


class AnthropicProvider(BaseModelProvider):
    """Anthropic Messages API wrapper."""

    def __init__(
        self,
        config: ModelProviderConfig,
        client_factory: Callable[[str], Any] | None = None,
    ) -> None:
        super().__init__(config)
        self._client_factory = client_factory or self._default_client_factory
        self._client = self._client_factory(self.config.api_key)

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> ProviderResponse:
        response = await self._client.messages.create(
            model=self.config.model_name,
            max_tokens=kwargs["max_tokens"],
            system=kwargs.get("system_prompt", ""),
            messages=messages,
            **self.config.extra_params,
        )
        parts: list[str] = []
        for block in getattr(response, "content", []) or []:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        usage = getattr(response, "usage", None)
        return ProviderResponse(
            text="\n".join(parts).strip(),
            input_tokens=getattr(usage, "input_tokens", 0),
            output_tokens=getattr(usage, "output_tokens", 0),
            raw_response=response,
        )

    def _default_client_factory(self, api_key: str) -> Any:
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:
            raise AIServiceError(
                "未安装 anthropic 依赖，无法创建 AI 客户端。", original_error=exc
            ) from exc

        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if self.config.base_url:
            client_kwargs["base_url"] = self.config.base_url
        if self.config.headers:
            client_kwargs["default_headers"] = self.config.headers
        return AsyncAnthropic(**client_kwargs)
