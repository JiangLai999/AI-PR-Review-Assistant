"""思考参数规格表（`services/reasoning_specs.py`）的映射断言。

数据源是 `docs/DEV_RECORD.md`（19 家官方文档调研，2026-09-26）。
这里断言的是**表本身**：四档映射、官方约束、以及"查不到就不编造"的兜底行为；
`_chat` / `/think` 的落地行为在 `tests/test_jsonl_backend.py` 里验。

刻意写成"19 家 × 四档"的表驱动形式：新增一家供应商时，漏登记会直接红。
"""

from __future__ import annotations

from typing import Any

import pytest

from ai_pr_review.config import CHAT_REASONING_TOKEN_BUDGETS, PROVIDER_MODEL_PRESETS
from ai_pr_review.services.reasoning_specs import (
    ANTHROPIC_PROTOCOL_REASON,
    CONFIDENCE_DOCUMENTED,
    CONFIDENCE_PRODUCT_DECISION,
    CONFIDENCE_TRANSPARENT,
    CONFIDENCE_UNKNOWN,
    CONFIDENCE_UNSUPPORTED_BY_MODEL,
    FORM_BUDGET,
    FORM_EFFORT,
    FORM_SWITCH,
    FORM_TRANSPARENT,
    FORM_UNSUPPORTED,
    FORM_VARIANT,
    LOCAL_PRODUCT_REASON,
    REASONING_LEVELS,
    REASONING_SPECS,
    STATE_SET,
    STATE_TRANSPARENT,
    STATE_UNSUPPORTED,
    build_reasoning_params,
    covered_providers,
    describe_support,
    get_reasoning_spec,
    reasoning_delivery_blocked_reason,
    reasoning_kwargs_consumed,
    reasoning_support,
    split_reasoning_params,
)

# 四档 → 期望注入的参数（调研 §2 总表逐行；`None` 表示"该档不注入"）。
# 预算型供应商（anthropic/qwen/siliconflow）的数值是项目档位预算表
# （CHAT_REASONING_TOKEN_BUDGETS），不是官方给的档位表——调研文档已注明。
_EMPTY: dict[str, Any] = {}
# C 组四家（中转/自定义）：跟随上游 OpenAI，透传 reasoning_effort。
_PASSTHROUGH = {
    "off": {"reasoning_effort": "none"},
    "low": {"reasoning_effort": "low"},
    "high": {"reasoning_effort": "high"},
    "max": {"reasoning_effort": "max"},
}

