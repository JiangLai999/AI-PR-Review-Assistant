"""配置管理模块。

从环境变量和配置文件加载应用配置。
"""

from __future__ import annotations

import json
import os
import warnings
from collections.abc import Callable, Hashable
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from ai_pr_review.services.prompt_assembler import Finding


DEFAULT_FILTER_EXCLUDE_PATTERNS = [
    "tests/**",
    "**/tests/**",
    "test_*.py",
    "**/test_*.py",
    "**/test/**",
    "**/__test__/**",
    "**/*.test.*",
    "**/*.spec.*",
    "docs/**",
    "**/*.md",
    "**/*.rst",
    "**/.github/**",
    "**/CHANGELOG*",
    "**/LICENSE*",
    "**/*.json",
    "**/*.lock",
    "**/*.yml",
    "**/*.yaml",
]

# 环境变量：自定义配置文件路径
CONFIG_PATH_ENV_VAR = "AI_PR_REVIEW_CONFIG"
# 项目级配置目录名
PROJECT_CONFIG_DIRNAME = ".ai_pr_review"
# 项目级共享配置文件名（可提交到仓库）
PROJECT_CONFIG_FILENAME = "config.json"
# 项目本地私有配置文件名（不应提交，含 API Key 等敏感信息）
PROJECT_LOCAL_CONFIG_FILENAME = "config.local.json"
# 旧版默认配置路径（向后兼容）
LEGACY_DEFAULT_CONFIG_PATH = Path("~/.ai_pr_review/config.json").expanduser()


def _default_config_path() -> Path:
    """获取默认用户配置文件路径。

    Windows 下优先使用 %APPDATA%/ai-pr-review/config.json，
    其他平台使用 ~/.ai_pr_review/config.json。
    """
    appdata = os.getenv("APPDATA", "").strip()
    if os.name == "nt" and appdata:
        modern_path = Path(appdata) / "ai-pr-review" / "config.json"
        if modern_path.exists() or not LEGACY_DEFAULT_CONFIG_PATH.exists():
            return modern_path
    return LEGACY_DEFAULT_CONFIG_PATH


DEFAULT_CONFIG_PATH = _default_config_path()


def _default_result_store_path() -> Path:
    """Return a stable, writable per-user SQLite path."""
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if os.name == "nt" and local_app_data:
        return Path(local_app_data) / "ai-pr-review" / "results.db"
    xdg_data_home = os.getenv("XDG_DATA_HOME", "").strip()
    if xdg_data_home:
        return Path(xdg_data_home) / "ai-pr-review" / "results.db"
    return Path("~/.local/share/ai-pr-review/results.db").expanduser()


