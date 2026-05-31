"""Config 子命令入口辅助函数。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_pr_review.config import (
    AIClientConfig,
    AppConfig,
    PreferencesConfig,
    PROJECT_CONFIG_DIRNAME,
    PROJECT_CONFIG_FILENAME,
    PROJECT_LOCAL_CONFIG_FILENAME,
)
from ai_pr_review.config import ProviderConfig, _default_config_path
from ai_pr_review.config_helpers import (
    append_gitignore_entry,
    build_local_example_payload,
    build_project_config_payload,
    provider_env_var,
)


def build_config_show_output(
    config: AppConfig,
    *,
    config_path: Path | None,
    export_config_payload,
) -> str:
    return json.dumps(
        export_config_payload(config, config_path=config_path, mask_secrets=True),
        ensure_ascii=False,
        indent=2,
    )


def run_config_init(
    *,
    provider: str,
    model_name: str | None,
    base_url: str | None,
    api_format: str | None,
    directory: Path | None,
    force: bool,
    local_example: bool,
    update_gitignore: bool,
) -> tuple[Path, Path | None, Path | None, str]:
    directory = directory or Path.cwd()
    config_dir = directory / PROJECT_CONFIG_DIRNAME
    config_dir.mkdir(parents=True, exist_ok=True)

    config_path = config_dir / PROJECT_CONFIG_FILENAME
    if config_path.exists() and not force:
        raise ValueError(f"配置文件已存在：{config_path}。如需覆盖请使用 --force。")

    payload = build_project_config_payload(
        provider,
        model_name=model_name,
        base_url=base_url,
        api_format=api_format,
    )
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    example_path: Path | None = None
    if local_example:
        example_path = config_dir / f"{PROJECT_LOCAL_CONFIG_FILENAME}.example"
        if force or not example_path.exists():
            example_payload = build_local_example_payload(provider)
            example_path.write_text(
                json.dumps(example_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    gitignore_path: Path | None = None
    if update_gitignore:
        gitignore_path = directory / ".gitignore"
        ignored = f"{PROJECT_CONFIG_DIRNAME}/{PROJECT_LOCAL_CONFIG_FILENAME}"
        append_gitignore_entry(gitignore_path, ignored)

    return config_path, example_path, gitignore_path, provider_env_var(provider)


def run_config_export(
    output: Path,
    *,
    config: AppConfig,
    config_path: Path | None,
    include_secrets: bool,
    export_config_payload,
) -> Path:
    payload = export_config_payload(
        config, config_path=config_path, mask_secrets=not include_secrets
    )
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def run_config_import(
    input_path: Path,
    *,
    config: AppConfig,
    save_key: bool,
    config_path: Path | None,
) -> None:
    raw = json.loads(input_path.read_text(encoding="utf-8"))
    provider_payload = raw.get("provider")
    preferences_payload = raw.get("preferences", {})
    if not isinstance(provider_payload, dict):
        raise ValueError("导入失败：缺少 provider 配置对象。")

    provider = ProviderConfig.from_dict(provider_payload)
    provider.validate()
    config.provider = provider
    config.github_token = str(raw.get("github_token", ""))
    if isinstance(preferences_payload, dict):
        config.preferences = PreferencesConfig(**preferences_payload)
    model_provider = provider.to_model_provider()
    config.ai_client = AIClientConfig(
        **{
            **config.ai_client.__dict__,
            "provider": model_provider.name,
            "api_key": model_provider.api_key,
            "model": model_provider.model_name,
            "base_url": model_provider.base_url,
            "api_format": model_provider.api_format,
        }
    )
    config.pr_fetcher.github_token = config.github_token
    config.save(config_path, save_key=save_key)
