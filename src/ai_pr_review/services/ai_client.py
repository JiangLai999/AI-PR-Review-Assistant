"""Unified AI client built on model providers."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from ai_pr_review.config import AIClientConfig, CostControllerConfig
from ai_pr_review.services.cost_controller import CostController, UsageRecord
from ai_pr_review.services.exceptions import (
    AIAuthenticationError,
    AICostLimitError,
    AIRequestTimeoutError,
    AIResponseFormatError,
    AIServiceError,
)
from ai_pr_review.services.model_providers.factory import create_model_provider
from ai_pr_review.services.prompt_assembler import ReviewResult

class AIClient:
    """调用模型供应商 API 并返回结构化审查结果。"""

    def __init__(
        self,
        config: AIClientConfig | None = None,
        client_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self._config = config or AIClientConfig()
        self._provider_config = self._config.model_provider
        self._api_key = self._provider_config.api_key

        if not self._api_key:
            raise AIAuthenticationError(
                "模型供应商 API Key 未提供。请设置对应环境变量或直接传入配置。"
            )

        self._provider = create_model_provider(self._provider_config, client_factory=client_factory)
        self._client = getattr(self._provider, "_client", self._provider)
        self._cost_controller = CostController(
            CostControllerConfig(
                run_limit=self._config.max_cost_per_run,
                daily_limit=self._config.max_cost_per_24h,
                input_cost_per_million=self._config.input_cost_per_million,
                output_cost_per_million=self._config.output_cost_per_million,
            )
        )
        self._usage_history = self._cost_controller._usage_history

    async def review_code(self, system_prompt: str, user_prompt: str) -> ReviewResult:
        """调用 AI 进行代码审查。"""
        estimated_input_tokens = self._estimate_text_tokens(system_prompt) + self._estimate_text_tokens(
            user_prompt
        )
        estimated_max_cost = self.estimate_cost(estimated_input_tokens, self._config.max_tokens)
        self._enforce_cost_limits(estimated_max_cost)

        last_error: Exception | None = None
        for attempt in range(self._config.max_retries):
            try:
                response = await asyncio.wait_for(
                    self._provider.chat(
                        [{"role": "user", "content": user_prompt}],
                        system_prompt=system_prompt,
                        max_tokens=self._config.max_tokens,
                        timeout_seconds=self._config.timeout_seconds,
                    ),
                    timeout=self._config.timeout_seconds,
                )

                result = self._parse_review_result(response)
                self._record_usage(response, fallback_input_tokens=estimated_input_tokens)
                return result
            except asyncio.TimeoutError as exc:
                last_error = AIRequestTimeoutError(
                    f"AI 请求超时（>{self._config.timeout_seconds}s）。", original_error=exc
                )
            except AIResponseFormatError as exc:
                last_error = exc
            except AIAuthenticationError:
                raise
            except AICostLimitError:
                raise
            except Exception as exc:
                last_error = self._map_service_error(exc)

            if attempt == self._config.max_retries - 1:
                break
            await asyncio.sleep(self._config.retry_base_delay * (2**attempt))

        assert last_error is not None
        raise last_error

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
    def total_run_cost(self) -> float:
        """当前运行累计成本。"""
        return self._cost_controller.get_total_cost()

    def _parse_review_result(self, response: Any) -> ReviewResult:
        text = self._extract_text_content(response)
        payload_text = self._extract_json_payload(text)

        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            raise AIResponseFormatError("AI 返回的 JSON 无法解析。", original_error=exc) from exc

        try:
            return ReviewResult.model_validate(payload)
        except ValidationError as exc:
            raise AIResponseFormatError("AI 返回的 JSON 结构无效。", original_error=exc) from exc

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

    def _record_usage(self, response: Any, fallback_input_tokens: int) -> None:
        input_tokens = getattr(response, "input_tokens", fallback_input_tokens)
        output_tokens = getattr(response, "output_tokens", 0)
        if input_tokens == fallback_input_tokens and output_tokens == 0:
            usage = getattr(response, "usage", None)
            input_tokens = getattr(usage, "input_tokens", fallback_input_tokens)
            output_tokens = getattr(usage, "output_tokens", 0)
        cost = self.estimate_cost(input_tokens, output_tokens)
        self._enforce_cost_limits(cost)
        self._cost_controller.record_usage(input_tokens, output_tokens, self._config.model)

    def _enforce_cost_limits(self, pending_cost: float) -> None:
        if not self._cost_controller.check_budget(pending_cost):
            if self._cost_controller.get_total_cost() + pending_cost > self._config.max_cost_per_run:
                raise AICostLimitError(
                    f"本次 AI 调用预计成本 ${pending_cost:.4f}，超过单次上限 ${self._config.max_cost_per_run:.2f}。"
                )

            rolling_total = self.total_cost_last_24h + pending_cost
            raise AICostLimitError(
                f"最近 24 小时 AI 累计成本预计达到 ${rolling_total:.4f}，超过上限 ${self._config.max_cost_per_24h:.2f}。"
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
