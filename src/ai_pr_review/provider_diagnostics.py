"""Provider 诊断辅助函数。

封装 provider 健康检查、模型发现和最小探测逻辑，避免 cli.py 继续膨胀。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from ai_pr_review.config import AppConfig, resolve_config_path
from ai_pr_review.services.model_providers.factory import create_model_provider


def build_provider_health_payload(
    config: AppConfig,
    *,
    config_path: Path | None,
    discovered_models: list[str] | None = None,
    probe_response: str | None = None,
) -> dict[str, Any]:
    provider = config.ai_client.model_provider
    payload: dict[str, Any] = {
        "config_path": str(resolve_config_path(config_path)),
        "provider": provider.name,
        "display_name": provider.display_name,
        "model": provider.model_name,
        "base_url": provider.base_url,
        "api_format": provider.api_format,
        "api_key_present": bool(provider.api_key),
    }
    if discovered_models is not None:
        payload["discovered_model_count"] = len(discovered_models)
        payload["discovered_models"] = discovered_models
    if probe_response is not None:
        payload["probe_ok"] = True
        payload["probe_response_excerpt"] = probe_response[:120]
    return payload


def build_model_discovery_fallback_message(config: AppConfig, exc: Exception) -> str:
    return (
        f"{exc}\n\n"
        "Fallback 建议：\n"
        "1. 先运行 `pr-review config health --discover-models` 检查当前 provider 是否支持远端模型发现。\n"
        "2. 如果服务商不支持 `/models`，请手动设置模型名："
        "`pr-review config model --name \"<模型ID>\"`。\n"
        f"3. 当前配置的模型是 `{config.ai_client.model}`；如果 chat 已提示 `Not supported model`，请改成服务商实际支持的模型 ID。"
    )


async def discover_remote_models(
    config: AppConfig,
    *,
    missing_api_key_message: Callable[[str], str],
) -> list[str]:
    provider_config = config.ai_client.model_provider
    if not provider_config.api_key:
        raise click.ClickException(missing_api_key_message(provider_config.name))
    provider = create_model_provider(provider_config)
    return await provider.list_models(timeout_seconds=config.ai_client.timeout_seconds)


async def probe_provider_connection(
    config: AppConfig,
    *,
    missing_api_key_message: Callable[[str], str],
) -> str:
    provider_config = config.ai_client.model_provider
    if not provider_config.api_key:
        raise click.ClickException(missing_api_key_message(provider_config.name))
    provider = create_model_provider(provider_config)
    response = await provider.chat(
        [{"role": "user", "content": "ping"}],
        system_prompt="Reply with a short connectivity confirmation.",
        max_tokens=16,
        timeout_seconds=config.ai_client.timeout_seconds,
    )
    return response.text
