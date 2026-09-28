"""Unified AI client built on model providers."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from pydantic import ValidationError

from ai_pr_review.config import (
    CHAT_REASONING_TOKEN_BUDGETS,
    DEFAULT_REVIEW_REASONING_EFFORT,
    PROVIDER_MODEL_PRESETS,
    REVIEW_REASONING_EFFORTS,
    AIClientConfig,
    CostControllerConfig,
)
from ai_pr_review.services.cost_controller import CostController, CostLedger, UsageRecord
from ai_pr_review.services.exceptions import (
    AIAuthenticationError,
    AICostLimitError,
    AIRequestTimeoutError,
    AIResponseFormatError,
    AIServiceError,
)
from ai_pr_review.services.model_capabilities import (
    calculate_review_output_budget,
    get_model_capabilities,
)
from ai_pr_review.services.model_providers.factory import create_model_provider
from ai_pr_review.services.prompt_assembler import ReviewResult
from ai_pr_review.services.reasoning_specs import (
    build_reasoning_params,
    reasoning_support,
    split_reasoning_params,
)

# 本地端点不开放 review 档位（产品决策，与 chat 同口径：`reasoning_specs` 里
# ollama/local 的 confidence = product-decision）。OllamaProvider 自己会发
# `think: false` 走快速模式（ollama.py:24），这里不再叠加任何注入。
LOCAL_REVIEW_PROVIDER_NAMES: frozenset[str] = frozenset({"ollama", "local"})


class AIClient:
    """调用模型供应商 API 并返回结构化审查结果。"""

    def __init__(
        self,
        config: AIClientConfig | None = None,
        client_factory: Callable[[str], Any] | None = None,
        cost_ledger: CostLedger | None = None,
    ) -> None:
        self._config = config or AIClientConfig()
        self._provider_config = self._config.model_provider
        self._api_key = self._provider_config.api_key

        if not self._api_key and self._provider_config.name.lower() not in {"ollama", "local"}:
            raise AIAuthenticationError(
                "模型供应商 API Key 未提供。请设置对应环境变量或直接传入配置。"
            )

        # 保留工厂：review 请求需要"本次请求专用"的 provider 副本时要用同一个工厂重建
        # （anthropic 走 SDK，副本必须沿用调用方注入的 client_factory，测试才打得住）。
        self._client_factory = client_factory
        self._provider = create_model_provider(self._provider_config, client_factory=client_factory)
        self._client = getattr(self._provider, "_client", self._provider)
        self._cost_controller = CostController(
            CostControllerConfig(
                run_limit=self._config.max_cost_per_run,
                daily_limit=self._config.max_cost_per_24h,
                input_cost_per_million=self._config.input_cost_per_million,
                output_cost_per_million=self._config.output_cost_per_million,
            ),
            # 共享账本：hybrid 编排器把 local / remote 两个客户端接到同一个 ledger 上，
            # run 级与 24h 预算才不会被"每个槽位各算一份"稀释。
            # 不传则自建（默认行为与改造前一致）。
            ledger=cost_ledger,
        )
        self._usage_history = self._cost_controller._usage_history
        # Concurrent file reviews share one budget. Reserve estimated capacity
        # before starting a request so parallel tasks cannot all pass the same check.
        self._budget_lock = asyncio.Lock()
        self._reserved_cost = 0.0

    async def review_code(self, system_prompt: str, user_prompt: str) -> ReviewResult:
        """调用 AI 进行代码审查。"""
        estimated_input_tokens = self._estimate_text_tokens(
            system_prompt
        ) + self._estimate_text_tokens(user_prompt)
        # Keep an explicit user override (including advanced configs), but
        # replace the legacy 4096 default with a task-aware review budget.
        base_max_tokens = (
            self._config.max_tokens
            if self._config.max_tokens != 4096
            else calculate_review_output_budget(
                self._config.provider,
                self._config.model,
                input_chars=len(system_prompt) + len(user_prompt),
            )
        )
        # 思考档位按**本次请求**计算（不落盘、不进 `AIClientConfig.extra_params`）：
        # 混合编排会按文件重建 provider 配置并用 `dict(selected_config.extra_params)`
        # 覆盖（hybrid_orchestrator.py:151），写进落盘字段的档位下一个文件就没了。
        effective_max_tokens, reasoning_kwargs, reasoning_extra = self._review_reasoning_plan(
            base_max_tokens
        )
        request_provider, reasoning_kwargs = self._review_request_provider(
            reasoning_kwargs, reasoning_extra
        )
        estimated_max_cost = self.estimate_cost(estimated_input_tokens, effective_max_tokens)
        await self._reserve_cost(estimated_max_cost)

        last_error: Exception | None = None
        format_repair_attempted = False
        request_system_prompt = system_prompt
        request_user_prompt = user_prompt
        try:
            for attempt in range(self._config.max_retries):
                try:
                    response = await asyncio.wait_for(
                        request_provider.chat(
                            [{"role": "user", "content": request_user_prompt}],
                            system_prompt=request_system_prompt,
                            max_tokens=effective_max_tokens,
                            timeout_seconds=self._config.timeout_seconds,
                            structured_output=True,
                            **reasoning_kwargs,
                        ),
                        timeout=self._config.timeout_seconds,
                    )

                    result = self._parse_review_result(response)
                    self._record_usage(
                        response,
                        fallback_input_tokens=estimated_input_tokens,
                        reserved_cost=estimated_max_cost,
                    )
                    return result
                except asyncio.TimeoutError as exc:
                    last_error = AIRequestTimeoutError(
                        f"AI 请求超时（>{self._config.timeout_seconds}s）。", original_error=exc
                    )
                except AIResponseFormatError as exc:
                    last_error = exc
                    if not format_repair_attempted and attempt < self._config.max_retries - 1:
                        # Some compatible endpoints ignore response_format and return
                        # a prose walkthrough. Use one dedicated repair pass instead
                        # of repeating the same request three times.
                        format_repair_attempted = True
                        request_system_prompt = (
                            f"{system_prompt}\n\nSTRICT RECOVERY: Your previous output was not valid JSON. "
                            "Return ONLY one JSON object matching the schema. Do not explain, reason, "
                            "use Markdown, or include any text before or after the JSON."
                        )
                        request_user_prompt = (
                            f"{user_prompt}\n\nIMPORTANT: Output only the required ReviewResult JSON object. "
                            'If there are no supported findings, return {"summary":"No supported findings.","findings":[]}.'
                        )
                        continue
                except AIAuthenticationError:
                    raise
                except AICostLimitError:
                    raise
                except Exception as exc:
                    # `asyncio.CancelledError` 是 BaseException，不会被这里接住：
                    # 取消必须一路抛给编排器（转成 `ReviewCancelled`），既不能变成
                    # `AIServiceError` 再重试，也不能被记成一次失败的模型调用。
                    last_error = self._map_service_error(exc)

                if attempt == self._config.max_retries - 1:
                    break
                await asyncio.sleep(self._config.retry_base_delay * (2**attempt))

            assert last_error is not None
            raise last_error
        finally:
            await self._release_cost(estimated_max_cost)

    def _review_reasoning_effort(self) -> str:
        """当前 review 思考档位（默认 ``off`` = 现状）。

        与 `jsonl_server._chat_reasoning_effort` 同一读法：非法值静默回退默认档，
        不在这里告警——配置层（`PreferencesConfig.__post_init__`）加载时已经告警过一次，
        每次审查再喊一遍只会刷屏。构造之后直接赋坏值也必须能跑（同 resolve_* 的口径）。
        """
        effort = getattr(self._config, "review_reasoning_effort", None)
        normalized = str(effort or DEFAULT_REVIEW_REASONING_EFFORT).strip().lower()
        return (
            normalized
            if normalized in REVIEW_REASONING_EFFORTS
            else DEFAULT_REVIEW_REASONING_EFFORT
        )

    def _review_reasoning_plan(
        self, base_max_tokens: int
    ) -> tuple[int, dict[str, Any], dict[str, Any]]:
        """按档位算出 (本轮 max_tokens, 直传 kwargs, extra_params)。

        规则（docs/DEV_RECORD.md §4.3 第二步）：

        - ``off``（默认）/ ``auto`` → 不注入、不预留：**完全维持现状**——deepseek 仍由
          policy 追加显式 `thinking: {"type": "disabled"}`（`review_policy.py`），
          anthropic / 多数兼容供应商依旧不发思考参数。`auto` 的语义就是"不干预，
          由 policy / 供应商默认决定"，因此与 `off` 在 wire 上同形。
        - 本地 ``ollama`` / ``local`` → 置灰（产品决策，与 chat 同口径），档位不生效。
        - unsupported / 未收录供应商 → 不注入、也不预留（不编造参数，同规格表口径）。
        - ``low`` / ``high`` / ``max`` → 查 `reasoning_specs` 规格表注入，并按 chat 口径
          （`CHAT_REASONING_TOKEN_BUDGETS`：+4000/+8000/+12000）给 `max_tokens` 预留思考
          额度，仍受模型规格 `max_output` 封顶（`_review_tokens_with_budget`）。

        真机依据：**只补 `reasoning_effort` 不开 `thinking` 是无效的**（reasoning 仍 0 字符），
        所以 low/high/max 必须同时覆盖 policy 的 `disabled`——规格表里 deepseek 那一条
        正是 `{"thinking": {"type": "enabled"}, "reasoning_effort": ...}`。

        **整档送不出去就不预留**：无论是因为官方区间放不下（`_clamp_budget` 返回空），
        还是因为协议不消费 kwargs（`api_format="anthropic"` 的中转端点，见
        `split_reasoning_params`），只要两路都是空的，就退回基础额度——预留一份送不出去的
        思考额度只会把额度白白丢给答案。
        """
        level = self._review_reasoning_effort()
        if level == "off" or level == "auto":
            return base_max_tokens, {}, {}
        provider_name = str(self._config.provider or "").strip()
        if provider_name.lower() in LOCAL_REVIEW_PROVIDER_NAMES:
            return base_max_tokens, {}, {}
        support = reasoning_support(provider_name)
        if not support.injects:
            return base_max_tokens, {}, {}

        reasoning_budget = CHAT_REASONING_TOKEN_BUDGETS.get(level, 0)
        max_tokens = self._review_tokens_with_budget(base_max_tokens, reasoning_budget)
        # 预算型供应商（anthropic/qwen/siliconflow）的预算字段要按官方约束收敛进
        # 最终额度，所以先定 max_tokens 再建参数；`answer_tokens` 用 review 自己的
        # 基础额度（= 答案应该占的份额），不是 `AIClientConfig.max_tokens` 那个
        # 兼容旧默认值的 4096。
        params = build_reasoning_params(
            provider_name,
            level,
            max_tokens=max_tokens,
            answer_tokens=base_max_tokens,
        )
        kwargs, extra_params = split_reasoning_params(
            params,
            provider_name=provider_name,
            api_format=self._config.api_format,
        )
        if not kwargs and not extra_params:
            return base_max_tokens, {}, {}
        return max_tokens, kwargs, extra_params

    def _review_tokens_with_budget(self, base_max_tokens: int, reasoning_budget: int) -> int:
        """把思考预留加进 review 的输出额度，并受模型规格 `max_output` 封顶。

        与 chat 的 `_chat_max_tokens` 同一思路：回答与思考**共用同一份 completion 额度**
        （docs/DEV_RECORD.md 的教训是预算是真的会顶满），因此总额度取
        `min(基础额度 + 预留, max_output)`；`max_output` 的来源见 `_review_max_output`。
        """
        requested = base_max_tokens + max(0, reasoning_budget)
        return max(1, min(requested, self._review_max_output()))

    def _review_max_output(self) -> int:
        """review 模型的输出上限（思考预留的封顶来源）。

        取舍与 chat 的 `_chat_max_output` 一致（"谁背书用谁的数字"）：**优先内置预设**
        `PROVIDER_MODEL_PRESETS`——仓库里唯一可引用的厂商数值，封顶只会降低请求额度、
        防的是云端按模型输出上限直接 400（`jsonl_server._chat_max_tokens` 的注释记录了
        同一个坑）。预设里没有这个模型时退回能力档案（deepseek 32_768 / anthropic
        8_192 / Ollama 1_024 / 其余 8_192）——那是我们自己的保守估计，至少不会比
        改动前的行为更激进。

        用户逐模型规格（配置助手写进 `provider.models[...]` 的值）**到不了这里**：
        `AIClientConfig` 只带 provider 名与模型名，这也正是 off 档基础额度一贯的口径
        （`calculate_review_output_budget` 同样按能力档案，不读用户规格）。
        """
        provider_key = str(self._config.provider or "").strip().lower()
        model_name = str(self._config.model or "").strip()
        preset = PROVIDER_MODEL_PRESETS.get(provider_key, {}).get(model_name)
        if preset is not None:
            return int(preset["max_output"])
        return get_model_capabilities(self._config.provider, self._config.model).max_output_tokens

    def _review_request_provider(
        self, kwargs: dict[str, Any], extra_params: dict[str, Any]
    ) -> tuple[Any, dict[str, Any]]:
        """返回 (本次请求用的 provider, 直传 kwargs)。

        - 两路拆分由 `reasoning_specs.split_reasoning_params` 唯一决定
          （`think`/`reasoning_effort` → OpenAI 兼容 provider 的 kwargs 白名单，
          `openai.py:386-388`；其余顶层参数 → `extra_params`，`openai.py:384` 与
          anthropic 的 `messages.create(**extra_params)` 都会原样并进请求体）。
        - `extra_params` **必须**落到配置对象上，但绝不能写进落盘配置、也不能改动
          `self._provider` 共享的那一份：同一个 `AIClient` 会被并发复用来审多个文件
          （`review_orchestrator` 只建一个客户端 + 并发 2），而混合编排还会按文件重建
          配置。因此这里按请求新建一份配置副本 + provider，请求结束即丢弃。
        """
        if not extra_params:
            return self._provider, kwargs
        provider_config = replace(
            self._provider_config,
            extra_params={**self._provider_config.extra_params, **extra_params},
        )
        return (
            create_model_provider(provider_config, client_factory=self._client_factory),
            kwargs,
        )

    async def _reserve_cost(self, estimated_cost: float) -> None:
        """Atomically reserve budget for a concurrent request."""
        async with self._budget_lock:
            if not self._budget_available(estimated_cost):
                self._enforce_cost_limits(estimated_cost)
            self._reserved_cost += estimated_cost

    async def _release_cost(self, estimated_cost: float) -> None:
        """Release a reservation without ever blocking on the budget lock.

        释放发生在取消路径的 `finally` 里：如果这里去等锁，取消（尤其是收尾期间
        的第二次取消）会把这次释放打断，额度永远留在 `_reserved_cost` 上，之后
        同一客户端的所有调用都会误以为预算已被占满。读改写过程没有 `await`，在
        单线程事件循环里本身就是原子的，不会与 `_reserve_cost` 的临界区交错。
        """
        self._reserved_cost = max(0.0, self._reserved_cost - estimated_cost)

    def _budget_available(self, estimated_cost: float) -> bool:
        run_total = self._cost_controller.get_total_cost() + self._reserved_cost + estimated_cost
        daily_total = self.total_cost_last_24h + self._reserved_cost + estimated_cost
        return (
            run_total <= self._config.max_cost_per_run
            and daily_total <= self._config.max_cost_per_24h
        )

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """估算 API 调用成本（美元）。"""
        return self._provider.estimate_cost(
            input_tokens,
            output_tokens,
            self._config.input_cost_per_million,
            self._config.output_cost_per_million,
        )

    @property
    def total_cost_last_24h(self) -> float:
        """最近 24 小时累计成本。"""
        return self._cost_controller.get_daily_cost()

    @property
    def reserved_cost(self) -> float:
        """Estimated budget currently reserved by in-flight requests."""
        return self._reserved_cost

    @property
    def total_run_cost(self) -> float:
        """当前运行累计成本。"""
        return self._cost_controller.get_total_cost()

    def _parse_review_result(self, response: Any) -> ReviewResult:
        text = self._extract_text_content(response)
        payload_text = self._extract_json_payload(text)

        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            excerpt = text.replace("\n", " ")[:240]
            raise AIResponseFormatError(
                f"AI 返回的 JSON 无法解析。模型原文片段：{excerpt}", original_error=exc
            ) from exc

        try:
            result = ReviewResult.model_validate(payload)
        except ValidationError as exc:
            raise AIResponseFormatError("AI 返回的 JSON 结构无效。", original_error=exc) from exc
        return self._normalize_model_findings(result)

    @staticmethod
    def _normalize_model_findings(result: ReviewResult) -> ReviewResult:
        """丢弃模型自述的服务端字段。

        来源、证据状态、finding_id 与规则身份都由确定性分析器 / 校验器填写，
        模型自述不得影响下游控制流（来源判定、中文本地化分支）。
        """
        if not result.findings:
            return result
        return result.model_copy(
            update={
                "findings": [
                    finding.model_copy(
                        update={
                            "sources": ["ai_analysis"],
                            "evidence": [],
                            "evidence_status": "unverified",
                            "evidence_issues": [],
                            "finding_id": "",
                            "rule_id": "",
                        }
                    )
                    for finding in result.findings
                ]
            }
        )

    def _extract_text_content(self, response: Any) -> str:
        if hasattr(response, "text"):
            text = getattr(response, "text", "")
            if text:
                return str(text).strip()
        content = getattr(response, "content", None)
        if not content:
            raise AIResponseFormatError("AI 响应缺少 content 文本块。")

        parts: list[str] = []
        for block in content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)

        if not parts:
            raise AIResponseFormatError("AI 响应中未找到可解析的文本内容。")
        return "\n".join(parts).strip()

    def _extract_json_payload(self, text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if len(lines) >= 3 and lines[-1].strip() == "```":
                stripped = "\n".join(lines[1:-1]).strip()
                if stripped.lower().startswith("json\n"):
                    stripped = stripped[5:].strip()

        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or start > end:
            raise AIResponseFormatError("AI 响应中未找到 JSON 对象。")
        return stripped[start : end + 1]

    def _record_usage(
        self,
        response: Any,
        fallback_input_tokens: int,
        reserved_cost: float = 0.0,
    ) -> None:
        input_tokens = getattr(response, "input_tokens", fallback_input_tokens)
        output_tokens = getattr(response, "output_tokens", 0)
        if input_tokens == fallback_input_tokens and output_tokens == 0:
            usage = getattr(response, "usage", None)
            input_tokens = getattr(usage, "input_tokens", fallback_input_tokens)
            output_tokens = getattr(usage, "output_tokens", 0)
        cost = self.estimate_cost(input_tokens, output_tokens)
        self._enforce_cost_limits(cost, excluded_reserved_cost=reserved_cost)
        self._cost_controller.record_usage(input_tokens, output_tokens, self._config.model)

    def _enforce_cost_limits(
        self,
        pending_cost: float,
        *,
        excluded_reserved_cost: float = 0.0,
    ) -> None:
        other_reserved_cost = max(0.0, self._reserved_cost - excluded_reserved_cost)
        projected_run_cost = (
            self._cost_controller.get_total_cost() + other_reserved_cost + pending_cost
        )
        projected_daily_cost = self.total_cost_last_24h + other_reserved_cost + pending_cost
        if projected_run_cost > self._config.max_cost_per_run:
            raise AICostLimitError(
                f"本次 AI 调用预计成本 ${pending_cost:.4f}，超过单次上限 ${self._config.max_cost_per_run:.2f}。"
            )

        if projected_daily_cost > self._config.max_cost_per_24h:
            raise AICostLimitError(
                f"最近 24 小时 AI 累计成本预计达到 ${projected_daily_cost:.4f}，超过上限 ${self._config.max_cost_per_24h:.2f}。"
            )

        if pending_cost > self._config.max_cost_per_run:
            raise AICostLimitError(
                f"本次 AI 调用预计成本 ${pending_cost:.4f}，超过单次上限 ${self._config.max_cost_per_run:.2f}。"
            )

    def _estimate_text_tokens(self, text: str) -> int:
        stripped = text.strip()
        if not stripped:
            return 0
        return max(1, len(stripped) // 4)

    def _map_service_error(self, exc: Exception) -> AIServiceError | AIAuthenticationError:
        status_code = getattr(exc, "status_code", None)
        if status_code == 401:
            return AIAuthenticationError("模型供应商 API 认证失败。", original_error=exc)
        return AIServiceError("AI 服务调用失败。", original_error=exc)