EXPECTED_LEVELS: dict[str, dict[str, dict[str, Any]]] = {
    "anthropic": {
        "off": {"thinking": {"type": "disabled"}},
        "low": {"thinking": {"type": "enabled", "budget_tokens": 4_000}},
        "high": {"thinking": {"type": "enabled", "budget_tokens": 8_000}},
        "max": {"thinking": {"type": "enabled", "budget_tokens": 12_000}},
    },
    "openai": {
        "off": {"reasoning_effort": "none"},
        "low": {"reasoning_effort": "low"},
        "high": {"reasoning_effort": "high"},
        "max": {"reasoning_effort": "max"},
    },
    "deepseek": {
        "off": {"thinking": {"type": "disabled"}},
        "low": {"thinking": {"type": "enabled"}, "reasoning_effort": "low"},
        "high": {"thinking": {"type": "enabled"}, "reasoning_effort": "high"},
        "max": {"thinking": {"type": "enabled"}, "reasoning_effort": "max"},
    },
    "qwen": {
        "off": {"enable_thinking": False},
        "low": {"enable_thinking": True, "thinking_budget": 4_000},
        "high": {"enable_thinking": True, "thinking_budget": 8_000},
        "max": {"enable_thinking": True, "thinking_budget": 12_000},
    },
    "zhipu": {
        "off": {"thinking": {"type": "disabled"}},
        "low": {"thinking": {"type": "enabled"}, "reasoning_effort": "low"},
        "high": {"thinking": {"type": "enabled"}, "reasoning_effort": "high"},
        "max": {"thinking": {"type": "enabled"}, "reasoning_effort": "max"},
    },
    "moonshot": {
        "off": {"thinking": {"type": "disabled"}},
        "low": {"reasoning_effort": "low"},
        "high": {"reasoning_effort": "high"},
        "max": {"reasoning_effort": "max"},
    },
    "minimax": {
        "off": {"thinking": {"type": "disabled"}},
        "low": {"thinking": {"type": "adaptive"}},
        "high": {"thinking": {"type": "adaptive"}},
        "max": {"thinking": {"type": "adaptive"}},
    },
    "doubao": {
        "off": {"thinking": {"type": "disabled"}},
        "low": {"reasoning_effort": "low"},
        "high": {"reasoning_effort": "high"},
        "max": {"reasoning_effort": "max"},
    },
    "hunyuan": {
        "off": _EMPTY,  # 官方未给关闭方式
        "low": {"reasoning_effort": "low"},
        "high": {"reasoning_effort": "high"},
        "max": {"reasoning_effort": "high"},  # 就近映射（官方只有 low/medium/high）
    },
    "stepfun": {
        "off": _EMPTY,  # 官方：off = 不传（按模型默认）
        "low": {"reasoning_effort": "low"},
        "high": {"reasoning_effort": "high"},
        "max": {"reasoning_effort": "high"},
    },
    "baichuan": {"off": _EMPTY, "low": _EMPTY, "high": _EMPTY, "max": _EMPTY},
    "yi": {"off": _EMPTY, "low": _EMPTY, "high": _EMPTY, "max": _EMPTY},
    "openrouter": {
        "off": {"reasoning": {"effort": "none"}},
        "low": {"reasoning": {"effort": "low"}},
        "high": {"reasoning": {"effort": "high"}},
        "max": {"reasoning": {"effort": "xhigh"}},  # 官方无 max 档
    },
    "siliconflow": {
        "off": {"enable_thinking": False},
        "low": {"enable_thinking": True, "thinking_budget": 4_000},
        "high": {"enable_thinking": True, "thinking_budget": 8_000},
        "max": {"enable_thinking": True, "thinking_budget": 12_000},
    },
    "ollama": {"off": _EMPTY, "low": _EMPTY, "high": _EMPTY, "max": _EMPTY},  # 产品决策置灰
    "local": {"off": _EMPTY, "low": _EMPTY, "high": _EMPTY, "max": _EMPTY},
    "api2d": _PASSTHROUGH,
    "closeai": _PASSTHROUGH,
    "ohmygpt": _PASSTHROUGH,
    "custom": _PASSTHROUGH,
}

EXPECTED_FORMS = {
    "anthropic": FORM_BUDGET,
    "openai": FORM_EFFORT,
    "deepseek": FORM_SWITCH,
    "qwen": FORM_SWITCH,
    "zhipu": FORM_VARIANT,
    "moonshot": FORM_SWITCH,
    "minimax": FORM_VARIANT,
    "doubao": FORM_SWITCH,
    "hunyuan": FORM_VARIANT,
    "stepfun": FORM_EFFORT,
    "baichuan": FORM_UNSUPPORTED,
    "yi": FORM_UNSUPPORTED,
    "openrouter": FORM_EFFORT,
    "siliconflow": FORM_SWITCH,
    "ollama": FORM_SWITCH,
    "local": FORM_SWITCH,
    "api2d": FORM_TRANSPARENT,
    "closeai": FORM_TRANSPARENT,
    "ohmygpt": FORM_TRANSPARENT,
    "custom": FORM_TRANSPARENT,
}


def test_specs_cover_every_preset_and_the_local_slot() -> None:
    """19 个预设 key 一个不少（unsupported/transparent 也要有条目）+ 本地 `local`。"""
    assert set(PROVIDER_MODEL_PRESETS) <= set(REASONING_SPECS)
    assert len(PROVIDER_MODEL_PRESETS) == 19
    # `local` 不在预设表里，但可能是聊天槽的 provider 名（调研 §6.2）。
    assert "local" in REASONING_SPECS
    assert set(covered_providers()) == set(EXPECTED_LEVELS)