def resolve_config_path(path: Path | None = None) -> Path:
    """解析实际使用的配置文件路径。

    优先级：显式传入的 path > 环境变量 AI_PR_REVIEW_CONFIG > 默认路径。
    """
    if path is not None:
        return path
    override = os.getenv(CONFIG_PATH_ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser()
    return DEFAULT_CONFIG_PATH


def resolve_save_path(path: Path | None = None, *, source_path: Path | None = None) -> Path:
    """Resolve the highest-precedence writable config path.

    Loading is intentionally layered (user -> project shared -> project local),
    so saving personal settings back to the user config is not enough: a project
    shared file would keep shadowing them on the next load. When a project-level
    config exists, personal edits therefore go to the highest-precedence
    project-local file, which is private and gitignored by convention.
    """
    if path is not None:
        return path
    override = os.getenv(CONFIG_PATH_ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser()
    if source_path is not None:
        return Path(source_path).expanduser()
    try:
        default_is_authoritative = (
            DEFAULT_CONFIG_PATH.expanduser().resolve()
            == _default_config_path().expanduser().resolve()
        )
    except OSError:
        default_is_authoritative = False
    if default_is_authoritative:
        project_paths = project_config_paths()
        if any(project_path.exists() for project_path in project_paths):
            return project_paths[-1]
    return DEFAULT_CONFIG_PATH


def _find_project_root(start: Path | None = None) -> Path | None:
    """从指定目录向上查找包含 .git 的项目根目录。"""
    current = (start or Path.cwd()).resolve()
    while True:
        if (current / ".git").exists():
            return current
        if current.parent == current:
            return None
        current = current.parent


def project_config_paths(start: Path | None = None) -> list[Path]:
    """获取项目级配置文件路径列表。

    返回项目根目录下的 .ai_pr_review/config.json 和 config.local.json。
    如果不在 git 仓库中，返回空列表。
    """
    root = _find_project_root(start)
    if root is None:
        return []
    config_dir = root / PROJECT_CONFIG_DIRNAME
    return [
        config_dir / PROJECT_CONFIG_FILENAME,
        config_dir / PROJECT_LOCAL_CONFIG_FILENAME,
    ]


def active_config_paths(path: Path | None = None) -> list[Path]:
    """获取所有生效的配置文件路径。

    加载顺序（后者覆盖前者）：
    1. 用户级配置文件
    2. 项目级 .ai_pr_review/config.json
    3. 项目本地 .ai_pr_review/config.local.json
    """
    user_config_path = resolve_config_path(path)
    if path is not None:
        return [user_config_path]
    project_paths = project_config_paths()
    if user_config_path == _default_config_path():
        return [user_config_path, *project_paths]
    # Test/portable overrides should not accidentally inherit the repository's
    # own project config. Keep project overlays only when the overridden config
    # root owns the current project (the explicit project-isolation case).
    project_root = _find_project_root()
    if project_root is not None and user_config_path.parent in project_root.parents:
        return [user_config_path, *project_paths]
    return [user_config_path]


def _deep_merge_dicts(base: dict[str, object], override: dict[str, object]) -> dict[str, object]:
    """深度合并两个字典，override 中的值覆盖 base 中的同名键。"""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dicts(merged[key], value)
            continue
        merged[key] = value
    return merged


def mask_api_key(api_key: str) -> str:
    """对 API Key 进行脱敏处理，用于安全显示。

    示例：sk-ant-abc123 -> sk-ant-***123
    """
    if not api_key:
        return ""

    prefix_end = api_key.find("-") + 1 if "-" in api_key else min(2, len(api_key))
    prefix = api_key[:prefix_end]
    suffix = api_key[-4:] if len(api_key) > 4 else api_key[-1:]

    if len(api_key) <= prefix_end + len(suffix):
        return f"{prefix}***"
    return f"{prefix}***{suffix}"


class ConfigValidationError(ValueError):
    """配置校验错误，当配置文件或运行时配置无效时抛出。"""


MODEL_PROVIDER_PRESETS: dict[str, dict[str, object]] = {
    "anthropic": {
        "display_name": "Anthropic",
        "base_url": "https://api.anthropic.com",
        "model_name": "claude-sonnet-4-20250514",
        "api_format": "anthropic",
        "env_var": "ANTHROPIC_API_KEY",
    },
    "openai": {
        "display_name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model_name": "gpt-4o-mini",
        "api_format": "openai",
        "env_var": "OPENAI_API_KEY",
    },
    "ollama": {
        "display_name": "Ollama (Local)",
        "base_url": "http://127.0.0.1:11434/v1",
        "model_name": "qwen3.5:4b",
        "api_format": "openai",
        "env_var": "",
    },
    "deepseek": {
        "display_name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model_name": "deepseek-chat",
        "api_format": "openai",
        "env_var": "DEEPSEEK_API_KEY",
    },
    "qwen": {
        "display_name": "Qwen",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model_name": "qwen-plus",
        "api_format": "openai",
        "env_var": "DASHSCOPE_API_KEY",
    },
    "siliconflow": {
        "display_name": "SiliconFlow",
        "base_url": "https://api.siliconflow.cn/v1",
        "model_name": "deepseek-ai/DeepSeek-V3",
        "api_format": "openai",
        "env_var": "SILICONFLOW_API_KEY",
    },
    "moonshot": {
        "display_name": "Moonshot AI",
        "base_url": "https://api.moonshot.cn/v1",
        "model_name": "moonshot-v1-8k",
        "api_format": "openai",
        "env_var": "MOONSHOT_API_KEY",
    },
    "zhipu": {
        "display_name": "Zhipu AI",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model_name": "glm-4-flash",
        "api_format": "openai",
        "env_var": "ZHIPUAI_API_KEY",
    },
    "baichuan": {
        "display_name": "Baichuan AI",
        "base_url": "https://api.baichuan-ai.com/v1",
        "model_name": "Baichuan4",
        "api_format": "openai",
        "env_var": "BAICHUAN_API_KEY",
    },
    "minimax": {
        "display_name": "MiniMax",
        "base_url": "https://api.minimax.chat/v1",
        "model_name": "MiniMax-Text-01",
        "api_format": "openai",
        "env_var": "MINIMAX_API_KEY",
    },
    "stepfun": {
        "display_name": "StepFun",
        "base_url": "https://api.stepfun.com/v1",
        "model_name": "step-2-16k",
        "api_format": "openai",
        "env_var": "STEPFUN_API_KEY",
    },
    "doubao": {
        "display_name": "Doubao Ark",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model_name": "doubao-seed-1-6-250615",
        "api_format": "openai",
        "env_var": "ARK_API_KEY",
    },
    "hunyuan": {
        "display_name": "Tencent Hunyuan",
        "base_url": "https://api.hunyuan.cloud.tencent.com/v1",
        "model_name": "hunyuan-turbos-latest",
        "api_format": "openai",
        "env_var": "HUNYUAN_API_KEY",
    },
    "yi": {
        "display_name": "01.AI Yi",
        "base_url": "https://api.lingyiwanwu.com/v1",
        "model_name": "yi-lightning",
        "api_format": "openai",
        "env_var": "YI_API_KEY",
    },
    "openrouter": {
        "display_name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model_name": "openai/gpt-4o-mini",
        "api_format": "openai",
        "env_var": "OPENROUTER_API_KEY",
    },
    "api2d": {
        "display_name": "API2D",
        "base_url": "https://openai.api2d.net/v1",
        "model_name": "gpt-4o-mini",
        "api_format": "openai",
        "env_var": "API2D_API_KEY",
    },
    "closeai": {
        "display_name": "CloseAI",
        "base_url": "https://api.closeai-proxy.xyz/v1",
        "model_name": "gpt-4o-mini",
        "api_format": "openai",
        "env_var": "CLOSEAI_API_KEY",
    },
    "ohmygpt": {
        "display_name": "OhMyGPT",
        "base_url": "https://api.ohmygpt.com/v1",
        "model_name": "gpt-4o-mini",
        "api_format": "openai",
        "env_var": "OHMYGPT_API_KEY",
    },
    "custom": {
        "display_name": "Custom Endpoint",
        "base_url": "",
        "model_name": "custom-model",
        "api_format": "openai",
        "env_var": "MODEL_PROVIDER_API_KEY",
    },
}


def _build_models(*models: tuple[str, int, int]) -> dict[str, dict[str, int | str]]:
    return {
        name: {
            "name": name,
            "context_window": context_window,
            "max_output": max_output,
        }
        for name, context_window, max_output in models
    }


PROVIDER_MODEL_PRESETS: dict[str, dict[str, dict[str, int | str]]] = {
    "anthropic": _build_models(
        ("claude-sonnet-4-20250514", 200_000, 8_192),
        ("claude-opus-4-20250514", 200_000, 8_192),
    ),
    "openai": _build_models(
        ("gpt-4o-mini", 128_000, 16_384),
        ("gpt-4.1", 128_000, 16_384),
    ),
    "ollama": _build_models(
        ("qwen3.5:4b", 8_192, 1_024),
        ("qwen3:4b", 8_192, 1_024),
        ("phi4-mini", 8_192, 1_024),
        ("gemma3:4b", 8_192, 1_024),
        ("qwen2.5-coder:3b", 8_192, 1_024),
    ),
    "deepseek": _build_models(
        ("deepseek-flash", 1_048_576, 384_000),
        ("deepseek-v4-pro", 1_048_576, 128_000),
    ),
    "qwen": _build_models(
        ("qwen-plus", 131_072, 8_192),
        ("qwen-max", 32_768, 8_192),
        ("qwen-coder-plus", 131_072, 8_192),
    ),
    "siliconflow": _build_models(
        ("deepseek-ai/DeepSeek-V3", 65_536, 8_192),
        ("deepseek-ai/DeepSeek-R1", 65_536, 8_192),
        ("Qwen/Qwen3-Coder-480B-A35B-Instruct", 262_144, 8_192),
        ("Qwen/Qwen3-235B-A22B-Instruct-2507", 262_144, 8_192),
    ),
    "moonshot": _build_models(
        ("moonshot-v1-8k", 8_192, 4_096),
        ("moonshot-v1-32k", 32_768, 4_096),
        ("moonshot-v1-128k", 131_072, 4_096),
        ("kimi-k2-0711-preview", 131_072, 8_192),
    ),
    "zhipu": _build_models(
        ("glm-4-flash", 128_000, 4_096),
        ("glm-4-plus", 128_000, 4_096),
        ("glm-4-air", 128_000, 4_096),
    ),
    "baichuan": _build_models(
        ("Baichuan4", 32_768, 4_096),
        ("Baichuan3-Turbo", 32_768, 4_096),
    ),
    "minimax": _build_models(
        ("MiniMax-Text-01", 1_000_000, 8_192),
        ("abab6.5s-chat", 245_760, 8_192),
    ),
    "stepfun": _build_models(
        ("step-2-16k", 16_384, 4_096),
        ("step-1-256k", 262_144, 4_096),
    ),
    "doubao": _build_models(
        ("doubao-seed-1-6-250615", 256_000, 8_192),
        ("doubao-1-5-pro-32k-250115", 32_768, 8_192),
    ),
    "hunyuan": _build_models(
        ("hunyuan-turbos-latest", 256_000, 8_192),
        ("hunyuan-large", 32_768, 4_096),
    ),
    "yi": _build_models(
        ("yi-lightning", 16_384, 4_096),
        ("yi-large", 32_768, 4_096),
    ),
    "openrouter": _build_models(
        ("openai/gpt-4o-mini", 128_000, 16_384),
        ("anthropic/claude-3.5-sonnet", 200_000, 8_192),
    ),
    "api2d": _build_models(("gpt-4o-mini", 128_000, 16_384)),
    "closeai": _build_models(("gpt-4o-mini", 128_000, 16_384)),
    "ohmygpt": _build_models(("gpt-4o-mini", 128_000, 16_384)),
    "custom": _build_models(("custom-model", 32_768, 4_096)),
}


@dataclass
class ModelProviderConfig:
    """Unified model provider configuration."""

    name: str = "anthropic"
    display_name: str = "Anthropic"
    api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    base_url: str = "https://api.anthropic.com"
    model_name: str = "claude-sonnet-4-20250514"
    api_format: str = "anthropic"
    headers: dict[str, str] = field(default_factory=dict)
    extra_params: dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_name(cls, name: str, **overrides: object) -> "ModelProviderConfig":
        preset = MODEL_PROVIDER_PRESETS.get(name.lower())
        if preset is None:
            raise ConfigValidationError(f"不支持的模型供应商: {name}")
        env_var = str(preset.get("env_var", ""))
        payload = {**preset, "name": name.lower(), "api_key": os.getenv(env_var, "")}
        payload.update(overrides)
        payload.pop("env_var", None)
        return cls(**payload)

    def validate(self) -> None:
        if not self.name.strip():
            raise ConfigValidationError("模型供应商名称不能为空。")
        if not self.model_name.strip():
            raise ConfigValidationError("模型名称不能为空。")
        if self.api_format not in {"anthropic", "openai", "custom"}:
            raise ConfigValidationError("api_format 仅支持 anthropic、openai 或 custom。")
        if self.api_format != "anthropic" and not self.base_url.strip():
            raise ConfigValidationError("OpenAI 兼容或自定义接口必须配置 base_url。")
        if self.base_url.strip():
            parsed = urlparse(self.base_url)
            is_local_endpoint = self.name.lower() in {"ollama", "local"} and parsed.hostname in {
                "127.0.0.1",
                "localhost",
                "::1",
            }
            if parsed.scheme.lower() != "https" and not is_local_endpoint:
                raise ConfigValidationError(
                    "base_url 必须使用 HTTPS；本地 Ollama 仅允许回环地址使用 HTTP。"
                )
        if not isinstance(self.headers, dict) or not isinstance(self.extra_params, dict):
            raise ConfigValidationError("headers 和 extra_params 必须为对象。")

    @property
    def risk_warning(self) -> str | None:
        if self.name.lower() == "custom" or self.api_format == "custom":
            return "Warning: custom provider may route code through an untrusted endpoint. Verify data handling before use."
        return None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class ProviderModelConfig:
    """Persisted model metadata for provider configuration."""

    name: str
    context_window: int = 32_768
    max_output: int = 4_096


@dataclass
class ProviderConfig:
    """Top-level persisted provider configuration."""

    name: str = "deepseek"
    display_name: str = "DeepSeek"
    api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))
    base_url: str = "https://api.deepseek.com/v1"
    api_format: str = "openai"
    models: dict[str, ProviderModelConfig] = field(
        default_factory=lambda: {
            name: ProviderModelConfig(**payload)
            for name, payload in PROVIDER_MODEL_PRESETS["deepseek"].items()
        }
    )
    default_model: str = "deepseek-chat"

    @classmethod
    def from_model_provider(cls, provider: ModelProviderConfig) -> "ProviderConfig":
        models = PROVIDER_MODEL_PRESETS.get(provider.name, {})
        if provider.model_name not in models:
            models = {
                **models,
                provider.model_name: {
                    "name": provider.model_name,
                    "context_window": 32_768,
                    "max_output": 4_096,
                },
            }
        return cls(
            name=provider.name,
            display_name=provider.display_name,
            api_key=provider.api_key,
            base_url=provider.base_url,
            api_format=provider.api_format,
            models={name: ProviderModelConfig(**payload) for name, payload in models.items()},
            default_model=provider.model_name,
        )

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ProviderConfig":
        payload = dict(data)
        raw_models = payload.get("models")
        if isinstance(raw_models, dict):
            payload["models"] = {
                str(name): ProviderModelConfig(**model_data)
                for name, model_data in raw_models.items()
                if isinstance(model_data, dict)
            }
        config = cls(**payload)
        config.ensure_default_model_present()
        return config

    def ensure_default_model_present(self) -> None:
        if not self.models:
            self.models = {
                self.default_model: ProviderModelConfig(name=self.default_model),
            }
        if self.default_model not in self.models:
            self.models[self.default_model] = ProviderModelConfig(name=self.default_model)

    def validate(self) -> None:
        provider = self.to_model_provider()
        provider.validate()
        self.ensure_default_model_present()

    def to_model_provider(self) -> ModelProviderConfig:
        self.ensure_default_model_present()
        return ModelProviderConfig(
            name=self.name,
            display_name=self.display_name,
            api_key=self.api_key,
            base_url=self.base_url,
            model_name=self.default_model,
            api_format=self.api_format,
        )

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["models"] = {
            name: asdict(model_config) for name, model_config in self.models.items()
        }
        return payload


