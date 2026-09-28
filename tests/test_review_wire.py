"""review 思考语义的 **wire 级**加锁（第一步加锁 → 第二步按新语义修订）。

背景与结论见 `docs/review-reasoning-assessment.md`：

- 默认档 ``off``（= 现状）：review 对支持关闭思考的供应商（deepseek）是**显式关闭**——
  `structured_output=True` 会经 `structured_review_params()` 追加
  `thinking: {"type": "disabled"}`（`review_policy.py` ← `model_capabilities.py`）；
- **第二步（claude-review-effort-step2）起** review 消费 `preferences.review_reasoning_effort`
  （默认 `off`，词表与 chat 相同）：`low/high/max` **同时**把 `thinking` 覆盖成
  `{"type": "enabled"}` 并传 `reasoning_effort`（真机证明只传 effort 无效），
  且请求体预算随档位增加（+4000/+8000/+12000，受模型规格 `max_output` 封顶）；
  `auto` 表示"不干预"，因此与 `off` 在 wire 上同形；
- 本地 ollama 走另一条机制（`OllamaProvider` 强制 `think=False`），档位置灰**不生效**；
- unsupported（如 baichuan）/ 未收录供应商**不注入**任何思考参数，也不预留额度；
- anthropic 默认档不发思考参数；开启档位时走 `thinking.budget_tokens`（官方预算制）。

这些断言的职责是**钉住行为**：任何意外开关都会被这里拦下。第一步的现状断言在
`off`/`auto` 两档下依然逐字有效（默认即现状）；`low/high/max` 的断言是第二步新增。

测试方法：monkeypatch `urllib.request.urlopen`（provider 的真实出网口）捕获请求体，
不 mock provider 的请求构造，因此断言的是**真正上线的内容**。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from ai_pr_review.config import CHAT_REASONING_TOKEN_BUDGETS, AIClientConfig
from ai_pr_review.services.ai_client import AIClient

REVIEW_JSON = json.dumps({"summary": "ok", "findings": []})

# deepseek 的 review 输出额度（能力档案口径，不含思考预留）：见现有用例 d。
DEEPSEEK_BASE_MAX_TOKENS = 6144


def _deepseek_config(level: str | None) -> AIClientConfig:
    """deepseek 客户端配置；`level=None` 表示不设档位（走默认 off）。"""
    payload: dict[str, Any] = {
        "provider": "deepseek",
        "api_key": "test-key",
        "model": "deepseek-flash",
        "api_format": "openai",
    }
    if level is not None:
        payload["review_reasoning_effort"] = level
    return AIClientConfig(**payload)


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
    """默认档（未设置 / `off`）：`response_format` + 显式 `thinking: disabled`，无 effort。

    第二步的默认值就是 `off`，因此这条第一步的断言在新语义下**逐字仍然成立**：
    没有设置档位的客户端行为与改造前完全一致。
    """
    captured = _capture_review_body(monkeypatch)
    client = AIClient(config=_deepseek_config(None))

    result = await client.review_code("system prompt", "user prompt")

    assert result.summary == "ok"
    # a. 结构化输出（审查必须是 JSON）
    assert captured["response_format"] == {"type": "json_object"}
    # b. 现状语义：显式关闭思考（docs/review-reasoning-assessment.md §0.1）
    assert captured["thinking"] == {"type": "disabled"}
    # c. 默认档 off 不注入 effort——"缺省即现状"是第二步的核心约束
    assert "reasoning_effort" not in captured
    # d. 审查输出预算来自能力档案（deepseek + 小输入 = 6144，不含思考预留）
    assert captured["max_tokens"] == DEEPSEEK_BASE_MAX_TOKENS


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
    # ollama 的能力档案 max_output = 1024：review 输出额度本来就封在这里
    assert captured["max_tokens"] == 1024


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
        config=AIClientConfig(
            provider="anthropic", api_key="key", model="claude-sonnet-4-20250514"
        ),
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


# ---------------------------------------------------------------------------
# 第二步（claude-review-effort-step2）：review 独立档位，默认 off
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("level", ["low", "high", "max"])
async def test_deepseek_review_wire_enables_thinking_for_the_three_levels(
    monkeypatch: pytest.MonkeyPatch, level: str
) -> None:
    """`low/high/max`：**同时**覆盖 policy 的 disabled 并传 effort，预算随档位增加。

    真机依据（docs/review-reasoning-assessment.md §0.2）：只传 `reasoning_effort` 而
    `thinking` 仍是 disabled 时 reasoning 恒为 0 字符，所以两个参数必须一起出现。
    """
    captured = _capture_review_body(monkeypatch)
    client = AIClient(config=_deepseek_config(level))

    result = await client.review_code("system prompt", "user prompt")

    assert result.summary == "ok"
    assert captured["response_format"] == {"type": "json_object"}  # 结构化策略不受影响
    assert captured["thinking"] == {"type": "enabled"}
    assert captured["reasoning_effort"] == level
    assert captured["max_tokens"] == DEEPSEEK_BASE_MAX_TOKENS + CHAT_REASONING_TOKEN_BUDGETS[level]
    # 档位是**按请求计算**的：落盘字段一个字节都不该被写脏（混合编排会按文件重建配置）。
    assert client._config.extra_params == {}  # noqa: SLF001 - 落盘字段必须保持干净
    assert client._provider.config.extra_params == {}  # noqa: SLF001


@pytest.mark.asyncio
@pytest.mark.parametrize("level", ["off", "auto"])
async def test_off_and_auto_never_inject_for_non_deepseek_providers(
    monkeypatch: pytest.MonkeyPatch, level: str
) -> None:
    """`off` = **维持现状**，不是"对所有供应商强发 disabled"。

    zhipu 这类供应商的 policy 不发 `thinking`（`supports_thinking_disable` 只对 deepseek
    为真），规格表里它们的 off 档虽然有 `{"thinking": {"type": "disabled"}}`，但 review 侧
    `off`/`auto` 一律**不注入任何参数**——强发一个从未真机验证过的关闭参数属于行为变更，
    不在本档位的语义内。
    """
    bodies: list[dict[str, Any]] = []

    def fake_urlopen(req: Any, **kwargs: Any) -> _DummyResponse:
        bodies.append(json.loads(req.data.decode("utf-8")))
        return _DummyResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = AIClient(
        config=AIClientConfig(
            provider="zhipu",
            api_key="test-key",
            model="glm-4-flash",
            api_format="openai",
            review_reasoning_effort=level,
        )
    )

    await client.review_code("system prompt", "user prompt")

    assert "thinking" not in bodies[0]
    assert "reasoning_effort" not in bodies[0]
    assert bodies[0]["response_format"] == {"type": "json_object"}
    assert bodies[0]["max_tokens"] == 4096  # 没有思考预留

    # 正对照：同一客户端切到 high 后**确实**会注入——否则上面两条"没有"是空断言，
    # 删掉整个功能也照样通过。
    client._config.review_reasoning_effort = "high"  # noqa: SLF001 - 模拟用户改档
    await client.review_code("system prompt", "user prompt")

    assert bodies[1]["reasoning_effort"] == "high"
    assert bodies[1]["max_tokens"] == 4096  # 预设 glm-4-flash 的 max_output 就是 4096（封顶）


@pytest.mark.asyncio
async def test_deepseek_review_wire_auto_is_indistinguishable_from_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`auto` = 不干预：wire 与 `off` 同形（policy 决定），也不预留思考额度。"""
    bodies: list[dict[str, Any]] = []

    def fake_urlopen(req: Any, **kwargs: Any) -> _DummyResponse:
        bodies.append(json.loads(req.data.decode("utf-8")))
        return _DummyResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = AIClient(config=_deepseek_config("auto"))

    await client.review_code("system prompt", "user prompt")

    assert bodies[0]["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in bodies[0]
    assert bodies[0]["max_tokens"] == DEEPSEEK_BASE_MAX_TOKENS

    # 正对照：切到 low 后请求体必须变化，证明上面断言的不是"功能整个没接上"。
    client._config.review_reasoning_effort = "low"  # noqa: SLF001 - 模拟用户改档
    await client.review_code("system prompt", "user prompt")

    assert bodies[1]["thinking"] == {"type": "enabled"}
    assert bodies[1]["reasoning_effort"] == "low"
    assert bodies[1]["max_tokens"] == DEEPSEEK_BASE_MAX_TOKENS + 4000


@pytest.mark.asyncio
async def test_deepseek_review_wire_invalid_level_falls_back_to_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非法档位（构造之后直接赋坏值）按 `off` 处理，不抛异常也不注入。"""
    captured = _capture_review_body(monkeypatch)
    config = _deepseek_config(None)
    config.review_reasoning_effort = "extreme"
    client = AIClient(config=config)

    await client.review_code("system prompt", "user prompt")

    assert captured["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in captured
    assert captured["max_tokens"] == DEEPSEEK_BASE_MAX_TOKENS


@pytest.mark.asyncio
async def test_review_wire_levels_do_not_leak_across_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同一个客户端先 `max` 再 `off`：第二次请求必须回到"关思考"，不留残留。"""
    bodies: list[dict[str, Any]] = []

    def fake_urlopen(req: Any, **kwargs: Any) -> _DummyResponse:
        bodies.append(json.loads(req.data.decode("utf-8")))
        return _DummyResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = AIClient(config=_deepseek_config("max"))

    await client.review_code("system prompt", "user prompt")
    client._config.review_reasoning_effort = "off"  # noqa: SLF001 - 模拟配置变更
    await client.review_code("system prompt", "user prompt")

    assert [body["thinking"] for body in bodies] == [
        {"type": "enabled"},
        {"type": "disabled"},
    ]
    assert "reasoning_effort" in bodies[0]
    assert "reasoning_effort" not in bodies[1]


@pytest.mark.asyncio
async def test_local_review_wire_stays_greyed_out_at_max_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """本地（产品决策置灰）：档位设了也不生效——仍是 `think: false`、无预留。"""
    captured = _capture_review_body(monkeypatch)
    client = AIClient(
        config=AIClientConfig(
            provider="ollama",
            api_key="",
            model="qwen3.5:4b",
            base_url="http://127.0.0.1:11434/v1",
            api_format="openai",
            review_reasoning_effort="max",
        )
    )

    await client.review_code("system prompt", "user prompt")

    assert captured.get("think") is False
    assert "thinking" not in captured
    assert "reasoning_effort" not in captured
    assert captured["max_tokens"] == 1024  # 没有思考预留


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "model", "base_url"),
    [
        ("baichuan", "Baichuan4", "https://api.baichuan-ai.com/v1"),
        ("mystery-llm", "mystery-1", "https://mystery.example.com/v1"),
    ],
)
async def test_unsupported_and_unknown_review_providers_inject_nothing(
    monkeypatch: pytest.MonkeyPatch, provider: str, model: str, base_url: str
) -> None:
    """置灰供应商（官方无该参数 / 未收录）**不编造参数**：不注入、也不预留额度。"""
    captured = _capture_review_body(monkeypatch)
    client = AIClient(
        config=AIClientConfig(
            provider=provider,
            api_key="test-key",
            model=model,
            base_url=base_url,
            api_format="openai",
            review_reasoning_effort="max",
        )
    )

    await client.review_code("system prompt", "user prompt")

    assert "thinking" not in captured
    assert "reasoning_effort" not in captured
    # 非 deepseek 供应商的能力档案基础额度是 4096（小输入），没有被思考预留顶高。
    assert captured["max_tokens"] == 4096


