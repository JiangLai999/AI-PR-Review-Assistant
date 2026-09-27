"""审查结果问答服务层（Phase 3 后端 · p3-chat-service）。

HTTP 路由与 code ↔ HTTP 映射在 `web_server._handle_chat`（本模块不碰 `web_server`），
这里只做协议背后的事：

1. 参数校验（`text` 必填、`run_id` 必须是已落库的审查记录）；
2. 上下文装配 —— **复用** `services/review_context.py` 的分层渲染与 token 估算，
   不另起一套 Markdown（`build_review_context_meta` / `wrap_review_context` /
   `estimate_tokens`）；
3. 调模型 —— 复用 CLI 的建客户端方式（`services/model_providers/factory.create_model_provider`
   + `provider.chat`，与 `cli._send_chat_message` 同一条路）；
4. 组出冻结契约的响应形状 `{reply, model, usage, context_meta}`。

冻结契约（`POST /api/chat`）::

    200 { "reply": str, "model": str,
          "usage": {"prompt_tokens","completion_tokens","total_tokens"} | None,
          "context_meta": {"bound_run", "token_estimate", "sections", "truncated", "note"} }

    text 缺失        -> ChatError("invalid_request", ...)
    run_id 查不到    -> ChatError("not_found", ...)
    没配模型 Key      -> ChatError("missing_api_key", ...)
    上游模型报错      -> ChatError("chat_failed", ...)

错误码 → HTTP 由 `web_server._CHAT_STATUS_CODES` 负责（invalid_request 400 /
not_found 404 / missing_api_key 503 / chat_failed 502）。
"""

from __future__ import annotations

from typing import Any

from ai_pr_review.config import (
    CHAT_SLOT_VALUES,
    DEFAULT_CHAT_CONTEXT_BUDGET,
    AppConfig,
    ModelProviderConfig,
    resolve_chat_slot,
)
from ai_pr_review.services.model_providers.factory import create_model_provider
from ai_pr_review.services.result_store import ResultStore
from ai_pr_review.services.review_context import (
    build_review_context_meta,
    estimate_tokens,
    wrap_review_context,
)

#: `ChatError.code` 的全部取值；服务层只抛这四个，HTTP 映射表因此是封闭的。
CHAT_ERROR_CODES = ("invalid_request", "not_found", "missing_api_key", "chat_failed")

MISSING_API_KEY_MESSAGE = "未配置模型 API Key：请先在设置页或 CLI 配置，或切换到本地模型。"

#: 本地槽不查 Key（`jsonl_server._chat` 与 `cli._send_chat_message` 同一口径）。
LOCAL_PROVIDER_NAMES = frozenset({"ollama", "local"})

#: `review_context` 渲染出的四段标题。`context_meta.sections` 必须**如实反映最终真的
#: 注入了哪几段**，所以只认这些标题，而不是按"打算注入什么"填。
SECTION_HEADERS: tuple[tuple[str, str], ...] = (
    ("run_summary", "[L1 运行摘要]"),
    ("findings", "[L2 FINDINGS 清单]"),
    ("finding_details", "[L3 重点 FINDING 全文]"),
    ("filtered_findings", "[L4 被过滤 FINDING]"),
)
_L2_HEADER = dict(SECTION_HEADERS)["findings"]


