"""Base interfaces for model providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
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
