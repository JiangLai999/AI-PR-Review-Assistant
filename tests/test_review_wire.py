"""review 思考语义的 **wire 级**加锁（第一步，零行为变更）。

背景与结论见 `docs/review-reasoning-assessment.md`：

- 当前 review 对支持关闭思考的供应商（deepseek）是**显式关闭**——
  `structured_output=True` 会经 `structured_review_params()` 追加
  `thinking: {"type": "disabled"}`（`review_policy.py` ← `model_capabilities.py`）；
- review **不消费**用户的 `/think` 档位：`AIClient.review_code` 从不传 `reasoning_effort`；
- 本地 ollama 走另一条机制（`OllamaProvider` 强制 `think=False`）；
- anthropic 与多数 OpenAI 兼容供应商**不发**思考参数（沿用供应商默认）。

这些断言的职责是**钉住现状**：等 review 独立档位（claude-review-effort-step2）落地时，
本文件按新语义更新，任何意外开关都会被这里拦下。

测试方法：monkeypatch `urllib.request.urlopen`（provider 的真实出网口）捕获请求体，
不 mock provider 的请求构造，因此断言的是**真正上线的内容**。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from ai_pr_review.config import AIClientConfig
from ai_pr_review.services.ai_client import AIClient

REVIEW_JSON = json.dumps({"summary": "ok", "findings": []})


class _DummyResponse:
    """urlopen 的最小替身：返回一段合法 review JSON。"""

    def __enter__(self) -> "_DummyResponse":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps({"choices": [{"message": {"content": REVIEW_JSON}}]}).encode("utf-8")


def _capture_review_body(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """跑一次真实 provider 的 review 请求，返回捕获到的 wire body。"""
    captured: dict[str, Any] = {}

    def fake_urlopen(req: Any, **kwargs: Any) -> _DummyResponse:
        captured.update(json.loads(req.data.decode("utf-8")))
        captured["__url__"] = req.full_url
        return _DummyResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return captured


@pytest.mark.asyncio
async def test_deepseek_review_wire_disables_thinking(monkeypatch: pytest.MonkeyPatch) -> None:
    """deepseek：`response_format` + 显式 `thinking: disabled`，且**不带** reasoning_effort。"""
    captured = _capture_review_body(monkeypatch)
    client = AIClient(
        config=AIClientConfig(
            provider="deepseek",
            api_key="test-key",
            model="deepseek-flash",
            api_format="openai",
        )
    )

    result = await client.review_code("system prompt", "user prompt")

    assert result.summary == "ok"
    # a. 结构化输出（审查必须是 JSON）
    assert captured["response_format"] == {"type": "json_object"}
    # b. 现状语义：显式关闭思考（docs/review-reasoning-assessment.md §0.1）
    assert captured["thinking"] == {"type": "disabled"}
    # c. 审查路径不消费用户档位——这是本文件要守住的核心约束
    assert "reasoning_effort" not in captured
    # d. 审查输出预算来自能力档案（deepseek + 小输入 = 6144，不含思考预留）
    assert captured["max_tokens"] == 6144


@pytest.mark.asyncio
async def test_local_ollama_review_wire_forces_think_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """本地 ollama：另一条机制——`think: false`，且不出现 `thinking` 对象形态。"""
    captured = _capture_review_body(monkeypatch)
    client = AIClient(
        config=AIClientConfig(
            provider="ollama",
            api_key="",  # 本地豁免 Key
            model="qwen3.5:4b",
            base_url="http://127.0.0.1:11434/v1",
            api_format="openai",
        )
    )

    result = await client.review_code("system prompt", "user prompt")

    assert result.summary == "ok"
    assert captured.get("think") is False
    assert "thinking" not in captured
    assert "reasoning_effort" not in captured


@pytest.mark.asyncio
async def test_anthropic_review_wire_sends_no_thinking_params() -> None:
    """anthropic：policy 为空表且 provider 不看 `structured_output` → 不发思考参数。

    该 provider 走 SDK（不经 urllib），因此这里用 client_factory 捕获**传给 provider 的
    kwargs**；对 anthropic 而言它能证明"我们没有主动注入 thinking/effort"。
    """
    seen: dict[str, Any] = {}

    class _StubAnthropicMessages:
        async def create(self, **kwargs: Any) -> Any:
            seen.update(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(text=REVIEW_JSON)],
                usage=SimpleNamespace(input_tokens=3, output_tokens=2),
            )

    class _StubAnthropicClient:
        def __init__(self) -> None:
            self.messages = _StubAnthropicMessages()

    client = AIClient(
        config=AIClientConfig(provider="anthropic", api_key="key", model="claude-sonnet-4-20250514"),
        client_factory=lambda _: _StubAnthropicClient(),
    )

    result = await client.review_code("system prompt", "user prompt")

    assert result.summary == "ok"
    assert "thinking" not in seen
    assert "reasoning_effort" not in seen


@pytest.mark.asyncio
async def test_patch_generator_path_wire_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """`patch_generator` 路径快照：非结构化请求**不经过** review policy。

    ⚠️ 这是**现状快照，不是期望语义**：同一轮 review 里主路径显式关思考、
    建议 patch 生成路径（`structured_output=False`）却可能让思考型模型**默认开启**。
    该差异已记入 `docs/review-reasoning-assessment.md` §1.2 的风险项；
    若产品决定统一，请先更新本快照再改产品代码。
    """
    captured = _capture_review_body(monkeypatch)
    client = AIClient(
        config=AIClientConfig(
            provider="deepseek",
            api_key="test-key",
            model="deepseek-flash",
            api_format="openai",
        )
    )

    # patch_generator 走的形态：结构化关闭的普通 chat 调用
    await client._provider.chat(  # noqa: SLF001 - wire 级快照必须直达 provider
        [{"role": "user", "content": "generate a patch"}],
        max_tokens=128,
        timeout_seconds=5,
        structured_output=False,
    )

    assert "response_format" not in captured
    # 现状：无 thinking / 无 effort —— 对 DeepSeek 即"供应商默认"（思考型模型会思考）
    assert "thinking" not in captured
    assert "reasoning_effort" not in captured