class ChatError(Exception):
    """问答失败，带 `web_server` 映射 HTTP 用的错误码。

    与 `services/publish_service.PublishError` 同形（`code` + `message`），
    两者的 code 都是发给前端的稳定值，不从异常文本里反解析。
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


async def answer_with_context(
    config: AppConfig, *, run_id: str = "", text: str = ""
) -> dict[str, Any]:
    """回答一次追问；`run_id` 非空时把该次审查的上下文注入 system prompt。

    校验顺序与 `PublishService.load_target` 一致：**先报请求自己的问题**
    （`invalid_request` / `not_found`），再报机器的问题（`missing_api_key`）——
    配好 Key 并不会让一个不存在的 run 变得存在。
    """
    question = text.strip() if isinstance(text, str) else ""
    if not question:
        raise ChatError("invalid_request", "text is required")

    key = str(run_id or "").strip()
    context_text = ""
    context_meta = _plain_context_meta()
    if key:
        store = ResultStore(config.result_store)
        if store.get_run_summary(key) is None or store.get_result(key) is None:
            raise ChatError("not_found", f"未找到审查记录：{key}")
        context_text, context_meta = _bound_context(config, store, key)

    provider_config = _chat_provider_config(config)
    _require_api_key(config, provider_config)

    chat_options: dict[str, Any] = {
        "max_tokens": config.ai_client.max_tokens,
        "timeout_seconds": config.ai_client.timeout_seconds,
    }
    if context_text:
        chat_options["system_prompt"] = wrap_review_context(key, context_text)
    if provider_config.name.lower() in LOCAL_PROVIDER_NAMES:
        chat_options["reasoning_effort"] = "none"

    try:
        provider = create_model_provider(provider_config)
        response = await provider.chat([{"role": "user", "content": question}], **chat_options)
    except Exception as exc:
        raise ChatError("chat_failed", f"模型调用失败：{exc}") from exc

    return {
        "reply": response.text,
        "model": str(provider_config.model_name or provider_config.name),
        "usage": _usage_payload(response),
        "context_meta": context_meta,
    }


# ---------------------------------------------------------------------------
# 上下文装配
# ---------------------------------------------------------------------------


def _plain_context_meta() -> dict[str, Any]:
    """未绑定 run（或上下文被裁空）时的 `context_meta`：一切为空，不编造估算值。"""
    return {
        "bound_run": None,
        "token_estimate": None,
        "sections": [],
        "truncated": False,
        "note": "",
    }


def _bound_context(
    config: AppConfig, store: ResultStore, run_id: str
) -> tuple[str, dict[str, Any]]:
    """渲染绑定 run 的审查上下文，并给出如实的 `context_meta`。

    分层渲染与内层预算阶梯完全交给 `review_context`；本函数只做两件它不管的事：
    外层兜底裁剪（见 `_shrink_to_budget`）与 `sections` 的如实登记。
    """
    budget = _context_budget(config)
    built = build_review_context_meta(store, run_id, token_budget=budget)
    meta: dict[str, Any] = {
        "bound_run": run_id,
        "token_estimate": 0,
        "sections": [],
        "truncated": False,
        "note": "",
    }
    if built is None:
        # `review_context` 的既定降级：读库失败不得中断对话（§9.2 C），
        # 按普通对话回答，但把降级写进 note，不让用户以为上下文真的注入了。
        meta["note"] = "审查上下文装配失败，本轮按普通对话回答。"
        return "", meta

    notes: list[str] = []
    text = built.text
    if built.trimmed:
        notes.append(
            f"上下文超出 {budget} token 预算，"
            f"已按 L4 → L3 → L2 顺序裁剪 {'、'.join(built.trimmed)}"
        )
    text, dropped = _shrink_to_budget(text, budget)
    if dropped:
        notes.append(_outer_note(dropped, budget))

    meta["token_estimate"] = estimate_tokens(text)
    meta["sections"] = _sections_of(text)
    meta["truncated"] = bool(built.trimmed or dropped)
    meta["note"] = "；".join(notes)
    return text, meta


def _shrink_to_budget(text: str, budget: int) -> tuple[str, tuple[str, ...]]:
    """外层兜底：`review_context` 的内层阶梯到底（L1 + critical/high L2）仍超预算时，
    按冻结的顺序继续裁 —— **先裁 findings，再裁运行摘要，最后只留问题本身**。

    `review_context` 承诺 L1 永不裁剪（否则模型不知道在说哪一次审查），所以这一层
    必须放在它外面；返回被裁掉的段名，由调用方写进 `context_meta.note`。
    """
    if not text or estimate_tokens(text) <= budget:
        return text, ()
    index = text.find(_L2_HEADER)
    if index == -1:
        return "", ("run_summary",)
    without_findings = text[:index].rstrip("\n")
    if not without_findings:
        return "", ("run_summary",)
    if estimate_tokens(without_findings) <= budget:
        return without_findings, ("findings",)
    return "", ("findings", "run_summary")


def _outer_note(dropped: tuple[str, ...], budget: int) -> str:
    tail = "仅保留问题本身" if "run_summary" in dropped else "仅保留运行摘要"
    return f"上下文超出 {budget} token 预算，已继续裁剪 {'、'.join(dropped)}，{tail}"


def _sections_of(text: str) -> list[str]:
    """最终注入文本里**实际存在**的段（按 L1 → L4 顺序）。"""
    return [key for key, header in SECTION_HEADERS if header in text]


def _context_budget(config: AppConfig) -> int:
    """`preferences.chat_context_budget`；缺字段/坏值回落 `DEFAULT_CHAT_CONTEXT_BUDGET`。

    不经过 `PreferencesConfig.__post_init__` 的归一化（构造之后再赋值会绕过它），
    所以这里自己兜底；0/负数按 1 处理，与 `review_context._normalize_budget` 同语义。
    """
    raw = getattr(getattr(config, "preferences", None), "chat_context_budget", None)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_CHAT_CONTEXT_BUDGET
    return max(1, value)


# ---------------------------------------------------------------------------
# 模型选择与调用
# ---------------------------------------------------------------------------


def _chat_provider_config(config: AppConfig) -> ModelProviderConfig:
    """聊天槽位真正承载配置的 Provider。

    判定与 `backend/jsonl_server.py:_chat_slot_config`（`:1823`）逐条一致 —— 那是
    `JSONLBackend` 的私有方法，实例化整个后端（会建会话存储、事件计数、审查超时等
    运行态）只为读一段配置太重，因此这里镜像同一套规则，用的都是 `config.py` 的公开
    词汇（`resolve_chat_slot` / `CHAT_SLOT_VALUES`）。
    """
    if resolve_chat_slot(config) == "remote":
        return config.provider.to_model_provider()
    chat_slot = str(getattr(config.preferences, "chat_slot", "") or "").strip().lower()
    if chat_slot in CHAT_SLOT_VALUES:
        return config.local_provider.to_model_provider()
    if getattr(config, "_env_provider_override", False):
        return config.provider.to_model_provider()
    # 由 `local_only` 预设推导出的本地槽：主 Provider 自己就是 Ollama/Local 时以它
    # 为准（用户自定义端点在主槽里），否则用持久化的本地槽。
    if config.provider.name.lower() in LOCAL_PROVIDER_NAMES:
        return config.provider.to_model_provider()
    return config.local_provider.to_model_provider()


def _require_api_key(config: AppConfig, provider_config: ModelProviderConfig) -> None:
    """本地豁免；远端则 `ai_client` / `provider` 两处 Key 全空即报 `missing_api_key`。"""
    if provider_config.name.lower() in LOCAL_PROVIDER_NAMES:
        return
    configured = (
        str(provider_config.api_key or "").strip()
        or str(getattr(config.ai_client, "api_key", "") or "").strip()
        or str(getattr(config.provider, "api_key", "") or "").strip()
    )
    if not configured:
        raise ChatError("missing_api_key", MISSING_API_KEY_MESSAGE)


def _usage_payload(response: Any) -> dict[str, int] | None:
    """供应商报了多少就转多少；拿不到就回 `None`（绝不编造 total）。

    与 `backend/jsonl_server.py:_chat_usage_payload`（`:3250`）同口径：优先
    `response.usage` 字典，退化到 `input_tokens`/`output_tokens`，两者皆空为 `None`。
    """
    raw_usage = getattr(response, "usage", None)
    if isinstance(raw_usage, dict):
        try:
            prompt_tokens = int(raw_usage.get("prompt_tokens") or 0)
            completion_tokens = int(raw_usage.get("completion_tokens") or 0)
            total_tokens = int(
                raw_usage.get("total_tokens") or (prompt_tokens + completion_tokens) or 0
            )
        except (TypeError, ValueError):
            return None
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }
    try:
        prompt_tokens = int(getattr(response, "input_tokens", 0) or 0)
        completion_tokens = int(getattr(response, "output_tokens", 0) or 0)
    except (TypeError, ValueError):
        return None
    if prompt_tokens <= 0 and completion_tokens <= 0:
        return None
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
