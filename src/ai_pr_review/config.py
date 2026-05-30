"""配置管理模块。

从环境变量和配置文件加载应用配置。
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Hashable
from dataclasses import asdict, dataclass, field
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
    return [user_config_path, *project_config_paths()]


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
    "deepseek": _build_models(
        ("deepseek-chat", 32_768, 4_096),
        ("deepseek-coder", 32_768, 4_096),
        ("deepseek-v3", 65_536, 8_192),
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
            if parsed.scheme.lower() != "https":
                raise ConfigValidationError("base_url 必须使用 HTTPS。")
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


@dataclass
class PreferencesConfig:
    """User-facing CLI preferences."""

    output_format: str = "terminal"
    language: str = "zh-CN"
    ui_language: str = "zh-CN"
    chat_layout: str = "compact"
    auto_publish_comment: bool = False


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

    max_retries: int = 3
    retry_base_delay: float = 1.0

    input_cost_per_million: float = 3.0
    output_cost_per_million: float = 15.0
    max_cost_per_run: float = 5.0
    max_cost_per_24h: float = 50.0
    sliding_window_hours: int = 24

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

    db_path: str = "~/.ai_pr_review/results.db"
    max_results: int = 1000


@dataclass
class ReportRendererConfig:
    """Report Renderer 的可调配置。"""

    title: str = "AI PR Review Report"
    markdown_template: str | None = None
    github_comment_template: str | None = None
    json_indent: int = 2
    include_code_snippets_in_github_comment: bool = False


@dataclass
class AppConfig:
    """应用全局配置。"""

    provider: ProviderConfig = field(default_factory=ProviderConfig)
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

    def _sync_runtime_sections(self) -> None:
        provider = self.provider.to_model_provider()
        api_key = provider.api_key or self.ai_client.api_key
        if api_key:
            self.provider.api_key = api_key
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
        provider_name = os.getenv("AI_PR_REVIEW_PROVIDER", "").strip() or self.provider.name
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
            self.ai_client = AIClientConfig(**ai_client_data)
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
        if isinstance(data.get("github_token"), str):
            self.github_token = str(data["github_token"])
        if isinstance(data.get("preferences"), dict):
            self.preferences = PreferencesConfig(**data["preferences"])
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
        config._sync_runtime_sections()
        config._apply_env_overrides()
        return config

    def save(self, path: Path | None = None, *, save_key: bool = False) -> Path:
        config_path = resolve_config_path(path)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if self.ai_client.api_key and not self.provider.api_key:
            self.provider = ProviderConfig.from_model_provider(self.ai_client.model_provider)
        elif self.provider.api_key and not self.ai_client.api_key:
            provider = self.provider.to_model_provider()
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
        if self.ai_client.api_key or self.provider.api_key:
            api_key = self.ai_client.api_key or self.provider.api_key
            self.ai_client.api_key = api_key
            self.provider.api_key = api_key
        self._sync_runtime_sections()
        self.provider = ProviderConfig.from_model_provider(self.ai_client.model_provider)
        if self.provider.api_key or self.ai_client.api_key:
            api_key = self.provider.api_key or self.ai_client.api_key
            self.provider.api_key = api_key
            self.ai_client.api_key = api_key
        self._sync_runtime_sections()
        payload = {
            "provider": self.provider.to_dict(),
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
            "result_store": asdict(self.result_store),
            "report_renderer": asdict(self.report_renderer),
        }
        if not save_key:
            payload["provider"].pop("api_key", None)
            payload["ai_client"].pop("api_key", None)
        config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return config_path