# 审查工作台显示模式（preferences.workbench_mode）：
# auto=审查开始时自动展开（Alt+W 可收起）；always=工作台常驻；off=仅 Alt+W 手动打开。
WORKBENCH_MODES: tuple[str, ...] = ("auto", "always", "off")
DEFAULT_WORKBENCH_MODE = "auto"

CHAT_REASONING_EFFORTS: tuple[str, ...] = ("off", "low", "high", "max", "auto")
DEFAULT_CHAT_REASONING_EFFORT = "auto"
DEFAULT_CHAT_CONTEXT_BUDGET = 8000


def normalize_workbench_mode(value: object) -> str:
    """把任意输入归一化为合法的 ``workbench_mode``。

    旧版本写出的配置没有这个字段，手改配置也可能写错值，两种情况都必须能加载，
    因此非法值只回退到 ``auto`` 并记录一次 warning，不抛异常。提示里不回显原值：
    配置内容可能含终端控制字符或误粘贴的密钥。
    """
    normalized = str(value or "").strip().lower()
    if normalized in WORKBENCH_MODES:
        return normalized
    warnings.warn(
        "配置项 preferences.workbench_mode 的值不受支持，已回退为 auto"
        "（可选值：auto、always、off）。",
        RuntimeWarning,
        stacklevel=2,
    )
    return DEFAULT_WORKBENCH_MODE