@pytest.mark.asyncio
async def test_relay_review_wire_passes_reasoning_effort_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """中转/自定义端点（transparent）：按 OpenAI 兼容透传 `reasoning_effort` 并预留额度。"""
    captured = _capture_review_body(monkeypatch)
    client = AIClient(
        config=AIClientConfig(
            provider="api2d",
            api_key="test-key",
            model="gpt-4o-mini",
            api_format="openai",
            review_reasoning_effort="high",
        )
    )

    await client.review_code("system prompt", "user prompt")

    assert captured["reasoning_effort"] == "high"
    assert "thinking" not in captured
    # min(4096 + 8000, 预设 gpt-4o-mini 的 max_output 16384) = 12096：
    # 封顶按内置预设（chat 的 `_chat_max_output` 同样信任预设），不是能力档案的 8192。
    assert captured["max_tokens"] == 12096


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "model", "preset_max_output"),
    [
        # 能力档案给这些供应商的默认 max_output 是 8192，但仓库预设（厂商数值）只有 4096：
        # 封顶必须按 4096 来，否则请求额度会超过模型输出上限（云端直接 400）。
        ("stepfun", "step-2-16k", 4096),
        ("hunyuan", "hunyuan-large", 4096),
    ],
)
async def test_review_budget_is_capped_by_the_preset_not_the_profile_default(
    monkeypatch: pytest.MonkeyPatch, provider: str, model: str, preset_max_output: int
) -> None:
    """预设优先：档位预留不得把 `max_tokens` 顶到预设 `max_output` 之上。"""
    captured = _capture_review_body(monkeypatch)
    client = AIClient(
        config=AIClientConfig(
            provider=provider,
            api_key="test-key",
            model=model,
            api_format="openai",
            review_reasoning_effort="low",
        )
    )

    await client.review_code("system prompt", "user prompt")

    # 档位参数照发（供应商确实支持 effort），但没有额度可预留：4096 + 4000 被封回 4096。
    assert captured["reasoning_effort"] == "low"
    assert captured["max_tokens"] == preset_max_output


