"""OpenAI 兼容接口模型供应商实现。

支持所有 OpenAI 兼容的 API 服务，包括 DeepSeek、Qwen、SiliconFlow 等。
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Awaitable, Callable
from typing import Any
from urllib import error, request

from ai_pr_review.config import ModelProviderConfig
from ai_pr_review.services.exceptions import (
    AIAuthenticationError,
    AIResponseFormatError,
    AIServiceError,
)
from ai_pr_review.services.model_providers.base import BaseModelProvider, ProviderResponse
from ai_pr_review.services.review_policy import structured_review_params


def _safe_close(response: Any) -> None:
    """Best-effort close used to unblock a reader thread during cancellation."""
    try:
        response.close()
    except Exception:  # pragma: no cover - closing must never mask the cancel
        pass


class _ResponseSlot:
    """Thread-safe holder for the in-flight streaming response.

    The reader thread stores the response while the event loop thread closes it
    on cancel, so every touch goes through the lock instead of relying on the
    GIL making list append/index atomic.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._response: Any = None

    def set(self, response: Any) -> None:
        with self._lock:
            self._response = response

    def clear(self) -> None:
        with self._lock:
            self._response = None

    def take(self) -> Any:
        """Detach and return the stored response."""
        with self._lock:
            response, self._response = self._response, None
            return response

    def close(self) -> None:
        """Close whatever is stored; safe from any thread, any number of times."""
        response = self.take()
        if response is not None:
            _safe_close(response)


