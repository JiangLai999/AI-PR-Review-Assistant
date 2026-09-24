"""Base interfaces for model providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ai_pr_review.config import ModelProviderConfig


@dataclass(slots=True)
class ProviderResponse:
    """Normalized provider response."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    raw_response: Any = None


class BaseModelProvider(ABC):
    """Unified provider interface."""

    def __init__(self, config: ModelProviderConfig) -> None:
        self.config = config
        self.config.validate()

    @abstractmethod
    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> ProviderResponse:
        """Send a chat completion request."""

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        on_delta: Callable[[str], Awaitable[None]],
        **kwargs: Any,
    ) -> ProviderResponse:
        """Complete-response fallback for providers without an incremental API.

        Providers that can emit deltas override this method; there is no separate
        capability flag because nothing ever needed to branch on one — the JSONL
        backend always emits `assistant.delta` frames either way.
        """
        cancel_event = kwargs.pop("cancel_event", None)
        response = await self.chat(messages, **kwargs)
        if cancel_event is not None and cancel_event.is_set():
            # Already cancelled while the complete response was in flight: hand
            # the text back to the caller but do not push it into the transcript.
            return response
        if response.text:
            await on_delta(response.text)
        return response

    async def list_models(self, **kwargs: Any) -> list[str]:
        """Return remotely available model IDs when the provider supports discovery."""

        return []

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        input_cost_per_million: float,
        output_cost_per_million: float,
    ) -> float:
        return (input_tokens / 1_000_000) * input_cost_per_million + (
            output_tokens / 1_000_000
        ) * output_cost_per_million
