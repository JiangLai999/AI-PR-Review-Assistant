"""Model provider and config integration tests."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from types import SimpleNamespace
from urllib import error

import pytest

from ai_pr_review.config import AIClientConfig, ConfigValidationError, ModelProviderConfig
from ai_pr_review.services.ai_client import AIClient
from ai_pr_review.services.exceptions import (
    AIAuthenticationError,
    AIResponseFormatError,
    AIServiceError,
)
from ai_pr_review.services.model_providers.anthropic import AnthropicProvider
from ai_pr_review.services.model_providers.base import ProviderResponse
from ai_pr_review.services.model_providers.factory import create_model_provider
from ai_pr_review.services.model_providers.ollama import OllamaProvider
from ai_pr_review.services.model_providers.openai import OpenAICompatibleProvider


class StubAnthropicMessages:
    async def create(self, **kwargs):
        return SimpleNamespace(
            content=[SimpleNamespace(text='{"summary":"ok","findings":[]}')],
            usage=SimpleNamespace(input_tokens=12, output_tokens=5),
        )


class StubAnthropicClient:
    def __init__(self):
        self.messages = StubAnthropicMessages()


def test_model_provider_config_from_name_uses_preset(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")

    config = ModelProviderConfig.from_name("deepseek")

    assert config.base_url == "https://api.deepseek.com/v1"
    assert config.api_format == "openai"
    assert config.api_key == "deepseek-key"


def test_model_provider_validate_rejects_missing_base_url_for_openai_format():
    config = ModelProviderConfig(
        name="custom",
        display_name="Custom",
        api_key="key",
        base_url="",
        model_name="m",
        api_format="openai",
    )

    with pytest.raises(ConfigValidationError, match="base_url"):
        config.validate()


def test_model_provider_validate_rejects_non_https_base_url():
    config = ModelProviderConfig(
        name="custom",
        display_name="Custom",
        api_key="key",
        base_url="http://example.com/v1",
        model_name="m",
        api_format="openai",
    )

    with pytest.raises(ConfigValidationError, match="HTTPS"):
        config.validate()


def test_model_provider_custom_risk_warning_is_exposed():
    config = ModelProviderConfig(
        name="custom",
        display_name="Custom",
        api_key="key",
        base_url="https://example.com/v1",
        model_name="m",
        api_format="custom",
    )

    assert config.risk_warning is not None
    assert "untrusted endpoint" in config.risk_warning


def test_factory_returns_anthropic_provider():
    provider = create_model_provider(
        ModelProviderConfig.from_name("anthropic", api_key="key"),
        client_factory=lambda _: StubAnthropicClient(),
    )

    assert isinstance(provider, AnthropicProvider)


def test_factory_returns_openai_compatible_provider():
    provider = create_model_provider(ModelProviderConfig.from_name("openrouter", api_key="key"))

    assert isinstance(provider, OpenAICompatibleProvider)


@pytest.mark.asyncio
async def test_ai_client_uses_provider_factory_for_anthropic_config():
    client = AIClient(
        config=AIClientConfig(provider="anthropic", api_key="key", model="claude-test"),
        client_factory=lambda _: StubAnthropicClient(),
    )

    result = await client.review_code("system", "user")

    assert result.summary == "ok"


def test_openai_compatible_provider_parses_response(monkeypatch):
    provider = OpenAICompatibleProvider(
        ModelProviderConfig.from_name(
            "custom",
            api_key="key",
            base_url="https://example.com/v1",
            model_name="custom-model",
            api_format="openai",
        )
    )

    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [{"message": {"content": '{"summary":"ok","findings":[]}'}}],
                    "usage": {"prompt_tokens": 9, "completion_tokens": 3},
                }
            ).encode("utf-8")

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: DummyResponse())

    response = provider._chat_sync(
        [{"role": "user", "content": "hello"}], max_tokens=32, timeout_seconds=5
    )

    assert response.text == '{"summary":"ok","findings":[]}'
    assert response.input_tokens == 9
    assert response.output_tokens == 3


def test_deepseek_chat_requests_json_mode(monkeypatch):
    provider = OpenAICompatibleProvider(
        ModelProviderConfig.from_name("deepseek", api_key="key", model_name="deepseek-flash")
    )
    captured = {}

    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": '{"summary":"ok","findings":[]}'}}]}
            ).encode()

    def fake_urlopen(req, **kwargs):
        captured.update(json.loads(req.data.decode()))
        return DummyResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider._chat_sync([], max_tokens=32, timeout_seconds=5, structured_output=True)
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["thinking"] == {"type": "disabled"}


def test_openai_compatible_provider_lists_models(monkeypatch):
    provider = OpenAICompatibleProvider(
        ModelProviderConfig.from_name(
            "custom",
            api_key="key",
            base_url="https://example.com/v1",
            model_name="custom-model",
            api_format="openai",
        )
    )
    requested_urls: list[str] = []

    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "data": [
                        {"id": "model-b"},
                        {"id": "model-a"},
                        {"id": "model-b"},
                        "model-c",
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(req, **kwargs):
        requested_urls.append(req.full_url)
        return DummyResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    models = provider._list_models_sync(timeout_seconds=5)

    assert requested_urls == ["https://example.com/v1/models"]
    assert models == ["model-a", "model-b", "model-c"]


def test_openai_compatible_provider_models_url_handles_chat_completions_base():
    provider = OpenAICompatibleProvider(
        ModelProviderConfig.from_name(
            "custom",
            api_key="key",
            base_url="https://example.com/v1/chat/completions",
            model_name="custom-model",
            api_format="openai",
        )
    )

    assert provider._models_url == "https://example.com/v1/models"


def test_openai_compatible_provider_rejects_invalid_models_payload(monkeypatch):
    provider = OpenAICompatibleProvider(
        ModelProviderConfig.from_name(
            "custom",
            api_key="key",
            base_url="https://example.com/v1",
            model_name="custom-model",
            api_format="openai",
        )
    )

    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"object": "list"}).encode("utf-8")

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: DummyResponse())

    with pytest.raises(AIResponseFormatError, match="data"):
        provider._list_models_sync(timeout_seconds=5)


def test_openai_provider_parses_block_content_and_reasoning_fallback(monkeypatch):
    provider = OpenAICompatibleProvider(
        ModelProviderConfig.from_name(
            "custom",
            api_key="key",
            base_url="https://example.com/v1",
            model_name="m",
            api_format="openai",
        )
    )

    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {"type": "text", "text": '{"summary":"ok","findings":[]}'}
                                ]
                            }
                        }
                    ]
                }
            ).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: DummyResponse())
    response = provider._chat_sync([], max_tokens=8, timeout_seconds=5)
    assert response.text == '{"summary":"ok","findings":[]}'


def test_openai_provider_uses_reasoning_content_when_content_is_null(monkeypatch):
    provider = OpenAICompatibleProvider(
        ModelProviderConfig.from_name(
            "custom",
            api_key="key",
            base_url="https://example.com/v1",
            model_name="m",
            api_format="openai",
        )
    )

    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "reasoning_content": '{"summary":"ok","findings":[]}',
                            }
                        }
                    ]
                }
            ).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: DummyResponse())
    response = provider._chat_sync([], max_tokens=8, timeout_seconds=5)
    assert response.text.startswith('{"summary"')


def test_deepseek_review_policy_disables_thinking_and_uses_json(monkeypatch):
    from ai_pr_review.services.review_policy import structured_review_params

    assert structured_review_params("deepseek", "deepseek-flash") == {
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
    }


def test_openai_provider_does_not_force_json_for_normal_chat(monkeypatch):
    provider = OpenAICompatibleProvider(
        ModelProviderConfig.from_name("deepseek", api_key="key", model_name="deepseek-flash")
    )
    captured = {}

    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "hello"}}]}).encode()

    def fake_urlopen(req, **kwargs):
        captured.update(json.loads(req.data.decode()))
        return DummyResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider._chat_sync([], max_tokens=16, timeout_seconds=5)
    assert "response_format" not in captured
    assert "thinking" not in captured


def test_ollama_preset_allows_local_http_and_defaults_to_qwen():
    config = ModelProviderConfig.from_name("ollama")

    assert config.base_url == "http://127.0.0.1:11434/v1"
    assert config.model_name == "qwen3.5:4b"
    config.validate()


def test_factory_returns_ollama_provider():
    provider = create_model_provider(ModelProviderConfig.from_name("ollama"))

    assert isinstance(provider, OllamaProvider)


def test_ollama_lists_native_models(monkeypatch):
    provider = OllamaProvider(ModelProviderConfig.from_name("ollama"))

    class DummyResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"models": [{"name": "qwen3.5:4b"}, {"name": "phi4-mini"}]}).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: DummyResponse())

    assert provider._list_ollama_models_sync(timeout_seconds=2) == ["phi4-mini", "qwen3.5:4b"]


def test_ollama_capability_profile_supports_structured_output():
    from ai_pr_review.services.model_capabilities import get_model_capabilities

    profile = get_model_capabilities("ollama", "qwen3.5:4b")

    assert profile.supports_json_object is True
    assert profile.context_window == 8192


@pytest.mark.asyncio
async def test_openai_compatible_provider_streams_sse_before_completion(monkeypatch):
    provider = OpenAICompatibleProvider(
        ModelProviderConfig.from_name(
            "custom",
            api_key="key",
            base_url="https://example.com/v1",
            model_name="custom-model",
            api_format="openai",
        )
    )
    payloads = []

    class StreamResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"hello "}}]}\n'
            yield b'data: {"choices":[{"delta":{"content":"world"}}]}\n'
            yield b'data: {"choices":[],"usage":{"prompt_tokens":2,"completion_tokens":3}}\n'
            yield b"data: [DONE]\n"

    def fake_urlopen(req, **kwargs):
        payloads.append(json.loads(req.data.decode()))
        return StreamResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    deltas = []

    async def on_delta(delta):
        deltas.append(delta)

    response = await provider.stream_chat(
        [{"role": "user", "content": "hi"}], on_delta, max_tokens=16, timeout_seconds=2
    )
    assert payloads[0]["stream"] is True
    assert deltas == ["hello ", "world"]
    assert response.text == "hello world"
    assert (response.input_tokens, response.output_tokens) == (2, 3)


def _streaming_provider() -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        ModelProviderConfig.from_name(
            "custom",
            api_key="key",
            base_url="https://example.com/v1",
            model_name="custom-model",
            api_format="openai",
        )
    )


def test_stream_emit_after_event_loop_closed_returns_quietly(monkeypatch):
    """事件循环关闭后到达的 delta 必须静默丢弃，且不能白等 EMIT_TIMEOUT_SECONDS。

    旧用例在事件循环线程内调用 emit：`run_coroutine_threadsafe` 会成功入队，
    紧接着 `future.result(EMIT_TIMEOUT_SECONDS)` 把循环本身挡住，于是只能等满
    10 秒超时 —— 既没有覆盖「循环已关闭」这条分支，又让每次跑测试白付 10 秒墙钟。
    这里改成在 `asyncio.run` 返回（循环已关闭）之后再投递，并把投递上限打桩，
    确保这条路径从此既快又真的被执行。
    """
    provider = _streaming_provider()
    monkeypatch.setattr(provider, "EMIT_TIMEOUT_SECONDS", 1.0)
    captured: dict[str, object] = {}
    delivered: list[str] = []

    def fake_sync(messages, emit, cancel_event, active_response, **kwargs):
        captured["emit"] = emit
        return ProviderResponse(text="")

    monkeypatch.setattr(provider, "_stream_chat_sync", fake_sync)

    async def on_delta(delta):
        delivered.append(delta)

    asyncio.run(
        provider.stream_chat(
            [{"role": "user", "content": "hi"}], on_delta, max_tokens=8, timeout_seconds=2
        )
    )

    emit = captured["emit"]
    started = time.monotonic()
    emit("late delta")  # 必须静默返回
    assert time.monotonic() - started < 1.0
    assert delivered == []


@pytest.mark.asyncio
async def test_stream_emit_after_cancel_does_not_schedule_delivery(monkeypatch):
    """取消后到达的 delta 不能投递 —— 事件循环仍然存活，唯一的拦截点是取消复查。"""
    provider = _streaming_provider()
    monkeypatch.setattr(provider, "EMIT_TIMEOUT_SECONDS", 0.2)
    captured: dict[str, object] = {}
    delivered: list[str] = []

    def fake_sync(messages, emit, cancel_event, active_response, **kwargs):
        captured["emit"] = emit
        cancel_event.set()  # 取消先到，delta 后到
        return ProviderResponse(text="")

    monkeypatch.setattr(provider, "_stream_chat_sync", fake_sync)

    async def on_delta(delta):
        delivered.append(delta)

    await provider.stream_chat(
        [{"role": "user", "content": "hi"}], on_delta, max_tokens=8, timeout_seconds=2
    )
    emit = captured["emit"]
    await asyncio.to_thread(emit, "late delta")

    assert delivered == []


@pytest.mark.asyncio
async def test_stream_read_error_after_cancel_is_not_reported_as_failure(monkeypatch):
    """取消方关闭 response 会让读线程抛 ValueError；这属于预期收尾，不是故障。"""
    provider = _streaming_provider()

    class ClosedResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def __iter__(self):
            return self

        def __next__(self):
            raise ValueError("I/O operation on closed file")

    monkeypatch.setattr("urllib.request.urlopen", lambda req, **kwargs: ClosedResponse())
    deltas: list[str] = []

    async def on_delta(delta):
        deltas.append(delta)

    cancel_event = threading.Event()
    cancel_event.set()
    response = await provider.stream_chat(
        [{"role": "user", "content": "hi"}],
        on_delta,
        max_tokens=16,
        timeout_seconds=2,
        cancel_event=cancel_event,
    )
    assert response.text == ""
    assert deltas == []


@pytest.mark.asyncio
async def test_stream_read_error_without_cancel_is_still_a_failure(monkeypatch):
    provider = _streaming_provider()

    class BrokenResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def __iter__(self):
            return self

        def __next__(self):
            raise ValueError("I/O operation on closed file")

    monkeypatch.setattr("urllib.request.urlopen", lambda req, **kwargs: BrokenResponse())

    async def on_delta(delta):  # pragma: no cover - 失败路径不投递
        return None

    with pytest.raises(AIServiceError):
        await provider.stream_chat(
            [{"role": "user", "content": "hi"}],
            on_delta,
            max_tokens=16,
            timeout_seconds=2,
            cancel_event=threading.Event(),
        )


def test_stream_cancel_before_response_headers_returns_without_waiting(monkeypatch):
    """取消落在「等待首字节」窗口时必须立刻返回，并关掉迟到到达的响应。

    旧实现只在 `urlopen` 返回之后才登记 response，所以这期间的取消既救不了读线程
    （它一直挂在 urlopen 里，要等首字节或 timeout_seconds 到期），也没有句柄可关。
    连接改到辅助线程后，轮询 cancel_event 让取消立刻生效；迟到响应由持有方关闭，
    否则那条连接要挂到进程退出。
    """
    provider = _streaming_provider()
    release = threading.Event()
    closed: list[str] = []
    delivered: list[str] = []

    class LateResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def __iter__(self):
            return iter([b'data: {"choices":[{"delta":{"content":"late"}}]}\n'])

        def close(self):
            closed.append("closed")

    def slow_urlopen(req, **kwargs):
        release.wait(timeout=5)  # 供应商还在 thinking，响应头迟迟不来
        return LateResponse()

    monkeypatch.setattr("urllib.request.urlopen", slow_urlopen)
    cancel_event = threading.Event()

    def cancel_after_a_moment() -> None:
        time.sleep(0.1)
        cancel_event.set()

    async def on_delta(delta):
        delivered.append(delta)

    threading.Thread(target=cancel_after_a_moment, daemon=True).start()
    started = time.monotonic()
    response = asyncio.run(
        provider.stream_chat(
            [{"role": "user", "content": "hi"}],
            on_delta,
            max_tokens=8,
            timeout_seconds=30,  # 旧实现会一直等到首字节或这里到期
            cancel_event=cancel_event,
        )
    )
    elapsed = time.monotonic() - started

    assert response.text == ""
    assert elapsed < 1
    assert delivered == []

    release.set()  # 首字节最终到达：迟到响应必须被关掉
    deadline = time.monotonic() + 5
    while not closed and time.monotonic() < deadline:
        time.sleep(0.01)
    assert closed == ["closed"]


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (error.URLError("connection refused"), AIServiceError),
        (
            error.HTTPError(
                "https://example.com/v1/chat/completions", 401, "Unauthorized", {}, None
            ),
            AIAuthenticationError,
        ),
    ],
)
def test_stream_connect_failures_survive_the_connector_thread(
    monkeypatch, raised, expected
) -> None:
    """把 urlopen 挪到连接线程后，真正的连接失败仍要按原语义抛出。"""
    provider = _streaming_provider()

    def failing_urlopen(req, **kwargs):
        raise raised

    monkeypatch.setattr("urllib.request.urlopen", failing_urlopen)

    async def on_delta(delta):  # pragma: no cover - 失败路径不投递
        return None

    with pytest.raises(expected):
        asyncio.run(
            provider.stream_chat(
                [{"role": "user", "content": "hi"}],
                on_delta,
                max_tokens=8,
                timeout_seconds=2,
                cancel_event=threading.Event(),
            )
        )


class StubMessageStream:
    """Minimal stand-in for `client.messages.stream(...)`."""

    def __init__(self, chunks: list[str], final: object) -> None:
        self._chunks = chunks
        self._final = final
        self.final_requested = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    @property
    def text_stream(self):
        async def iterate():
            for chunk in self._chunks:
                yield chunk

        return iterate()

    async def get_final_message(self):
        self.final_requested = True
        return self._final


class StubStreamingMessages:
    def __init__(self, chunks: list[str], final: object) -> None:
        self._chunks = chunks
        self._final = final
        self.streams: list[StubMessageStream] = []

    def stream(self, **kwargs):
        stream = StubMessageStream(self._chunks, self._final)
        self.streams.append(stream)
        return stream


class StubStreamingClient:
    def __init__(self, chunks: list[str], final: object) -> None:
        self.messages = StubStreamingMessages(chunks, final)


def _anthropic_streaming_provider(client: StubStreamingClient) -> AnthropicProvider:
    return AnthropicProvider(
        ModelProviderConfig.from_name("anthropic", api_key="key"),
        client_factory=lambda api_key: client,
    )


@pytest.mark.asyncio
async def test_anthropic_provider_streams_text_deltas():
    final = SimpleNamespace(
        content=[SimpleNamespace(text="hello world")],
        usage=SimpleNamespace(input_tokens=3, output_tokens=2),
    )
    client = StubStreamingClient(["hello", " world"], final)
    provider = _anthropic_streaming_provider(client)
    deltas: list[str] = []

    async def on_delta(text):
        deltas.append(text)

    response = await provider.stream_chat(
        [{"role": "user", "content": "hi"}], on_delta, max_tokens=32
    )

    assert deltas == ["hello", " world"]
    assert response.text == "hello world"
    assert (response.input_tokens, response.output_tokens) == (3, 2)
    assert client.messages.streams[0].final_requested is True


@pytest.mark.asyncio
async def test_anthropic_stream_cancel_stops_without_waiting_for_the_final_message():
    """取消后不能再 `await get_final_message()`，否则仍要等完整回复生成完。"""
    final = SimpleNamespace(
        content=[SimpleNamespace(text="first second")],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    client = StubStreamingClient(["first", " second"], final)
    provider = _anthropic_streaming_provider(client)
    cancel_event = threading.Event()
    deltas: list[str] = []

    async def on_delta(text):
        deltas.append(text)
        cancel_event.set()

    response = await provider.stream_chat(
        [{"role": "user", "content": "hi"}],
        on_delta,
        max_tokens=32,
        cancel_event=cancel_event,
    )

    assert deltas == ["first"]
    assert response.text == "first"
    assert client.messages.streams[0].final_requested is False


@pytest.mark.asyncio
async def test_anthropic_stream_falls_back_to_final_message_text():
    """只有 thinking 块（没有文本增量）时，流式路径也要拿到文本。

    修复前这里返回 `text=""`，`jsonl_server._chat` 会把空串写进会话，
    用户在界面上看到一条空回答；而非流式 `chat()` 一直能从 thinking 块里取到文本。
    """
    final = SimpleNamespace(
        content=[SimpleNamespace(thinking="reasoned answer")],
        usage=SimpleNamespace(input_tokens=4, output_tokens=6),
    )
    client = StubStreamingClient([], final)
    provider = _anthropic_streaming_provider(client)

    async def on_delta(text):  # pragma: no cover - 没有任何文本增量可投递
        raise AssertionError("no text delta should be streamed")

    response = await provider.stream_chat(
        [{"role": "user", "content": "hi"}], on_delta, max_tokens=32
    )

    assert response.text == "reasoned answer"
    assert (response.input_tokens, response.output_tokens) == (4, 6)
    assert client.messages.streams[0].final_requested is True


@pytest.mark.asyncio
async def test_anthropic_stream_without_any_text_raises_format_error():
    """流和最终消息都没有文本时必须报错，而不是把空串当成一次成功回答。"""
    final = SimpleNamespace(
        content=[],
        usage=SimpleNamespace(input_tokens=1, output_tokens=0),
    )
    client = StubStreamingClient([], final)
    provider = _anthropic_streaming_provider(client)

    async def on_delta(text):  # pragma: no cover - 没有文本增量可投递
        return None

    with pytest.raises(AIResponseFormatError):
        await provider.stream_chat([{"role": "user", "content": "hi"}], on_delta, max_tokens=32)


@pytest.mark.asyncio
async def test_anthropic_cancelled_stream_without_text_is_not_a_format_error():
    """取消造成的空文本不是格式错误（并且此时不能再 await final message）。"""
    final = SimpleNamespace(
        content=[SimpleNamespace(text="never streamed")],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    client = StubStreamingClient(["", ""], final)
    provider = _anthropic_streaming_provider(client)
    cancel_event = threading.Event()
    cancel_event.set()

    async def on_delta(text):  # pragma: no cover - 取消后不得投递
        raise AssertionError("cancelled stream must not deliver deltas")

    response = await provider.stream_chat(
        [{"role": "user", "content": "hi"}],
        on_delta,
        max_tokens=32,
        cancel_event=cancel_event,
    )

    assert response.text == ""
    assert client.messages.streams[0].final_requested is False
