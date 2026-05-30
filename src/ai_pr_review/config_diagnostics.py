"""Config 诊断辅助逻辑。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ai_pr_review.config import AppConfig, ConfigValidationError
from ai_pr_review.provider_diagnostics import (
    build_model_discovery_fallback_message,
    build_provider_health_payload,
    discover_remote_models,
    probe_provider_connection,
)
from ai_pr_review.services.exceptions import AIClientError


def validate_provider_for_test(
    config: AppConfig,
    *,
    missing_api_key_message: Callable[[str], str],
) -> None:
    provider = config.provider.to_model_provider()
    provider.validate()
    if not provider.api_key:
        raise ConfigValidationError(missing_api_key_message(provider.name))


def build_health_check_output(
    config: AppConfig,
    *,
    config_path: Path | None,
    discover_models_enabled: bool,
    probe_enabled: bool,
    missing_api_key_message: Callable[[str], str],
) -> dict[str, Any]:
    validate_provider_for_test(config, missing_api_key_message=missing_api_key_message)

    discovered_models: list[str] | None = None
    probe_response: str | None = None
    if discover_models_enabled:
        try:
            discovered_models = asyncio.run(
                discover_remote_models(config, missing_api_key_message=missing_api_key_message)
            )
        except AIClientError as exc:
            raise ConfigValidationError(str(exc)) from exc
    if probe_enabled:
        try:
            probe_response = asyncio.run(
                probe_provider_connection(config, missing_api_key_message=missing_api_key_message)
            )
        except AIClientError as exc:
            raise ConfigValidationError(f"Provider probe failed: {exc}") from exc

    return build_provider_health_payload(
        config,
        config_path=config_path,
        discovered_models=discovered_models,
        probe_response=probe_response,
    )


def resolve_model_discovery(
    config: AppConfig,
    *,
    model_name: str | None,
    set_first: bool,
    config_path: Path | None,
    missing_api_key_message: Callable[[str], str],
    save_key_checker: Callable[[Path | None], bool],
    set_active_model: Callable[[AppConfig, str], None],
) -> dict[str, Any]:
    try:
        models = asyncio.run(
            discover_remote_models(config, missing_api_key_message=missing_api_key_message)
        )
    except AIClientError as exc:
        raise ConfigValidationError(build_model_discovery_fallback_message(config, exc)) from exc

    if not models:
        raise ConfigValidationError("当前 provider 未返回可发现的模型列表，请手动设置模型名。")

    if model_name is not None:
        if model_name not in models:
            raise ConfigValidationError(f"远端模型列表中未找到：{model_name}")
        set_active_model(config, model_name)
        config.save(config_path, save_key=save_key_checker(config_path))
    elif set_first:
        set_active_model(config, models[0])
        config.save(config_path, save_key=save_key_checker(config_path))

    return {"models": models, "active_model": config.ai_client.model}