@pytest.mark.asyncio
async def test_anthropic_format_relay_review_wire_is_inert_instead_of_pretending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`api_format="anthropic"` 的中转端点：effort 透传会被 SDK 丢弃 → 整档不生效。

    `factory.create_model_provider` 按 **api_format** 选 provider，所以 `custom`/`api2d`
    这类名字配成 anthropic 协议后走的是 `AnthropicProvider`，它的 `chat()` 只读
    `max_tokens`/`system_prompt`/`extra_params`——kwargs 里的 `reasoning_effort` 到不了
    线上。此时既不注入也不预留（否则用户付了额度却什么都没发生）。
    """
    seen: list[dict[str, Any]] = []

    class _StubAnthropicMessages:
        async def create(self, **kwargs: Any) -> Any:
            seen.append(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(text=REVIEW_JSON)],
                usage=SimpleNamespace(input_tokens=3, output_tokens=2),
            )

    class _StubAnthropicClient:
        def __init__(self) -> None:
            self.messages = _StubAnthropicMessages()

    client = AIClient(
        config=AIClientConfig(
            provider="custom",
            api_key="relay-key",
            model="relay-claude",
            base_url="https://relay.example.com",
            api_format="anthropic",
            review_reasoning_effort="high",
        ),
        client_factory=lambda _: _StubAnthropicClient(),
    )

    await client.review_code("system prompt", "user prompt")

    assert len(seen) == 1
    assert "reasoning_effort" not in seen[0]
    assert "thinking" not in seen[0]
    # 没有思考预留（基础额度原样）：能力档案对未知供应商给 4096。
    assert seen[0]["max_tokens"] == 4096


@pytest.mark.asyncio
async def test_qwen_review_wire_uses_the_switch_and_budget_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非 kwargs 通道（`enable_thinking` / `thinking_budget`）确实落进请求体且受封顶。"""
    captured = _capture_review_body(monkeypatch)
    client = AIClient(
        config=AIClientConfig(
            provider="qwen",
            api_key="test-key",
            model="qwen-plus",
            api_format="openai",
            review_reasoning_effort="high",
        )
    )

    await client.review_code("system prompt", "user prompt")

    assert captured["enable_thinking"] is True
    # min(4096 + 8000, max_output 8192) = 8192；预算字段再收敛到"回答额度之外"的
    # 8192 - 4096 = 4096（官方区间 1..32768 之内）。
    assert captured["max_tokens"] == 8192
    assert captured["thinking_budget"] == 4096
    assert "reasoning_effort" not in captured  # qwen3.8 系两者不可同传


