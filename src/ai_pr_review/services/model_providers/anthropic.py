"""Anthropic provider implementation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from ai_pr_review.config import ModelProviderConfig
from ai_pr_review.services.exceptions import AIResponseFormatError, AIServiceError
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

    @staticmethod
    def _extract_text(message: Any) -> str:
        """Join the text blocks of a Messages API response.

        Shared by the streaming and non-streaming paths: a thinking-only reply
        carries its answer in `thinking` blocks, so reading `text_stream` alone
        returned an empty string for a response the complete path could read.
        """
        parts: list[str] = []
        for block in getattr(message, "content", []) or []:
            text = getattr(block, "text", None)
            if not text:
                text = getattr(block, "thinking", None)
            if not text and isinstance(block, dict):
                text = block.get("text") or block.get("thinking") or block.get("content")
            if text:
                parts.append(str(text))
        if not parts:
            output_text = getattr(message, "output_text", None)
            if output_text:
                parts.append(str(output_text))
        return "\n".join(parts).strip()

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> ProviderResponse:
        response = await self._client.messages.create(
            model=self.config.model_name,
            max_tokens=kwargs["max_tokens"],
            system=kwargs.get("system_prompt", ""),
            messages=messages,
            **self.config.extra_params,
        )
        usage = getattr(response, "usage", None)
        return ProviderResponse(
            text=self._extract_text(response),
            input_tokens=getattr(usage, "input_tokens", 0),
            output_tokens=getattr(usage, "output_tokens", 0),
            raw_response=response,
        )

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        on_delta: Callable[[str], Awaitable[None]],
        **kwargs: Any,
    ) -> ProviderResponse:
        """Stream text deltas through the SDK helper.

        The previous behaviour fell back to a complete response, so a cancel
        only took effect after the whole reply had been generated.
        """
        cancel_event = kwargs.pop("cancel_event", None)
        parts: list[str] = []
        final: Any = None
        cancelled = False
        async with self._client.messages.stream(
            model=self.config.model_name,
            max_tokens=kwargs["max_tokens"],
            system=kwargs.get("system_prompt", ""),
            messages=messages,
            **self.config.extra_params,
        ) as stream:
            async for chunk in stream.text_stream:
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    break
                if not chunk:
                    continue
                parts.append(chunk)
                await on_delta(chunk)
            if not cancelled:
                # Skipping this while cancelled matters: the call would block
                # until the whole response finished, which is exactly what the
                # user asked to stop.
                final = await stream.get_final_message()
        text = "".join(parts)
        if not text and final is not None:
            # A thinking-only reply (extra_params.thinking) or a stream that ends
            # without any text block produces no deltas at all. The complete path
            # already recovered the answer from the final message; without the
            # same fallback the caller persisted "" into the transcript and the
            # user saw an empty answer instead of the reply.
            text = self._extract_text(final)
        if not text and not cancelled:
            # Matches the OpenAI-compatible provider: an empty stream is a
            # failure, not a valid blank assistant turn.
            raise AIResponseFormatError("模型流式响应没有可解析的文本内容。")
        usage = getattr(final, "usage", None)
        return ProviderResponse(
            text=text,
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            raw_response=final,
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
