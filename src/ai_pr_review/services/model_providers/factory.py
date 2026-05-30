"""Provider factory."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ai_pr_review.config import ModelProviderConfig
from ai_pr_review.services.model_providers.anthropic import AnthropicProvider
from ai_pr_review.services.model_providers.api2d import API2DProvider
from ai_pr_review.services.model_providers.base import BaseModelProvider
from ai_pr_review.services.model_providers.deepseek import DeepSeekProvider
from ai_pr_review.services.model_providers.openai import OpenAICompatibleProvider
from ai_pr_review.services.model_providers.openrouter import OpenRouterProvider


def create_model_provider(
    config: ModelProviderConfig,
    *,
    client_factory: Callable[[str], Any] | None = None,
) -> BaseModelProvider:
    provider_name = config.name.lower()
    api_format = config.api_format.lower()

    if provider_name == "anthropic" or api_format == "anthropic":
        return AnthropicProvider(config, client_factory=client_factory)
    if provider_name == "deepseek":
        return DeepSeekProvider(config)
    if provider_name == "openrouter":
        return OpenRouterProvider(config)
    if provider_name == "api2d":
        return API2DProvider(config)
    return OpenAICompatibleProvider(config)