# CHAT/REVIEW 双槽路由（docs/dual-model-roles-plan.md §3）。
# 两个槽都是**可选覆盖**：`""` 表示"跟随运行模式预设"（即按 hybrid_strategy 推导），
# 因此旧配置文件不需要任何改动就能加载。
CHAT_SLOT_VALUES: tuple[str, ...] = ("remote", "local")
REVIEW_SLOT_VALUES: tuple[str, ...] = ("remote", "local", "hybrid")
DEFAULT_CHAT_SLOT = ""
DEFAULT_REVIEW_SLOT = ""
# 显式 review_slot -> 派生的 hybrid_strategy（方案 §3.2）。
REVIEW_SLOT_TO_STRATEGY: dict[str, str] = {
    "remote": "remote_only",
    "local": "local_only",
    "hybrid": "balanced",
}
# 旧配置方向：hybrid_strategy -> 推导出的 review_slot（方案 §3.4）。
REVIEW_STRATEGY_TO_SLOT: dict[str, str] = {
    "remote_only": "remote",
    "local_only": "local",
    "balanced": "hybrid",
}

# 仓库感知审查的偏好项（docs/repo-aware-review-plan.md §4.6）。
REPO_CONTEXT_MODES: tuple[str, ...] = ("off", "tests", "tests+imports")
DEFAULT_REPO_CONTEXT = "tests+imports"
DEFAULT_REPO_CONTEXT_MAX_FILES = 3
DEFAULT_REPO_CONTEXT_BUDGET_TOKENS = 4000
DEFAULT_REPO_CACHE_MAX_MB = 200
# L2 符号级定位开关（docs/mimo-l2-symbol-locator.md）：默认开启，
# 仅在签名变化时触发 trees+grep，异常一律降级。
DEFAULT_SYMBOL_LOCATE = True
# L3 修复建议 patch 开关（docs/repo-aware-review-plan.md §6）：**默认关闭**。
# 打开后每条 critical/high 且证据校验通过的 finding 都会额外发起一次模型调用
# （真实成本），因此只有用户明确开启才跑；关闭时零构造、零调用。
DEFAULT_SUGGESTED_PATCH = False
# 模型目录自动同步开关（docs/chat-experience-plan.md §B2）：配置助手打开时可
# 拉一次 models.dev；chat/review 等高频路径不触发网络请求。
DEFAULT_MODEL_CATALOG_FETCH = True
# 合法闭区间（含端点）；越界一律回退默认值。
REPO_CONTEXT_MAX_FILES_RANGE: tuple[int, int] = (1, 10)
REPO_CONTEXT_BUDGET_TOKENS_RANGE: tuple[int, int] = (500, 32000)
REPO_CACHE_MAX_MB_RANGE: tuple[int, int] = (10, 10000)


def _warn_invalid_preference(field: str, detail: str) -> None:
    """非法偏好值的统一告警。

    与 ``normalize_workbench_mode`` 同风格：只回退 + 告警，绝不抛异常
    （配置坏了也要能进 ``pr-review config`` 去修）。提示里不回显原值：
    配置内容可能含终端控制字符或误粘贴的密钥。
    """
    warnings.warn(
        f"配置项 preferences.{field} 的值不受支持，{detail}。",
        RuntimeWarning,
        stacklevel=3,
    )


def normalize_chat_slot(value: object) -> str:
    """把任意输入归一化为合法的 ``chat_slot``。

    空串（含缺失、``None``）**不是**非法值：它的语义就是"跟随运行模式预设"，
    与非法值回退后的结果一致，因此不告警。
    """
    normalized = str(value or "").strip().lower()
    if not normalized:
        return DEFAULT_CHAT_SLOT
    if normalized in CHAT_SLOT_VALUES:
        return normalized
    _warn_invalid_preference(
        "chat_slot", "已回退为跟随运行模式预设（可选值：remote、local，或留空）"
    )
    return DEFAULT_CHAT_SLOT


def normalize_review_slot(value: object) -> str:
    """把任意输入归一化为合法的 ``review_slot``（"hybrid" 仅审查侧可填）。"""
    normalized = str(value or "").strip().lower()
    if not normalized:
        return DEFAULT_REVIEW_SLOT
    if normalized in REVIEW_SLOT_VALUES:
        return normalized
    _warn_invalid_preference(
        "review_slot", "已回退为跟随运行模式预设（可选值：remote、local、hybrid，或留空）"
    )
    return DEFAULT_REVIEW_SLOT


def normalize_repo_context(value: object) -> str:
    """把任意输入归一化为合法的 ``repo_context``（仓库上下文预取范围）。"""
    normalized = str(value or "").strip().lower()
    if normalized in REPO_CONTEXT_MODES:
        return normalized
    _warn_invalid_preference(
        "repo_context", "已回退为 tests+imports（可选值：off、tests、tests+imports）"
    )
    return DEFAULT_REPO_CONTEXT


def _normalize_bounded_int(
    value: object, *, field: str, default: int, bounds: tuple[int, int]
) -> int:
    """把任意输入归一化为 ``bounds`` 闭区间内的整数，否则回退 ``default``。"""
    minimum, maximum = bounds
    candidate: int | None
    if isinstance(value, bool):
        # bool 是 int 的子类：True 会被当成 1 通过范围检查，但"最大文件数 = True"
        # 不是用户能表达的意思，按非法值处理比静默当 1 更安全。
        candidate = None
    elif isinstance(value, int):
        candidate = value
    elif isinstance(value, float) and value.is_integer():
        # JSON 里的 3.0 与 3 等价，不该因此触发一次回退告警。
        candidate = int(value)
    elif isinstance(value, str) and value.strip():
        try:
            candidate = int(value.strip())
        except ValueError:
            candidate = None
    else:
        candidate = None
    if candidate is None or not minimum <= candidate <= maximum:
        _warn_invalid_preference(field, f"已回退为 {default}（允许范围：{minimum}..{maximum}）")
        return default
    return candidate


def normalize_repo_context_max_files(value: object) -> int:
    """每个变更文件最多预取几个相关仓库文件（1..10）。"""
    return _normalize_bounded_int(
        value,
        field="repo_context_max_files",
        default=DEFAULT_REPO_CONTEXT_MAX_FILES,
        bounds=REPO_CONTEXT_MAX_FILES_RANGE,
    )


def normalize_repo_context_budget_tokens(value: object) -> int:
    """每个变更文件的相关文件总 token 预算（500..32000）。"""
    return _normalize_bounded_int(
        value,
        field="repo_context_budget_tokens",
        default=DEFAULT_REPO_CONTEXT_BUDGET_TOKENS,
        bounds=REPO_CONTEXT_BUDGET_TOKENS_RANGE,
    )


def normalize_repo_cache_max_mb(value: object) -> int:
    """仓库文件缓存目录的容量上限，单位 MB（10..10000）。"""
    return _normalize_bounded_int(
        value,
        field="repo_cache_max_mb",
        default=DEFAULT_REPO_CACHE_MAX_MB,
        bounds=REPO_CACHE_MAX_MB_RANGE,
    )


def normalize_symbol_locate(value: object) -> bool:
    """把任意输入归一化为合法的 ``symbol_locate`` 开关。

    旧配置没有这个字段时保持默认开启；手改配置可能写成字符串或数字，
    非法值只回退到 ``True`` 并记录一次 warning，不抛异常（与
    ``normalize_workbench_mode`` 同风格）。提示里不回显原值。
    """
    return _normalize_bool_preference(
        value, field="symbol_locate", default=DEFAULT_SYMBOL_LOCATE
    )