@pytest.mark.asyncio
async def test_anthropic_review_wire_caps_the_budget_at_max_output() -> None:
    """anthropic：预算制供应商，总额度封顶到规格 `max_output`，预算留出回答额度。

    anthropic 走 SDK（不经 urllib），因此用 client_factory 捕获**传给 provider 的 kwargs**
    与 `extra_params` 展开后的调用参数。
    """
    seen: list[dict[str, Any]] = []

    class _StubAnthropicMessages:
        async def create(self, **kwargs: Any) -> Any:
            seen.append(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(text=REVIEW_JSON)],
                usage=SimpleNamespace(input_tokens=3, output_tokens=2),
            )

    class _StubAnthropicClient:
        def __init__(self) -> None:
            self.messages = _StubAnthropicMessages()

    client = AIClient(
        config=AIClientConfig(
            provider="anthropic",
            api_key="key",
            model="claude-sonnet-4-20250514",
            review_reasoning_effort="max",
        ),
        client_factory=lambda _: _StubAnthropicClient(),
    )

    result = await client.review_code("system prompt", "user prompt")

    assert result.summary == "ok"
    assert len(seen) == 1
    call = seen[0]
    # 基础额度 4096 + max 预留 12000 = 16096 → 封顶到 anthropic 的 max_output 8192。
    assert call["max_tokens"] == 8192
    # budget_tokens 必须 < max_tokens，且给回答留出基础额度：8192 - 4096 = 4096。
    assert call["thinking"] == {"type": "enabled", "budget_tokens": 4096}
