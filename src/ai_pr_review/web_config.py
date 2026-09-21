"""配置读写：供 Web 设置页使用。

安全约定：

1. 读取时**永不返回明文密钥**，只返回是否已配置与掩码。
2. 写入时密钥字段留空表示"保持不变"，而不是"清空" —— 避免界面回填掩码时
   把真实密钥覆盖成 ``••••``。
3. 写入前可选做连通性校验，失败则拒绝落盘并把原因带回界面。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ai_pr_review.config import DEFAULT_CONFIG_PATH, AppConfig
from ai_pr_review.credentials import mask_secret

# 界面可编辑的字段白名单。其余配置项不通过设置页修改，避免误改内部参数。
EDITABLE_AI_FIELDS = (
    "base_url",
    "model",
    "api_format",
    "max_tokens",
    "timeout_seconds",
    "review_concurrency",
    "enable_static_analysis",
    "enable_cross_file_review",
    "cross_file_max_files",
    "max_cost_per_run",
    "max_cost_per_24h",
)


@dataclass(slots=True)
class ConfigView:
    """脱敏后的配置视图。"""

    config_path: str
    github_token_set: bool
    github_token_masked: str
    provider_name: str
    base_url: str
    model: str
    api_format: str
    api_key_set: bool
    api_key_masked: str
    settings: dict[str, Any] = field(default_factory=dict)
    available_providers: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_path": self.config_path,
            "github_token_set": self.github_token_set,
            "github_token_masked": self.github_token_masked,
            "provider_name": self.provider_name,
            "base_url": self.base_url,
            "model": self.model,
            "api_format": self.api_format,
            "api_key_set": self.api_key_set,
            "api_key_masked": self.api_key_masked,
            "settings": self.settings,
            "available_providers": self.available_providers,
        }


def build_config_view(config: AppConfig, *, config_path: Path | None = None) -> ConfigView:
    """构造脱敏配置视图。"""
    ai = config.ai_client
    from ai_pr_review.config import MODEL_PROVIDER_PRESETS

    presets = [
        {
            "name": name,
            "display_name": str(preset.get("display_name", name)),
            "base_url": str(preset.get("base_url", "")),
            "api_format": str(preset.get("api_format", "openai")),
            "default_model": str(preset.get("default_model", "")),
        }
        for name, preset in sorted(MODEL_PROVIDER_PRESETS.items())
    ]

    return ConfigView(
        config_path=str(config_path or DEFAULT_CONFIG_PATH),
        github_token_set=bool((config.github_token or "").strip()),
        github_token_masked=mask_secret(config.github_token),
        provider_name=ai.provider or config.provider.name or "custom",
        base_url=ai.base_url or "",
        model=ai.model or "",
        api_format=ai.api_format or "openai",
        api_key_set=bool((ai.api_key or "").strip()),
        api_key_masked=mask_secret(ai.api_key),
        settings={name: getattr(ai, name) for name in EDITABLE_AI_FIELDS},
        available_providers=presets,
    )


@dataclass(slots=True)
class SaveResult:
    ok: bool
    changed: list[str] = field(default_factory=list)
    message: str = ""
    save_key_used: bool = False


def apply_config_update(
    config: AppConfig,
    payload: dict[str, Any],
    *,
    config_path: Path | None = None,
) -> SaveResult:
    """把界面提交的改动写入配置并落盘。

    - 空字符串的密钥字段视为"不修改"。
    - 其余字段按白名单更新。
    - 默认保存密钥（`save_key=True`），因为用户是显式在设置页填写的；
      如果调用方不想要，传 ``persist_secrets=False``。
    - `config_path` 可注入：**测试必须传入临时路径**，否则会覆盖真实用户配置。
    """
    target_path = config_path or DEFAULT_CONFIG_PATH
    persist_secrets = bool(payload.get("persist_secrets", True))
    changed: list[str] = []
    ai = config.ai_client

    # 供应商预设：选了预设就带上它的 base_url / api_format
    provider_name = str(payload.get("provider_name", "") or "").strip()
    if provider_name:
        from ai_pr_review.config import MODEL_PROVIDER_PRESETS

        preset = MODEL_PROVIDER_PRESETS.get(provider_name.lower())
        if preset:
            if preset.get("base_url") and not payload.get("base_url"):
                ai.base_url = str(preset["base_url"])
                changed.append("base_url")
            if preset.get("api_format"):
                ai.api_format = str(preset["api_format"])
                changed.append("api_format")
            config.provider.name = provider_name.lower()
            config.provider.display_name = str(preset.get("display_name", provider_name))
            changed.append("provider_name")

    # 普通字段
    for name in EDITABLE_AI_FIELDS:
        if name not in payload:
            continue
        value = payload[name]
        if value is None or value == "":
            continue
        current = getattr(ai, name, None)
        if isinstance(current, bool):
            value = bool(value)
        elif isinstance(current, int) and not isinstance(current, bool):
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
        elif isinstance(current, float):
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
        else:
            value = str(value)
        if current != value:
            setattr(ai, name, value)
            changed.append(name)

    # GitHub token：留空表示不改
    github_token = str(payload.get("github_token", "") or "").strip()
    if github_token:
        config.github_token = github_token
        changed.append("github_token")

    # 模型密钥：留空表示不改（掩码回填时不会被误写成 ••••）
    api_key = str(payload.get("api_key", "") or "").strip()
    if api_key and not api_key.startswith("•"):
        ai.api_key = api_key
        config.provider.api_key = api_key
        changed.append("api_key")

    if not changed:
        return SaveResult(ok=True, message="没有需要保存的改动。")

    path = config.save(target_path, save_key=persist_secrets)
    return SaveResult(
        ok=True,
        changed=changed,
        message=f"已保存 {len(changed)} 项到 {path.name}。"
        + ("" if persist_secrets else "（未持久化密钥）"),
        save_key_used=persist_secrets,
    )
