"""OpenAI 兼容接口模型供应商实现。

支持所有 OpenAI 兼容的 API 服务，包括 DeepSeek、Qwen、SiliconFlow 等。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib import error, request

from ai_pr_review.config import ModelProviderConfig
from ai_pr_review.services.exceptions import AIAuthenticationError, AIResponseFormatError, AIServiceError
from ai_pr_review.services.model_providers.base import BaseModelProvider, ProviderResponse


class OpenAICompatibleProvider(BaseModelProvider):
    """OpenAI 兼容接口的 HTTP 客户端。

    支持 chat completion 和模型列表发现。
    """

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> ProviderResponse:
        """异步发送聊天补全请求。"""
        return await asyncio.to_thread(self._chat_sync, messages, **kwargs)

    async def list_models(self, **kwargs: Any) -> list[str]:
        """异步获取远端可用模型列表。"""
        return await asyncio.to_thread(self._list_models_sync, **kwargs)

    def _list_models_sync(self, **kwargs: Any) -> list[str]:
        """同步获取模型列表，调用 /models 接口。

        返回去重排序后的模型 ID 列表。
        """
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            **self.config.headers,
        }
        req = request.Request(self._models_url, headers=headers, method="GET")

        try:
            with request.urlopen(req, timeout=kwargs.get("timeout_seconds", 30)) as response:
                raw_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            if exc.code == 401:
                raise AIAuthenticationError("模型供应商 API 认证失败。", original_error=exc) from exc
            detail = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else ""
            raise AIServiceError(f"模型列表请求失败: HTTP {exc.code} {detail}".strip(), original_error=exc) from exc
        except error.URLError as exc:
            raise AIServiceError("模型列表网络请求失败。", original_error=exc) from exc

        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise AIResponseFormatError("模型列表返回的 JSON 无法解析。", original_error=exc) from exc

        data = payload.get("data")
        if not isinstance(data, list):
            raise AIResponseFormatError("模型列表返回格式无效：缺少 data 数组。")
        models: list[str] = []
        for item in data:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                models.append(item["id"])
            elif isinstance(item, str):
                models.append(item)
        return sorted(dict.fromkeys(models))

    def _chat_sync(self, messages: list[dict[str, Any]], **kwargs: Any) -> ProviderResponse:
        payload = {
            "model": self.config.model_name,
            "messages": messages,
            "max_tokens": kwargs["max_tokens"],
            **self.config.extra_params,
        }
        system_prompt = kwargs.get("system_prompt", "")
        if system_prompt and not any(message.get("role") == "system" for message in messages):
            payload["messages"] = [{"role": "system", "content": system_prompt}, *messages]

        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            **self.config.headers,
        }
        req = request.Request(self._chat_url, data=body, headers=headers, method="POST")

        try:
            with request.urlopen(req, timeout=kwargs["timeout_seconds"]) as response:
                raw_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            if exc.code == 401:
                raise AIAuthenticationError("模型供应商 API 认证失败。", original_error=exc) from exc
            detail = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else ""
            raise AIServiceError(f"模型供应商请求失败: HTTP {exc.code} {detail}".strip(), original_error=exc) from exc
        except error.URLError as exc:
            raise AIServiceError("模型供应商网络请求失败。", original_error=exc) from exc

        try:
            payload = json.loads(raw_body)
            choice = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise AIResponseFormatError("OpenAI 兼容接口返回格式无效。", original_error=exc) from exc

        usage = payload.get("usage", {})
        return ProviderResponse(
            text=str(choice).strip(),
            input_tokens=int(usage.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage.get("completion_tokens", 0) or 0),
            raw_response=payload,
        )

    @property
    def _chat_url(self) -> str:
        base_url = self.config.base_url.rstrip("/")
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"

    @property
    def _models_url(self) -> str:
        base_url = self.config.base_url.rstrip("/")
        if base_url.endswith("/chat/completions"):
            return f"{base_url.removesuffix('/chat/completions')}/models"
        return f"{base_url}/models"
