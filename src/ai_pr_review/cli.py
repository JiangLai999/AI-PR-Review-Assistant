"""CLI entry for AI PR Review assistant."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import click
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from ai_pr_review.config import (
    CONFIG_PATH_ENV_VAR,
    DEFAULT_CONFIG_PATH,
    MODEL_PROVIDER_PRESETS,
    PROJECT_CONFIG_DIRNAME,
    PROJECT_CONFIG_FILENAME,
    PROJECT_LOCAL_CONFIG_FILENAME,
    PROVIDER_MODEL_PRESETS,
    AIClientConfig,
    AppConfig,
    ConfigValidationError,
    ModelProviderConfig,
    PreferencesConfig,
    ProviderConfig,
    ProviderModelConfig,
    mask_api_key,
    resolve_config_path,
)
from ai_pr_review.services.exceptions import AIClientError, PRFetcherError
from ai_pr_review.services.model_providers.factory import create_model_provider
from ai_pr_review.services.pr_fetcher import PRFetcher
from ai_pr_review.services.prompt_assembler import ReviewResult
from ai_pr_review.services.report_renderer import ReportRenderer
from ai_pr_review.services.result_store import ResultStore
from ai_pr_review.services.review_orchestrator import ReviewArtifacts, ReviewOrchestrator

PROVIDER_WIZARD_OPTIONS = [
    {
        "key": "anthropic",
        "type": "官方",
        "recommendation": "★★★",
        "default_choice": False,
        "api_key_hint": "sk-ant-...",
        "steps": [
            "访问 https://console.anthropic.com",
            "注册或登录账号",
            "进入 API Keys 页面",
            "创建新的 API Key",
            "复制生成的 Key",
        ],
    },
    {
        "key": "openai",
        "type": "官方",
        "recommendation": "★★★",
        "default_choice": False,
        "api_key_hint": "sk-...",
        "steps": [
            "访问 https://platform.openai.com",
            "注册或登录账号",
            "打开 API keys 页面",
            "点击 Create new secret key",
            "复制生成的 Key",
        ],
    },
    {
        "key": "deepseek",
        "type": "官方",
        "recommendation": "★★★",
        "default_choice": True,
        "api_key_hint": "sk-...",
        "steps": [
            "访问 https://platform.deepseek.com",
            "注册或登录账号",
            "进入 API Keys 页面",
            "点击创建 API Key",
            "复制生成的 Key",
        ],
    },
    {
        "key": "qwen",
        "type": "官方",
        "recommendation": "★★☆",
        "default_choice": False,
        "api_key_hint": "sk-...",
        "steps": [
            "访问 https://dashscope.console.aliyun.com",
            "开通 DashScope 服务",
            "进入 API-KEY 管理页面",
            "创建 API Key",
            "复制生成的 Key",
        ],
    },
    {
        "key": "siliconflow",
        "type": "国内聚合",
        "recommendation": "★★★",
        "default_choice": False,
        "api_key_hint": "sk-...",
        "steps": [
            "访问 https://cloud.siliconflow.cn",
            "注册或登录账号",
            "进入 API Keys 页面",
            "创建新的 API Key",
            "复制生成的 Key",
        ],
    },
    {
        "key": "moonshot",
        "type": "国内官方",
        "recommendation": "★★☆",
        "default_choice": False,
        "api_key_hint": "sk-...",
        "steps": [
            "访问 https://platform.moonshot.cn",
            "注册或登录账号",
            "进入 API Key 管理页面",
            "创建新的 API Key",
            "复制生成的 Key",
        ],
    },
    {
        "key": "zhipu",
        "type": "国内官方",
        "recommendation": "★★☆",
        "default_choice": False,
        "api_key_hint": "平台提供的 Key",
        "steps": [
            "访问 https://open.bigmodel.cn",
            "注册或登录账号",
            "进入 API Key 管理页面",
            "创建新的 Key",
            "复制生成的 Key",
        ],
    },
    {
        "key": "baichuan",
        "type": "国内官方",
        "recommendation": "★★☆",
        "default_choice": False,
        "api_key_hint": "平台提供的 Key",
        "steps": [
            "访问百川智能开放平台",
            "注册或登录账号",
            "进入 API Key 管理页面",
            "创建新的 Key",
            "复制生成的 Key",
        ],
    },
    {
        "key": "minimax",
        "type": "国内官方",
        "recommendation": "★★☆",
        "default_choice": False,
        "api_key_hint": "平台提供的 Key",
        "steps": [
            "访问 MiniMax 开放平台",
            "注册或登录账号",
            "进入 API Key 管理页面",
            "创建新的 Key",
            "复制生成的 Key",
        ],
    },
    {
        "key": "stepfun",
        "type": "国内官方",
        "recommendation": "★★☆",
        "default_choice": False,
        "api_key_hint": "平台提供的 Key",
        "steps": [
            "访问阶跃星辰开放平台",
            "注册或登录账号",
            "进入 API Key 管理页面",
            "创建新的 Key",
            "复制生成的 Key",
        ],
    },
    {
        "key": "doubao",
        "type": "国内官方",
        "recommendation": "★★☆",
        "default_choice": False,
        "api_key_hint": "Ark API Key",
        "steps": [
            "访问火山方舟控制台",
            "开通模型服务并创建推理接入点",
            "进入 API Key 管理页面",
            "创建新的 Key",
            "复制生成的 Key",
        ],
    },
    {
        "key": "hunyuan",
        "type": "国内官方",
        "recommendation": "★★☆",
        "default_choice": False,
        "api_key_hint": "平台提供的 Key",
        "steps": [
            "访问腾讯混元开放平台",
            "注册或登录账号",
            "进入 API Key 管理页面",
            "创建新的 Key",
            "复制生成的 Key",
        ],
    },
    {
        "key": "yi",
        "type": "国内官方",
        "recommendation": "★★☆",
        "default_choice": False,
        "api_key_hint": "平台提供的 Key",
        "steps": [
            "访问零一万物开放平台",
            "注册或登录账号",
            "进入 API Key 管理页面",
            "创建新的 Key",
            "复制生成的 Key",
        ],
    },
    {
        "key": "openrouter",
        "type": "第三方",
        "recommendation": "★★☆",
        "default_choice": False,
        "api_key_hint": "sk-or-v1-...",
        "steps": [
            "访问 https://openrouter.ai",
            "注册或登录账号",
            "进入 Keys 页面",
            "创建新的 API Key",
            "复制生成的 Key",
        ],
    },
    {
        "key": "api2d",
        "type": "第三方",
        "recommendation": "★★☆",
        "default_choice": False,
        "api_key_hint": "fk-... 或平台提供格式",
        "steps": [
            "访问 https://api2d.com",
            "注册或登录账号",
            "进入 API Key 页面",
            "创建新的 Key",
            "复制生成的 Key",
        ],
    },
    {
        "key": "closeai",
        "type": "第三方",
        "recommendation": "★☆☆",
        "default_choice": False,
        "api_key_hint": "平台提供的 Key",
        "steps": [
            "访问对应代理平台控制台",
            "注册或登录账号",
            "进入 API Key 管理页面",
            "创建新的 Key",
            "复制生成的 Key",
        ],
    },
    {
        "key": "custom",
        "type": "自定义",
        "recommendation": "-",
        "default_choice": False,
        "api_key_hint": "由服务端定义",
        "steps": [
            "确认服务端支持 OpenAI / Anthropic / Custom 协议",
            "准备 HTTPS Base URL",
            "准备模型名称与认证信息",
            "按接口要求填写 Header 或额外参数",
            "完成后进行本地验证",
        ],
    },
]


def _provider_option_map() -> dict[str, dict[str, Any]]:
    return {item["key"]: item for item in PROVIDER_WIZARD_OPTIONS}


def _default_provider_index() -> int:
    for index, item in enumerate(PROVIDER_WIZARD_OPTIONS, start=1):
        if item["default_choice"]:
            return index
    return 1


def _render_welcome(console: Console) -> None:
    steps = Table.grid(padding=(0, 1))
    steps.add_row("欢迎使用 AI PR Review 助手！")
    steps.add_row("本向导会同时生成 JSON 配置，并兼容环境变量覆盖。")
    steps.add_row("请按照以下步骤完成配置：")
    steps.add_row("")
    steps.add_row("1. 选择模型供应商")
    steps.add_row("2. 输入 API Key")
    steps.add_row("3. 配置模型参数")
    steps.add_row("4. 验证并保存配置")
    console.print(
        Panel(
            steps,
            title="AI PR Review 助手 - 配置向导",
            border_style="cyan",
            padding=(1, 2),
        )
    )


def _render_section_header(console: Console, title: str, subtitle: str) -> None:
    console.print(Panel(subtitle, title=title, border_style="cyan", padding=(1, 2)))


def _select_provider(console: Console) -> str:
    table = Table(box=box.ROUNDED, expand=True)
    table.add_column("序号", justify="right", style="cyan", no_wrap=True)
    table.add_column("供应商", style="bold")
    table.add_column("类型")
    table.add_column("推荐", justify="center")

    for index, item in enumerate(PROVIDER_WIZARD_OPTIONS, start=1):
        preset = MODEL_PROVIDER_PRESETS[item["key"]]
        table.add_row(
            str(index),
            str(preset["display_name"]),
            str(item["type"]),
            str(item["recommendation"]),
        )

    default_index = _default_provider_index()
    console.print(
        Panel(
            table,
            title="选择模型供应商",
            subtitle="推荐：3（DeepSeek，国产模型，性价比高）",
            border_style="blue",
            padding=(1, 1),
        )
    )

    while True:
        choice = IntPrompt.ask("请输入数字选择", default=default_index, console=console)
        if 1 <= choice <= len(PROVIDER_WIZARD_OPTIONS):
            return str(PROVIDER_WIZARD_OPTIONS[choice - 1]["key"])
        console.print("请输入有效序号。", style="bold red")


def _prompt_api_key(console: Console, provider: ModelProviderConfig) -> str:
    provider_details = _provider_option_map()[provider.name]
    instruction = Table.grid(padding=(0, 1))
    instruction.add_column()
    instruction.add_row(f"获取 {provider.display_name} API Key：")
    instruction.add_row("")
    for index, step in enumerate(provider_details["steps"], start=1):
        instruction.add_row(f"{index}. {step}")
    instruction.add_row("")
    instruction.add_row(f"API Key 格式参考：{provider_details['api_key_hint']}")
    console.print(
        Panel(
            instruction,
            title="输入 API Key",
            border_style="magenta",
            padding=(1, 2),
        )
    )
    api_key = click.prompt(
        "请输入 API Key",
        default=provider.api_key,
        hide_input=True,
        show_default=False,
    )
    console.print(f"[green]✓[/green] 已输入 API Key（{len(api_key)} 个字符）")
    return api_key


def _prompt_provider_model(
    console: Console, provider_name: str, default_model: str
) -> ProviderModelConfig:
    raw_models = PROVIDER_MODEL_PRESETS.get(provider_name, {})
    models = [ProviderModelConfig(**payload) for payload in raw_models.values()]
    if not models:
        models = [ProviderModelConfig(name=default_model)]

    table = Table(box=box.ROUNDED, expand=True)
    table.add_column("序号", justify="right", style="cyan")
    table.add_column("模型", style="bold")
    table.add_column("上下文窗口", justify="right")
    table.add_column("最大输出", justify="right")

    default_index = 1
    for index, model in enumerate(models, start=1):
        if model.name == default_model:
            default_index = index
        table.add_row(str(index), model.name, str(model.context_window), str(model.max_output))

    console.print(Panel(table, title="选择模型", border_style="green", padding=(1, 1)))
    choice = IntPrompt.ask("请输入数字选择", default=default_index, console=console)
    selected = models[max(1, min(choice, len(models))) - 1]

    model_name = Prompt.ask("模型名称", default=selected.name, console=console)
    context_window = IntPrompt.ask("上下文窗口", default=selected.context_window, console=console)
    max_output = IntPrompt.ask("最大输出 Token", default=selected.max_output, console=console)
    return ProviderModelConfig(
        name=model_name,
        context_window=context_window,
        max_output=max_output,
    )


def _prompt_provider_settings(
    console: Console,
    provider: ModelProviderConfig,
    *,
    quick: bool,
) -> tuple[str, str]:
    _render_section_header(
        console, "连接设置", "支持使用配置文件保存，也支持后续通过环境变量覆盖。"
    )
    base_url = provider.base_url
    api_format = provider.api_format
    if not quick or provider.name == "custom":
        base_url = Prompt.ask("API Base URL", default=provider.base_url, console=console)
        api_format = Prompt.ask(
            "API 协议格式",
            choices=["anthropic", "openai", "custom"],
            default=provider.api_format,
            console=console,
        )
    return base_url, api_format


def _validate_github_token_input(github_token: str) -> None:
    token = github_token.strip()
    if not token:
        raise ConfigValidationError("GitHub Token 不能为空。")
    if not token.startswith("ghp_"):
        raise ConfigValidationError("GitHub Token 格式不正确，必须以 ghp_ 开头。")
    if len(token) < 40:
        raise ConfigValidationError("GitHub Token 长度过短，请确认输入是否完整。")


def _prompt_github_token(console: Console, default_value: str) -> str:
    instruction = Table.grid(padding=(0, 1))
    instruction.add_column()
    instruction.add_row("获取 GitHub Token：")
    instruction.add_row("")
    instruction.add_row("1. 访问 https://github.com/settings/tokens")
    instruction.add_row("2. 点击 Generate new token -> Generate new token (classic)")
    instruction.add_row('3. 填写名称（如 "AI PR Review"）')
    instruction.add_row("4. 选择权限：repo（完整仓库访问）")
    instruction.add_row("5. 点击 Generate token")
    instruction.add_row("6. 复制生成的 Token")
    instruction.add_row("")
    instruction.add_row("Token 格式：ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
    console.print(
        Panel(
            instruction,
            title="GitHub 认证",
            subtitle="用于读取 PR 元数据和发布评论。GitHub Token 为必填项。",
            border_style="yellow",
            padding=(1, 2),
        )
    )

    while True:
        github_token = click.prompt(
            "请输入 GitHub Token",
            default=default_value,
            hide_input=True,
            show_default=False,
        )
        try:
            _validate_github_token_input(github_token)
        except ConfigValidationError as exc:
            console.print(f"错误：{exc}", style="bold red")
            continue
        return github_token.strip()


def _prompt_interface_preferences(
    console: Console, current: PreferencesConfig
) -> PreferencesConfig:
    _render_section_header(
        console,
        "界面与语言",
        "先选择 CLI 界面语言、聊天布局和模型默认回复语言，后续可用 preferences 命令调整。",
    )
    ui_language = Prompt.ask(
        "界面语言 / UI language",
        choices=["zh-CN", "en-US"],
        default=getattr(current, "ui_language", "zh-CN"),
        console=console,
    )
    chat_layout = Prompt.ask(
        "聊天布局 / Chat layout",
        choices=["compact", "split", "plain"],
        default=getattr(current, "chat_layout", "compact"),
        console=console,
    )
    language = Prompt.ask(
        "模型回复语言 / Model response language",
        choices=["zh-CN", "en-US"],
        default=current.language,
        console=console,
    )
    return PreferencesConfig(
        output_format=current.output_format,
        language=language,
        ui_language=ui_language,
        chat_layout=chat_layout,
        auto_publish_comment=current.auto_publish_comment,
    )


def _prompt_preferences(console: Console, current: PreferencesConfig) -> PreferencesConfig:
    _render_section_header(
        console, "输出偏好", "输出格式和默认发布行为会优先读取配置文件，并允许命令行参数覆盖。"
    )
    output_format = Prompt.ask(
        "默认输出格式",
        choices=["terminal", "markdown", "json"],
        default=current.output_format,
        console=console,
    )
    auto_publish_comment = Confirm.ask(
        "审查完成后默认自动发布 GitHub 评论？",
        default=current.auto_publish_comment,
        console=console,
    )
    return PreferencesConfig(
        output_format=output_format,
        language=current.language,
        ui_language=getattr(current, "ui_language", "zh-CN"),
        chat_layout=getattr(current, "chat_layout", "compact"),
        auto_publish_comment=auto_publish_comment,
    )


def _render_config_summary(
    console: Console,
    provider_config: ProviderConfig,
    github_token: str,
    preferences: PreferencesConfig,
) -> None:
    model = provider_config.models[provider_config.default_model]
    table = Table(box=box.SIMPLE_HEAVY)
    table.add_column("配置项", style="cyan")
    table.add_column("当前值", style="white")
    table.add_row("供应商", provider_config.display_name)
    table.add_row("默认模型", provider_config.default_model)
    table.add_row("上下文窗口", str(model.context_window))
    table.add_row("最大输出", str(model.max_output))
    table.add_row("API 端点", provider_config.base_url or "<自定义填写>")
    table.add_row("协议格式", provider_config.api_format)
    table.add_row("GitHub Token", mask_api_key(github_token))
    table.add_row("默认输出", preferences.output_format)
    table.add_row("界面语言", getattr(preferences, "ui_language", "zh-CN"))
    table.add_row("模型回复语言", preferences.language)
    table.add_row("聊天布局", getattr(preferences, "chat_layout", "compact"))
    table.add_row("自动发布评论", "是" if preferences.auto_publish_comment else "否")
    console.print(Panel(table, title="配置摘要", border_style="green", padding=(1, 2)))


def _validate_api_key_input(provider_name: str, api_key: str) -> None:
    if not api_key.strip():
        raise ConfigValidationError("API Key 不能为空。")
    if provider_name in {"anthropic", "openai", "deepseek", "qwen"} and len(api_key.strip()) < 8:
        raise ConfigValidationError("API Key 长度过短，请确认输入是否完整。")


def _run_provider_validation(
    console: Console, provider: ModelProviderConfig, config_path: Path
) -> None:
    validation_steps = [
        "检查 API Key 输入",
        "验证供应商配置",
        "检查模型参数",
        "生成配置预览",
    ]
    completed_messages = [
        "API Key 输入检查通过",
        "供应商配置验证通过",
        "模型参数检查通过",
        "配置预览生成完成",
    ]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=24),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
        transient=True,
    ) as progress:
        task_id = progress.add_task("正在验证配置...", total=len(validation_steps))
        for index, step in enumerate(validation_steps):
            progress.update(task_id, description=f"正在验证配置... {step}")
            if index == 0:
                _validate_api_key_input(provider.name, provider.api_key)
            elif index == 1:
                provider.validate()
            elif index == 2:
                if provider.name == "custom" and provider.base_url.strip() == "":
                    raise ConfigValidationError("自定义供应商必须配置 Base URL。")
            progress.advance(task_id)
            console.print(f"[green]✓[/green] {completed_messages[index]}")

    info_table = Table(box=box.ROUNDED)
    info_table.add_column("配置项", style="cyan")
    info_table.add_column("值")
    info_table.add_row("供应商", provider.display_name)
    info_table.add_row("模型", provider.model_name)
    info_table.add_row("API 端点", provider.base_url or "<未设置>")
    info_table.add_row("配置文件", str(config_path))
    console.print(Panel(info_table, title="验证配置", border_style="green", padding=(1, 2)))


def _export_config_payload(
    config: AppConfig, *, config_path: Path | None = None, mask_secrets: bool = False
) -> dict[str, Any]:
    provider_payload = config.provider.to_dict()
    github_token = config.github_token
    if mask_secrets:
        provider_payload["api_key"] = mask_api_key(str(provider_payload.get("api_key", "")))
        github_token = mask_api_key(github_token)
    active_paths = [str(path) for path in AppConfig.active_config_paths(config_path)]
    return {
        "config_path": str((config_path or DEFAULT_CONFIG_PATH)),
        "config_env_var": CONFIG_PATH_ENV_VAR,
        "config_sources": active_paths,
        "provider": provider_payload,
        "github_token": github_token,
        "preferences": config.preferences.__dict__,
    }


def _render_completion(console: Console, config_path: Path) -> None:
    content = Table.grid(padding=(0, 1))
    content.add_row("配置已成功完成。")
    content.add_row("")
    content.add_row("现在可以使用以下命令：")
    content.add_row("pr-review https://github.com/owner/repo/pull/123")
    content.add_row("")
    content.add_row("更多用法：")
    content.add_row("pr-review config show    - 查看配置")
    content.add_row("pr-review config test    - 测试配置")
    content.add_row("pr-review history        - 查看历史")
    content.add_row("pr-review stats          - 查看统计")
    content.add_row("")
    content.add_row(f"配置文件：{config_path}")
    console.print(Panel(content, title="配置完成", border_style="bright_green", padding=(1, 2)))


class DefaultReviewGroup(click.Group):
    """Treat unknown first token as the default review command."""

    def resolve_command(
        self, ctx: click.Context, args: list[str]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError:
            return super().resolve_command(ctx, ["review", *args])


def infer_output_format(output_format: str, output_path: str | None) -> str:
    if output_format != "terminal":
        return output_format

    if output_path is None:
        return output_format

    suffix = Path(output_path).suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix in {".md", ".markdown"}:
        return "markdown"
    return output_format


async def run_review(
    pr_url: str,
    *,
    model: str | None = None,
    verbose: bool = False,
    config: AppConfig | None = None,
) -> ReviewArtifacts:
    app_config = config or AppConfig.load()
    orchestrator = ReviewOrchestrator(app_config)

    def progress_callback(filename: str, active_model: str) -> None:
        if verbose:
            click.echo(f"Reviewing {filename} with model {active_model}...")

    return await orchestrator.review(pr_url, model=model, progress_callback=progress_callback)


def build_report_payload(artifacts: ReviewArtifacts) -> dict:
    renderer = ReportRenderer()
    payload = json.loads(
        renderer.render_json(
            artifacts.review_result or ReviewResult(summary="", findings=[]),
            artifacts.pr_data,
        )
    )
    payload["pr"]["files_reviewed"] = artifacts.filter_result.included_count
    payload["pr"]["files_skipped"] = artifacts.filter_result.excluded_count
    payload["filter"] = artifacts.filter_result.to_dict()
    payload["run"] = {
        "id": artifacts.run_id,
        "duration_seconds": artifacts.duration_seconds,
        "total_cost": artifacts.total_cost,
    }
    return payload


def _build_filter_summary_markdown(artifacts: ReviewArtifacts) -> str:
    filter_result = artifacts.filter_result
    if hasattr(filter_result, "excluded_reason_counts"):
        reason_counts = filter_result.excluded_reason_counts()
    else:
        reason_counts = filter_result.to_dict().get("excluded_reason_counts", {})
    if not reason_counts:
        return ""
    total_files = getattr(filter_result, "total_files", filter_result.to_dict().get("total_files", 0))
    included_count = getattr(
        filter_result,
        "included_count",
        filter_result.to_dict().get("included_count", 0),
    )
    excluded_count = getattr(
        filter_result,
        "excluded_count",
        filter_result.to_dict().get("excluded_count", 0),
    )
    lines = ["## Filter Summary", ""]
    lines.append(f"- **Total Files**: {total_files}")
    lines.append(f"- **Included**: {included_count}")
    lines.append(f"- **Excluded**: {excluded_count}")
    lines.append("")
    lines.append("### Excluded Reason Counts")
    lines.append("")
    for code, count in sorted(reason_counts.items()):
        lines.append(f"- `{code}`: {count}")
    return "\n".join(lines)


def render_markdown_report(artifacts: ReviewArtifacts, config: AppConfig | None = None) -> str:
    app_config = config or AppConfig.load()
    rendered = ReportRenderer(app_config.report_renderer).render_markdown(
        artifacts.review_result or ReviewResult(summary="", findings=[]),
        artifacts.pr_data,
    )
    filter_summary = _build_filter_summary_markdown(artifacts)
    if not filter_summary:
        return rendered
    return f"{rendered}\n\n{filter_summary}"


def render_github_comment_report(
    artifacts: ReviewArtifacts, config: AppConfig | None = None
) -> str:
    app_config = config or AppConfig.load()
    return ReportRenderer(app_config.report_renderer).render_github_comment(
        artifacts.review_result or ReviewResult(summary="", findings=[]),
        artifacts.pr_data,
    )


def render_json_report(artifacts: ReviewArtifacts, config: AppConfig | None = None) -> str:
    app_config = config or AppConfig.load()
    return json.dumps(
        build_report_payload(artifacts),
        ensure_ascii=False,
        indent=app_config.report_renderer.json_indent,
    )


def render_terminal_report(
    console: Console, artifacts: ReviewArtifacts, config: AppConfig | None = None
) -> None:
    app_config = config or AppConfig.load()
    console.print(
        ReportRenderer(app_config.report_renderer).render_terminal(
            artifacts.review_result or ReviewResult(summary="", findings=[]),
            artifacts.pr_data,
        ),
        end="",
    )


def maybe_publish_comment(
    artifacts: ReviewArtifacts, comment_body: str, config: AppConfig | None = None
) -> None:
    app_config = config or AppConfig.load()
    fetcher = PRFetcher(config=app_config.pr_fetcher)
    pull_request = fetcher._get_pull_request(
        artifacts.pr_data.owner,
        artifacts.pr_data.repo,
        artifacts.pr_data.pr_number,
    )
    pull_request.create_issue_comment(comment_body)


def _provider_choices() -> list[str]:
    return list(MODEL_PROVIDER_PRESETS.keys())


def _provider_env_var(provider_name: str) -> str:
    return str(MODEL_PROVIDER_PRESETS.get(provider_name, {}).get("env_var", "AI_PR_REVIEW_API_KEY"))


def _missing_api_key_message(provider_name: str) -> str:
    provider_env_var = _provider_env_var(provider_name)
    return (
        "模型供应商 API Key 未提供。请重新运行 `pr-review config` 并选择保存 API Key，"
        f"或设置环境变量 {provider_env_var} / AI_PR_REVIEW_API_KEY。"
    )


def _response_language_instruction(language: str) -> str:
    """根据语言设置生成模型回复语言指令。"""
    if language.lower().startswith("en"):
        return "Respond in English unless the user explicitly asks for another language."
    return "请默认使用中文回答，除非用户明确要求使用其他语言。"


def _chat_title(config: AppConfig) -> str:
    """生成聊天窗口标题，显示供应商名和模型名。"""
    provider = config.provider
    return f"AI PR Review Chat | {provider.display_name} / {provider.default_model}"


def _set_active_model(config: AppConfig, model_name: str) -> None:
    """设置当前活跃模型，同时更新 provider 和 ai_client 配置。"""
    model_name = model_name.strip()
    if not model_name:
        raise click.ClickException("模型名称不能为空。")
    if model_name not in config.provider.models:
        config.provider.models[model_name] = ProviderModelConfig(name=model_name)
    config.provider.default_model = model_name
    config.ai_client.model = model_name


def _format_chat_error(exc: Exception, config: AppConfig) -> str:
    """将模型调用错误转换为用户友好的提示信息。"""
    message = str(exc)
    if "Not supported model" in message:
        return (
            f"模型服务不支持当前模型：{config.ai_client.model}\n"
            "请确认服务商实际支持的模型 ID，然后运行：\n"
            f'  pr-review config model --name "<模型ID>"\n'
            "也可以仅本次聊天临时覆盖：\n"
            f'  pr-review chat --model "<模型ID>"'
        )
    return message


async def _send_chat_message(config: AppConfig, messages: list[dict[str, Any]]) -> str:
    """发送聊天消息到模型并返回回复文本。"""
    provider_config = config.ai_client.model_provider
    if not provider_config.api_key:
        raise click.ClickException(_missing_api_key_message(provider_config.name))
    provider = create_model_provider(provider_config)
    response = await provider.chat(
        messages,
        system_prompt=_response_language_instruction(config.preferences.language),
        max_tokens=config.ai_client.max_tokens,
        timeout_seconds=config.ai_client.timeout_seconds,
    )
    return response.text


async def _discover_remote_models(config: AppConfig) -> list[str]:
    """通过 provider 的 /models 接口自动发现可用模型列表。"""
    provider_config = config.ai_client.model_provider
    if not provider_config.api_key:
        raise click.ClickException(_missing_api_key_message(provider_config.name))
    provider = create_model_provider(provider_config)
    return await provider.list_models(timeout_seconds=config.ai_client.timeout_seconds)


def _build_provider_health_payload(
    config: AppConfig,
    *,
    config_path: Path | None,
    discovered_models: list[str] | None = None,
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
    return payload


def _model_discovery_fallback_message(config: AppConfig, exc: Exception) -> str:
    return (
        f"{exc}\n\n"
        "Fallback 建议：\n"
        "1. 先运行 `pr-review config health --discover-models` 检查当前 provider 是否支持远端模型发现。\n"
        "2. 如果服务商不支持 `/models`，请手动设置模型名："
        "`pr-review config model --name \"<模型ID>\"`。\n"
        f"3. 当前配置的模型是 `{config.ai_client.model}`；如果 chat 已提示 `Not supported model`，请改成服务商实际支持的模型 ID。"
    )


def _print_chat_message(console: Console, role: str, text: str, *, layout: str) -> None:
    """打印聊天消息，支持 plain/compact/split 三种布局。"""
    if layout == "plain":
        console.print(f"{role}: {text}")
        return
    border_style = "cyan" if role == "You" else "green"
    console.print(Panel(text, title=role, border_style=border_style, expand=layout == "split"))


def _active_config_has_saved_api_key(config_path: Path | None) -> bool:
    """检查当前配置文件中是否已保存 API Key。"""
    path = resolve_config_path(config_path)
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    provider = payload.get("provider")
    ai_client = payload.get("ai_client")
    return bool(
        (isinstance(provider, dict) and provider.get("api_key"))
        or (isinstance(ai_client, dict) and ai_client.get("api_key"))
    )


def _chat_session_path(config_path: Path | None) -> Path:
    return resolve_config_path(config_path).parent / "chat_session.json"


def _load_chat_session(config_path: Path | None) -> list[dict[str, Any]]:
    session_path = _chat_session_path(config_path)
    if not session_path.exists():
        return []
    try:
        payload = json.loads(session_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    messages: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if isinstance(role, str) and isinstance(content, str):
            messages.append({"role": role, "content": content})
    return messages


def _save_chat_session(config_path: Path | None, messages: list[dict[str, Any]]) -> None:
    session_path = _chat_session_path(config_path)
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")


def _clear_chat_session(config_path: Path | None) -> None:
    session_path = _chat_session_path(config_path)
    if session_path.exists():
        session_path.unlink()


def _chat_help_text() -> str:
    return (
        "/help - 显示可用聊天命令\n"
        "/config - 显示当前会话配置\n"
        "/history - 显示最近 5 条审查历史\n"
        "/stats - 显示审查统计\n"
        "/model <模型ID> - 仅本次会话切换模型\n"
        "/review <PR_URL> - 在当前会话中运行 PR 审查\n"
        "/clear - 清空当前会话历史\n"
        "/exit - 退出聊天"
    )


def _render_chat_config(config: AppConfig, layout: str) -> str:
    return json.dumps(
        {
            "provider": config.ai_client.provider,
            "model": config.ai_client.model,
            "base_url": config.ai_client.base_url,
            "response_language": config.preferences.language,
            "layout": layout,
        },
        ensure_ascii=False,
        indent=2,
    )


def _handle_chat_slash_command(
    console: Console,
    config: AppConfig,
    config_path: Path | None,
    messages: list[dict[str, Any]],
    command_text: str,
    layout: str,
) -> bool:
    parts = command_text.split(maxsplit=1)
    command = parts[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else ""

    if command == "/help":
        console.print(Panel(_chat_help_text(), title="Chat Commands", border_style="cyan"))
        return True
    if command == "/config":
        console.print(Panel(_render_chat_config(config, layout), title="Chat Config", border_style="green"))
        return True
    if command == "/history":
        store = ResultStore(config.result_store)
        payload = {"runs": store.list_runs(limit=5)}
        console.print(Panel(json.dumps(payload, ensure_ascii=False, indent=2), title="History", border_style="green"))
        return True
    if command == "/stats":
        store = ResultStore(config.result_store)
        payload = store.get_statistics()
        console.print(Panel(json.dumps(payload, ensure_ascii=False, indent=2), title="Stats", border_style="green"))
        return True
    if command == "/clear":
        messages.clear()
        _clear_chat_session(config_path)
        console.print("Conversation cleared.")
        return True
    if command == "/model":
        if not argument:
            console.print("Usage: /model <模型ID>", style="bold red")
            return True
        _set_active_model(config, argument)
        console.print(f"Active model set to: {config.ai_client.model}")
        return True
    if command == "/review":
        if not argument:
            console.print("Usage: /review <PR_URL>", style="bold red")
            return True
        try:
            artifacts = asyncio.run(run_review(argument, model=config.ai_client.model, config=config))
            render_terminal_report(console, artifacts, config)
            console.print(
                f"Saved run {artifacts.run_id} | cost=${artifacts.total_cost:.4f} | duration={artifacts.duration_seconds:.2f}s"
            )
        except (PRFetcherError, AIClientError) as exc:
            console.print(Panel(f"Error: {exc}", title="Review Error", border_style="red"))
        return True
    return False


def _build_project_config_payload(
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


def _build_local_example_payload(provider_name: str) -> dict[str, Any]:
    return {
        "provider": {
            "api_key": "",
        },
        "_note": (
            f"Do not commit this file after copying it to {PROJECT_LOCAL_CONFIG_FILENAME}. "
            f"Recommended: set {_provider_env_var(provider_name)} or AI_PR_REVIEW_API_KEY instead."
        ),
    }


def _append_gitignore_entry(gitignore_path: Path, entry: str) -> bool:
    existing = gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else ""
    lines = {line.strip() for line in existing.splitlines()}
    if entry in lines:
        return False
    suffix = "" if not existing or existing.endswith("\n") else "\n"
    gitignore_path.write_text(f"{existing}{suffix}{entry}\n", encoding="utf-8")
    return True


def _json_prompt(text: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
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


def _run_config_wizard(quick: bool, advanced: bool, save_key: bool | None) -> Path:
    console = Console()
    existing = AppConfig.load()
    _render_welcome(console)
    preferences = _prompt_interface_preferences(console, existing.preferences)

    provider_name = _select_provider(console)
    provider = ModelProviderConfig.from_name(provider_name)
    api_key = _prompt_api_key(console, provider)
    selected_model = _prompt_provider_model(console, provider_name, provider.model_name)
    base_url, api_format = _prompt_provider_settings(console, provider, quick=quick)
    headers: dict[str, str] = {}
    extra_params: dict[str, Any] = {}
    if advanced:
        headers = _json_prompt("Headers JSON", default=provider.headers)
        extra_params = _json_prompt("Extra params JSON", default=provider.extra_params)
    github_token = _prompt_github_token(console, existing.github_token)
    preferences = _prompt_preferences(console, preferences)

    final_provider = ModelProviderConfig(
        name=provider_name,
        display_name=provider.display_name,
        api_key=api_key,
        base_url=base_url,
        model_name=selected_model.name,
        api_format=api_format,
        headers={str(key): str(value) for key, value in headers.items()},
        extra_params=extra_params,
    )

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
    if save_key is None:
        save_key = Confirm.ask(
            "是否保存 API Key 到配置文件？选择否时需通过环境变量提供 Key。",
            default=True,
            console=console,
        )
    elif save_key:
        confirmed = Confirm.ask(
            "警告：API Key 将以明文形式保存到配置文件，是否继续？",
            default=True,
            console=console,
        )
        if not confirmed:
            raise click.Abort()

    config_path = DEFAULT_CONFIG_PATH
    _run_provider_validation(console, final_provider, config_path)
    _render_config_summary(console, config.provider, github_token, preferences)
    config_path = config.save(save_key=save_key)
    _render_completion(console, config_path)
    return config_path


@click.group(
    cls=DefaultReviewGroup,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Load and save config from a custom JSON path. Overrides default user config location.",
)
@click.pass_context
def main(ctx: click.Context, config_path: Path | None) -> None:
    """Review a GitHub Pull Request with AI assistance."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path


