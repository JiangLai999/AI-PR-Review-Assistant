"""Config 子命令实现辅助函数。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ai_pr_review.config import AppConfig
from ai_pr_review.config_diagnostics import (
    build_health_check_output,
    resolve_model_discovery,
    validate_provider_for_test,
)


def run_config_test(
    config: AppConfig,
    *,
    missing_api_key_message: Callable[[str], str],
) -> dict[str, Any]:
    validate_provider_for_test(config, missing_api_key_message=missing_api_key_message)
    provider = config.provider.to_model_provider()
    return {
        "provider": provider,
        "output_format": config.preferences.output_format,
        "risk_warning": provider.risk_warning,
    }


def run_config_health(
    config: AppConfig,
    *,
    config_path: Path | None,
    discover_models: bool,
    probe: bool,
    missing_api_key_message: Callable[[str], str],
) -> dict[str, Any]:
    return build_health_check_output(
        config,
        config_path=config_path,
        discover_models_enabled=discover_models,
        probe_enabled=probe,
        missing_api_key_message=missing_api_key_message,
    )


def run_config_model(
    config: AppConfig,
    *,
    config_path: Path | None,
    model_name: str,
    save_key_checker: Callable[[Path | None], bool],
    set_active_model: Callable[[AppConfig, str], None],
) -> str:
    set_active_model(config, model_name)
    config.save(config_path, save_key=save_key_checker(config_path))
    return model_name


def run_config_models(
    config: AppConfig,
    *,
    config_path: Path | None,
    model_name: str | None,
    set_first: bool,
    missing_api_key_message: Callable[[str], str],
    save_key_checker: Callable[[Path | None], bool],
    set_active_model: Callable[[AppConfig, str], None],
) -> dict[str, Any]:
    return resolve_model_discovery(
        config,
        model_name=model_name,
        set_first=set_first,
        config_path=config_path,
        missing_api_key_message=missing_api_key_message,
        save_key_checker=save_key_checker,
        set_active_model=set_active_model,
    )
