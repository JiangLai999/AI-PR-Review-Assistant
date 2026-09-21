"""Ollama provider helpers built on the local OpenAI-compatible endpoint."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib import error, request

from ai_pr_review.config import ModelProviderConfig
from ai_pr_review.services.exceptions import (
    AIAuthenticationError,
    AIResponseFormatError,
    AIServiceError,
)
from ai_pr_review.services.model_providers.openai import OpenAICompatibleProvider


class OllamaProvider(OpenAICompatibleProvider):
    """Local Ollama provider with health and installed-model discovery."""

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any):
        """Use fast non-thinking mode for Copilot routing by default."""
        kwargs.setdefault("think", False)
        # Ollama/Qwen may spend a small JSON-routing budget entirely in reasoning
        # when response_format is forced. The router already validates JSON, so
        # keep the wire request prompt-constrained and non-thinking.
        kwargs["structured_output"] = False
        return await super().chat(messages, **kwargs)

    async def health_check(self, **kwargs: Any) -> bool:
        return await asyncio.to_thread(self._health_check_sync, **kwargs)

    async def list_models(self, **kwargs: Any) -> list[str]:
        """Prefer Ollama's native /api/tags endpoint for local model discovery."""

        return await asyncio.to_thread(self._list_ollama_models_sync, **kwargs)

    def _health_check_sync(self, **kwargs: Any) -> bool:
        base_url = self.config.base_url.rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]
        req = request.Request(f"{base_url}/api/tags", method="GET")
        try:
            with request.urlopen(req, timeout=kwargs.get("timeout_seconds", 5)) as response:
                return 200 <= response.status < 300
        except (error.HTTPError, error.URLError, TimeoutError) as exc:
            raise AIServiceError(
                "无法连接本地 Ollama 服务，请确认 Ollama 已启动。", original_error=exc
            ) from exc

    def _list_ollama_models_sync(self, **kwargs: Any) -> list[str]:
        base_url = self.config.base_url.rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]
        req = request.Request(f"{base_url}/api/tags", method="GET")
        try:
            with request.urlopen(req, timeout=kwargs.get("timeout_seconds", 10)) as response:
                body = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise AIAuthenticationError(
                    "本地 Ollama 服务拒绝请求。", original_error=exc
                ) from exc
            raise AIServiceError(
                f"Ollama 模型列表请求失败：HTTP {exc.code}", original_error=exc
            ) from exc
        except (error.URLError, TimeoutError) as exc:
            raise AIServiceError(
                "无法连接本地 Ollama 服务，请确认 Ollama 已启动。", original_error=exc
            ) from exc
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
            raise AIResponseFormatError(
                "Ollama 模型列表响应格式无效。", original_error=exc
            ) from exc

        models = body.get("models") if isinstance(body, dict) else None
        if not isinstance(models, list):
            raise AIResponseFormatError("Ollama 模型列表响应缺少 models 字段。")
        names = [item.get("name") for item in models if isinstance(item, dict) and item.get("name")]
        return sorted(dict.fromkeys(str(name) for name in names))