def normalize_suggested_patch(value: object) -> bool:
    """把任意输入归一化为合法的 ``suggested_patch`` 开关（L3 修复建议）。

    与 ``normalize_symbol_locate`` 同一套规则，但默认值是 **False**：旧配置没有
    这个字段时保持关闭（开启会为达标 finding 增加模型调用），非法值只回退到
    ``False`` 并记录一次 warning，不抛异常。提示里不回显原值。
    """
    return _normalize_bool_preference(
        value, field="suggested_patch", default=DEFAULT_SUGGESTED_PATCH
    )


def normalize_model_catalog_fetch(value: object) -> bool:
    """把任意输入归一化为合法的 ``model_catalog_fetch`` 开关。"""
    return _normalize_bool_preference(
        value, field="model_catalog_fetch", default=DEFAULT_MODEL_CATALOG_FETCH
    )


def normalize_chat_reasoning_effort(value: object) -> str:
    """把任意输入归一化为合法的 ``chat_reasoning_effort``，否则回退 auto。"""
    normalized = str(value or "").strip().lower()
    if normalized in CHAT_REASONING_EFFORTS:
        return normalized
    _warn_invalid_preference(
        "chat_reasoning_effort",
        "已回退为 auto（可选值：off、low、high、max、auto）",
    )
    return DEFAULT_CHAT_REASONING_EFFORT


