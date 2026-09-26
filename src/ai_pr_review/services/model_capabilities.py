"""Provider/model capability profiles used by review request policy."""

from __future__ import annotations

from dataclasses import dataclass

from ai_pr_review.services.reasoning_specs import reasoning_support


@dataclass(frozen=True, slots=True)
class ModelCapabilityProfile:
    provider: str
    model: str
    context_window: int = 32_768
    max_output_tokens: int = 8_192
    supports_json_object: bool = False
    supports_json_schema: bool = False
    supports_thinking_disable: bool = False
    reasoning_field: str | None = None
    api_style: str = "custom"

    @property
    def reasoning_form(self) -> str:
        """供应商的思考参数形态（`reasoning_specs` 是唯一数据源）。

        做成属性而不是新字段：档案对象的构造点（含测试）都不用改，且不会出现
        "档案里抄了一份参数形态、规格表里又一份"的漂移。
        """
        return reasoning_support(self.provider).form


def get_model_capabilities(provider: str, model: str) -> ModelCapabilityProfile:
    """Return conservative capabilities; provider adapters may refine these later."""
    provider_key = provider.lower().strip()
    model_key = model.lower().strip()
    if provider_key == "deepseek":
        return ModelCapabilityProfile(
            provider=provider_key,
            model=model,
            context_window=1_048_576,
            max_output_tokens=32_768,
            supports_json_object=True,
            supports_thinking_disable=True,
            reasoning_field="reasoning_content",
            api_style="openai",
        )
    if provider_key in {"ollama", "local"}:
        return ModelCapabilityProfile(
            provider=provider_key,
            model=model,
            context_window=8_192,
            max_output_tokens=1_024,
            supports_json_object=True,
            supports_json_schema=False,
            api_style="openai",
        )
    if provider_key in {"openai", "qwen", "zhipu", "moonshot", "siliconflow", "openrouter"}:
        return ModelCapabilityProfile(
            provider=provider_key,
            model=model,
            supports_json_object=True,
            supports_json_schema=provider_key == "openai",
            api_style="openai",
        )
    if provider_key == "anthropic":
        return ModelCapabilityProfile(
            provider=provider_key,
            model=model,
            context_window=200_000,
            max_output_tokens=8_192,
            reasoning_field="thinking",
            api_style="anthropic",
        )
    return ModelCapabilityProfile(provider=provider_key, model=model, api_style="custom")


def calculate_review_output_budget(
    provider: str, model: str, *, input_chars: int, cross_file: bool = False
) -> int:
    """Choose an output budget from task size without exceeding model policy."""
    profile = get_model_capabilities(provider, model)
    if provider.lower() == "deepseek":
        budget = 12_288 if cross_file else (8_192 if input_chars >= 12_000 else 6_144)
    elif cross_file:
        budget = 8_192
    else:
        budget = 6_144 if input_chars >= 12_000 else 4_096
    return min(budget, profile.max_output_tokens)