def _config_path_from_context(ctx: click.Context | None) -> Path | None:
    if ctx is None or not isinstance(ctx.obj, dict):
        return None
    raw_path = ctx.obj.get("config_path")
    return raw_path if isinstance(raw_path, Path) else None


@main.command("review", hidden=True)
@click.argument("pr_url")
@click.option("--model", default=None, help="Override configured model name.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["terminal", "markdown", "json"]),
    default="terminal",
    show_default=True,
    help="Report output format.",
)
@click.option(
    "--output", type=click.Path(dir_okay=False, path_type=Path), help="Write report to file."
)
@click.option(
    "--publish-comment",
    is_flag=True,
    help="Publish GitHub comment report to the GitHub PR comment thread.",
)
@click.option("--verbose", is_flag=True, help="Show detailed progress information.")
@click.option(
    "--dry-run", is_flag=True, help="Fetch and filter only, then show planned review scope."
)
@click.option("--only-fetch", is_flag=True, help="Fetch PR data only and print metadata.")
@click.option(
    "--only-filter", is_flag=True, help="Fetch and filter files only, then print filter results."
)
@click.option(
    "--show-filter-reasons",
    is_flag=True,
    help="Include structured filter reasons in fetch/filter output.",
)
@click.pass_context
def review_command(
    ctx: click.Context,
    pr_url: str,
    model: str | None,
    output_format: str,
    output: Path | None,
    publish_comment: bool,
    verbose: bool,
    dry_run: bool,
    only_fetch: bool,
    only_filter: bool,
    show_filter_reasons: bool,
) -> None:
    """Review a GitHub Pull Request with AI assistance."""
    console = Console()

    try:
        app_config = AppConfig.load(_config_path_from_context(ctx))
        effective_format = infer_output_format(output_format, str(output) if output else None)
        selected_modes = sum(bool(flag) for flag in (dry_run, only_fetch, only_filter))
        if selected_modes > 1:
            raise click.ClickException("--dry-run、--only-fetch 和 --only-filter 不能同时使用。")

        if only_fetch:
            orchestrator = ReviewOrchestrator(app_config)
            artifacts = asyncio.run(orchestrator.fetch_only(pr_url))
            payload = {
                "pr": artifacts.pr_data.model_dump(mode="json"),
                "run": {"duration_seconds": artifacts.duration_seconds},
            }
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        if only_filter or dry_run:
            orchestrator = ReviewOrchestrator(app_config)
            artifacts = asyncio.run(orchestrator.filter_only(pr_url))
            payload = {
                "pr": {
                    "number": artifacts.pr_data.pr_number,
                    "title": artifacts.pr_data.title,
                    "url": artifacts.pr_data.url,
                    "repository": artifacts.pr_data.repo_full_name,
                    "files_changed": artifacts.pr_data.changed_files_count,
                },
                "filter": artifacts.filter_result.to_dict(),
                "run": {
                    "dry_run": dry_run,
                    "duration_seconds": artifacts.duration_seconds,
                },
            }
            if not show_filter_reasons:
                for result in payload["filter"]["results"]:
                    result.pop("reasons", None)
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        artifacts = asyncio.run(run_review(pr_url, model=model, verbose=verbose, config=app_config))

        terminal_text: str | None = None
        if effective_format == "markdown":
            rendered = render_markdown_report(artifacts, app_config)
        elif effective_format == "json":
            rendered = render_json_report(artifacts, app_config)
        else:
            rendered = None
            terminal_text = None

        if effective_format == "terminal":
            render_terminal_report(console, artifacts, app_config)
        elif output is None:
            click.echo(rendered)

        if output is not None:
            content = rendered
            if content is None:
                terminal_console = Console(record=True)
                render_terminal_report(terminal_console, artifacts, app_config)
                content = terminal_console.export_text()
            output.write_text(content, encoding="utf-8")
            console.print(f"Report written to {output}")

        if publish_comment:
            comment_report = render_github_comment_report(artifacts, app_config)
            maybe_publish_comment(artifacts, comment_report, app_config)
            console.print("Published review comment to GitHub PR.")

        console.print(
            f"Saved run {artifacts.run_id} | cost=${artifacts.total_cost:.4f} | duration={artifacts.duration_seconds:.2f}s"
        )
    except (PRFetcherError, AIClientError) as exc:
        console.print(f"Error: {exc}", style="bold red")
        raise SystemExit(1) from exc
    except Exception as exc:
        console.print(f"Unexpected error: {exc}", style="bold red")
        raise SystemExit(1) from exc


