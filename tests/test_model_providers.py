"""Model provider and config integration tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ai_pr_review.config import AIClientConfig, ConfigValidationError, ModelProviderConfig
from ai_pr_review.services.ai_client import AIClient
from ai_pr_review.services.exceptions import AIResponseFormatError
from ai_pr_review.services.model_providers.anthropic import AnthropicProvider
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
