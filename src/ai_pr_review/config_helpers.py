"""配置辅助函数。

封装项目配置模板生成和本地配置文件辅助逻辑，减少 cli.py 中的样板代码。
"""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

from ai_pr_review.config import (
    MODEL_PROVIDER_PRESETS,
    PROJECT_LOCAL_CONFIG_FILENAME,
    PreferencesConfig,
    ModelProviderConfig,
    ProviderConfig,
)


def provider_env_var(provider_name: str) -> str:
    return str(MODEL_PROVIDER_PRESETS.get(provider_name, {}).get("env_var", "AI_PR_REVIEW_API_KEY"))


def build_project_config_payload(
    provider_name: str,
    *,
    model_name: str | None = None,
    base_url: str | None = None,
    api_format: str | None = None,
) -> dict[str, Any]:
    provider = ModelProviderConfig.from_name(provider_name, api_key="")
    if model_name is not None:
        provider.model_name = model_name
    if base_url is not None:
        provider.base_url = base_url
    if api_format is not None:
        provider.api_format = api_format

    provider_config = ProviderConfig.from_model_provider(provider)
    provider_payload = provider_config.to_dict()
    provider_payload.pop("api_key", None)
    return {
        "provider": provider_payload,
        "preferences": asdict(PreferencesConfig()),
    }


def build_local_example_payload(provider_name: str) -> dict[str, Any]:
    return {
        "provider": {
            "api_key": "",
        },
        "_note": (
            f"Do not commit this file after copying it to {PROJECT_LOCAL_CONFIG_FILENAME}. "
            f"Recommended: set {provider_env_var(provider_name)} or AI_PR_REVIEW_API_KEY instead."
        ),
    }


def append_gitignore_entry(gitignore_path: Path, entry: str) -> bool:
    existing = gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else ""
    lines = {line.strip() for line in existing.splitlines()}
    if entry in lines:
        return False
    suffix = "" if not existing or existing.endswith("\n") else "\n"
    gitignore_path.write_text(f"{existing}{suffix}{entry}\n", encoding="utf-8")
    return True