@main.group("config", invoke_without_command=True)
@click.option("--quick", is_flag=True, help="Use a minimal interactive wizard.")
@click.option("--advanced", is_flag=True, help="Prompt for headers and extra params.")
@click.option(
    "--save-key/--no-save-key",
    default=None,
    help="Persist API Key to config file, or require environment variables instead.",
)
@click.pass_context
def config_command(ctx: click.Context, quick: bool, advanced: bool, save_key: bool | None) -> None:
    """Run the interactive configuration wizard.

    Recommended setup:
    - shared project config in .ai_pr_review/config.json
    - private overrides in .ai_pr_review/config.local.json
    - API keys via the wizard, config.local.json, or environment variables
    """
    if ctx.invoked_subcommand is not None:
        return
    try:
        _run_config_wizard(quick=quick, advanced=advanced, save_key=save_key)
    except ConfigValidationError as exc:
        raise click.ClickException(str(exc)) from exc


@config_command.command("show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    """Show resolved configuration and active config sources."""
    config_path = _config_path_from_context(ctx)
    config = AppConfig.load(config_path)
    click.echo(
        json.dumps(
            _export_config_payload(config, config_path=config_path, mask_secrets=True),
            ensure_ascii=False,
            indent=2,
        )
    )


@config_command.command("init")
@click.option(
    "--provider",
    type=click.Choice(_provider_choices()),
    default="deepseek",
    show_default=True,
    help="Provider preset to use in the project config template.",
)
@click.option("--model", "model_name", default=None, help="Override default model name.")
@click.option("--base-url", default=None, help="Override provider API base URL.")
@click.option(
    "--api-format",
    type=click.Choice(["anthropic", "openai", "custom"]),
    default=None,
    help="Override API protocol format.",
)
@click.option(
    "--directory",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Project directory where .ai_pr_review will be created.",
)
@click.option("--force", is_flag=True, help="Overwrite existing generated files.")
@click.option(
    "--local-example/--no-local-example",
    default=True,
    show_default=True,
    help="Create config.local.json.example for private local overrides.",
)
@click.option(
    "--update-gitignore/--no-update-gitignore",
    default=True,
    show_default=True,
    help="Add .ai_pr_review/config.local.json to .gitignore.",
)
def config_init(
    provider: str,
    model_name: str | None,
    base_url: str | None,
    api_format: str | None,
    directory: Path | None,
    force: bool,
    local_example: bool,
    update_gitignore: bool,
) -> None:
    """Initialize project-level config templates."""
    directory = directory or Path.cwd()
    config_dir = directory / PROJECT_CONFIG_DIRNAME
    config_dir.mkdir(parents=True, exist_ok=True)

    config_path = config_dir / PROJECT_CONFIG_FILENAME
    if config_path.exists() and not force:
        raise click.ClickException(f"配置文件已存在：{config_path}。如需覆盖请使用 --force。")

    payload = _build_project_config_payload(
        provider,
        model_name=model_name,
        base_url=base_url,
        api_format=api_format,
    )
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    click.echo(f"Created project config: {config_path}")

    if local_example:
        example_path = config_dir / f"{PROJECT_LOCAL_CONFIG_FILENAME}.example"
        if force or not example_path.exists():
            example_payload = _build_local_example_payload(provider)
            example_path.write_text(
                json.dumps(example_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            click.echo(f"Created local override example: {example_path}")

    if update_gitignore:
        gitignore_path = directory / ".gitignore"
        ignored = f"{PROJECT_CONFIG_DIRNAME}/{PROJECT_LOCAL_CONFIG_FILENAME}"
        if _append_gitignore_entry(gitignore_path, ignored):
            click.echo(f"Updated gitignore: {gitignore_path}")

    env_var = _provider_env_var(provider)
    click.echo(f"Set API key via environment variable: {env_var} or AI_PR_REVIEW_API_KEY")


@config_command.command("test")
@click.pass_context
def config_test(ctx: click.Context) -> None:
    """Validate the resolved provider configuration."""
    config = AppConfig.load(_config_path_from_context(ctx))
    provider = config.provider.to_model_provider()
    try:
        provider.validate()
    except ConfigValidationError as exc:
        raise click.ClickException(str(exc)) from exc
    if not provider.api_key:
        raise click.ClickException(_missing_api_key_message(provider.name))
    click.echo(
        f"Configuration valid: provider={provider.name}, model={provider.model_name}, format={provider.api_format}"
    )
    click.echo(f"Default output format: {config.preferences.output_format}")
    if provider.risk_warning is not None:
        click.echo(provider.risk_warning)


@config_command.command("health")
@click.option(
    "--discover-models",
    is_flag=True,
    help="Try provider model discovery through the remote /models endpoint.",
)
@click.pass_context
def config_health(ctx: click.Context, discover_models: bool) -> None:
    """Check whether the configured provider is ready to use."""
    config_path = _config_path_from_context(ctx)
    config = AppConfig.load(config_path)
    provider = config.provider.to_model_provider()
    try:
        provider.validate()
    except ConfigValidationError as exc:
        raise click.ClickException(str(exc)) from exc
    if not provider.api_key:
        raise click.ClickException(_missing_api_key_message(provider.name))

    discovered_models: list[str] | None = None
    if discover_models:
        try:
            discovered_models = asyncio.run(_discover_remote_models(config))
        except AIClientError as exc:
            raise click.ClickException(str(exc)) from exc

    click.echo(
        json.dumps(
            _build_provider_health_payload(
                config,
                config_path=config_path,
                discovered_models=discovered_models,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


@config_command.command("model")
@click.option("--name", "model_name", required=True, help="Set active model name.")
@click.pass_context
def config_model(ctx: click.Context, model_name: str) -> None:
    """Update the active model name in the current config."""
    config_path = _config_path_from_context(ctx)
    config = AppConfig.load(config_path)
    _set_active_model(config, model_name)
    config.save(config_path, save_key=_active_config_has_saved_api_key(config_path))
    click.echo(f"Active model set to: {model_name}")


@config_command.command("models")
@click.option("--set", "model_name", default=None, help="Set active model after discovery.")
@click.option("--set-first", is_flag=True, help="Set the first discovered model as active.")
@click.option("--json", "as_json", is_flag=True, help="Output discovered models as JSON.")
@click.pass_context
def config_models(
    ctx: click.Context, model_name: str | None, set_first: bool, as_json: bool
) -> None:
    """Discover remote models from the configured provider."""
    config_path = _config_path_from_context(ctx)
    config = AppConfig.load(config_path)
    try:
        models = asyncio.run(_discover_remote_models(config))
    except AIClientError as exc:
        raise click.ClickException(_model_discovery_fallback_message(config, exc)) from exc
    if not models:
        raise click.ClickException("当前 provider 未返回可发现的模型列表，请手动设置模型名。")

    if model_name is not None:
        if model_name not in models:
            raise click.ClickException(f"远端模型列表中未找到：{model_name}")
        _set_active_model(config, model_name)
        config.save(config_path, save_key=_active_config_has_saved_api_key(config_path))
    elif set_first:
        _set_active_model(config, models[0])
        config.save(config_path, save_key=_active_config_has_saved_api_key(config_path))

    if as_json:
        click.echo(
            json.dumps(
                {"models": models, "active_model": config.ai_client.model},
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    click.echo("Discovered models:")
    for model in models:
        marker = "*" if model == config.ai_client.model else " "
        click.echo(f"{marker} {model}")


@config_command.command("export")
@click.option(
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
    help="Write exported config JSON to file.",
)
@click.option(
    "--include-secrets", is_flag=True, help="Include API key and GitHub token in export file."
)
def config_export(output: Path, include_secrets: bool) -> None:
    """Export the resolved configuration to JSON file."""
    ctx = click.get_current_context(silent=True)
    config_path = _config_path_from_context(ctx)
    config = AppConfig.load(config_path)
    payload = _export_config_payload(
        config,
        config_path=config_path,
        mask_secrets=not include_secrets,
    )
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    click.echo(f"Exported configuration to {output}")


@config_command.command("import")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--save-key", is_flag=True, help="Persist imported API key and GitHub token.")
def config_import(input_path: Path, save_key: bool) -> None:
    """Import configuration from JSON file into the active user config path."""
    raw = json.loads(input_path.read_text(encoding="utf-8"))
    provider_payload = raw.get("provider")
    preferences_payload = raw.get("preferences", {})
    if not isinstance(provider_payload, dict):
        raise click.ClickException("导入失败：缺少 provider 配置对象。")

    provider = ProviderConfig.from_dict(provider_payload)
    provider.validate()
    ctx = click.get_current_context(silent=True)
    config_path = _config_path_from_context(ctx)
    config = AppConfig.load(config_path)
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
    click.echo(f"Imported configuration from {input_path}")


@main.command("history")
@click.option("--pr-url", default=None, help="Filter by PR URL.")
@click.option("--limit", default=10, show_default=True, type=int, help="Maximum runs to show.")
@click.pass_context
def history_command(ctx: click.Context, pr_url: str | None, limit: int) -> None:
    """Show persisted review history."""
    config = AppConfig.load(_config_path_from_context(ctx))
    store = ResultStore(config.result_store)
    payload = {
        "runs": store.list_runs(pr_url=pr_url, limit=limit),
        "statistics": store.get_statistics(),
    }
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@main.command("preferences")
@click.option(
    "--ui-language",
    type=click.Choice(["zh-CN", "en-US"]),
    default=None,
    help="Set CLI UI language.",
)
@click.option(
    "--response-language",
    type=click.Choice(["zh-CN", "en-US"]),
    default=None,
    help="Set model response language.",
)
@click.option(
    "--chat-layout",
    type=click.Choice(["compact", "split", "plain"]),
    default=None,
    help="Set chat layout.",
)
@click.option(
    "--output-format",
    type=click.Choice(["terminal", "markdown", "json"]),
    default=None,
    help="Set default review output format.",
)
@click.pass_context
def preferences_command(
    ctx: click.Context,
    ui_language: str | None,
    response_language: str | None,
    chat_layout: str | None,
    output_format: str | None,
) -> None:
    """Show or update CLI preferences."""
    config_path = _config_path_from_context(ctx)
    config = AppConfig.load(config_path)
    changed = False
    if ui_language is not None:
        config.preferences.ui_language = ui_language
        changed = True
    if response_language is not None:
        config.preferences.language = response_language
        changed = True
    if chat_layout is not None:
        config.preferences.chat_layout = chat_layout
        changed = True
    if output_format is not None:
        config.preferences.output_format = output_format
        changed = True
    if changed:
        config.save(config_path, save_key=_active_config_has_saved_api_key(config_path))
    click.echo(json.dumps(asdict(config.preferences), ensure_ascii=False, indent=2))


@main.command("chat")
@click.option("--message", "message", default=None, help="Send one message and exit.")
@click.option("--model", "model_name", default=None, help="Override model for this chat session.")
@click.option(
    "--layout",
    type=click.Choice(["compact", "split", "plain"]),
    default=None,
    help="Override chat layout for this session.",
)
@click.pass_context
def chat_command(
    ctx: click.Context, message: str | None, model_name: str | None, layout: str | None
) -> None:
    """Open a lightweight terminal chat with the configured model."""
    console = Console()
    config_path = _config_path_from_context(ctx)
    config = AppConfig.load(config_path)
    if model_name is not None:
        _set_active_model(config, model_name)
    active_layout = layout or getattr(config.preferences, "chat_layout", "compact")
    messages = _load_chat_session(config_path)
    console.print(Panel("输入 /exit 退出。", title=_chat_title(config), border_style="cyan"))
    if messages:
        console.print(f"Restored {len(messages)} messages from the previous chat session.")

    def send_once(user_text: str) -> None:
        messages.append({"role": "user", "content": user_text})
        _print_chat_message(console, "You", user_text, layout=active_layout)
        try:
            answer = asyncio.run(_send_chat_message(config, messages))
        except AIClientError as exc:
            messages.pop()
            console.print(Panel(_format_chat_error(exc, config), title="Error", border_style="red"))
            return
        except click.ClickException as exc:
            messages.pop()
            console.print(Panel(str(exc), title="Error", border_style="red"))
            return
        messages.append({"role": "assistant", "content": answer})
        _save_chat_session(config_path, messages)
        _print_chat_message(console, "Assistant", answer, layout=active_layout)

    if message is not None:
        send_once(message)
        return

    while True:
        user_text = Prompt.ask("You", console=console).strip()
        if user_text.lower() in {"/exit", "exit", "quit", "q"}:
            break
        if not user_text:
            continue
        if user_text.startswith("/") and _handle_chat_slash_command(
            console, config, config_path, messages, user_text, active_layout
        ):
            continue
        send_once(user_text)


@main.command("stats")
@click.pass_context
def stats_command(ctx: click.Context) -> None:
    """Show persisted review statistics."""
    config = AppConfig.load(_config_path_from_context(ctx))
    store = ResultStore(config.result_store)
    click.echo(json.dumps(store.get_statistics(), ensure_ascii=False, indent=2))


__all__ = [
    "ReviewArtifacts",
    "build_report_payload",
    "chat_command",
    "config_command",
    "infer_output_format",
    "main",
    "maybe_publish_comment",
    "preferences_command",
    "history_command",
    "stats_command",
    "render_github_comment_report",
    "review_command",
    "render_json_report",
    "render_markdown_report",
    "render_terminal_report",
    "run_review",
]