def _normalize_bool_preference(value: object, *, field: str, default: bool) -> bool:
    """布尔偏好项的统一归一化：bool / 0-1 / "true|yes|on" 等字面量，其余回退。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    _warn_invalid_preference(
        field, f"已回退为 {'true' if default else 'false'}（可选值：true、false）"
    )
    return default


@dataclass
class PreferencesConfig:
    """User-facing CLI preferences."""

    output_format: str = "terminal"
    language: str = "zh-CN"
    ui_language: str = "zh-CN"
    chat_layout: str = "compact"
    auto_publish_comment: bool = False
    hybrid_strategy: str = "balanced"  # 新增：双模型协作策略
    max_cost_per_review: float = 0.50  # 新增：单次审查最大成本
    workbench_mode: str = DEFAULT_WORKBENCH_MODE  # 审查工作台显示模式
    # CHAT/REVIEW 双槽路由：空 = 跟随运行模式预设（由 resolve_* 推导）。
    chat_slot: str = DEFAULT_CHAT_SLOT
    review_slot: str = DEFAULT_REVIEW_SLOT
    # 仓库感知审查：预取范围 + 上限（见 docs/repo-aware-review-plan.md §4.6）。
    repo_context: str = DEFAULT_REPO_CONTEXT
    repo_context_max_files: int = DEFAULT_REPO_CONTEXT_MAX_FILES
    repo_context_budget_tokens: int = DEFAULT_REPO_CONTEXT_BUDGET_TOKENS
    repo_cache_max_mb: int = DEFAULT_REPO_CACHE_MAX_MB
    # L2 符号定位：签名变化时在仓库内定位外部引用点（trees+grep）。
    symbol_locate: bool = DEFAULT_SYMBOL_LOCATE
    # L3 修复建议 patch：为 critical/high 且证据校验通过的 finding 生成 unified
    # diff 片段（每条多一次模型调用），默认关闭；只展示、绝不自动提交。
    suggested_patch: bool = DEFAULT_SUGGESTED_PATCH
    # 模型目录：配置助手打开时可同步一次 models.dev；断网/关闭时回退内置预设。
    model_catalog_fetch: bool = DEFAULT_MODEL_CATALOG_FETCH
    # Chat 思考档位与上下文预算（docs/chat-experience-plan.md §A5/§C6）。
    chat_reasoning_effort: str = DEFAULT_CHAT_REASONING_EFFORT
    chat_context_budget: int = DEFAULT_CHAT_CONTEXT_BUDGET

    def __post_init__(self) -> None:
        # 属性一旦构造出来就保证合法，加载/导入/向导三条路径因此共用同一套回退规则。
        # （resolve_* 仍会对"构造之后直接赋值"的坏值兜底，见 resolve_chat_slot。）
        self.workbench_mode = normalize_workbench_mode(self.workbench_mode)
        self.chat_slot = normalize_chat_slot(self.chat_slot)
        self.review_slot = normalize_review_slot(self.review_slot)
        self.repo_context = normalize_repo_context(self.repo_context)
        self.repo_context_max_files = normalize_repo_context_max_files(
            self.repo_context_max_files
        )
        self.repo_context_budget_tokens = normalize_repo_context_budget_tokens(
            self.repo_context_budget_tokens
        )
        self.repo_cache_max_mb = normalize_repo_cache_max_mb(self.repo_cache_max_mb)
        self.symbol_locate = normalize_symbol_locate(self.symbol_locate)
        self.suggested_patch = normalize_suggested_patch(self.suggested_patch)
        self.model_catalog_fetch = normalize_model_catalog_fetch(self.model_catalog_fetch)
        self.chat_reasoning_effort = normalize_chat_reasoning_effort(
            self.chat_reasoning_effort
        )
        self.chat_context_budget = _normalize_bounded_int(
            self.chat_context_budget,
            field="chat_context_budget",
            default=DEFAULT_CHAT_CONTEXT_BUDGET,
            bounds=(1, 200_000),
        )


def _preferences_of(config: object) -> object:
    """取出偏好对象：同时接受 ``AppConfig`` 与裸 ``PreferencesConfig``。

    ``PreferencesConfig`` 自己没有 ``preferences`` 属性，因此直接传它也能工作；
    传其它东西（``None``/字典/任意对象）时返回原对象，后续 ``getattr`` 全部走默认值，
    保证 resolve_* 永不抛异常。
    """
    preferences = getattr(config, "preferences", None)
    return config if preferences is None else preferences


def _hybrid_strategy_of(config: object) -> str:
    """当前运行模式预设，归一化为小写（与既有 `hybrid_strategy` 读法一致）。"""
    return str(getattr(_preferences_of(config), "hybrid_strategy", "") or "").strip().lower()


def resolve_chat_slot(config: object) -> str:
    """返回聊天槽位：``"remote"`` 或 ``"local"``。

    显式 ``chat_slot`` 优先；为空（或非法）时按运行模式预设推导：
    ``local_only`` -> 本地，其余（``remote_only`` / ``balanced`` / 未知）一律远端。

    非法显式值只告警回退，不抛异常。构造之后再直接赋值
    （``preferences.chat_slot = "cloud"``）会绕过 ``__post_init__``，所以这里重新
    归一化一次——告警只由这一处发出，同一次读取不会重复告警。
    """
    explicit = normalize_chat_slot(getattr(_preferences_of(config), "chat_slot", ""))
    if explicit:
        return explicit
    return "local" if _hybrid_strategy_of(config) == "local_only" else "remote"


def resolve_review_slot(config: object) -> str:
    """返回审查槽位：``"remote"``、``"local"`` 或 ``"hybrid"``。

    显式 ``review_slot`` 优先；为空（或非法）时按运行模式预设推导：
    ``local_only`` -> 本地、``balanced`` -> 混合、其余（含未知）-> 远端。
    """
    explicit = normalize_review_slot(getattr(_preferences_of(config), "review_slot", ""))
    if explicit:
        return explicit
    return REVIEW_STRATEGY_TO_SLOT.get(_hybrid_strategy_of(config), "remote")


def sync_review_slot_to_strategy(config: object) -> None:
    """把显式 ``review_slot`` 折算写回 ``preferences.hybrid_strategy``。

    仅在 ``review_slot`` 是三个合法值之一时执行
    （``remote`` -> ``remote_only``、``local`` -> ``local_only``、``hybrid`` -> ``balanced``）；
    空值或非法值一律不改动 ``hybrid_strategy``——"用户没细化路由时，预设就是唯一事实来源"。

    非法值不在这里告警：``resolve_review_slot`` 已经是告警点，两处都发会让同一次
    读取重复告警。聊天槽不参与折算（聊天只从预设**推导**，从不反向写回预设）。
    """
    preferences = _preferences_of(config)
    explicit = str(getattr(preferences, "review_slot", "") or "").strip().lower()
    strategy = REVIEW_SLOT_TO_STRATEGY.get(explicit)
    if strategy is not None:
        preferences.hybrid_strategy = strategy


@dataclass
class PRFetcherConfig:
    """PR Fetcher 专用配置。"""

    github_token: str = field(default_factory=lambda: os.getenv("GITHUB_TOKEN", ""))

    token_bucket_rate: float = 5000.0 / 3600.0

    max_retries: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 30.0

    request_timeout: int = 30
    diff_timeout: int = 60
    fetch_concurrency: int = 4

    user_agent: str = "ai-pr-review/0.1.0"


@dataclass
class FilterPipelineConfig:
    """Filter Pipeline 的可调配置。

    该配置负责描述“哪些文件默认应该被跳过”，以及“哪些文件需要
    强制保留”。自定义规则本身通常是运行时注入的可调用对象，因此不
    放在配置文件里，避免把不可序列化对象塞进全局配置。
    """

    force_include: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(
        default_factory=lambda: list(DEFAULT_FILTER_EXCLUDE_PATTERNS)
    )
    skip_deletion_only: bool = True
    max_changes: int | None = 500


@dataclass
class ContextBuilderConfig:
    """Context Builder 的可调配置。"""

    context_lines: int = 10
    enable_tree_sitter: bool = True
    max_ast_items: int = 200


@dataclass
class PromptAssemblerConfig:
    """Prompt Assembler 的可调配置。"""

    include_json_schema_in_system_prompt: bool = True
    include_custom_rules_in_system_prompt: bool = True
    custom_rules: list[str] = field(default_factory=list)
    max_diff_chars: int | None = None
    max_context_chars: int | None = None


@dataclass
class AIClientConfig:
    """AI Client 专用配置。"""

    api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    model: str = "claude-sonnet-4-20250514"
    provider: str = "anthropic"
    base_url: str = "https://api.anthropic.com"
    api_format: str = "anthropic"
    headers: dict[str, str] = field(default_factory=dict)
    extra_params: dict[str, object] = field(default_factory=dict)
    max_tokens: int = 4096
    timeout_seconds: int = 120
    review_concurrency: int = 2
    enable_static_analysis: bool = True
    enable_cross_file_review: bool = False
    cross_file_max_files: int = 8

    max_retries: int = 3
    retry_base_delay: float = 1.0

    input_cost_per_million: float = 3.0
    output_cost_per_million: float = 15.0
    max_cost_per_run: float = 5.0
    max_cost_per_24h: float = 50.0
    sliding_window_hours: int = 24

    # 新增：本地模型配置
    local_model: str = "qwen3.5:4b"
    local_provider: str = "ollama"

    def __post_init__(self) -> None:
        try:
            preset = ModelProviderConfig.from_name(self.provider)
        except ConfigValidationError:
            preset = ModelProviderConfig(
                name=self.provider,
                display_name=self.provider,
                api_key=self.api_key,
                base_url=self.base_url,
                model_name=self.model,
                api_format=self.api_format,
                headers=dict(self.headers),
                extra_params=dict(self.extra_params),
            )
        if not self.base_url:
            self.base_url = preset.base_url
        if not self.api_format:
            self.api_format = preset.api_format
        if not self.api_key:
            self.api_key = preset.api_key
        if not self.headers:
            self.headers = dict(preset.headers)
        if not self.extra_params:
            self.extra_params = dict(preset.extra_params)

    @property
    def model_provider(self) -> ModelProviderConfig:
        """返回 ModelProviderConfig 实例供 AIClient 使用。"""
        return ModelProviderConfig(
            name=self.provider,
            display_name=MODEL_PROVIDER_PRESETS.get(self.provider, {}).get(
                "display_name", self.provider
            ),
            api_key=self.api_key,
            base_url=self.base_url,
            model_name=self.model,
            api_format=self.api_format,
            headers=dict(self.headers),
            extra_params=dict(self.extra_params),
        )


@dataclass
class CostControllerConfig:
    """Cost Controller 的可调配置。"""

    run_limit: float = 5.0
    daily_limit: float = 50.0
    warning_threshold: float = 0.8
    input_cost_per_million: float = 3.0
    output_cost_per_million: float = 15.0

    @property
    def max_cost_per_run(self) -> float:
        return self.run_limit

    @property
    def max_cost_per_24h(self) -> float:
        return self.daily_limit

    @property
    def sliding_window_hours(self) -> int:
        return 24


@dataclass
class PostProcessorConfig:
    """Post-Processor 的可调配置。"""

    confidence_threshold: float = 0.6
    deduplication_rule: Callable[[Finding], Hashable] | None = None


@dataclass
class ResultStoreConfig:
    """Result Store 的可调配置。"""

    db_path: str = field(default_factory=lambda: str(_default_result_store_path()))
    max_results: int = 1000


@dataclass
class ReportRendererConfig:
    """Report Renderer 的可调配置。"""

    title: str = "AI PR Review Report"
    markdown_template: str | None = None
    github_comment_template: str | None = None
    json_indent: int = 2
    include_code_snippets_in_github_comment: bool = False


def _default_local_provider() -> "ProviderConfig":
    """Local slot default (Ollama).

    Kept as a separate slot so switching the runtime profile to ``local`` never
    overwrites the user's cloud provider (endpoint, model list and API key).
    """
    return ProviderConfig.from_model_provider(ModelProviderConfig.from_name("ollama"))


@dataclass
class AppConfig:
    """应用全局配置。"""

    provider: ProviderConfig = field(default_factory=ProviderConfig)
    # 本地槽位：只有 hybrid_strategy == "local_only" 时才会被激活。
    local_provider: ProviderConfig = field(default_factory=_default_local_provider)
    github_token: str = field(default_factory=lambda: os.getenv("GITHUB_TOKEN", ""))
    preferences: PreferencesConfig = field(default_factory=PreferencesConfig)
    pr_fetcher: PRFetcherConfig = field(default_factory=PRFetcherConfig)
    filter_pipeline: FilterPipelineConfig = field(default_factory=FilterPipelineConfig)
    context_builder: ContextBuilderConfig = field(default_factory=ContextBuilderConfig)
    prompt_assembler: PromptAssemblerConfig = field(default_factory=PromptAssemblerConfig)
    ai_client: AIClientConfig = field(default_factory=AIClientConfig)
    cost_controller: CostControllerConfig = field(default_factory=CostControllerConfig)
    post_processor: PostProcessorConfig = field(default_factory=PostProcessorConfig)
    result_store: ResultStoreConfig = field(default_factory=ResultStoreConfig)
    report_renderer: ReportRendererConfig = field(default_factory=ReportRendererConfig)

    @staticmethod
    def active_config_paths(path: Path | None = None) -> list[Path]:
        return active_config_paths(path)

    def _resolve_github_token(self) -> str:
        if self.github_token:
            return self.github_token
        if self.pr_fetcher.github_token:
            return self.pr_fetcher.github_token
        return ""

    @classmethod
    def from_env(cls) -> "AppConfig":
        config = cls(
            provider=ProviderConfig.from_model_provider(AIClientConfig().model_provider),
            github_token=os.getenv("GITHUB_TOKEN", ""),
            preferences=PreferencesConfig(),
            pr_fetcher=PRFetcherConfig(),
            filter_pipeline=FilterPipelineConfig(),
            context_builder=ContextBuilderConfig(),
            prompt_assembler=PromptAssemblerConfig(),
            ai_client=AIClientConfig(),
            cost_controller=CostControllerConfig(),
            post_processor=PostProcessorConfig(),
            result_store=ResultStoreConfig(),
            report_renderer=ReportRendererConfig(),
        )
        config._sync_runtime_sections()
        return config

    def _active_provider_config(self) -> ProviderConfig:
        """Provider slot currently in effect.

        ``local_only`` activates the local slot, but a user whose *primary*
        provider already is Ollama keeps using the primary slot so a runtime
        profile round trip neither duplicates nor drops their custom endpoint
        and model list.

        An explicit ``AI_PR_REVIEW_PROVIDER`` override always activates the
        primary slot for this process; it is never persisted back into
        ``preferences.hybrid_strategy``.
        """
        if getattr(self, "_env_provider_override", False):
            return self.provider
        strategy = str(getattr(self.preferences, "hybrid_strategy", "") or "").strip().lower()
        if strategy == "local_only" and self.provider.name.lower() not in {"ollama", "local"}:
            return self.local_provider
        return self.provider

    def _sync_runtime_sections(self) -> None:
        active = self._active_provider_config()
        provider = active.to_model_provider()
        # A key from the previous provider must never be copied into a newly
        # selected provider (especially when switching cloud -> local).
        same_provider = self.ai_client.provider.lower() == provider.name.lower()
        api_key = provider.api_key or (self.ai_client.api_key if same_provider else "")
        if api_key:
            active.api_key = api_key
            provider.api_key = api_key
        self.github_token = self._resolve_github_token()
        self.pr_fetcher.github_token = self.github_token
        self.ai_client = AIClientConfig(
            **{
                **asdict(self.ai_client),
                "provider": provider.name,
                "api_key": provider.api_key,
                "model": provider.model_name,
                "base_url": provider.base_url,
                "api_format": provider.api_format,
            }
        )

    def _apply_env_overrides(self) -> None:
        provider_override = os.getenv("AI_PR_REVIEW_PROVIDER", "").strip()
        override_applied = False
        if provider_override:
            name_matches = provider_override.lower() == self.provider.name.lower()
            try:
                # Validate even when names match: a legacy/custom provider name
                # must not bypass the preset allow-list and be displayed raw.
                validated = ModelProviderConfig.from_name(provider_override)
                # Rebuild the whole provider when the name changes; a name-only
                # replacement would retain the previous endpoint/key/model.
                override_config = None if name_matches else validated
            except ConfigValidationError:
                # Do not echo the raw environment value: it could contain a
                # pasted secret or terminal control characters. The CLI warns,
                # while TUI consumes the same safe message through snapshot.
                warning = "AI_PR_REVIEW_PROVIDER 的值不受支持，已忽略该覆盖；请检查环境变量。"
                self._ignored_env_overrides = [warning]
                warnings.warn(warning, RuntimeWarning, stacklevel=2)
            else:
                if override_config is not None:
                    self.provider = ProviderConfig.from_model_provider(override_config)
                    self.ai_client.api_key = ""
                # An explicit provider override must win over a persisted
                # `local_only` profile — but only for this process. Writing it
                # back to `preferences.hybrid_strategy` silently and permanently
                # overwrote the user's "prefer local" choice on the next save.
                self._env_provider_override = True
                override_applied = True
        provider_name = (provider_override if override_applied else "") or self.provider.name
        model_name = os.getenv("AI_PR_REVIEW_MODEL", "").strip() or self.provider.default_model
        api_key = os.getenv("AI_PR_REVIEW_API_KEY", "").strip()
        base_url = os.getenv("AI_PR_REVIEW_BASE_URL", "").strip()
        api_format = os.getenv("AI_PR_REVIEW_API_FORMAT", "").strip()
        github_token = os.getenv("GITHUB_TOKEN", "").strip()

        provider_env_var = str(MODEL_PROVIDER_PRESETS.get(provider_name, {}).get("env_var", ""))
        provider_api_key = os.getenv(provider_env_var, "").strip() if provider_env_var else ""

        effective_api_key = api_key or provider_api_key
        if provider_name:
            self.provider.name = provider_name
            self.provider.display_name = str(
                MODEL_PROVIDER_PRESETS.get(provider_name, {}).get("display_name", provider_name)
            )
            self.ai_client.provider = provider_name
        if model_name:
            self.provider.default_model = model_name
            self.ai_client.model = model_name
        if base_url:
            self.provider.base_url = base_url
            self.ai_client.base_url = base_url
        if api_format:
            self.provider.api_format = api_format
            self.ai_client.api_format = api_format
        if effective_api_key:
            self.provider.api_key = effective_api_key
            self.ai_client.api_key = effective_api_key
        if github_token:
            self.github_token = github_token
            self.pr_fetcher.github_token = github_token
        self._sync_runtime_sections()

    @staticmethod
    def _filter_dataclass_payload(
        config_type: type, payload: dict[str, object]
    ) -> dict[str, object]:
        """Ignore fields introduced by newer versions when loading old installs.

        User config files outlive the CLI version that created them. Filtering
        unknown keys keeps an older pipx installation from crashing before it can
        run `pr-review config` or `pr-review chat` and lets the user upgrade in
        place instead of losing access to the CLI.
        """
        allowed = {item.name for item in fields(config_type)}
        return {key: value for key, value in payload.items() if key in allowed}

    def _apply_payload(self, data: dict[str, object]) -> None:
        if isinstance(data.get("pr_fetcher"), dict):
            self.pr_fetcher = PRFetcherConfig(**data["pr_fetcher"])
        if isinstance(data.get("filter_pipeline"), dict):
            self.filter_pipeline = FilterPipelineConfig(**data["filter_pipeline"])
        if isinstance(data.get("context_builder"), dict):
            self.context_builder = ContextBuilderConfig(**data["context_builder"])
        if isinstance(data.get("prompt_assembler"), dict):
            self.prompt_assembler = PromptAssemblerConfig(**data["prompt_assembler"])
        ai_client_data = data.get("ai_client")
        if isinstance(ai_client_data, dict):
            self.ai_client = AIClientConfig(
                **self._filter_dataclass_payload(AIClientConfig, ai_client_data)
            )
        if isinstance(data.get("cost_controller"), dict):
            self.cost_controller = CostControllerConfig(**data["cost_controller"])
        if isinstance(data.get("post_processor"), dict):
            self.post_processor = PostProcessorConfig(**data["post_processor"])
        if isinstance(data.get("result_store"), dict):
            self.result_store = ResultStoreConfig(**data["result_store"])
        if isinstance(data.get("report_renderer"), dict):
            self.report_renderer = ReportRendererConfig(**data["report_renderer"])
        provider_data = data.get("provider")
        if isinstance(provider_data, dict):
            self.provider = ProviderConfig.from_dict(provider_data)
        local_provider_data = data.get("local_provider")
        if isinstance(local_provider_data, dict):
            self.local_provider = ProviderConfig.from_dict(local_provider_data)
        if isinstance(data.get("github_token"), str):
            self.github_token = str(data["github_token"])
        if isinstance(data.get("preferences"), dict):
            # Preferences grow over time (`workbench_mode` is the newest one), so a
            # config written by a newer release must not crash an older install
            # before the user can reach `pr-review config`.
            self.preferences = PreferencesConfig(
                **self._filter_dataclass_payload(PreferencesConfig, data["preferences"])
            )
        model_provider_data = data.get("model_provider")
        if isinstance(model_provider_data, dict):
            provider = ModelProviderConfig(**model_provider_data)
            provider.validate()
            self.provider = ProviderConfig.from_model_provider(provider)
        if not isinstance(provider_data, dict) and isinstance(ai_client_data, dict):
            self.provider = ProviderConfig.from_model_provider(self.ai_client.model_provider)

    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        config = cls.from_env()
        merged_payload: dict[str, object] = {}
        for config_path in cls.active_config_paths(path):
            if not config_path.exists():
                continue
            data = json.loads(config_path.read_text(encoding="utf-8"))
            merged_payload = _deep_merge_dicts(merged_payload, data)
        if merged_payload:
            config._apply_payload(merged_payload)
        raw_store = merged_payload.get("result_store")
        explicit_db = isinstance(raw_store, dict) and bool(raw_store.get("db_path"))
        config._config_source_path = path
        config._explicit_result_store_db_path = explicit_db
        if not explicit_db:
            # Any config outside the real per-user default is a workspace
            # boundary: keep history next to it instead of leaking into the
            # shared per-user database (or reading someone else's runs).
            derived = config._derived_result_store_default()
            if derived is not None:
                config.result_store.db_path = str(derived)
        config._sync_runtime_sections()
        config._apply_env_overrides()
        return config

    def save(self, path: Path | None = None, *, save_key: bool = False) -> Path:
        config_path = resolve_save_path(
            path, source_path=getattr(self, "_config_source_path", None)
        )
        config_path.parent.mkdir(parents=True, exist_ok=True)
        active = self._active_provider_config()
        if self.ai_client.api_key or active.api_key:
            api_key = self.ai_client.api_key or active.api_key
            active.api_key = api_key
            self.ai_client.api_key = api_key
        # Rebuilding a slot from `ai_client` is only meaningful for the active
        # slot. Doing it to the remote slot while the runtime profile is local
        # silently replaced the cloud endpoint, model list and key with the
        # Ollama preset, permanently destroying the user's configuration.
        if active is self.provider:
            self.provider = ProviderConfig.from_model_provider(self.ai_client.model_provider)
        self._sync_runtime_sections()
        if not save_key:
            payload_api_key = ""
            # 默认不落盘密钥是刻意的安全设计，但必须让人知道这件事发生了：
            # 调用方若按常规 `save(path)` 保存，密钥会被静默丢弃，
            # 下次启动就变成"未配置"，而现场没有任何线索。
            if self.ai_client.api_key or self.provider.api_key or self.local_provider.api_key:
                warnings.warn(
                    "save_key=False：API Key 未写入配置文件（这是默认的安全行为）。"
                    "若希望持久化密钥，请调用 save(path, save_key=True)，"
                    "或在 Web 设置页保存。",
                    RuntimeWarning,
                    stacklevel=2,
                )
        else:
            payload_api_key = self.ai_client.api_key or active.api_key or ""
        payload = {
            "provider": self.provider.to_dict(),
            "local_provider": self.local_provider.to_dict(),
            "github_token": self.github_token,
            "preferences": asdict(self.preferences),
            "pr_fetcher": {
                key: value
                for key, value in asdict(self.pr_fetcher).items()
                if key != "github_token"
            },
            "filter_pipeline": asdict(self.filter_pipeline),
            "context_builder": asdict(self.context_builder),
            "prompt_assembler": asdict(self.prompt_assembler),
            "ai_client": asdict(self.ai_client),
            "cost_controller": asdict(self.cost_controller),
            "post_processor": asdict(self.post_processor),
            "result_store": self._result_store_payload(),
            "report_renderer": asdict(self.report_renderer),
        }
        # 每个槽位只携带自己的 Key；`ai_client` 跟随当前激活槽位。
        # save_key=False 时不落盘任何 Key（安全默认）。
        if save_key and payload_api_key:
            payload["ai_client"]["api_key"] = payload_api_key
        else:
            payload["ai_client"].pop("api_key", None)
        for slot in ("provider", "local_provider"):
            if not save_key or not payload[slot].get("api_key"):
                payload[slot].pop("api_key", None)
        config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return config_path

    def _derived_result_store_default(self) -> Path | None:
        """Per-workspace history path, or None when using the real default config."""
        resolved_config = resolve_config_path(getattr(self, "_config_source_path", None))
        try:
            resolved_config = resolved_config.expanduser().resolve()
            default_config = _default_config_path().expanduser().resolve()
        except OSError:
            return None
        if resolved_config == default_config:
            return None
        return resolved_config.parent / "results.db"

    def _result_store_payload(self) -> dict[str, object]:
        """Persist a user-chosen database, never a value we derived ourselves.

        Freezing a derived path would make the isolation one-shot and would
        leave a moved workspace pointing at the old machine path.
        """
        payload = asdict(self.result_store)
        try:
            current = Path(self.result_store.db_path).expanduser().resolve()
            platform_default = _default_result_store_path().expanduser().resolve()
            derived = self._derived_result_store_default()
        except (OSError, TypeError, ValueError):
            return payload
        explicit_db = getattr(self, "_explicit_result_store_db_path", False)
        if not explicit_db and (
            current == platform_default or (derived is not None and current == derived)
        ):
            payload.pop("db_path", None)
        return payload