def test_every_entry_declares_levels_provenance_and_confidence() -> None:
    """每条规格都要有出处：doc_url / captured_at / confidence（custom 无官方文档）。"""
    for name, spec in REASONING_SPECS.items():
        assert set(spec.levels) == set(REASONING_LEVELS), name
        assert spec.captured_at == "2026-09-26", name
        if name == "custom":
            assert spec.doc_url is None  # 调研 §2 第 19 行：无官方文档
            continue
        # 按调研文档原样记录（deepseek 的官方域名是 http://api-docs.deepseek.com/）。
        assert spec.doc_url and spec.doc_url.startswith(("http://", "https://")), name
        if spec.confidence == CONFIDENCE_DOCUMENTED:
            assert spec.form in {FORM_EFFORT, FORM_BUDGET, FORM_VARIANT, FORM_SWITCH}, name
        elif spec.confidence in {CONFIDENCE_UNSUPPORTED_BY_MODEL, CONFIDENCE_PRODUCT_DECISION}:
            assert spec.form == FORM_UNSUPPORTED or spec.levels == dict.fromkeys(
                REASONING_LEVELS, {}
            ), name


@pytest.mark.parametrize("provider", sorted(EXPECTED_LEVELS))
@pytest.mark.parametrize("level", REASONING_LEVELS)
def test_level_mapping(provider: str, level: str) -> None:
    """19 家 (+local) × 四档 → 要注入请求体的参数（调研总表逐行对照）。"""
    spec = REASONING_SPECS[provider]
    assert dict(spec.levels[level]) == EXPECTED_LEVELS[provider][level]
    assert spec.form == EXPECTED_FORMS[provider]
    # 不带 max_tokens 时（例如文档/UI 预览）返回表里的原值。
    assert build_reasoning_params(provider, level) == EXPECTED_LEVELS[provider][level]


def test_documented_budget_fields_match_the_project_level_table() -> None:
    """预算型供应商的数值 = 项目档位预算表（`low/high/max` 三档，off 不预留）。"""
    for provider, path in (("anthropic", ("thinking", "budget_tokens")),):
        for level, tokens in CHAT_REASONING_TOKEN_BUDGETS.items():
            params = build_reasoning_params(provider, level)
            node: Any = params
            for key in path:
                node = node[key]
            assert node == tokens, (provider, level)
    for provider in ("qwen", "siliconflow"):
        for level, tokens in CHAT_REASONING_TOKEN_BUDGETS.items():
            assert build_reasoning_params(provider, level)["thinking_budget"] == tokens


# ---------------------------------------------------------------------------
# 兜底与约束
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider", ["mystery-llm", "", "gpt-5-direct", None])
def test_unknown_provider_never_invents_params(provider: object) -> None:
    """未收录的供应商：不注入任何参数，`/think` 态为 unsupported + 原因。"""
    support = reasoning_support(provider)
    assert support.form == "unknown"
    assert support.state == STATE_UNSUPPORTED
    assert support.confidence == CONFIDENCE_UNKNOWN
    assert support.doc_url is None
    assert "未收录" in (support.reason or "")
    assert not support.injects
    for level in REASONING_LEVELS:
        assert build_reasoning_params(provider, level) == {}
        assert build_reasoning_params(provider, level, max_tokens=8_192) == {}


@pytest.mark.parametrize("provider", ["baichuan", "yi"])
def test_unsupported_by_model_providers_are_greyed(provider: str) -> None:
    """官方文档可见但无该参数 → 置灰，并给出官方 URL 供回溯。"""
    support = reasoning_support(provider)
    assert support.state == STATE_UNSUPPORTED
    assert support.confidence == CONFIDENCE_UNSUPPORTED_BY_MODEL
    assert support.doc_url and support.reason
    assert all(build_reasoning_params(provider, level) == {} for level in REASONING_LEVELS)


@pytest.mark.parametrize("provider", ["ollama", "local"])
def test_local_is_a_product_decision_not_an_endpoint_limitation(provider: str) -> None:
    """本地：能力存在（官方 think 参数有文档），但产品决策置灰。"""
    support = reasoning_support(provider)
    assert support.state == STATE_UNSUPPORTED
    assert support.confidence == CONFIDENCE_PRODUCT_DECISION
    assert support.form == FORM_SWITCH  # 官方 API 的形态如实记录
    assert support.reason == LOCAL_PRODUCT_REASON
    assert support.doc_url == "https://docs.ollama.com/capabilities/thinking"


@pytest.mark.parametrize("provider", ["api2d", "closeai", "ohmygpt", "custom"])
def test_relay_providers_are_transparent_not_silently_ignored(provider: str) -> None:
    """C 组：四档都透传 `reasoning_effort`（off → none），态为 transparent。"""
    support = reasoning_support(provider)
    assert support.state == STATE_TRANSPARENT
    assert support.confidence == CONFIDENCE_TRANSPARENT
    assert "取决于上游" in (support.reason or "")
    assert support.injects  # 参数是真发了（是否生效才取决于上游）
    assert build_reasoning_params(provider, "high") == {"reasoning_effort": "high"}
    assert build_reasoning_params(provider, "off") == {"reasoning_effort": "none"}


