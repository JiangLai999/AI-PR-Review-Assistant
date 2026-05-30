"""OpenRouter provider implementation."""

from ai_pr_review.services.model_providers.openai import OpenAICompatibleProvider


class OpenRouterProvider(OpenAICompatibleProvider):
    """OpenRouter uses an OpenAI-compatible API."""
