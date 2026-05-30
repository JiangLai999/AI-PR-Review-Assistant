"""API2D provider implementation."""

from ai_pr_review.services.model_providers.openai import OpenAICompatibleProvider


class API2DProvider(OpenAICompatibleProvider):
    """API2D uses an OpenAI-compatible API."""