@pytest.mark.parametrize("provider", ["deepseek", "anthropic", "openai", "qwen"])
def test_auto_never_touches_the_request(provider: str) -> None:
    """`auto` 的语义是"不碰参数"，不是"用默认档"——任何供应商都不该注入。"""
    assert build_reasoning_params(provider, "auto") == {}
    assert build_reasoning_params(provider, "AUTO") == {}
    assert build_reasoning_params(provider, "medium") == {}  # 非四档值也不编造


def test_anthropic_budget_respects_official_constraints() -> None:
    """官方约束：`budget_tokens` ≥ 1024 且 < `max_tokens`（调研 §3.1 原句）。"""
    # 默认安装：max_tokens 封顶 8_192、回答额度 4_096 → 思考只能拿 4_096。
    high = build_reasoning_params("anthropic", "high", max_tokens=8_192, answer_tokens=4_096)
    assert high["thinking"] == {"type": "enabled", "budget_tokens": 4_096}

    # max_tokens 再小也要守住两条：≥1024、< max_tokens。
    tight = build_reasoning_params("anthropic", "max", max_tokens=2_000, answer_tokens=4_096)
    assert tight["thinking"]["budget_tokens"] == 1_024
    assert 1_024 < 2_000

    # 规格小到连 1024 都放不下（max_tokens ≤ 1024）：整档不注入，不发会被 400 拒收的值。
    assert build_reasoning_params("anthropic", "max", max_tokens=1_024) == {}
    assert build_reasoning_params("anthropic", "max", max_tokens=1_000) == {}
    # off 档是纯关闭开关，与预算约束无关（仍走 thinking.type=disabled）。
    assert build_reasoning_params("anthropic", "off", max_tokens=1_000) == {
        "thinking": {"type": "disabled"}
    }


def test_qwen_budget_stays_inside_the_documented_range() -> None:
    """qwen/siliconflow：预算不得越出官方区间（qwen 为 1–32768）。"""
    spec = get_reasoning_spec("qwen")
    assert spec is not None and spec.budget_min == 1 and spec.budget_max == 32_768
    params = build_reasoning_params("qwen", "max", max_tokens=64_000, answer_tokens=0)
    assert params["thinking_budget"] == 12_000
    # 回答额度把空间吃光（2_000 - 4_096 < 0）时退回**官方下限**而不是发越界值——
    # qwen 的下限 1 只是合法性边界（1–32768），因此这种退化配置下档位实际等于关思考。
    tight = build_reasoning_params("qwen", "low", max_tokens=2_000, answer_tokens=4_096)
    assert tight["thinking_budget"] == 1
    assert build_reasoning_params("siliconflow", "max", max_tokens=64_000) == {
        "enable_thinking": True,
        "thinking_budget": 12_000,
    }


def test_returned_params_are_copy_safe() -> None:
    """返回的是深拷贝：调用方（`_chat`）往里塞 provider 配置，不能污染规格表。"""
    first = build_reasoning_params("deepseek", "high")
    first["thinking"]["type"] = "tampered"
    first["injected"] = True
    assert REASONING_SPECS["deepseek"].levels["high"]["thinking"] == {"type": "enabled"}
    assert build_reasoning_params("deepseek", "high") == {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
    }


def test_describe_support_feeds_the_think_result() -> None:
    """`/think` 的随供应商字段：形态 + 依据 URL + 原因（有则给）。"""
    documented = describe_support("stepfun")
    assert documented["form"] == FORM_EFFORT
    assert documented["doc_url"].startswith("https://platform.stepfun.com")
    assert "reason" not in documented  # 支持的供应商没有"置灰原因"

    greyed = describe_support("ollama")
    assert greyed["reason"] == LOCAL_PRODUCT_REASON
    assert greyed["doc_url"] == "https://docs.ollama.com/capabilities/thinking"

    unknown = describe_support("mystery-llm")
    assert unknown["form"] == "unknown"
    assert "doc_url" not in unknown  # 没有依据就不给 URL（不编造）


