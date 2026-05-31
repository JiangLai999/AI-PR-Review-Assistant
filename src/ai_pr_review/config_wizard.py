"""Config 向导辅助函数。"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

import click
from rich.console import Console
from rich.prompt import Confirm

from ai_pr_review.config import (
    AIClientConfig,
    AppConfig,
    ModelProviderConfig,
    PreferencesConfig,
    ProviderConfig,
    ProviderModelConfig,
)


def json_prompt(text: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = click.prompt(
        text, default=json.dumps(default or {}, ensure_ascii=False), show_default=True
    )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"JSON 解析失败: {exc}") from exc
    if not isinstance(payload, dict):
        raise click.ClickException("JSON 输入必须是对象。")
    return payload


def apply_wizard_configuration(
    existing: AppConfig,
    *,
    final_provider: ModelProviderConfig,
    selected_model: ProviderModelConfig,
    github_token: str,
    preferences: PreferencesConfig,
) -> AppConfig:
    config = existing
    config.provider = ProviderConfig(
        name=final_provider.name,
        display_name=final_provider.display_name,
        api_key=final_provider.api_key,
        base_url=final_provider.base_url,
        api_format=final_provider.api_format,
        models={selected_model.name: selected_model},
        default_model=selected_model.name,
    )
    config.github_token = github_token
    config.preferences = preferences
    config.ai_client = AIClientConfig(
        **{
            **config.ai_client.__dict__,
            "provider": final_provider.name,
            "api_key": final_provider.api_key,
            "model": final_provider.model_name,
            "base_url": final_provider.base_url,
            "api_format": final_provider.api_format,
            "headers": final_provider.headers,
            "extra_params": final_provider.extra_params,
        }
    )
    config.pr_fetcher.github_token = github_token
    return config


def resolve_save_key_choice(console: Console, save_key: bool | None) -> bool:
    if save_key is None:
        return Confirm.ask(
            "是否保存 API Key 到配置文件？选择否时需通过环境变量提供 Key。",
            default=True,
            console=console,
        )
    if save_key:
        confirmed = Confirm.ask(
            "警告：API Key 将以明文形式保存到配置文件，是否继续？",
            default=True,
            console=console,
        )
        if not confirmed:
            raise click.Abort()
    return save_key
