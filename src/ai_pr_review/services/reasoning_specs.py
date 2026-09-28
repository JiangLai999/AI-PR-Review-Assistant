"""供应商"思考档位 → 请求体参数"规格表（数据驱动）。

数据源：`docs/DEV_RECORD.md`（opencode 联网调研，抓取日期 2026-09-26，
覆盖 `config.PROVIDER_MODEL_PRESETS` 的 19 家 + 本地 `local`）。每条规格都带
`doc_url` / `captured_at` / `confidence`，本模块**只做查表与组装**：不联网、不做真机
验证、不猜测。

与调研文档/代码不一致的地方，一律以调研文档为准，取舍写在 `ReasoningSpec.note` 与
`docs/DEV_RECORD.md`：

- `deepseek` 的 `max` 是**兼容映射**（官方枚举为 low/medium/high），保留是因为本机
  实测过单调性（`docs/DEV_RECORD.md`：disabled 0 < low 2624 < high 4509
  < max 6834），属于既有行为，不属"编造参数"；
- `qwen` / `siliconflow` 用 `thinking_budget` 通道表达四档（qwen3.8 系
  `reasoning_effort` 与 `thinking_budget` 不可同传，官方原文见调研 §3.4）；
- 档位少于四档的供应商按**就近映射**（如 hunyuan/stepfun 无 max → 用 high），
  并在 `note` 里写明——不假装有独立档位。

数据不足（调研未收录 / 值为 unknown）一律**不编造参数**：按 `unsupported` 处理，
`/think` 返回 unsupported 并附原因。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping

from ai_pr_review.config import CHAT_REASONING_TOKEN_BUDGETS

# `split_reasoning_params` 的白名单：能经 `chat(**kwargs)` 直达请求体的键
# （OpenAI 兼容 provider 的透传白名单，见 openai.py 的 `for passthrough_key in ...`）。
_KWARG_REASONING_KEYS: frozenset[str] = frozenset({"think", "reasoning_effort"})

# 参数形态（调研 §1 判定口径）。
FORM_EFFORT = "effort"
FORM_BUDGET = "budget"
FORM_VARIANT = "variant"
FORM_SWITCH = "switch"
FORM_TRANSPARENT = "transparent"
FORM_UNSUPPORTED = "unsupported"

# `/think` 的结果态（前端 `frontend/tui/src/protocol.ts` 读 `state`/`effort`）：
# set=已切换且参数形态明确；transparent=已切换但只是透传上游；unsupported=置灰。
STATE_SET = "set"
STATE_TRANSPARENT = "transparent"
STATE_UNSUPPORTED = "unsupported"

# confidence 取值（沿用调研文档口径 + 两个项目内部判定）。
CONFIDENCE_DOCUMENTED = "documented"
CONFIDENCE_UNSUPPORTED_BY_MODEL = "unsupported-by-model"
CONFIDENCE_TRANSPARENT = "transparent"
# 官方 API 有参数、但本项目产品决策不开放（本地）。
CONFIDENCE_PRODUCT_DECISION = "product-decision"
CONFIDENCE_UNKNOWN = "unknown"

# 统一四档（不含 `auto`：auto 的语义是"不碰参数"，不映射）。
REASONING_LEVELS: tuple[str, ...] = ("off", "low", "high", "max")
# 本地（ollama/local）置灰时给出的人类可读原因：产品决策，不是端点限制
# （实测流式 `think=false` 生效，见 docs/DEV_RECORD.md）。
LOCAL_PRODUCT_REASON = (
    "本地模型固定使用快速模式（不展示思考），档位不可调；需要思考强度请切换云端模型"
)
# C 组（中转/自定义端点）的提示语：参数确实发了，但生效与否取决于上游。
TRANSPARENT_REASON = "已按 OpenAI 兼容透传 reasoning_effort；是否生效取决于上游服务"
# 中转/自定义端点配成 Anthropic 协议（`api_format="anthropic"`）时的提示语：这类端点的
# 规格表条目是 transparent（只透传 reasoning_effort），但 Anthropic 形态的 provider 不读
# 那两个 kwargs，参数一个都到不了线上——如实说明，不假装生效。
ANTHROPIC_PROTOCOL_REASON = (
    "该端点走 Anthropic 协议（api_format=anthropic）：思考参数只会被丢弃，档位不会生效"
)


@dataclass(frozen=True, slots=True)
class ReasoningSpec:
    """一家供应商的思考参数规格（`levels` 的键是 off/low/high/max）。

    `levels` 的值是**要注入请求体的参数**（空 dict = 该档不注入任何参数，例如
    off 档官方没有提供关闭方式时）。预算型供应商（anthropic / qwen / siliconflow）
    通过 `budget_path` 指出需要按 `max_tokens` 收敛的字段，收敛规则见
    `build_reasoning_params`。
    """

    provider: str
    form: str
    levels: Mapping[str, Mapping[str, Any]]
    doc_url: str | None
    captured_at: str | None
    confidence: str
    reason: str | None = None
    note: str | None = None
    # 预设模型层面的提示：官方参数只对某些模型族生效，而 `PROVIDER_MODEL_PRESETS`
    # 里的预设可能是非思考模型。**不参与档位判定**（判定按供应商，模型差异如实告知）。
    model_caveat: str | None = None
    # 预算字段路径（如 ("thinking", "budget_tokens")）与它的合法区间/约束。
    budget_path: tuple[str, ...] | None = None
    budget_min: int | None = None
    budget_max: int | None = None
    # Anthropic 官方约束：`budget_tokens` 必须 < `max_tokens`（调研 §3.1 原句）。
    budget_below_max_tokens: bool = False


@dataclass(frozen=True, slots=True)
class ReasoningSupport:
    """`reasoning_support()` 的返回值：`/think` 判定与文档展示都用它。"""

    provider: str
    form: str
    state: str
    confidence: str
    doc_url: str | None
    captured_at: str | None
    reason: str | None
    note: str | None
    model_caveat: str | None

    @property
    def injects(self) -> bool:
        """是否会向请求体注入思考参数（unsupported / unknown 一律不注入）。"""
        return self.state in {STATE_SET, STATE_TRANSPARENT}

    @property
    def supported(self) -> bool:
        return self.state == STATE_SET


def _levels(
    off: Mapping[str, Any] | None,
    low: Mapping[str, Any] | None,
    high: Mapping[str, Any] | None,
    max_: Mapping[str, Any] | None,
) -> dict[str, Mapping[str, Any]]:
    return {
        "off": dict(off or {}),
        "low": dict(low or {}),
        "high": dict(high or {}),
        "max": dict(max_ or {}),
    }


def _passthrough_levels() -> dict[str, Mapping[str, Any]]:
    """C 组（中转/自定义）：四档都透传 `reasoning_effort`（off → none）。"""
    return _levels(
        {"reasoning_effort": "none"},
        {"reasoning_effort": "low"},
        {"reasoning_effort": "high"},
        {"reasoning_effort": "max"},
    )


# ---------------------------------------------------------------------------
# 19 家规格表（+ 本地 `local`，见 docs/DEV_RECORD.md §6.2）
# ---------------------------------------------------------------------------

REASONING_SPECS: dict[str, ReasoningSpec] = {
    # 预算制：`thinking: {type: enabled, budget_tokens: N}`，N ≥ 1024 且 < max_tokens。
    # 预设（claude-sonnet-4 / claude-opus-4）属 extended thinking 支持范围；4.6 起弃用、
    # 4.7+ 会 400 —— 迁移目标是 `thinking:{type:"adaptive"}` + `output_config.effort`，
    # 待有 4.7+ 预设时再改（调研 §3.1）。
    "anthropic": ReasoningSpec(
        provider="anthropic",
        form=FORM_BUDGET,
        levels=_levels(
            {"thinking": {"type": "disabled"}},
            {"thinking": {"type": "enabled", "budget_tokens": 4000}},
            {"thinking": {"type": "enabled", "budget_tokens": 8000}},
            {"thinking": {"type": "enabled", "budget_tokens": 12000}},
        ),
        budget_path=("thinking", "budget_tokens"),
        budget_min=1024,
        budget_below_max_tokens=True,
        doc_url="https://platform.claude.com/docs/en/build-with-claude/extended-thinking",
        captured_at="2026-09-26",
        confidence=CONFIDENCE_DOCUMENTED,
        note=(
            "官方只给 token 预算、不给档位表：四档取项目档位预算表"
            "（CHAT_REASONING_TOKEN_BUDGETS），并按官方约束收敛 budget_tokens < max_tokens"
        ),
        model_caveat=(
            "预设为 Claude 4.x（在 extended thinking 范围内）；"
            "4.7+ 需改 adaptive + output_config.effort"
        ),
    ),
    # 档位制：`reasoning_effort: none|minimal|low|medium|high|xhigh|max`（取值为模型相关）。
    "openai": ReasoningSpec(
        provider="openai",
        form=FORM_EFFORT,
        levels=_levels(
            {"reasoning_effort": "none"},
            {"reasoning_effort": "low"},
            {"reasoning_effort": "high"},
            {"reasoning_effort": "max"},
        ),
        doc_url="https://developers.openai.com/api/docs/guides/reasoning",
        captured_at="2026-09-26",
        confidence=CONFIDENCE_DOCUMENTED,
        note="官方默认值随模型而变（gpt-5.5 默认 medium）；部分模型传 none 返回 400（如 GPT-6 Astra）",
        model_caveat="预设 gpt-4o-mini / gpt-4.1 为非推理模型，传档位会被上游忽略或报未知参数",
    ),
    # 顶层开关 + effort 字符串（官方示例里两者同现）。
    "deepseek": ReasoningSpec(
        provider="deepseek",
        form=FORM_SWITCH,
        levels=_levels(
            {"thinking": {"type": "disabled"}},
            {"thinking": {"type": "enabled"}, "reasoning_effort": "low"},
            {"thinking": {"type": "enabled"}, "reasoning_effort": "high"},
            {"thinking": {"type": "enabled"}, "reasoning_effort": "max"},
        ),
        doc_url="http://api-docs.deepseek.com/",
        captured_at="2026-09-26",
        confidence=CONFIDENCE_DOCUMENTED,
        note=(
            "官方 effort 枚举为 low/medium/high（示例用 high）；`max` 是兼容映射，"
            "保留是因为本机实测单调有效（docs/DEV_RECORD.md："
            "disabled 0 < low 2624 < high 4509 < max 6834）——既有行为，非编造参数"
        ),
        model_caveat="预设 deepseek-flash / deepseek-v4-pro 为混合思考模型；deepseek-chat 为非思考模型",
    ),
    # 开关 + 预算：qwen3.8 系 `reasoning_effort` 与 `thinking_budget` 不可同传，故只走预算通道。
    "qwen": ReasoningSpec(
        provider="qwen",
        form=FORM_SWITCH,
        levels=_levels(
            {"enable_thinking": False},
            {"enable_thinking": True, "thinking_budget": 4000},
            {"enable_thinking": True, "thinking_budget": 8000},
            {"enable_thinking": True, "thinking_budget": 12000},
        ),
        budget_path=("thinking_budget",),
        budget_min=1,
        budget_max=32_768,
        doc_url="https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions",
        captured_at="2026-09-26",
        confidence=CONFIDENCE_DOCUMENTED,
        note=(
            "四档走 thinking_budget（官方区间 1–32768），不发 reasoning_effort："
            "qwen3.8 系两者不可同传（调研 §3.4）；官方 effort 枚举 none/minimal/low/medium/high/xhigh"
        ),
        model_caveat="预设 qwen-plus / qwen-max / qwen-coder-plus 未逐模型确认思考能力（调研未列名）",
    ),
    # 变体开关 + effort（GLM-5.2+ 才有 reasoning_effort）。
    "zhipu": ReasoningSpec(
        provider="zhipu",
        form=FORM_VARIANT,
        levels=_levels(
            {"thinking": {"type": "disabled"}},
            {"thinking": {"type": "enabled"}, "reasoning_effort": "low"},
            {"thinking": {"type": "enabled"}, "reasoning_effort": "high"},
            {"thinking": {"type": "enabled"}, "reasoning_effort": "max"},
        ),
        doc_url="https://docs.bigmodel.cn/cn/guide/start/concept-param",
        captured_at="2026-09-26",
        confidence=CONFIDENCE_DOCUMENTED,
        note=(
            "GLM-5.2 支持 max/high/low/minimal/none/xhigh（low、medium→high；xhigh→max）；"
            "GLM-5.3 仅 max/high/low 且传 disabled 会报错"
        ),
        model_caveat="预设 glm-4-flash / plus / air 低于 GLM-4.5，官方标注 thinking 仅 GLM-4.5 及以上支持",
    ),
    # 三套参数因模型而异：kimi-k3 顶层 effort；k2.x 用 thinking.type(+keep)。
    "moonshot": ReasoningSpec(
        provider="moonshot",
        form=FORM_SWITCH,
        levels=_levels(
            {"thinking": {"type": "disabled"}},
            {"reasoning_effort": "low"},
            {"reasoning_effort": "high"},
            {"reasoning_effort": "max"},
        ),
        doc_url="https://platform.kimi.com/docs/guide/use-thinking-models",
        captured_at="2026-09-26",
        confidence=CONFIDENCE_DOCUMENTED,
        note=(
            "按 kimi-k3 的顶层 reasoning_effort（默认 max）映射；kimi-k2.6/k2.7-code 走 "
            "thinking.type（+keep:all），本表未区分模型，差异见 model_caveat"
        ),
        model_caveat="预设 moonshot-v1-8k/32k/128k、kimi-k2-0711-preview 未出现在思考参数适用模型列表",
    ),
    # 变体开关：无档位，adaptive 是唯一开启态（省略即默认），M2.x 无法关闭。
    "minimax": ReasoningSpec(
        provider="minimax",
        form=FORM_VARIANT,
        levels=_levels(
            {"thinking": {"type": "disabled"}},
            {"thinking": {"type": "adaptive"}},
            {"thinking": {"type": "adaptive"}},
            {"thinking": {"type": "adaptive"}},
        ),
        doc_url="https://platform.minimaxi.com/docs/api-reference/text-chat-openai",
        captured_at="2026-09-26",
        confidence=CONFIDENCE_DOCUMENTED,
        note="官方无 low/high/max 档：开启态统一是 adaptive；disabled 仅 M3 可关（M2.x 关不掉）",
        model_caveat="预设 MiniMax-Text-01 / abab6.5s-chat 不在 thinking 参数覆盖的 M3/M2.x 范围内",
    ),
    # 开关 + effort（设 disabled 时不可同传 effort）。
    "doubao": ReasoningSpec(
        provider="doubao",
        form=FORM_SWITCH,
        levels=_levels(
            {"thinking": {"type": "disabled"}},
            {"reasoning_effort": "low"},
            {"reasoning_effort": "high"},
            {"reasoning_effort": "max"},
        ),
        doc_url="https://docs.volcengine.com/docs/82379/1449737",
        captured_at="2026-09-26",
        confidence=CONFIDENCE_DOCUMENTED,
        note=(
            "官方 effort 枚举 low/medium/high/xhigh/max（默认 medium）；"
            "官方要求 disabled 时不带 effort，off 档因此只发 thinking"
        ),
        model_caveat="官方页为 JS 渲染，证据取自官方域名索引片段（调研 §7）",
    ),
    # 官方未给关闭方式：off 不注入（按模型默认）；effort 只有 low/medium/high，max 就近映射 high。
    "hunyuan": ReasoningSpec(
        provider="hunyuan",
        form=FORM_VARIANT,
        levels=_levels(
            {},
            {"reasoning_effort": "low"},
            {"reasoning_effort": "high"},
            {"reasoning_effort": "high"},
        ),
        doc_url="https://cloud.tencent.com/document/product/1729/111006",
        captured_at="2026-09-26",
        confidence=CONFIDENCE_DOCUMENTED,
        note="OpenAI 兼容侧官方未给 off；TokenHub 协议表的 effort 仅 low/medium/high，max 就近映射为 high",
        model_caveat=(
            "思考与否由模型名区分（hunyuan-2.0-thinking-* vs -instruct-*）；"
            "预设 hunyuan-turbos-latest / hunyuan-large 为非思考模型"
        ),
    ),
    # effort 三档；off 即"不传"。
    "stepfun": ReasoningSpec(
        provider="stepfun",
        form=FORM_EFFORT,
        levels=_levels(
            {},
            {"reasoning_effort": "low"},
            {"reasoning_effort": "high"},
            {"reasoning_effort": "high"},
        ),
        doc_url="https://platform.stepfun.com/docs/zh/guides/developer/reasoning",
        captured_at="2026-09-26",
        confidence=CONFIDENCE_DOCUMENTED,
        note="官方 Chat Completion 只有 low/medium/high 三档（medium 为默认）；off=不传（按模型默认），max 就近映射 high",
        model_caveat="预设 step-2-16k / step-1-256k 未在支持说明中列名",
    ),
    # 官方文档未见思考参数（预设模型为非思考模型）→ 置灰，不编造参数。
    "baichuan": ReasoningSpec(
        provider="baichuan",
        form=FORM_UNSUPPORTED,
        levels=_levels({}, {}, {}, {}),
        doc_url="https://platform.baichuan-ai.com/docs",
        captured_at="2026-09-26",
        confidence=CONFIDENCE_UNSUPPORTED_BY_MODEL,
        reason="官方接口参数未见 thinking/reasoning 参数（预设 Baichuan4 / Baichuan3-Turbo 为非思考模型）",
        note="调研 §3.11：官方文档全量章节可见且无该参数，故判 unsupported-by-model（非 unknown）",
    ),
    "yi": ReasoningSpec(
        provider="yi",
        form=FORM_UNSUPPORTED,
        levels=_levels({}, {}, {}, {}),
        doc_url="https://platform.lingyiwanwu.com/docs",
        captured_at="2026-09-26",
        confidence=CONFIDENCE_UNSUPPORTED_BY_MODEL,
        reason="官方开放平台文档未见 thinking/reasoning 字段（预设 yi-lightning / yi-large 为非思考模型）",
        note="调研 §3.12：接口兼容 OpenAI 标准 Chat 参数，但未定义思考参数",
    ),
    # 平台统一规范：reasoning.{effort|max_tokens} 二选一。
    "openrouter": ReasoningSpec(
        provider="openrouter",
        form=FORM_EFFORT,
        levels=_levels(
            {"reasoning": {"effort": "none"}},
            {"reasoning": {"effort": "low"}},
            {"reasoning": {"effort": "high"}},
            {"reasoning": {"effort": "xhigh"}},
        ),
        doc_url="https://openrouter.ai/docs/guides/reasoning-tokens",
        captured_at="2026-09-26",
        confidence=CONFIDENCE_DOCUMENTED,
        note=(
            "官方 effort 枚举 none/minimal/low/medium/high/xhigh：max 映射为 xhigh（无 max 档）；"
            "另有 reasoning.exclude/enabled"
        ),
        model_caveat="预设 openai/gpt-4o-mini、anthropic/claude-3.5-sonnet 上游为非推理模型",
    ),
    # 开关 + 预算：无档位概念，档位由 thinking_budget 数值表达。
    "siliconflow": ReasoningSpec(
        provider="siliconflow",
        form=FORM_SWITCH,
        levels=_levels(
            {"enable_thinking": False},
            {"enable_thinking": True, "thinking_budget": 4000},
            {"enable_thinking": True, "thinking_budget": 8000},
            {"enable_thinking": True, "thinking_budget": 12000},
        ),
        budget_path=("thinking_budget",),
        budget_min=1,
        doc_url="https://docs.siliconflow.cn/cn/userguide/capabilities/reasoning",
        captured_at="2026-09-26",
        confidence=CONFIDENCE_DOCUMENTED,
        note="官方无 low/high/max 档（档位由 thinking_budget 数值表达）：四档取项目档位预算表",
        model_caveat="Qwen3 系到 thinking_budget 会强制停止思考，其它模型可能继续输出；预设里 DeepSeek-V3 非思考、R1 恒定思考无开关",
    ),
    # 本地：官方 API 有 think（bool 或 low/medium/high/max），但本项目产品决策不开放
    # （2026-09-26 用户裁定"不开放思考展示"）。`local` 不在 PROVIDER_MODEL_PRESETS 里，
    # 但可能是聊天槽的 provider 名，故单列一条（调研 §6.2）。
    "ollama": ReasoningSpec(
        provider="ollama",
        form=FORM_SWITCH,
        levels=_levels({}, {}, {}, {}),
        doc_url="https://docs.ollama.com/capabilities/thinking",
        captured_at="2026-09-26",
        confidence=CONFIDENCE_PRODUCT_DECISION,
        reason=LOCAL_PRODUCT_REASON,
        note=(
            "官方 API 支持 think: bool|low|medium|high|max（能力存在，非端点不支持）；"
            "本项目产品决策置灰（2026-09-26 用户裁定），`_chat` 另发快速模式兜底——"
            "实测流式 think=false 生效，见 docs/DEV_RECORD.md"
        ),
        model_caveat=(
            "预设 qwen3.5:4b / qwen3:4b 具备思考能力，"
            "phi4-mini / gemma3:4b / qwen2.5-coder:3b 不展示思考"
        ),
    ),
    "local": ReasoningSpec(
        provider="local",
        form=FORM_SWITCH,
        levels=_levels({}, {}, {}, {}),
        doc_url="https://docs.ollama.com/capabilities/thinking",
        captured_at="2026-09-26",
        confidence=CONFIDENCE_PRODUCT_DECISION,
        reason=LOCAL_PRODUCT_REASON,
        note="同 ollama：本地回环端点一律置灰（产品决策）",
    ),
    # C 组：中转/自定义端点无自有思考参数，按 OpenAI 兼容透传（是否生效取决于上游）。
    "api2d": ReasoningSpec(
        provider="api2d",
        form=FORM_TRANSPARENT,
        levels=_passthrough_levels(),
        doc_url="https://www.api2d.com/doc/doc",
        captured_at="2026-09-26",
        confidence=CONFIDENCE_TRANSPARENT,
        reason=TRANSPARENT_REASON,
        note="官方：接口与 OpenAI 严格一致，仅转发（调研 §5）",
    ),
    "closeai": ReasoningSpec(
        provider="closeai",
        form=FORM_TRANSPARENT,
        levels=_passthrough_levels(),
        doc_url="https://doc.closeai-asia.com/tutorial/api/openai.html",
        captured_at="2026-09-26",
        confidence=CONFIDENCE_TRANSPARENT,
        reason=TRANSPARENT_REASON,
        note="官方：参数与用法全部同 OpenAI，平台做 ChatCompletion↔Response/Anthropic/Gemini 协议转换",
    ),
    "ohmygpt": ReasoningSpec(
        provider="ohmygpt",
        form=FORM_TRANSPARENT,
        levels=_passthrough_levels(),
        doc_url="https://docs.ohmygpt.com/docs/api",
        captured_at="2026-09-26",
        confidence=CONFIDENCE_TRANSPARENT,
        reason=TRANSPARENT_REASON,
        note="官方：统一 OpenAI 兼容端点仅路由转发，模型库条目直接沿用上游 effort 描述",
    ),
    "custom": ReasoningSpec(
        provider="custom",
        form=FORM_TRANSPARENT,
        levels=_passthrough_levels(),
        doc_url=None,
        captured_at="2026-09-26",
        confidence=CONFIDENCE_TRANSPARENT,
        reason=TRANSPARENT_REASON,
        note="自定义 base_url：无官方文档，能力完全取决于上游；配置项定义见 config.PROVIDER_MODEL_PRESETS['custom']",
    ),
}

# 未收录供应商（含拼写错误 / 自建名字）：不编造参数，`/think` 返回 unsupported。
UNKNOWN_FORM = "unknown"
UNKNOWN_REASON = "未收录该供应商（调研文档无官方思考参数记录），未注入任何思考参数"


def _normalized(provider_name: object) -> str:
    return str(provider_name or "").strip().lower()


def get_reasoning_spec(provider_name: object) -> ReasoningSpec | None:
    """按供应商名取规格（未收录返回 None——调用方不得据此编造参数）。"""
    return REASONING_SPECS.get(_normalized(provider_name))


def reasoning_support(provider_name: object) -> ReasoningSupport:
    """供应商的思考支持情况（未收录 → 形态 unknown、态 unsupported）。"""
    provider = _normalized(provider_name)
    spec = REASONING_SPECS.get(provider)
    if spec is None:
        return ReasoningSupport(
            provider=provider,
            form=UNKNOWN_FORM,
            state=STATE_UNSUPPORTED,
            confidence=CONFIDENCE_UNKNOWN,
            doc_url=None,
            captured_at=None,
            reason=UNKNOWN_REASON,
            note=None,
            model_caveat=None,
        )
    return ReasoningSupport(
        provider=spec.provider,
        form=spec.form,
        state=(
            STATE_TRANSPARENT
            if spec.form == FORM_TRANSPARENT
            else (
                STATE_UNSUPPORTED
                if spec.form == FORM_UNSUPPORTED or spec.confidence == CONFIDENCE_PRODUCT_DECISION
                else STATE_SET
            )
        ),
        confidence=spec.confidence,
        doc_url=spec.doc_url,
        captured_at=spec.captured_at,
        reason=spec.reason,
        note=spec.note,
        model_caveat=spec.model_caveat,
    )


def _budget_value(params: Mapping[str, Any], path: tuple[str, ...]) -> int | None:
    node: Any = params
    for key in path:
        if not isinstance(node, Mapping) or key not in node:
            return None
        node = node[key]
    return node if isinstance(node, int) else None


def _set_budget(params: dict[str, Any], path: tuple[str, ...], value: int) -> None:
    node: Any = params
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value


def _clamp_budget(
    spec: ReasoningSpec, params: dict[str, Any], max_tokens: int, answer_tokens: int
) -> bool:
    """把预算字段收敛进官方合法区间；放不下时返回 False（调用方改为不下发）。

    官方约束（Anthropic，调研 §3.1 原句）：`budget_tokens` ≥ 1024 且 **< max_tokens**。
    收敛分两步：

    1. **官方区间优先**：先夹到 [budget_min, budget_max] 与 `< max_tokens`；官方区间本身
       就放不下（如 max_tokens ≤ 1024）直接返回 False——发一个会被 400 拒收的预算比不发
       更糟；
    2. **回答预留是软偏好**：给回答留出 `answer_tokens`（= `ai_client.max_tokens`）之外
       的额度才算思考预算；空间不够时退回官方下限（1024）而不是整档丢掉——此时答案额度
       由 `_chat_max_tokens` 的封顶决定，档位本身仍然合法。
    """
    value = _budget_value(params, spec.budget_path or ())
    if value is None:
        return True
    minimum = spec.budget_min if spec.budget_min is not None else 1
    limit = value
    if spec.budget_max is not None:
        limit = min(limit, spec.budget_max)
    if spec.budget_below_max_tokens:
        limit = min(limit, max_tokens - 1)
    if limit < minimum:
        return False
    room = max_tokens - max(0, answer_tokens)
    budget = min(limit, room)
    if budget < minimum:
        budget = minimum
    _set_budget(params, spec.budget_path or (), budget)
    return True


def build_reasoning_params(
    provider_name: object,
    level: object,
    *,
    max_tokens: int | None = None,
    answer_tokens: int = 0,
) -> dict[str, Any]:
    """组装本轮请求要注入的思考参数（不注入时返回空 dict）。

    规则（与 `_chat` 的调用点一一对应）：

    - `auto` / 非法档位 → `{}`（`auto` 的语义就是"不碰参数"）；
    - unsupported / 未收录 → `{}`（**不编造参数**）；
    - transparent → 透传 `reasoning_effort`（off → `none`）；
    - 其余按 `REASONING_SPECS` 查表；预算型供应商在给了 `max_tokens` 时按官方约束收敛
      （见 `_clamp_budget`，放不下则整档不注入）。

    返回的是**可安全改动**的新 dict（嵌套也已拷贝）：调用方会往里塞 provider 配置。
    """
    normalized_level = _normalized(level)
    if normalized_level not in REASONING_LEVELS:
        return {}
    support = reasoning_support(provider_name)
    if not support.injects:
        return {}
    params = copy.deepcopy(dict(REASONING_SPECS[support.provider].levels[normalized_level]))
    if not params:
        return {}
    spec = REASONING_SPECS[support.provider]
    if spec.budget_path and max_tokens is not None:
        if not _clamp_budget(spec, params, int(max_tokens), int(answer_tokens)):
            return {}
    return params


def reasoning_kwargs_consumed(provider_name: object, api_format: object = "openai") -> bool:
    """该 provider 的 `chat()` 是否会消费 `think` / `reasoning_effort` 这两个 kwargs。

    只有 OpenAI 兼容实现会（`openai.py` 的透传白名单）。**Anthropic 协议**不走这条路：
    `factory.create_model_provider` 按 `api_format == "anthropic"`（或名字就是 anthropic）
    选中 `AnthropicProvider`，它的 `chat()` 只读 `max_tokens`/`system_prompt` 与
    `config.extra_params`，其余 kwargs 一律丢弃。中转/自定义端点可以配成
    `api_format="anthropic"`（配置助手与 `AI_PR_REVIEW_API_FORMAT` 都能走到），
    此时"effort 透传"形态的参数一个都到不了线上——调用方据此判定"整档不生效"。
    """
    if str(provider_name or "").strip().lower() == "anthropic":
        return False
    return str(api_format or "openai").strip().lower() != "anthropic"


def reasoning_delivery_blocked_reason(
    provider_name: object, api_format: object = "openai"
) -> str | None:
    """该 provider 上"档位设了也一个参数都送不出去"的原因；能送出去则返回 `None`。

    出口（`config.options` / CLI 的说明文案）与注入点共用这一条判据，避免"代码不注入、
    出口却宣称已生效"这种自相矛盾。目前只有一种形态命中：规格表判为 transparent
    （只透传 `reasoning_effort`）而请求走 Anthropic 协议——那一路的 kwargs 会被丢弃
    （见 `reasoning_kwargs_consumed`）。预算型（anthropic/qwen/siliconflow）与
    switch/variant 形态走 `extra_params`，不受影响。
    """
    if reasoning_kwargs_consumed(provider_name, api_format):
        return None
    spec = get_reasoning_spec(provider_name)
    if spec is None or spec.form != FORM_TRANSPARENT:
        return None
    return ANTHROPIC_PROTOCOL_REASON


def split_reasoning_params(
    params: Mapping[str, Any],
    *,
    provider_name: object,
    api_format: object = "openai",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """把规格表算出的参数拆成 `(直传 kwargs, provider extra_params)` 两路。

    - `think` / `reasoning_effort` ∈ kwargs 白名单，但**仅当该 provider 会消费它们**
      （见 `reasoning_kwargs_consumed`）；Anthropic 协议下这些键会被丢弃；
    - 其余顶层参数（`thinking` / `enable_thinking` / `thinking_budget` / `reasoning`）
      只能进 provider 配置的 `extra_params`（OpenAI 兼容与 Anthropic 都会原样并进请求体）。

    返回的 dict 是新的（不修改入参）。调用方拿到两个空 dict 时，语义是"这一档在本次
    请求里一个参数都送不出去"——应当既不注入也不预留额度。
    """
    kwargs: dict[str, Any] = {}
    extra_params: dict[str, Any] = {}
    consumed = reasoning_kwargs_consumed(provider_name, api_format)
    for key, value in params.items():
        if key in _KWARG_REASONING_KEYS and consumed:
            kwargs[key] = value
        elif key in _KWARG_REASONING_KEYS:
            continue  # 该通道被协议丢弃：不要塞进 extra_params（会被 SDK 拒收）
        else:
            extra_params[key] = value
    return kwargs, extra_params


def describe_support(provider_name: object) -> dict[str, Any]:
    """`/think` 结果里随供应商变化的字段（不含档位本身，档位由调用方填）。"""
    support = reasoning_support(provider_name)
    payload: dict[str, Any] = {"form": support.form}
    if support.doc_url:
        payload["doc_url"] = support.doc_url
    if support.reason:
        payload["reason"] = support.reason
    if support.model_caveat:
        payload["model_caveat"] = support.model_caveat
    return payload


def covered_providers() -> tuple[str, ...]:
    """规格表覆盖的供应商名（含本地 `local`；未收录的走 unknown 兜底）。"""
    return tuple(REASONING_SPECS)


__all__ = [
    "ANTHROPIC_PROTOCOL_REASON",
    "CONFIDENCE_DOCUMENTED",
    "CONFIDENCE_PRODUCT_DECISION",
    "CONFIDENCE_TRANSPARENT",
    "CONFIDENCE_UNKNOWN",
    "CONFIDENCE_UNSUPPORTED_BY_MODEL",
    "FORM_BUDGET",
    "FORM_EFFORT",
    "FORM_SWITCH",
    "FORM_TRANSPARENT",
    "FORM_UNSUPPORTED",
    "FORM_VARIANT",
    "LOCAL_PRODUCT_REASON",
    "REASONING_LEVELS",
    "REASONING_SPECS",
    "STATE_SET",
    "STATE_TRANSPARENT",
    "STATE_UNSUPPORTED",
    "TRANSPARENT_REASON",
    "ReasoningSpec",
    "ReasoningSupport",
    "build_reasoning_params",
    "covered_providers",
    "describe_support",
    "get_reasoning_spec",
    "reasoning_delivery_blocked_reason",
    "reasoning_kwargs_consumed",
    "reasoning_support",
    "split_reasoning_params",
]
