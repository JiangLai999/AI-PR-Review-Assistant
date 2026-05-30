"""Model provider and config integration tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ai_pr_review.config import AIClientConfig, ConfigValidationError, ModelProviderConfig
from ai_pr_review.services.ai_client import AIClient
from ai_pr_review.services.model_providers.anthropic import AnthropicProvider
from ai_pr_review.services.model_providers.factory import create_model_provider
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
    config = ModelProviderConfig(name="custom", display_name="Custom", api_key="key", base_url="", model_name="m", api_format="openai")

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

    response = provider._chat_sync([{"role": "user", "content": "hello"}], max_tokens=32, timeout_seconds=5)

    assert response.text == '{"summary":"ok","findings":[]}'
    assert response.input_tokens == 9
    assert response.output_tokens == 3
