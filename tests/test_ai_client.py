"""AI Client 模块单元测试。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from ai_pr_review.config import AIClientConfig
from ai_pr_review.services.ai_client import AIClient, UsageRecord
from ai_pr_review.services.exceptions import (
    AIAuthenticationError,
    AICostLimitError,
    AIRequestTimeoutError,
    AIResponseFormatError,
    AIServiceError,
)


class MockMessagesAPI:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        current = self._responses.pop(0)
        if isinstance(current, Exception):
            raise current
        if callable(current):
            return await current(**kwargs)
        return current


class MockClient:
    def __init__(self, responses):
        self.messages = MockMessagesAPI(responses)


def build_response(text: str, input_tokens: int = 100, output_tokens: int = 200):
    return SimpleNamespace(
        content=[SimpleNamespace(text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def build_client(responses, **config_overrides) -> AIClient:
    config = AIClientConfig(api_key="test-key", **config_overrides)
    return AIClient(config=config, client_factory=lambda _: MockClient(responses))


class TestAIClientInit:
    def test_init_without_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(AIAuthenticationError, match="API Key"):
            AIClient(config=AIClientConfig(api_key=""), client_factory=lambda _: MockClient([]))


class TestAIClientReviewCode:
    @pytest.mark.asyncio
    async def test_review_code_returns_valid_review_result(self):
        client = build_client(
            [
                build_response(
                    '{"summary":"Found one issue","findings":[{"severity":"high","category":"security","file":"src/app.py","line_start":10,"line_end":12,"title":"SQL injection risk","problem":"User input is concatenated into SQL.","suggestion":"Use parameterized queries.","confidence":0.95,"code_snippet":"query = f\\"SELECT ... {user_input}\\""}]}'
                )
            ]
        )

        result = await client.review_code("system", "user")

        assert result.summary == "Found one issue"
        assert len(result.findings) == 1
        assert result.findings[0].file == "src/app.py"
        assert client.total_cost_last_24h > 0

    @pytest.mark.asyncio
    async def test_review_code_retries_on_invalid_json_then_succeeds(self):
        client = build_client(
            [
                build_response("not json"),
                build_response('{"summary":"ok","findings":[]}'),
            ]
        )

        result = await client.review_code("system", "user")

        assert result.summary == "ok"
        assert client._client.messages.calls == 2

    @pytest.mark.asyncio
    async def test_review_code_retries_service_errors_then_succeeds(self):
        client = build_client(
            [
                RuntimeError("temporary failure"),
                build_response('{"summary":"ok","findings":[]}'),
            ]
        )

        result = await client.review_code("system", "user")

        assert result.summary == "ok"
        assert client._client.messages.calls == 2

    @pytest.mark.asyncio
    async def test_review_code_raises_timeout_after_retries(self):
        async def slow_response(**kwargs):
            await asyncio.sleep(0.05)
            return build_response('{"summary":"slow","findings":[]}')

        client = build_client(
            [slow_response, slow_response, slow_response],
            timeout_seconds=0.01,
            retry_base_delay=0.001,
        )

        with pytest.raises(AIRequestTimeoutError, match="超时"):
            await client.review_code("system", "user")

    @pytest.mark.asyncio
    async def test_review_code_raises_format_error_after_retry_exhausted(self):
        client = build_client(
            [
                build_response("still bad"),
                build_response("still bad"),
                build_response("still bad"),
            ],
            retry_base_delay=0.001,
        )

        with pytest.raises(AIResponseFormatError, match="JSON"):
            await client.review_code("system", "user")

    @pytest.mark.asyncio
    async def test_review_code_maps_401_to_authentication_error(self):
        auth_error = RuntimeError("unauthorized")
        auth_error.status_code = 401

        client = build_client([auth_error], retry_base_delay=0.001, max_retries=1)

        with pytest.raises(AIAuthenticationError, match="认证失败"):
            await client.review_code("system", "user")

    @pytest.mark.asyncio
    async def test_review_code_rejects_when_single_run_cost_exceeds_limit(self):
        client = build_client(
            [build_response('{"summary":"ok","findings":[]}')],
            max_tokens=500000,
            max_cost_per_run=1.0,
        )

        with pytest.raises(AICostLimitError, match="单次上限"):
            await client.review_code("system prompt", "user prompt")

    @pytest.mark.asyncio
    async def test_review_code_rejects_when_sliding_window_exceeds_limit(self):
        client = build_client(
            [build_response('{"summary":"ok","findings":[]}')],
            max_cost_per_24h=0.5,
        )
        client._usage_history.append(UsageRecord(timestamp=10**10, cost=0.49))

        with pytest.raises(AICostLimitError, match="24 小时"):
            await client.review_code("system", "user")

    @pytest.mark.asyncio
    async def test_review_code_wraps_unexpected_errors(self):
        client = build_client([RuntimeError("boom")], retry_base_delay=0.001, max_retries=1)

        with pytest.raises(AIServiceError, match="AI 服务调用失败"):
            await client.review_code("system", "user")


class TestAIClientHelpers:
    def test_estimate_cost_uses_configured_rates(self):
        client = build_client([], input_cost_per_million=3.0, output_cost_per_million=15.0)
        cost = client.estimate_cost(1_000_000, 1_000_000)
        assert cost == pytest.approx(18.0)

    def test_total_cost_last_24h_prunes_expired_records(self):
        client = build_client([])
        client._usage_history.append(UsageRecord(timestamp=0, cost=10.0))
        client._usage_history.append(UsageRecord(timestamp=10**10, cost=2.0))

        assert client.total_cost_last_24h == pytest.approx(2.0)
