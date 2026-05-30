"""DeepSeek provider implementation."""

from ai_pr_review.services.model_providers.openai import OpenAICompatibleProvider


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek uses an OpenAI-compatible API."""