class OpenAICompatibleProvider(BaseModelProvider):
    """OpenAI 兼容接口的 HTTP 客户端。

    支持 chat completion 和模型列表发现。
    """

    # 取消/事件循环繁忙时的 delta 投递上限：丢掉一帧好过卡死读线程。
    EMIT_TIMEOUT_SECONDS = 10.0

    # 等待响应头期间对 cancel_event 的轮询间隔（供应商 thinking 阶段可能长达数十秒）。
    CONNECT_POLL_SECONDS = 0.05

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> ProviderResponse:
        """异步发送聊天补全请求。"""
        return await asyncio.to_thread(self._chat_sync, messages, **kwargs)

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        on_delta: Callable[[str], Awaitable[None]],
        **kwargs: Any,
    ) -> ProviderResponse:
        """Read SSE frames as they arrive, without waiting for a complete response."""
        loop = asyncio.get_running_loop()
        cancel_event: threading.Event = kwargs.pop("cancel_event", threading.Event())
        active_response = _ResponseSlot()
        on_reasoning: Callable[[str], Awaitable[None]] | None = kwargs.pop(
            "on_reasoning", None
        )

        def emit(delta: str) -> None:
            if cancel_event.is_set():
                return
            if loop.is_closed():
                # Nothing can be delivered once the loop is gone. Returning here
                # instead of letting `run_coroutine_threadsafe` raise also avoids
                # building a coroutine that would never be awaited.
                return
            try:
                future = asyncio.run_coroutine_threadsafe(on_delta(delta), loop)
            except RuntimeError:
                # The event loop is already gone (cancelled turn): there is
                # nobody left to deliver deltas to.
                return
            try:
                future.result(timeout=self.EMIT_TIMEOUT_SECONDS)
            except TimeoutError:
                future.cancel()

        def emit_reasoning(delta: str) -> None:
            if on_reasoning is None or cancel_event.is_set() or loop.is_closed():
                return
            try:
                future = asyncio.run_coroutine_threadsafe(on_reasoning(delta), loop)
            except RuntimeError:
                return
            try:
                future.result(timeout=self.EMIT_TIMEOUT_SECONDS)
            except TimeoutError:
                future.cancel()

        try:
            return await asyncio.to_thread(
                self._stream_chat_sync,
                messages,
                emit,
                cancel_event,
                active_response,
                on_reasoning=emit_reasoning,
                **kwargs,
            )
        except asyncio.CancelledError:
            cancel_event.set()
            # Closing unblocks the reader's socket read. Doing it from a helper
            # thread keeps the event loop free and lets the reader observe the
            # resulting ValueError on its own thread, where the cancel path
            # below can treat it as an expected shutdown. The slot is still empty
            # when the cancel lands before the provider sent its headers — the
            # connector closes the late response instead (see `_open_stream`).
            threading.Thread(target=active_response.close, daemon=True).start()
            raise

    def _stream_chat_sync(
        self,
        messages: list[dict[str, Any]],
        emit: Callable[[str], None],
        cancel_event: threading.Event,
        active_response: _ResponseSlot,
        on_reasoning: Callable[[str], None] | None = None,
        **kwargs: Any,
    ) -> ProviderResponse:
        payload: dict[str, Any] = {
            "model": self.config.model_name,
            "messages": messages,
            "max_tokens": kwargs["max_tokens"],
            **self.config.extra_params,
            "stream": True,
        }
        for passthrough_key in ("think", "reasoning_effort"):
            if passthrough_key in kwargs:
                payload[passthrough_key] = kwargs[passthrough_key]
        system_prompt = kwargs.get("system_prompt", "")
        if system_prompt and not any(message.get("role") == "system" for message in messages):
            payload["messages"] = [{"role": "system", "content": system_prompt}, *messages]
        req = request.Request(
            self._chat_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                **self.config.headers,
            },
            method="POST",
        )
        parts: list[str] = []
        reasoning_parts: list[str] = []
        usage: dict[str, Any] = {}
        try:
            response = self._open_stream(req, kwargs["timeout_seconds"], cancel_event)
            # `None` means the user cancelled while the provider was still
            # thinking; the connector owns (and closes) whatever arrives later.
            if response is not None:
                active_response.set(response)
                with response:
                    for line in response:
                        if cancel_event.is_set():
                            break
                        data = line.decode("utf-8").strip()
                        if not data.startswith("data:"):
                            continue
                        data = data[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            frame = json.loads(data)
                        except json.JSONDecodeError as exc:
                            raise AIResponseFormatError(
                                "模型流式响应格式无效。", original_error=exc
                            ) from exc
                        if isinstance(frame.get("usage"), dict):
                            usage = frame["usage"]
                        choices = frame.get("choices") or []
                        delta = (
                            choices[0].get("delta", {})
                            if choices and isinstance(choices[0], dict)
                            else {}
                        )
                        content = delta.get("content") if isinstance(delta, dict) else None
                        if isinstance(content, list):
                            content = "".join(
                                str(block.get("text", ""))
                                for block in content
                                if isinstance(block, dict)
                            )
                        if isinstance(content, str) and content:
                            parts.append(content)
                            emit(content)
                        # Ollama/Qwen thinking models stream their chain of
                        # thought separately. Keep it as a last-resort answer,
                        # but do not interleave it with real content.
                        reasoning = (
                            delta.get("reasoning") or delta.get("reasoning_content")
                            if isinstance(delta, dict)
                            else None
                        )
                        if isinstance(reasoning, list):
                            reasoning = "".join(
                                str(block.get("text", ""))
                                for block in reasoning
                                if isinstance(block, dict)
                            )
                        if isinstance(reasoning, str) and reasoning:
                            reasoning_parts.append(reasoning)
                            if on_reasoning is not None:
                                on_reasoning(reasoning)
        except error.HTTPError as exc:
            if exc.code == 401:
                raise AIAuthenticationError(
                    "模型供应商 API 认证失败。", original_error=exc
                ) from exc
            raise AIServiceError(
                f"模型供应商请求失败: HTTP {exc.code}", original_error=exc
            ) from exc
        except error.URLError as exc:
            raise AIServiceError("模型供应商网络请求失败。", original_error=exc) from exc
        except (ValueError, OSError) as exc:
            # A cancel closes the response from another thread, which surfaces
            # here as a read on a closed file. Return whatever streamed so far
            # instead of reporting a user cancel as a provider failure.
            if not cancel_event.is_set():
                raise AIServiceError("模型供应商流式连接中断。", original_error=exc) from exc
        finally:
            active_response.clear()
        text = "".join(parts)
        if not text and not cancel_event.is_set():
            # Some reasoning models ignore `reasoning_effort` and only return
            # the reasoning channel. Surface it instead of a hard format error.
            text = "".join(reasoning_parts).strip()
            if text:
                emit(text)
        if not text and not cancel_event.is_set():
            raise AIResponseFormatError("模型流式响应没有可解析的文本内容。")
        return ProviderResponse(
            text=text,
            input_tokens=int(usage.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage.get("completion_tokens", 0) or 0),
            usage=self._normalize_usage(usage),
            reasoning="".join(reasoning_parts) or None,
        )

    def _open_stream(
        self,
        req: request.Request,
        timeout_seconds: float,
        cancel_event: threading.Event,
    ) -> Any | None:
        """Open the SSE response, giving up as soon as the user cancels.

        ``urlopen`` only returns once the provider has sent response headers, and
        a reasoning model can spend tens of seconds "thinking" before that.
        Waiting inline made a cancel during this window a no-op: the reader kept
        its socket until the first byte or the socket timeout expired. Connecting
        on a helper thread lets the worker poll the cancel flag meanwhile. When
        it fires we abandon the connection, and whichever side ends up holding
        the late response closes it — an unclosed response pins the connection.

        Returns ``None`` when the caller cancelled before the headers arrived.
        """
        lock = threading.Lock()
        state: dict[str, Any] = {"response": None, "error": None, "abandoned": False}

        def connect() -> None:
            try:
                response = request.urlopen(req, timeout=timeout_seconds)
            except BaseException as exc:  # re-raised on the worker thread
                with lock:
                    state["error"] = exc
                return
            with lock:
                abandoned = bool(state["abandoned"])
                if not abandoned:
                    state["response"] = response
            if abandoned:
                _safe_close(response)

        thread = threading.Thread(target=connect, daemon=True)
        thread.start()
        while thread.is_alive():
            # ``join`` returns as soon as the connector finishes, so a provider
            # that answers promptly pays no extra latency.
            thread.join(self.CONNECT_POLL_SECONDS)
            if cancel_event.is_set():
                with lock:
                    state["abandoned"] = True
                    stale, state["response"] = state["response"], None
                if stale is not None:
                    _safe_close(stale)
                return None
        with lock:
            outcome = state["error"] if state["error"] is not None else state["response"]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

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
                raise AIAuthenticationError(
                    "模型供应商 API 认证失败。", original_error=exc
                ) from exc
            detail = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else ""
            raise AIServiceError(
                f"模型列表请求失败: HTTP {exc.code} {detail}".strip(), original_error=exc
            ) from exc
        except error.URLError as exc:
            raise AIServiceError("模型列表网络请求失败。", original_error=exc) from exc

        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise AIResponseFormatError(
                "模型列表返回的 JSON 无法解析。", original_error=exc
            ) from exc

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
        for passthrough_key in ("think", "reasoning_effort"):
            if passthrough_key in kwargs:
                payload[passthrough_key] = kwargs[passthrough_key]
        # Structured output is a review-task policy, not a global chat default.
        # Ordinary `pr-review chat` must keep its natural-language responses.
        if kwargs.get("structured_output", False):
            for key, value in structured_review_params(
                self.config.name, self.config.model_name
            ).items():
                payload.setdefault(key, value)
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
                raise AIAuthenticationError(
                    "模型供应商 API 认证失败。", original_error=exc
                ) from exc
            detail = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else ""
            raise AIServiceError(
                f"模型供应商请求失败: HTTP {exc.code} {detail}".strip(), original_error=exc
            ) from exc
        except error.URLError as exc:
            raise AIServiceError("模型供应商网络请求失败。", original_error=exc) from exc

        try:
            payload = json.loads(raw_body)
            choice = payload["choices"][0]
            message = choice.get("message", {}) if isinstance(choice, dict) else {}
            text = self._extract_message_text(message, payload)
            if not text:
                raise ValueError(
                    f"empty model content; finish_reason={choice.get('finish_reason') if isinstance(choice, dict) else None}"
                )
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AIResponseFormatError(
                "OpenAI 兼容接口返回中没有可解析的文本内容。请检查模型是否支持当前 Chat Completions 接口。",
                original_error=exc,
            ) from exc

        usage = payload.get("usage", {})
        return ProviderResponse(
            text=text,
            input_tokens=int(usage.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage.get("completion_tokens", 0) or 0),
            raw_response=payload,
        )

    @staticmethod
    def _extract_message_text(message: Any, payload: dict[str, Any]) -> str:
        """Normalize string, block-array, and reasoning-style responses."""
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, str) and block.strip():
                    parts.append(block)
                elif isinstance(block, dict):
                    value = block.get("text") or block.get("content") or block.get("output_text")
                    if isinstance(value, str) and value.strip():
                        parts.append(value)
            if parts:
                return "\n".join(parts).strip()
        for candidate in (
            message.get("output_text") if isinstance(message, dict) else None,
            message.get("reasoning_content") if isinstance(message, dict) else None,
            message.get("thinking") if isinstance(message, dict) else None,
            message.get("reasoning") if isinstance(message, dict) else None,
            payload.get("output_text"),
            payload.get("reasoning"),
        ):
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return ""

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