def test_capability_profile_reuses_the_same_table() -> None:
    """`model_capabilities` 的思考形态来自规格表（单一数据源，不抄第二份）。"""
    from ai_pr_review.services.model_capabilities import get_model_capabilities

    assert get_model_capabilities("deepseek", "deepseek-flash").reasoning_form == FORM_SWITCH
    assert get_model_capabilities("anthropic", "claude-sonnet-4-20250514").reasoning_form == (
        FORM_BUDGET
    )
    assert get_model_capabilities("mystery", "m").reasoning_form == "unknown"


def test_state_constants_match_the_frontend_contract() -> None:
    """三态字符串是前后端契约（`frontend/tui/src/protocol.ts` 读 `state`/`effort`）。"""
    assert (STATE_SET, STATE_TRANSPARENT, STATE_UNSUPPORTED) == (
        "set",
        "transparent",
        "unsupported",
    )
    assert reasoning_support("deepseek").state == STATE_SET
    assert reasoning_support("api2d").state == STATE_TRANSPARENT
    assert reasoning_support("ollama").state == STATE_UNSUPPORTED


# ---------------------------------------------------------------------------
# 参数落地通道（`split_reasoning_params`）与"送不出去"的判据
# ---------------------------------------------------------------------------


def test_split_reasoning_params_routes_by_channel() -> None:
    """kwargs 白名单进 kwargs，其余顶层参数进 extra_params；入参不被修改。"""
    params = {"thinking": {"type": "enabled"}, "reasoning_effort": "high", "thinking_budget": 8000}
    kwargs, extra = split_reasoning_params(params, provider_name="zhipu", api_format="openai")

    assert kwargs == {"reasoning_effort": "high"}
    assert extra == {"thinking": {"type": "enabled"}, "thinking_budget": 8000}
    assert params == {  # 深拷贝语义：调用方给的 dict 原样不动
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
        "thinking_budget": 8000,
    }


def test_anthropic_protocol_drops_effort_but_keeps_budget_params() -> None:
    """Anthropic 形态（按 `api_format` 选 provider，与供应商名无关）：kwargs 通道失效。

    - 透传型（api2d/custom/...）只有 `reasoning_effort` → 两路皆空 = 整档送不出去；
    - 预算型（anthropic 自己）走 `extra_params` → 照旧能落地。
    """
    kwargs, extra = split_reasoning_params(
        {"reasoning_effort": "high"}, provider_name="api2d", api_format="anthropic"
    )
    assert (kwargs, extra) == ({}, {})

    kwargs, extra = split_reasoning_params(
        {"thinking": {"type": "enabled", "budget_tokens": 8000}},
        provider_name="anthropic",
        api_format="anthropic",
    )
    assert kwargs == {}
    assert extra == {"thinking": {"type": "enabled", "budget_tokens": 8000}}


def test_reasoning_kwargs_consumed_follows_the_factory_branch() -> None:
    """与 `factory.create_model_provider` 的分支一致：名字是 anthropic 或格式是 anthropic。"""
    assert reasoning_kwargs_consumed("deepseek", "openai") is True
    assert reasoning_kwargs_consumed("api2d", "custom") is True
    # 名字不是 anthropic，但协议是 → AnthropicProvider
    assert reasoning_kwargs_consumed("custom", "anthropic") is False
    # 格式不是 anthropic，但名字是 → 同样走 AnthropicProvider
    assert reasoning_kwargs_consumed("anthropic", "openai") is False


def test_delivery_blocked_reason_matches_the_injection_decision() -> None:
    """出口文案与注入点判据同源：判为 blocked 的组合，注入点确实两路皆空。"""
    blocked = reasoning_delivery_blocked_reason("custom", "anthropic")
    assert blocked == ANTHROPIC_PROTOCOL_REASON
    kwargs, extra = split_reasoning_params(
        build_reasoning_params("custom", "high"),
        provider_name="custom",
        api_format="anthropic",
    )
    assert (kwargs, extra) == ({}, {})

    # 能送出去的组合一律不给原因（出口据此判定"没有置灰说明"）。
    assert reasoning_delivery_blocked_reason("api2d", "openai") is None
    assert reasoning_delivery_blocked_reason("anthropic", "anthropic") is None
    assert reasoning_delivery_blocked_reason("deepseek", "openai") is None
    assert reasoning_delivery_blocked_reason("mystery-llm", "anthropic") is None
