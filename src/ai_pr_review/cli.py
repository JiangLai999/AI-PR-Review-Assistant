"""CLI entry for AI PR Review assistant."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, cast

import click
from prompt_toolkit.shortcuts import radiolist_dialog
from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from ai_pr_review.chat_commands import handle_basic_chat_slash_command
from ai_pr_review.chat_runtime import run_chat_session
from ai_pr_review.chat_session import (
    clear_chat_session,
    load_chat_context,
    load_chat_session,
    save_chat_context,
    save_chat_session,
)
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
from ai_pr_review.config_commands import (
    run_config_health,
    run_config_model,
    run_config_models,
    run_config_test,
)
from ai_pr_review.config_diagnostics import (
    validate_provider_for_test,
)
from ai_pr_review.config_entry import (
    build_config_show_output,
    run_config_export,
    run_config_import,
    run_config_init,
)
from ai_pr_review.config_helpers import (
    append_gitignore_entry,
    build_local_example_payload,
    build_project_config_payload,
    provider_env_var,
)
from ai_pr_review.config_wizard import (
    apply_wizard_configuration,
    json_prompt,
    resolve_save_key_choice,
)
from ai_pr_review.provider_diagnostics import (
    build_model_discovery_fallback_message,
    build_provider_health_payload,
    discover_remote_models,
    probe_provider_connection,
)
from ai_pr_review.review_commands import (
    build_fetch_only_payload,
    build_filter_only_payload,
    render_selected_report,
    write_report_output,
)
from ai_pr_review.review_entry import execute_review_flow
from ai_pr_review.services.agent import (
    ActionExecutor,
    ActionResult,
    AgentState,
    ChatAction,
    ChatActionRouter,
    ChatContext,
)
from ai_pr_review.services.exceptions import AIClientError, PRFetcherError
from ai_pr_review.services.hybrid_orchestrator import HybridReviewOrchestrator
from ai_pr_review.services.model_providers.factory import create_model_provider
from ai_pr_review.services.pr_fetcher import PRFetcher
from ai_pr_review.services.prompt_assembler import ReviewResult
from ai_pr_review.services.report_renderer import GitHubCommentMeta, ReportRenderer
from ai_pr_review.services.result_store import ResultStore
from ai_pr_review.services.review_orchestrator import (
    ReviewArtifacts,
    ReviewCancelled,
    ReviewOrchestrator,
)
from ai_pr_review.ui.pixel_theme import pixel_menu, pixel_print_frame, pixel_step_header, tr
from ai_pr_review.workspace_entry import (
    apply_workspace_preferences,
    build_history_output,
    build_stats_output,
)

_RENDERED_RUN_IDS: set[str] = set()


def _configure_terminal_encoding() -> None:
    """Prefer UTF-8 output on Windows while keeping redirected streams safe."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


_configure_terminal_encoding()


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


def _provider_type_label(provider_type: str, language: str) -> str:
    labels = {
        "官方": ("官方", "OFFICIAL"),
        "国内官方": ("国内官方", "CHINA OFFICIAL"),
        "国内聚合": ("国内聚合", "CHINA AGGREGATOR"),
        "第三方": ("第三方", "THIRD-PARTY"),
        "本地": ("本地", "LOCAL"),
    }
    zh, en = labels.get(provider_type, (provider_type, provider_type.upper()))
    return tr(language, zh, en)


def _setup_step_label(step: str, language: str) -> str:
    """Translate common provider setup instructions without changing provider data."""
    exact = {
        "注册或登录账号": "Register or sign in",
        "进入 API Keys 页面": "Open the API Keys page",
        "打开 API keys 页面": "Open the API keys page",
        "进入 API Key 管理页面": "Open the API key management page",
        "进入 Keys 页面": "Open the Keys page",
        "创建新的 API Key": "Create a new API key",
        "点击创建 API Key": "Create an API key",
        "创建 API Key": "Create an API key",
        "创建新的 Key": "Create a new key",
        "复制生成的 Key": "Copy the generated key",
        "开通 DashScope 服务": "Enable the DashScope service",
        "开通模型服务并创建推理接入点": "Enable the model service and create an inference endpoint",
        "注册或登录": "Register or sign in",
    }
    if not str(language).lower().startswith("en"):
        return step
    if step in exact:
        return exact[step]
    if step.startswith("访问 "):
        return "Visit " + step[3:]
    brand_names = {
        "访问百川智能开放平台": "Open the Baichuan AI platform",
        "访问 MiniMax 开放平台": "Open the MiniMax platform",
        "访问阶跃星辰开放平台": "Open the StepFun platform",
        "访问火山方舟控制台": "Open the Volcengine Ark console",
        "访问腾讯混元开放平台": "Open the Tencent Hunyuan platform",
        "访问零一万物开放平台": "Open the 01.AI platform",
    }
    return brand_names.get(step, step)


def _api_key_hint_label(hint: str, language: str) -> str:
    if not str(language).lower().startswith("en"):
        return hint
    if hint == "平台提供的 Key":
        return "Key issued by the platform"
    if hint == "或平台提供格式":
        return "or the platform-specific format"
    return hint


def _default_provider_index() -> int:
    for index, item in enumerate(PROVIDER_WIZARD_OPTIONS, start=1):
        if item["default_choice"]:
            return index
    return 1


def _pixel_select(
    *,
    title: str,
    text: str,
    values: list[tuple[str, str]],
    default: str,
    language: str,
) -> str:
    """Interactive keyboard/mouse selector with a deterministic test fallback."""
    try:
        import sys

        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return default
        result = radiolist_dialog(
            title=title,
            text=text,
            ok_text=tr(language, "确认", "Confirm"),
            cancel_text=tr(language, "取消", "Cancel"),
            values=values,
            default=default,
        ).run()
        return result if result is not None else default
    except (EOFError, KeyboardInterrupt):
        return default


def _prompt_runtime_profile(
    console: Console, current: PreferencesConfig
) -> tuple[str, str, str | None]:
    language = getattr(current, "ui_language", "zh-CN")
    profiles = [
        (
            "cloud",
            "云端 API 优先",
            "CLOUD-FIRST",
            "第三方 API 负责 Chat 与深度审查",
            "Third-party API for Chat and deep review",
            "remote_only",
        ),
        (
            "local",
            "本地 Ollama 优先",
            "LOCAL-FIRST",
            "Chat 与审查优先使用本地模型",
            "Use local Ollama for Chat and review",
            "local_only",
        ),
        (
            "hybrid",
            "混合模式",
            "HYBRID",
            "轻量任务本地，复杂任务使用 API",
            "Local for light tasks, API for complex tasks",
            "balanced",
        ),
    ]
    current_strategy = getattr(current, "hybrid_strategy", "remote_only")
    default_index = next(
        (i for i, item in enumerate(profiles, 1) if item[5] == current_strategy), 1
    )
    rows = [
        tr(language, "请选择模型运行场景", "SELECT MODEL RUNTIME PROFILE"),
        "",
    ]
    for index, (_, zh, en, detail_zh, detail_en, _) in enumerate(profiles, 1):
        label = tr(language, zh, en)
        detail = tr(language, detail_zh, detail_en)
        marker = ">" if index == default_index else " "
        rows.append(f"{marker} [{index}] {label:<22} {detail}")
    pixel_menu(
        console,
        title=tr(language, "模型场景配置", "MODEL RUNTIME PROFILE"),
        rows=rows,
        subtitle=tr(
            language,
            "首次选择将决定 Chat 与 PR 审查的默认模型路径",
            "This choice controls the default model path for Chat and PR review",
        ),
        width=92,
        border_style="bright_yellow",
    )
    import sys

    if sys.stdin.isatty() and sys.stdout.isatty():
        selected_key = _pixel_select(
            title=tr(language, "模型场景配置", "MODEL RUNTIME PROFILE"),
            text=tr(language, "方向键/鼠标选择，Enter 确认", "Use arrows/mouse, then press Enter"),
            values=[(item[0], tr(language, item[1], item[2])) for item in profiles],
            default=profiles[default_index - 1][0],
            language=language,
        )
        selected = next(item for item in profiles if item[0] == selected_key)
        return selected[0], selected[5], None

    raw_choice = Prompt.ask(
        tr(language, "输入场景编号", "Enter profile number"),
        default=str(default_index),
        console=console,
    ).strip()
    if raw_choice not in {"1", "2", "3"}:
        # Backward-compatible input handling for scripted setup flows created
        # before the runtime profile prompt existed. The consumed value is the
        # first UI-language answer and is passed to the next stage.
        return "cloud", "remote_only", raw_choice
    selected = profiles[int(raw_choice) - 1]
    return selected[0], selected[5], None


def _render_welcome(console: Console, language: str = "zh-CN") -> None:
    """Pixel setup welcome screen with consistent bilingual copy."""
    english = str(language).lower().startswith("en")
    pixel_step_header(
        console,
        step=1,
        total=7,
        title_zh="配置向导",
        title_en="CONFIGURATION WIZARD",
        detail_zh="准备本地模型、远程模型、GitHub 与 Chat 运行环境。",
        detail_en="Prepare local model, remote model, GitHub, and Chat runtime.",
        language=language,
    )
    rows = [
        tr(language, "欢迎使用 AI PR 审查智能体", "Welcome to AI PR Review Agent"),
    ]
    if not str(language).lower().startswith("en"):
        rows.append("AI PR Review 助手 - 配置向导")
    rows.extend(
        [
            tr(
                language,
                "配置完成后可直接进入 Chat、离线 Demo 或 PR 审查。",
                "After setup, open Chat, run Offline Demo, or review a PR.",
            ),
            "",
        ]
    )
    rows.extend(
        f"{index:02d}  {tr(language, zh, en)}"
        for index, (zh, en) in enumerate(
            [
                ("运行环境扫描", "Runtime scan"),
                ("选择模型运行场景", "Select model runtime profile"),
                ("界面与语言", "Interface & language"),
                ("配置模型和 API", "Configure models and API"),
                ("配置 GitHub Token", "Configure GitHub token"),
                ("输出偏好", "Output preferences"),
                ("验证并保存", "Verify and save"),
            ],
            start=1,
        )
    )
    pixel_menu(
        console,
        title="PIXEL SETUP",
        rows=rows,
        subtitle=tr(language, "↑↓ 选择   ENTER 确认", "↑↓ SELECT   ENTER CONFIRM"),
        width=92,
        border_style="bright_cyan",
    )


def _render_section_header(
    console: Console,
    title: str,
    subtitle: str,
    *,
    language: str = "zh-CN",
    step: int | None = None,
    title_en: str | None = None,
    subtitle_en: str | None = None,
) -> None:
    if step is not None:
        pixel_step_header(
            console,
            step=step,
            total=7,
            title_zh=title,
            title_en=title_en or title,
            detail_zh=subtitle,
            detail_en=subtitle_en or subtitle,
            language=language,
        )
    else:
        console.print(
            Panel(subtitle, title=title, border_style="cyan", padding=(1, 2), box=box.ROUNDED)
        )


def _select_provider(console: Console, language: str = "zh-CN") -> str:
    default_index = _default_provider_index()
    pixel_step_header(
        console,
        step=4,
        total=7,
        title_zh="选择模型供应商",
        title_en="SELECT MODEL PROVIDER",
        detail_zh="选择远程 API 供应商；本地 Ollama 配置可在运行模式中直接使用。",
        detail_en="Select a remote API provider; local Ollama can be used directly in runtime mode.",
        language=language,
    )
    rows = [
        f"{tr(language, '序号', 'NO.'):>4}  {tr(language, '供应商', 'PROVIDER'):<22} {tr(language, '类型', 'TYPE'):<18} {tr(language, '推荐', 'RECOMMENDED')}"
    ]
    for index, item in enumerate(PROVIDER_WIZARD_OPTIONS, start=1):
        preset = MODEL_PROVIDER_PRESETS[item["key"]]
        rows.append(
            f"{index:02d}    {str(preset['display_name']):<22} {_provider_type_label(str(item['type']), language):<18} {str(item['recommendation'])}"
        )
    pixel_menu(
        console,
        title=tr(language, "选择模型供应商", "SELECT MODEL PROVIDER"),
        rows=rows,
        subtitle=tr(
            language,
            "推荐：3（DeepSeek，国产模型，性价比高）",
            "Recommended: 3 (DeepSeek, strong value)",
        ),
        width=92,
        border_style="bright_blue",
    )

    import sys

    if sys.stdin.isatty() and sys.stdout.isatty():
        values = [
            (
                str(item["key"]),
                f"{MODEL_PROVIDER_PRESETS[item['key']]['display_name']} · {_provider_type_label(str(item['type']), language)}",
            )
            for item in PROVIDER_WIZARD_OPTIONS
        ]
        return _pixel_select(
            title=tr(language, "选择模型供应商", "SELECT MODEL PROVIDER"),
            text=tr(language, "方向键/鼠标选择，Enter 确认", "Use arrows/mouse, then press Enter"),
            values=values,
            default=str(PROVIDER_WIZARD_OPTIONS[default_index - 1]["key"]),
            language=language,
        )

    while True:
        choice = IntPrompt.ask(
            tr(language, "请输入数字选择", "Enter selection"),
            default=default_index,
            console=console,
        )
        if 1 <= choice <= len(PROVIDER_WIZARD_OPTIONS):
            return str(PROVIDER_WIZARD_OPTIONS[choice - 1]["key"])
        console.print(
            tr(language, "请输入有效序号。", "Please enter a valid number."), style="bold red"
        )


def _prompt_api_key(
    console: Console, provider: ModelProviderConfig, language: str = "zh-CN"
) -> str:
    provider_details = _provider_option_map()[provider.name]
    pixel_step_header(
        console,
        step=5,
        total=7,
        title_zh="配置模型与 API",
        title_en="CONFIGURE MODEL & API",
        detail_zh="输入密钥、选择模型，并确认连接参数。",
        detail_en="Enter the key, select a model, and confirm connection settings.",
        language=language,
    )
    instruction = Table.grid(padding=(0, 1))
    instruction.add_column()
    instruction.add_row(
        tr(
            language,
            f"获取 {provider.display_name} API Key：",
            f"Get an API key for {provider.display_name}:",
        )
    )
    instruction.add_row("")
    for index, step in enumerate(provider_details["steps"], start=1):
        instruction.add_row(f"{index}. {_setup_step_label(step, language)}")
    instruction.add_row("")
    instruction.add_row(
        tr(
            language,
            f"API Key 格式参考：{provider_details['api_key_hint']}",
            f"API key format: {_api_key_hint_label(provider_details['api_key_hint'], language)}",
        )
    )
    api_lines = [
        tr(
            language,
            f"获取 {provider.display_name} API Key：",
            f"Get an API key for {provider.display_name}:",
        ),
        *[
            f"{index}. {_setup_step_label(step, language)}"
            for index, step in enumerate(provider_details["steps"], start=1)
        ],
        tr(
            language,
            f"API Key 格式参考：{provider_details['api_key_hint']}",
            f"API key format: {_api_key_hint_label(provider_details['api_key_hint'], language)}",
        ),
    ]
    pixel_print_frame(
        console,
        tr(language, "输入 API Key", "ENTER API KEY"),
        api_lines,
        subtitle=tr(
            language, "用于连接所选模型供应商。", "Used to connect to the selected model provider."
        ),
        width=92,
        border_style="bright_magenta",
    )
    api_key = click.prompt(
        tr(language, "请输入 API Key", "Enter API key"),
        default=provider.api_key,
        hide_input=True,
        show_default=False,
    )
    console.print(
        tr(
            language,
            f"[green]✓[/green] 已输入 API Key（{len(api_key)} 个字符）",
            f"[green]✓[/green] API key entered ({len(api_key)} characters)",
        )
    )
    return api_key


def _is_likely_chat_model(model_name: str) -> bool:
    """Hide obvious non-chat / embedding entries from the setup wizard."""
    lowered = model_name.lower()
    blocked_tokens = ("embedding", "embed", "moderation", "rerank", "whisper", "tts", "image")
    return not any(token in lowered for token in blocked_tokens)


def _discover_wizard_models(
    console: Console, provider: ModelProviderConfig, api_key: str, language: str = "zh-CN"
) -> list[ProviderModelConfig]:
    """Discover current models after a key is entered, with static fallback."""
    fallback = [
        ProviderModelConfig(**payload)
        for payload in PROVIDER_MODEL_PRESETS.get(provider.name, {}).values()
    ]
    if not api_key.strip() or not provider.base_url.strip() or provider.api_format == "custom":
        return fallback

    candidate = ModelProviderConfig(
        name=provider.name,
        display_name=provider.display_name,
        api_key=api_key,
        base_url=provider.base_url,
        model_name=provider.model_name,
        api_format=provider.api_format,
        headers=dict(provider.headers),
        extra_params=dict(provider.extra_params),
    )
    try:
        console.print(
            tr(
                language,
                "[cyan]正在从供应商获取实时模型列表…[/cyan]",
                "[cyan]Loading live model list from provider...[/cyan]",
            )
        )
        remote = asyncio.run(create_model_provider(candidate).list_models(timeout_seconds=6))
        remote = [name for name in remote if _is_likely_chat_model(name)]
        if not remote:
            raise RuntimeError("远端没有返回可识别的聊天模型")
        fallback_by_name = {model.name: model for model in fallback}
        models = [
            fallback_by_name.get(
                name,
                ProviderModelConfig(name=name, context_window=32_768, max_output=4_096),
            )
            for name in remote
        ]
        console.print(
            tr(
                language,
                f"[green]✓[/green] 已发现 {len(models)} 个实时模型",
                f"[green]✓[/green] Discovered {len(models)} live models",
            )
        )
        return models
    except Exception as exc:
        if fallback:
            console.print(
                tr(
                    language,
                    f"[yellow]![/yellow] 实时模型发现失败：{exc}；将使用内置候选列表。",
                    f"[yellow]![/yellow] Live model discovery failed: {exc}; using built-in candidates.",
                )
            )
            return fallback
        console.print(
            tr(
                language,
                f"[yellow]![/yellow] 无法发现模型，请手动输入模型 ID：{exc}",
                f"[yellow]![/yellow] Could not discover models; enter a model ID manually: {exc}",
            )
        )
        return [ProviderModelConfig(name=provider.model_name)]


def _prompt_provider_model(
    console: Console, provider: ModelProviderConfig, api_key: str, language: str = "zh-CN"
) -> ProviderModelConfig:
    models = _discover_wizard_models(console, provider, api_key, language)
    default_model = provider.model_name
    if default_model not in {model.name for model in models}:
        default_model = models[0].name

    rows = [
        f"{tr(language, '序号', 'NO.'):>4}  {tr(language, '模型', 'MODEL'):<42} {tr(language, '上下文窗口', 'CONTEXT'):>10} {tr(language, '最大输出', 'MAX OUTPUT'):>12}"
    ]
    default_index = 1
    for index, model in enumerate(models, start=1):
        if model.name == default_model:
            default_index = index
        rows.append(
            f"{index:02d}    {model.name:<42} {model.context_window:>10} {model.max_output:>12}"
        )
    pixel_menu(
        console,
        title=tr(language, "选择实时模型", "SELECT LIVE MODEL"),
        rows=rows,
        subtitle=tr(
            language, "输入序号后可微调模型参数", "Enter a number, then adjust model parameters"
        ),
        width=92,
        border_style="bright_green",
    )
    import sys

    if sys.stdin.isatty() and sys.stdout.isatty():
        selected_key = _pixel_select(
            title=tr(language, "选择实时模型", "SELECT LIVE MODEL"),
            text=tr(language, "方向键/鼠标选择，Enter 确认", "Use arrows/mouse, then press Enter"),
            values=[(str(index), model.name) for index, model in enumerate(models, start=1)],
            default=str(default_index),
            language=language,
        )
        choice = int(selected_key)
    else:
        choice = IntPrompt.ask(
            tr(language, "请输入数字选择", "Enter selection"),
            default=default_index,
            console=console,
        )
    selected = models[max(1, min(choice, len(models))) - 1]

    model_name = Prompt.ask(
        tr(language, "模型名称", "Model name"), default=selected.name, console=console
    )
    context_window = IntPrompt.ask(
        tr(language, "上下文窗口", "Context window"),
        default=selected.context_window,
        console=console,
    )
    max_output = IntPrompt.ask(
        tr(language, "最大输出 Token", "Max output tokens"),
        default=selected.max_output,
        console=console,
    )
    return ProviderModelConfig(
        name=model_name, context_window=context_window, max_output=max_output
    )


def _prompt_provider_settings(
    console: Console,
    provider: ModelProviderConfig,
    *,
    quick: bool,
    language: str = "zh-CN",
) -> tuple[str, str]:
    _render_section_header(
        console,
        "连接设置",
        "支持使用配置文件保存，也支持后续通过环境变量覆盖。",
        language=language,
        title_en="CONNECTION SETTINGS",
        subtitle_en="Save settings in the config file or override them with environment variables.",
        step=3,
    )
    base_url = provider.base_url
    api_format = provider.api_format
    if not quick or provider.name == "custom":
        base_url = Prompt.ask(
            tr(language, "API Base URL", "API base URL"), default=provider.base_url, console=console
        )
        api_format = Prompt.ask(
            tr(language, "API 协议格式", "API protocol"),
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


def _prompt_github_token(console: Console, default_value: str, language: str = "zh-CN") -> str:
    pixel_step_header(
        console,
        step=6,
        total=7,
        title_zh="配置 GitHub Token",
        title_en="CONFIGURE GITHUB TOKEN",
        detail_zh="用于读取 PR 元数据，并在启用时发布审查评论。",
        detail_en="Used to read PR metadata and publish review comments when enabled.",
        language=language,
    )
    instruction = Table.grid(padding=(0, 1))
    instruction.add_column()
    instruction.add_row(tr(language, "获取 GitHub Token：", "Get a GitHub token:"))
    instruction.add_row("")
    instruction.add_row(
        tr(
            language,
            "1. 访问 https://github.com/settings/tokens",
            "1. Visit https://github.com/settings/tokens",
        )
    )
    instruction.add_row(
        tr(
            language,
            "2. 点击 Generate new token -> Generate new token (classic)",
            "2. Select Generate new token -> Generate new token (classic)",
        )
    )
    instruction.add_row(
        tr(
            language,
            '3. 填写名称（如 "AI PR Review"）',
            '3. Enter a name (for example, "AI PR Review")',
        )
    )
    instruction.add_row(
        tr(
            language,
            "4. 选择权限：repo（完整仓库访问）",
            "4. Grant the repo permission (full repository access)",
        )
    )
    instruction.add_row(tr(language, "5. 点击 Generate token", "5. Select Generate token"))
    instruction.add_row(tr(language, "6. 复制生成的 Token", "6. Copy the generated token"))
    instruction.add_row("")
    instruction.add_row(
        tr(
            language,
            "Token 格式：ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            "Token format: ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        )
    )
    pixel_print_frame(
        console,
        tr(language, "GitHub 认证", "GITHUB AUTHENTICATION"),
        [
            str(instruction),
            tr(
                language,
                "用于读取 PR 元数据和发布评论。GitHub Token 为必填项.",
                "Required to read PR metadata and publish comments. GitHub token is required.",
            ),
        ],
        width=92,
        border_style="bright_yellow",
    )

    while True:
        github_token = click.prompt(
            tr(language, "请输入 GitHub Token", "Enter GitHub token"),
            default=default_value,
            hide_input=True,
            show_default=False,
        )
        try:
            _validate_github_token_input(github_token)
        except ConfigValidationError as exc:
            console.print(tr(language, f"错误：{exc}", f"Error: {exc}"), style="bold red")
            continue
        return github_token.strip()


def _prompt_interface_preferences(
    console: Console, current: PreferencesConfig, initial_ui_language: str | None = None
) -> PreferencesConfig:
    _render_section_header(
        console,
        "界面与语言",
        "先选择 CLI 界面语言、聊天布局和模型默认回复语言，后续可用 preferences 命令调整。",
        language=getattr(current, "ui_language", "zh-CN"),
        step=2,
        title_en="INTERFACE & LANGUAGE",
        subtitle_en="Choose CLI language, chat layout, and the model response language.",
    )
    import sys

    language = getattr(current, "ui_language", "zh-CN")
    response_language: str = current.language

    if sys.stdin.isatty() and sys.stdout.isatty():
        ui_language = _pixel_select(
            title=tr(language, "界面语言", "UI LANGUAGE"),
            text=tr(language, "选择界面语言", "Select interface language"),
            values=[("zh-CN", "中文 / Chinese"), ("en-US", "English")],
            default=initial_ui_language or getattr(current, "ui_language", "zh-CN"),
            language=language,
        )
        chat_layout = _pixel_select(
            title=tr(ui_language, "聊天布局", "CHAT LAYOUT"),
            text=tr(ui_language, "选择 Chat 布局", "Select Chat layout"),
            values=[
                ("compact", tr(ui_language, "紧凑", "Compact")),
                ("split", tr(ui_language, "分栏", "Split")),
                ("plain", tr(ui_language, "纯文本", "Plain")),
            ],
            default=getattr(current, "chat_layout", "compact"),
            language=ui_language,
        )
        response_language = (
            _pixel_select(
                title=tr(ui_language, "模型回复语言", "MODEL RESPONSE LANGUAGE"),
                text=tr(ui_language, "选择模型默认回复语言", "Select default response language"),
                values=[("zh-CN", "中文 / Chinese"), ("en-US", "English")],
                default=current.language,
                language=ui_language,
            )
            or current.language
        )
    else:
        ui_language = cast(
            str,
            initial_ui_language
            or Prompt.ask(
                "界面语言 / UI language",
                choices=["zh-CN", "en-US"],
                default=getattr(current, "ui_language", "zh-CN"),
                console=console,
            ),
        )
        ui_language = ui_language or getattr(current, "ui_language", "zh-CN")
        chat_layout = Prompt.ask(
            "聊天布局 / Chat layout",
            choices=["compact", "split", "plain"],
            default=getattr(current, "chat_layout", "compact"),
            console=console,
        )
        response_language = Prompt.ask(
            "模型回复语言 / Model response language",
            choices=["zh-CN", "en-US"],
            default=current.language,
            console=console,
        )
    return PreferencesConfig(
        output_format=current.output_format,
        language=response_language,
        ui_language=ui_language,
        chat_layout=chat_layout,
        auto_publish_comment=current.auto_publish_comment,
        hybrid_strategy=getattr(current, "hybrid_strategy", "balanced"),
        max_cost_per_review=getattr(current, "max_cost_per_review", 0.50),
    )


def _prompt_preferences(console: Console, current: PreferencesConfig) -> PreferencesConfig:
    _render_section_header(
        console,
        "输出偏好",
        "输出格式和默认发布行为会优先读取配置文件，并允许命令行参数覆盖。",
        language=getattr(current, "ui_language", "zh-CN"),
        step=6,
        title_en="OUTPUT PREFERENCES",
        subtitle_en="Choose the default output format and publishing behavior.",
    )
    language = getattr(current, "ui_language", "zh-CN")
    import sys

    if sys.stdin.isatty() and sys.stdout.isatty():
        output_format = _pixel_select(
            title=tr(language, "默认输出格式", "DEFAULT OUTPUT FORMAT"),
            text=tr(language, "选择默认审查输出", "Select default review output"),
            values=[("terminal", "Terminal"), ("markdown", "Markdown"), ("json", "JSON")],
            default=current.output_format,
            language=language,
        )
        publish_value = _pixel_select(
            title=tr(language, "自动发布评论", "AUTO-PUBLISH COMMENT"),
            text=tr(
                language,
                "审查完成后自动发布 GitHub 评论？",
                "Publish a GitHub comment after review?",
            ),
            values=[("yes", tr(language, "是", "Yes")), ("no", tr(language, "否", "No"))],
            default="yes" if current.auto_publish_comment else "no",
            language=language,
        )
        auto_publish_comment = publish_value == "yes"
    else:
        output_format = Prompt.ask(
            tr(language, "默认输出格式", "Default output format"),
            choices=["terminal", "markdown", "json"],
            default=current.output_format,
            console=console,
        )
        auto_publish_comment = Confirm.ask(
            tr(
                language,
                "审查完成后默认自动发布 GitHub 评论？",
                "Publish a GitHub comment automatically after review?",
            ),
            default=current.auto_publish_comment,
            console=console,
        )
    return PreferencesConfig(
        output_format=output_format,
        language=current.language,
        ui_language=getattr(current, "ui_language", "zh-CN"),
        chat_layout=getattr(current, "chat_layout", "compact"),
        auto_publish_comment=auto_publish_comment,
        hybrid_strategy=getattr(current, "hybrid_strategy", "balanced"),
        max_cost_per_review=getattr(current, "max_cost_per_review", 0.50),
    )


def _render_config_summary(
    console: Console,
    provider_config: ProviderConfig,
    github_token: str,
    preferences: PreferencesConfig,
) -> None:
    language = getattr(preferences, "ui_language", "zh-CN")
    model = provider_config.models[provider_config.default_model]
    summary_rows = [
        f"{tr(language, '供应商', 'Provider'):<24} {provider_config.display_name}",
        f"{tr(language, '默认模型', 'Default model'):<24} {provider_config.default_model}",
        f"{tr(language, '运行策略', 'Runtime strategy'):<24} {getattr(preferences, 'hybrid_strategy', 'remote_only')}",
        f"{tr(language, '上下文窗口', 'Context window'):<24} {model.context_window}",
        f"{tr(language, '最大输出', 'Max output'):<24} {model.max_output}",
        f"{tr(language, 'API 端点', 'API endpoint'):<24} {provider_config.base_url or '<custom>'}",
        f"{tr(language, '协议格式', 'Protocol'):<24} {provider_config.api_format}",
        f"{tr(language, 'GitHub Token', 'GitHub token'):<24} {mask_api_key(github_token)}",
        f"{tr(language, '默认输出', 'Default output'):<24} {preferences.output_format}",
        f"{tr(language, '界面语言', 'UI language'):<24} {getattr(preferences, 'ui_language', 'zh-CN')}",
        f"{tr(language, '模型回复语言', 'Model language'):<24} {preferences.language}",
        f"{tr(language, '聊天布局', 'Chat layout'):<24} {getattr(preferences, 'chat_layout', 'compact')}",
    ]
    pixel_print_frame(
        console,
        tr(language, "配置摘要", "CONFIGURATION SUMMARY"),
        summary_rows,
        width=92,
        border_style="bright_green",
    )


def _validate_api_key_input(provider_name: str, api_key: str) -> None:
    if not api_key.strip():
        raise ConfigValidationError("API Key 不能为空。")
    if provider_name in {"anthropic", "openai", "deepseek", "qwen"} and len(api_key.strip()) < 8:
        raise ConfigValidationError("API Key 长度过短，请确认输入是否完整。")


def _run_provider_validation(
    console: Console,
    provider: ModelProviderConfig,
    config_path: Path,
    language: str = "zh-CN",
) -> None:
    validation_steps = [
        tr(language, "检查 API Key 输入", "Check API key input"),
        tr(language, "验证供应商配置", "Validate provider configuration"),
        tr(language, "检查模型参数", "Check model parameters"),
        tr(language, "生成配置预览", "Generate configuration preview"),
    ]
    completed_messages = [
        tr(language, "API Key 输入检查通过", "API key input passed"),
        tr(language, "供应商配置验证通过", "Provider configuration passed"),
        tr(language, "模型参数检查通过", "Model parameters passed"),
        tr(language, "配置预览生成完成", "Configuration preview generated"),
    ]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=24),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
        transient=True,
    ) as progress:
        task_id = progress.add_task(
            tr(language, "正在验证配置...", "Validating configuration..."),
            total=len(validation_steps),
        )
        for index, step in enumerate(validation_steps):
            progress.update(
                task_id,
                description=f"{tr(language, '正在验证配置...', 'Validating configuration...')} {step}",
            )
            if index == 0 and provider.name.lower() not in {"ollama", "local"}:
                _validate_api_key_input(provider.name, provider.api_key)
            elif index == 1:
                provider.validate()
            elif index == 2:
                if provider.name == "custom" and provider.base_url.strip() == "":
                    raise ConfigValidationError("自定义供应商必须配置 Base URL。")
            progress.advance(task_id)
            console.print(f"[green]✓[/green] {completed_messages[index]}")

    pixel_print_frame(
        console,
        tr(language, "验证配置", "VALIDATE CONFIGURATION"),
        [
            f"{tr(language, '供应商', 'Provider'):<24} {provider.display_name}",
            f"{tr(language, '模型', 'Model'):<24} {provider.model_name}",
            f"{tr(language, 'API 端点', 'API endpoint'):<24} {provider.base_url or '<not set>'}",
            f"{tr(language, '配置文件', 'Config file'):<24} {config_path}",
        ],
        width=92,
        border_style="bright_green",
    )


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


def _render_completion(console: Console, config_path: Path, language: str = "zh-CN") -> None:
    rows = [
        tr(language, "✓ 配置已完成", "✓ CONFIGURATION READY"),
        "",
        tr(language, "下一步：", "Next:"),
        tr(language, "pr-review chat          - 打开 Chat", "pr-review chat          - Open Chat"),
        tr(
            language, "pr-review demo          - 离线演示", "pr-review demo          - Offline Demo"
        ),
        tr(
            language,
            "pr-review config test   - 验证配置",
            "pr-review config test   - Verify config",
        ),
        tr(
            language,
            "pr-review history       - 查看历史",
            "pr-review history       - Review history",
        ),
        "",
        tr(language, f"配置文件：{config_path}", f"Config file: {config_path}"),
    ]
    pixel_print_frame(console, "PIXEL SETUP COMPLETE", rows, width=92, border_style="bright_green")


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
    progress_console: Console | None = None,
    use_hybrid: bool = True,
    stage_callback: Callable[[str, str], None] | None = None,
    progress_callback: Callable[[str, str], None] | None = None,
    file_done_callback: Callable[[str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    file_result_callback: Callable[[dict], None] | None = None,
) -> ReviewArtifacts:
    """Run a review with terminal guidance and animated progress when interactive.

    `file_result_callback(payload)` is optional and forwarded verbatim to the
    orchestrator (contract §10.2): filename / status / findings_count /
    duration_ms / error. Existing callers keep working unchanged.
    """
    app_config = config or AppConfig.load()

    # 根据配置决定使用混合编排器还是标准编排器
    orchestrator: ReviewOrchestrator | HybridReviewOrchestrator
    if use_hybrid and hasattr(app_config.preferences, "hybrid_strategy"):
        orchestrator = HybridReviewOrchestrator(app_config)
    else:
        orchestrator = ReviewOrchestrator(app_config)
    animate = progress_console is not None
    progress = None
    task_id = None
    started = time.perf_counter()
    stage_events: list[tuple[str, str, float]] = []
    total_review_files = 0
    completed_review_files = 0
    provider_label = (
        app_config._active_provider_config().display_name or app_config.ai_client.provider
    )
    model_label = app_config.ai_client.model
    stage_labels = {
        "fetching": ("获取 PR 数据", "正在连接 GitHub，读取 PR 元数据、Diff 与文件内容"),
        "filtering": ("过滤变更文件", "根据规则跳过文档、测试和无关文件"),
        "context": ("构建代码上下文", "提取 imports、函数、类和语法结构"),
        "reviewing": ("执行 AI 审查", f"{provider_label} 正在分析变更文件并生成结构化 Finding"),
        "cross_file": ("分析跨文件影响", "检查接口、签名和调用方是否受到影响"),
        "persisting": ("保存审查记录", "正在写入本地 SQLite 历史与反馈数据"),
    }

    if animate:
        animated_console = progress_console
        assert animated_console is not None
        animated_console.print(
            Panel.fit(
                "[bold]开始 AI PR 审查[/bold]\n"
                f"流程：抓取 → 规划 → 规则 / AST → {provider_label} ({model_label}) → 证据校验 → 历史复盘",
                border_style="blue",
            )
        )
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.fields[stage]}[/bold cyan]"),
            BarColumn(bar_width=26),
            TextColumn("{task.fields[detail]}"),
            TextColumn("[dim]{task.fields[elapsed]}[/dim]"),
            console=animated_console,
            transient=False,
        )
        task_id = progress.add_task(
            "review", total=100, stage="准备中", detail="正在初始化审查管线", elapsed="0.0s"
        )
        progress.start()

    def update(stage: str, detail: str = "") -> None:
        nonlocal total_review_files
        label, default_detail = stage_labels.get(stage, (stage, detail or "正在处理"))
        text = detail or default_detail
        context_match = re.search(r"为 (\d+) 个文件", text)
        if context_match:
            total_review_files = int(context_match.group(1))

        elapsed = time.perf_counter() - started
        stage_events.append((label, text, elapsed))
        if stage_callback is not None:
            stage_callback(stage, text)

        if progress is not None and task_id is not None:
            # 更精确的进度权重分配
            stage_ranges = {
                "fetching": (0, 5),  # 0% ~ 5%
                "filtering": (5, 10),  # 5% ~ 10%
                "context": (10, 20),  # 10% ~ 20%
                "reviewing": (20, 85),  # 20% ~ 85% (主要阶段)
                "cross_file": (85, 93),  # 85% ~ 93%
                "persisting": (93, 99),  # 93% ~ 99%
            }

            start_pct, end_pct = stage_ranges.get(stage, (0, 0))

            if stage == "reviewing" and total_review_files > 0:
                # 在 reviewing 阶段根据文件完成情况动态计算进度
                file_progress = completed_review_files / total_review_files
                completed = start_pct + round((end_pct - start_pct) * file_progress)
                text = f"{text} · 已完成 {completed_review_files}/{total_review_files} 个文件"
            else:
                # 其他阶段直接使用起始进度
                completed = start_pct

            progress.update(
                task_id,
                completed=min(99, completed),
                stage=label,
                detail=text,
                elapsed=f"{elapsed:.1f}s",
            )
        if verbose and not animate:
            click.echo(f"{label}：{text}")

    def file_started(filename: str, active_model: str) -> None:
        update("reviewing", f"正在分析 {filename} · {provider_label} / {active_model}")
        if progress_callback is not None:
            progress_callback(filename, active_model)

    def file_done(filename: str) -> None:
        nonlocal completed_review_files
        completed_review_files += 1
        update("reviewing", f"已完成 {filename}，继续处理下一个文件")
        if file_done_callback is not None:
            file_done_callback(filename)

    try:
        result = await orchestrator.review(
            pr_url,
            model=model,
            progress_callback=file_started,
            file_done_callback=file_done,
            stage_callback=update,
            cancel_check=cancel_check,
            file_result_callback=file_result_callback,
        )
        if progress is not None and task_id is not None:
            progress.update(
                task_id,
                completed=100,
                stage="审查完成",
                detail="Finding、证据与历史记录已准备就绪",
                elapsed=f"{time.perf_counter() - started:.1f}s",
            )
            progress.stop()
            if animated_console is not None:
                # 计算每个阶段的实际耗时
                stage_durations = {}
                prev_elapsed = 0.0
                for i, (label, detail, elapsed_seconds) in enumerate(stage_events):
                    if label not in stage_durations:
                        duration = elapsed_seconds - prev_elapsed
                        stage_durations[label] = (detail, duration)
                        prev_elapsed = elapsed_seconds

                stage_table = Table(title="审查阶段耗时", box=box.SIMPLE, header_style="bold cyan")
                stage_table.add_column("状态", width=4)
                stage_table.add_column("阶段", style="cyan")
                stage_table.add_column("说明", style="dim")
                stage_table.add_column("耗时", justify="right", style="green")

                for label, (detail, duration) in stage_durations.items():
                    # 截断过长的说明文字
                    short_detail = detail[:60] + "..." if len(detail) > 60 else detail
                    stage_table.add_row("✓", label, short_detail, f"{duration:.1f}s")

                animated_console.print(stage_table)
                animated_console.print(
                    f"\n[bold green]✓[/bold green] 审查完成，总耗时 [bold]{time.perf_counter() - started:.1f}s[/bold]"
                )
        return result
    finally:
        if progress is not None and progress.live is not None:
            progress.stop()


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
        "validation": artifacts.validation_summary,
    }
    if artifacts.review_plan is not None:
        payload["plan"] = artifacts.review_plan.model_dump(mode="json")
    return payload


def _build_filter_summary_markdown(artifacts: ReviewArtifacts) -> str:
    filter_result = artifacts.filter_result
    if hasattr(filter_result, "excluded_reason_counts"):
        reason_counts = filter_result.excluded_reason_counts()
    else:
        reason_counts = filter_result.to_dict().get("excluded_reason_counts", {})
    if not reason_counts:
        return ""
    total_files = getattr(
        filter_result, "total_files", filter_result.to_dict().get("total_files", 0)
    )
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
    sections = [rendered]
    if artifacts.review_plan is not None:
        plan = artifacts.review_plan
        sections.append(
            "\n".join(
                [
                    "## Review Plan",
                    "",
                    f"- **Risk Level**: {plan.risk_level}",
                    f"- **Risk Categories**: {', '.join(plan.risk_categories)}",
                    f"- **Strategies**: {', '.join(plan.strategies)}",
                    f"- **Cross-file Analysis**: {'enabled' if plan.requires_cross_file_analysis else 'not required'}",
                ]
            )
        )
    if artifacts.validation_summary:
        sections.append(
            "\n".join(
                [
                    "## Evidence Validation",
                    "",
                    *(
                        f"- **{status}**: {count}"
                        for status, count in sorted(artifacts.validation_summary.items())
                    ),
                ]
            )
        )
    if filter_summary:
        sections.append(filter_summary)
    return "\n\n".join(section for section in sections if section)


def render_github_comment_report(
    artifacts: ReviewArtifacts, config: AppConfig | None = None
) -> str:
    app_config = config or AppConfig.load()

    def _reviewed_at_now() -> str:
        """Reuse the publish-path formatter so both producers agree exactly."""
        from ai_pr_review.services.publish_service import format_reviewed_at

        return format_reviewed_at(datetime.now(timezone.utc))

    return ReportRenderer(app_config.report_renderer).render_github_comment(
        artifacts.review_result or ReviewResult(summary="", findings=[]),
        artifacts.pr_data,
        meta=GitHubCommentMeta(
            language=getattr(app_config.preferences, "ui_language", "zh-CN"),
            run_id=artifacts.run_id or "",
            model=app_config.ai_client.model or "",
            duration_seconds=artifacts.duration_seconds,
            cost=artifacts.total_cost,
            head_sha=getattr(artifacts.pr_data, "head_sha", "") or "",
            # Same formatter as the publish path so the two GitHub comment
            # producers cannot drift on the timestamp format (P6 follow-up).
            reviewed_at=_reviewed_at_now(),
            files_reviewed=artifacts.filter_result.included_count,
            files_skipped=artifacts.filter_result.excluded_count,
            # A fork's head commit lives in another repository, so blob links
            # would 404; PRData knows the head repository (§4.2).
            from_fork=artifacts.pr_data.is_fork,
        ),
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
    # Render once and guard by the exact report content on this Console. The
    # same review can pass through two adapters with different artifact/run
    # wrappers; content-based deduplication catches both paths without hiding
    # a later, genuinely different review.
    app_config = config or AppConfig.load()
    rendered = ReportRenderer(app_config.report_renderer).render_terminal(
        artifacts.review_result or ReviewResult(summary="", findings=[]),
        artifacts.pr_data,
        language=getattr(app_config.preferences, "ui_language", "zh-CN"),
    )
    fingerprint = hash(rendered)
    rendered_fingerprints = getattr(console, "_ai_pr_rendered_fingerprints", set())
    if fingerprint in rendered_fingerprints:
        return
    rendered_fingerprints.add(fingerprint)
    setattr(console, "_ai_pr_rendered_fingerprints", rendered_fingerprints)
    if artifacts.run_id:
        _RENDERED_RUN_IDS.add(artifacts.run_id)
    console.print(rendered, end="")


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


def _missing_api_key_message(provider_name: str) -> str:
    resolved_provider_env_var = provider_env_var(provider_name)
    return (
        "模型供应商 API Key 未提供。请重新运行 `pr-review config` 并选择保存 API Key，"
        f"或设置环境变量 {resolved_provider_env_var} / AI_PR_REVIEW_API_KEY。"
    )


def _response_language_instruction(language: str) -> str:
    """根据语言设置生成模型回复语言指令。"""
    if language.lower().startswith("en"):
        return "Respond in English unless the user explicitly asks for another language."
    return "请默认使用中文回答，除非用户明确要求使用其他语言。"


def _chat_title(config: AppConfig) -> str:
    """生成聊天窗口标题，显示供应商名和模型名。"""
    provider = config._active_provider_config()
    return f"AI PR Review Chat | {provider.display_name} / {provider.default_model}"


def _model_provider_hint(model_name: str) -> str | None:
    """Return the provider that owns a known or obviously local model name."""
    for provider_name, models in PROVIDER_MODEL_PRESETS.items():
        if model_name in models:
            return provider_name

    # Ollama model tags commonly use a local quantization/tag suffix. Keep this
    # deliberately conservative so custom remote model IDs remain supported.
    lowered = model_name.lower()
    local_prefixes = (
        "qwen",
        "llama",
        "mistral",
        "mixtral",
        "gemma",
        "phi",
        "deepseek-r1",
        "deepseek-coder",
        "codellama",
        "yi:",
    )
    if ":" in model_name and lowered.startswith(local_prefixes):
        return "ollama"
    return None


def _set_active_model(config: AppConfig, model_name: str) -> None:
    """Set the active model without silently changing its provider."""
    model_name = model_name.strip()
    if not model_name:
        raise click.ClickException("模型名称不能为空。")

    # Write to the *active* slot: in `local_only` mode the primary slot is the
    # remote one, so using it here reported success while changing nothing and
    # polluted the cloud slot with a local model name.
    slot = config._active_provider_config()
    current_provider = slot.name.lower().strip()
    expected_provider = _model_provider_hint(model_name)
    if expected_provider and expected_provider != current_provider:
        provider_label = slot.display_name or current_provider
        if expected_provider == "ollama":
            raise click.ClickException(
                f"模型 {model_name} 是本地 Ollama 模型，但当前 Provider 是 {provider_label}。\n"
                "方案 A 不会自动切换模型后端。请先运行 `pr-review config`，选择 Ollama，"
                "再选择该模型；也可以先执行 `pr-review local-model check` 验证 Ollama。"
            )
        raise click.ClickException(
            f"模型 {model_name} 属于 {expected_provider}，但当前 Provider 是 {provider_label}。\n"
            "请先运行 `pr-review config` 切换到对应 Provider，再设置模型。"
        )

    if model_name not in slot.models:
        slot.models[model_name] = ProviderModelConfig(name=model_name)
    slot.default_model = model_name
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


def _check_config_status(config: AppConfig) -> dict[str, bool]:
    """检查配置完成状态。"""
    active = config._active_provider_config()
    provider_name = active.name.lower().strip()
    local_provider = provider_name in {"ollama", "local"}
    return {
        "api_key_configured": local_provider or bool(active.api_key),
        "github_token_configured": bool(config._resolve_github_token()),
        "provider_valid": bool(active.name and config.ai_client.model),
    }


def _render_config_assistant_welcome(config: AppConfig) -> str:
    """渲染配置助手欢迎信息。"""
    status = _check_config_status(config)

    message = "## 🔧 配置助手\n\n"
    message += "检测到当前配置尚未完成。我可以帮助你完成：\n\n"

    if not status["api_key_configured"]:
        message += "- ❌ **配置模型供应商** - 需要 API Key\n"
    else:
        message += "- ✅ 模型供应商已配置\n"

    if not status["github_token_configured"]:
        message += "- ❌ **配置 GitHub Token** - 用于访问 PR\n"
    else:
        message += "- ✅ GitHub Token 已配置\n"

    message += "\n**快捷操作：**\n\n"
    message += "1. 输入 `开始配置` 或 `配置模型` - 配置 API Key\n"
    message += "2. 输入 `配置 GitHub` - 配置 GitHub Token\n"
    message += "3. 输入 `检查环境` - 查看当前配置状态\n"
    message += "4. 输入 `运行 demo` - 运行离线演示\n"
    message += "5. 输入 `跳过配置` - 直接进入普通聊天\n"

    return message


def _handle_configure_provider_action(
    action: ChatAction,
    context: ChatContext,
    config: AppConfig,
    console: Console,
) -> ActionResult:
    """Handle provider configuration."""
    from ai_pr_review.config_wizard import apply_wizard_configuration

    try:
        console.print("\n[bold cyan]配置模型供应商[/bold cyan]\n")

        # 简化的配置流程
        console.print("请选择供应商：")
        console.print("1. DeepSeek (推荐)")
        console.print("2. OpenAI")
        console.print("3. Anthropic")
        console.print("4. Ollama (本地)")
        console.print("5. 其他")

        choice = Prompt.ask("选择", choices=["1", "2", "3", "4", "5"], default="1")

        provider_map = {
            "1": "deepseek",
            "2": "openai",
            "3": "anthropic",
            "4": "ollama",
            "5": "custom",
        }

        provider_name = provider_map[choice]

        if provider_name == "ollama":
            return ActionResult(
                action="configure_provider",
                ok=True,
                message="Ollama 无需 API Key，已配置本地模型",
                data={"provider": "ollama"},
            )

        # 请求 API Key
        console.print(f"\n请输入 {provider_name} 的 API Key：")
        api_key = Prompt.ask("API Key", password=True)

        if not api_key or not api_key.strip():
            return ActionResult(
                action="configure_provider",
                ok=False,
                message="API Key 不能为空",
                error_code="empty_api_key",
            )

        return ActionResult(
            action="configure_provider",
            ok=True,
            message=f"配置成功！供应商: {provider_name}",
            data={"provider": provider_name, "api_key": "***"},
        )

    except Exception as exc:
        return ActionResult(
            action="configure_provider",
            ok=False,
            message=f"配置失败: {exc}",
            error_code="configure_failed",
        )


def _handle_configure_github_action(
    action: ChatAction,
    context: ChatContext,
    config: AppConfig,
    console: Console,
) -> ActionResult:
    """Handle GitHub token configuration."""
    try:
        console.print("\n[bold cyan]配置 GitHub Token[/bold cyan]\n")
        console.print("GitHub Token 用于访问私有仓库和发布评论。")
        console.print("获取 Token：https://github.com/settings/tokens\n")

        token = Prompt.ask("GitHub Token", password=True)

        if not token or not token.strip():
            return ActionResult(
                action="configure_github",
                ok=False,
                message="Token 不能为空",
                error_code="empty_token",
            )

        return ActionResult(
            action="configure_github",
            ok=True,
            message="GitHub Token 配置成功！",
            data={"token": "***"},
        )

    except Exception as exc:
        return ActionResult(
            action="configure_github",
            ok=False,
            message=f"配置失败: {exc}",
            error_code="configure_failed",
        )


async def _route_local_chat_action(
    config: AppConfig, user_text: str, context: ChatContext
) -> ChatAction:
    """Classify a local Chat request without sending it to a remote API."""
    provider_config = ModelProviderConfig.from_name("ollama")
    provider = create_model_provider(provider_config)
    router = ChatActionRouter(provider, model_name=provider_config.model_name)
    return await router.route(user_text, context)


# ========== Chat Action Handlers ==========


def _handle_chat_action(action: ChatAction, context: ChatContext) -> ActionResult:
    """Handle normal chat - just pass through."""
    return ActionResult(
        action="chat",
        ok=True,
        message="Chat message handled by normal flow",
    )


async def _handle_start_review_action(
    action: ChatAction,
    context: ChatContext,
    config: AppConfig,
    console: Console,
) -> ActionResult:
    """Execute a full PR review."""
    pr_url = action.arguments.get("pr_url")
    if not pr_url:
        return ActionResult(
            action="start_review",
            ok=False,
            message="缺少 PR URL 参数",
            error_code="missing_pr_url",
        )

    try:
        # Update context state
        context.current_pr_url = pr_url
        context.state = AgentState.REVIEW_RUNNING

        # Execute review
        artifacts = await asyncio.to_thread(
            run_review,
            pr_url,
            model=None,
            verbose=False,
            config=config,
            progress_console=console,
        )

        # Update context with results
        context.current_run_id = artifacts.run_id
        context.state = AgentState.REVIEW_COMPLETED

        finding_count = len(artifacts.review_result.findings) if artifacts.review_result else 0
        return ActionResult(
            action="start_review",
            ok=True,
            message=f"审查完成，发现 {finding_count} 个问题",
            data={
                "run_id": artifacts.run_id,
                "pr_url": pr_url,
                "finding_count": finding_count,
                "cost": artifacts.total_cost,
                "duration": artifacts.duration_seconds,
            },
        )
    except Exception as exc:
        context.state = AgentState.ERROR
        context.last_error = str(exc)
        return ActionResult(
            action="start_review",
            ok=False,
            message=f"审查失败: {exc}",
            error_code="review_failed",
        )


async def _handle_create_review_plan_action(
    action: ChatAction,
    context: ChatContext,
    config: AppConfig,
) -> ActionResult:
    """Generate a review plan without AI calls."""
    pr_url = action.arguments.get("pr_url")
    if not pr_url:
        return ActionResult(
            action="create_review_plan",
            ok=False,
            message="缺少 PR URL 参数",
            error_code="missing_pr_url",
        )

    try:
        from ai_pr_review.services.review_orchestrator import ReviewOrchestrator

        orchestrator = ReviewOrchestrator(config)
        artifacts = await orchestrator.plan_only(pr_url)

        plan = artifacts.review_plan
        if not plan:
            return ActionResult(
                action="create_review_plan",
                ok=False,
                message="计划生成失败",
                error_code="plan_generation_failed",
            )

        context.current_pr_url = pr_url
        context.state = AgentState.REVIEW_PLANNING

        return ActionResult(
            action="create_review_plan",
            ok=True,
            message=f"已生成审查计划，风险等级: {plan.risk_level}",
            data={
                "pr_url": pr_url,
                "risk_level": plan.risk_level,
                "risk_categories": plan.risk_categories,
                "priority_files": plan.priority_files,
                "estimated_file_reviews": plan.estimated_file_reviews,
                "strategies": plan.strategies,
            },
        )
    except Exception as exc:
        context.state = AgentState.ERROR
        context.last_error = str(exc)
        return ActionResult(
            action="create_review_plan",
            ok=False,
            message=f"计划生成失败: {exc}",
            error_code="plan_failed",
        )


def _handle_list_history_action(
    action: ChatAction,
    context: ChatContext,
    config: AppConfig,
) -> ActionResult:
    """List review history."""
    try:
        from ai_pr_review.services.result_store import ResultStore

        store = ResultStore(config.result_store)
        limit = action.arguments.get("limit", 10)
        runs = store.list_runs(limit=limit)

        return ActionResult(
            action="list_history",
            ok=True,
            message=f"找到 {len(runs)} 条审查记录",
            data={"runs": runs, "count": len(runs)},
        )
    except Exception as exc:
        return ActionResult(
            action="list_history",
            ok=False,
            message=f"查询历史失败: {exc}",
            error_code="history_query_failed",
        )


def _handle_analyze_history_action(
    action: ChatAction,
    context: ChatContext,
    config: AppConfig,
) -> ActionResult:
    """Analyze review history trends with AI."""
    try:
        from ai_pr_review.services.result_store import ResultStore

        store = ResultStore(config.result_store)
        limit = action.arguments.get("limit", 20)
        runs = store.list_runs(limit=limit)

        if not runs:
            return ActionResult(
                action="analyze_history",
                ok=False,
                message="没有历史记录可分析",
                error_code="no_history",
            )

        # Build analysis prompt
        prompt = f"""请分析最近 {len(runs)} 次代码审查记录，给出趋势报告。

**审查记录摘要**:
"""
        for i, run in enumerate(runs[:10], 1):  # 只显示前10条
            prompt += f"\n{i}. {run.get('timestamp', 'N/A')}"
            prompt += f"\n   - PR: {run.get('pr_url', 'N/A')}"
            prompt += f"\n   - 问题数: {run.get('finding_count', 0)}"
            prompt += f"\n   - 成本: ${run.get('cost', 0):.4f}"
            prompt += f"\n   - 模型: {run.get('model', 'N/A')}"

        prompt += """

请分析并回答：

1. **最常见的问题类型** - 列出前5种最常出现的问题类别
2. **风险趋势** - 问题数量是增加还是减少？
3. **成本分析** - 平均每次审查成本，是否有优化空间？
4. **改进建议** - 给团队 3-5 条具体的代码质量改进建议

请用中文回答，简洁清晰，重点突出。"""

        # Call AI model
        from ai_pr_review.services.ai_client import AIClient

        ai_client = AIClient(config.ai_client)
        messages = [{"role": "user", "content": prompt}]

        import asyncio

        response = asyncio.run(ai_client.chat(messages))
        analysis = response.get("text", "")

        return ActionResult(
            action="analyze_history",
            ok=True,
            message=analysis,
            data={
                "run_count": len(runs),
                "analysis": analysis,
            },
        )
    except Exception as exc:
        return ActionResult(
            action="analyze_history",
            ok=False,
            message=f"分析失败: {exc}",
            error_code="analysis_failed",
        )


def _handle_explain_finding_action(
    action: ChatAction,
    context: ChatContext,
    config: AppConfig,
) -> ActionResult:
    """Explain a specific finding with AI analysis."""
    run_id = action.arguments.get("run_id") or context.current_run_id
    finding_id = action.arguments.get("finding_id")

    if not run_id:
        return ActionResult(
            action="explain_finding",
            ok=False,
            message="需要提供 run_id 或在当前会话中有活跃的审查",
            error_code="missing_run_id",
        )

    try:
        from ai_pr_review.services.result_store import ResultStore

        store = ResultStore(config.result_store)
        result = store.get_result(run_id)

        if not result:
            return ActionResult(
                action="explain_finding",
                ok=False,
                message=f"未找到审查记录: {run_id}",
                error_code="run_not_found",
            )

        # Filter to specific finding if provided
        findings = result.get("findings", [])
        if finding_id:
            findings = [f for f in findings if f.get("finding_id") == finding_id]
            if not findings:
                return ActionResult(
                    action="explain_finding",
                    ok=False,
                    message=f"未找到 Finding: {finding_id}",
                    error_code="finding_not_found",
                )

        if not findings:
            return ActionResult(
                action="explain_finding",
                ok=False,
                message="没有可解释的 Finding",
                error_code="no_findings",
            )

        # Use AI to explain the finding
        finding = findings[0]  # Explain the first/selected finding

        # Build explanation prompt
        prompt = f"""请用用户能理解的语言详细解释这个代码问题：

**问题标题**: {finding.get('title', 'N/A')}
**文件**: {finding.get('file', 'N/A')}:{finding.get('line_start', 'N/A')}-{finding.get('line_end', 'N/A')}
**严重程度**: {finding.get('severity', 'N/A')}
**分类**: {finding.get('category', 'N/A')}

**代码片段**:
```
{finding.get('snippet', 'N/A')}
```

**原始描述**: {finding.get('description', 'N/A')}

**证据状态**: {finding.get('evidence_status', 'N/A')}
**置信度**: {finding.get('confidence', 'N/A')}

请按以下结构解释：

1. **这是什么问题？** - 用简单的语言描述问题本质
2. **为什么这是个问题？** - 解释潜在的风险和后果
3. **如何修复？** - 提供具体的修复建议和代码示例
4. **证据分析** - 根据证据状态评估这个问题的可靠性

请用中文回答，语言简洁清晰。"""

        # Call AI model
        from ai_pr_review.services.ai_client import AIClient

        ai_client = AIClient(config.ai_client)
        messages = [{"role": "user", "content": prompt}]

        import asyncio

        response = asyncio.run(ai_client.chat(messages))
        explanation = response.get("text", "")

        return ActionResult(
            action="explain_finding",
            ok=True,
            message=explanation,
            data={
                "finding": finding,
                "explanation": explanation,
                "run_id": run_id,
            },
        )
    except Exception as exc:
        return ActionResult(
            action="explain_finding",
            ok=False,
            message=f"解释失败: {exc}",
            error_code="explain_failed",
        )


def _handle_check_environment_action(
    action: ChatAction,
    context: ChatContext,
    config: AppConfig,
) -> ActionResult:
    """Check environment and configuration status."""
    try:
        status = {
            "provider": config._active_provider_config().display_name or config.ai_client.provider,
            "model": config.ai_client.model,
            "api_key_configured": _check_config_status(config)["api_key_configured"],
            "github_token_configured": bool(config._resolve_github_token()),
            "language": config.preferences.language,
        }

        return ActionResult(
            action="check_environment",
            ok=True,
            message="环境检查完成",
            data=status,
        )
    except Exception as exc:
        return ActionResult(
            action="check_environment",
            ok=False,
            message=f"环境检查失败: {exc}",
            error_code="check_failed",
        )


def _handle_cancel_review_action(
    action: ChatAction,
    context: ChatContext,
) -> ActionResult:
    """Cancel current review."""
    context.state = AgentState.READY
    context.current_pr_url = None
    context.current_action = None

    return ActionResult(
        action="cancel_review",
        ok=True,
        message="已取消当前操作",
    )


def _format_chat_action_preview(action: ChatAction) -> str:
    """Render a safe, non-executing Action preview for the current rollout."""
    labels = {
        "start_review": "开始完整审查",
        "create_review_plan": "生成审查计划",
        "explain_finding": "解释 Finding",
        "list_history": "查询审查历史",
        "check_environment": "检查运行环境",
        "cancel_review": "取消当前审查",
        "chat": "普通对话",
    }
    title = labels.get(action.action, action.action)
    confirmation = "需要确认后执行" if action.requires_confirmation else "无需确认"
    args = json.dumps(action.arguments, ensure_ascii=False) if action.arguments else "无"
    return (
        f"已识别操作：**{title}**\n\n"
        f"- 来源：{action.source}\n"
        f"- 风险级别：{action.risk_level}\n"
        f"- 执行策略：{confirmation}\n"
        f"- 参数：`{args}`\n\n"
        "当前版本已完成意图识别与 Action 路由，执行器已集成。"
    )


async def _send_chat_message(config: AppConfig, messages: list[dict[str, Any]]) -> str:
    """发送聊天消息到模型并返回回复文本。"""
    provider_config = config.ai_client.model_provider
    if not provider_config.api_key and provider_config.name.lower() not in {"ollama", "local"}:
        raise click.ClickException(_missing_api_key_message(provider_config.name))
    provider = create_model_provider(provider_config)
    chat_options: dict[str, Any] = {
        "system_prompt": _response_language_instruction(config.preferences.language),
        "max_tokens": config.ai_client.max_tokens,
        "timeout_seconds": config.ai_client.timeout_seconds,
    }
    if provider_config.name.lower() in {"ollama", "local"}:
        # Keep local thinking models in the content channel for ordinary Chat.
        chat_options["reasoning_effort"] = "none"
    response = await provider.chat(
        messages,
        **chat_options,
    )
    return response.text


def _print_chat_message(console: Console, role: str, text: str, *, layout: str) -> None:
    """打印聊天消息，支持 plain/compact/split 三种布局。"""
    if layout == "plain":
        style = "bold white"
        console.print(f"[{style}]{role}:[/{style}] {text}")
        return
    if role == "You":
        border_style = "grey35"
        title_style = "bold white"
        icon = "YOU"
        subtitle = "input"
    else:
        border_style = "white"
        title_style = "bold white"
        icon = "ASSISTANT"
        subtitle = "assistant"
    renderable = Markdown(text) if role == "Assistant" else text
    panel = Panel(
        renderable,
        title=f"[{title_style}]{icon}[/{title_style}]",
        subtitle=f"[dim]{subtitle}[/dim]",
        border_style=border_style,
        expand=layout == "split",
        padding=(0, 1),
        style="white on black",
    )
    console.print(panel)


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


def _extract_github_pr_url(text: str) -> str | None:
    """Extract a GitHub PR URL from plain text or Markdown link syntax."""
    match = re.search(
        r"https?://github\.com/[^/\s)\]]+/[^/\s)\]]+/pull/\d+(?:/[^\s)\]]*)?",
        text.strip(),
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return match.group(0).rstrip(".,;:，。；：")


def _is_github_pr_url(text: str) -> bool:
    return _extract_github_pr_url(text) is not None


def _handle_chat_slash_command(
    console: Console,
    config: AppConfig,
    config_path: Path | None,
    messages: list[dict[str, Any]],
    command_text: str,
    layout: str,
) -> bool:
    if handle_basic_chat_slash_command(
        console,
        config,
        config_path,
        messages,
        command_text,
        layout,
        clear_session=clear_chat_session,
        load_session=load_chat_session,
        save_session=save_chat_session,
        set_active_model=_set_active_model,
    ):
        return True

    parts = command_text.split(maxsplit=1)
    command = parts[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else ""
    if command == "/review":
        pr_url = _extract_github_pr_url(argument)
        if not pr_url:
            console.print("Usage: /review <PR_URL>", style="bold red")
            return True
        try:
            artifacts = asyncio.run(run_review(pr_url, model=config.ai_client.model, config=config))
            render_terminal_report(console, artifacts, config)
            console.print(
                f"Saved run {artifacts.run_id}  |  [green]SAVED[/green]  |  [cyan]COST[/cyan] ${artifacts.total_cost:.4f}  |  [cyan]DURATION[/cyan] {artifacts.duration_seconds:.2f}s"
            )
        except (PRFetcherError, AIClientError) as exc:
            console.print(Panel(f"Error: {exc}", title="Review Error", border_style="red"))
        return True
    return False


def _run_config_wizard(quick: bool, advanced: bool, save_key: bool | None) -> Path:
    console = Console()
    existing = AppConfig.load()
    _render_welcome(console, getattr(existing.preferences, "ui_language", "zh-CN"))
    runtime_mode, runtime_strategy, legacy_ui_language = _prompt_runtime_profile(
        console, existing.preferences
    )
    preferences = _prompt_interface_preferences(
        console, existing.preferences, initial_ui_language=legacy_ui_language
    )
    preferences.hybrid_strategy = runtime_strategy

    language = getattr(preferences, "ui_language", "zh-CN")
    provider_name = "ollama" if runtime_mode == "local" else _select_provider(console, language)
    provider = ModelProviderConfig.from_name(provider_name)
    api_key = "" if runtime_mode == "local" else _prompt_api_key(console, provider, language)
    selected_model = _prompt_provider_model(console, provider, api_key, language)
    base_url, api_format = _prompt_provider_settings(
        console, provider, quick=quick, language=language
    )
    headers: dict[str, str] = {}
    extra_params: dict[str, Any] = {}
    if advanced:
        headers = json_prompt("Headers JSON", default=provider.headers)
        extra_params = json_prompt("Extra params JSON", default=provider.extra_params)
    github_token = _prompt_github_token(console, existing.github_token, language)
    preferences = _prompt_preferences(console, preferences)
    if runtime_mode == "local":
        preferences.hybrid_strategy = "local_only"
    elif runtime_mode == "cloud":
        preferences.hybrid_strategy = "remote_only"
    else:
        preferences.hybrid_strategy = "balanced"

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

    config = apply_wizard_configuration(
        existing,
        final_provider=final_provider,
        selected_model=selected_model,
        github_token=github_token,
        preferences=preferences,
    )
    save_key = resolve_save_key_choice(console, save_key)

    # Enforce the selected runtime profile at the persistence boundary.
    if runtime_mode == "local":
        preferences.hybrid_strategy = "local_only"
    elif runtime_mode == "cloud":
        preferences.hybrid_strategy = "remote_only"
    else:
        preferences.hybrid_strategy = "balanced"

    config_path = DEFAULT_CONFIG_PATH
    _run_provider_validation(console, final_provider, config_path, language)
    _render_config_summary(console, config._active_provider_config(), github_token, preferences)
    config_path = config.save(save_key=save_key)
    _render_completion(console, config_path, language)
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


def _doctor_status(ok: bool | None) -> str:
    if ok is True:
        return "[green]✓ ready[/green]"
    if ok is False:
        return "[red]✗ unavailable[/red]"
    return "[yellow]! not configured[/yellow]"


def _path_writable(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        probe = path.parent / ".doctor-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


@main.command("doctor")
@click.option("--json-output", is_flag=True, help="Emit the diagnostic report as JSON.")
@click.pass_context
def doctor_command(ctx: click.Context, json_output: bool) -> None:
    """Check CLI, AI review, offline demo, and Web workbench readiness."""
    config_error = None
    config = None
    try:
        config = AppConfig.load(_config_path_from_context(ctx))
    except Exception as exc:
        config_error = str(exc)

    package_root = Path(__file__).resolve().parent
    web_static = package_root / "web_static"
    db_path = Path("~/.ai_pr_review/results.db").expanduser()
    store_detail = str(db_path)
    store_ok = False
    if config is not None:
        try:
            store = ResultStore(config.result_store)
            db_path = store.db_path
            store_detail = str(db_path)
            store_ok = True
        except Exception as exc:
            store_detail = str(exc)

    checks: list[dict[str, object]] = [
        {
            "key": "python",
            "label": "Python runtime",
            "ok": sys.version_info >= (3, 12),
            "detail": platform.python_version(),
        },
        {
            "key": "config",
            "label": "Configuration",
            "ok": config is not None,
            "detail": config_error or "resolved",
        },
        {
            "key": "github",
            "label": "GitHub token",
            "ok": bool(config and config._resolve_github_token()),
            "detail": (
                "configured"
                if config and config._resolve_github_token()
                else "offline demo remains available; set GITHUB_TOKEN for real PRs"
            ),
        },
        {
            "key": "provider",
            "label": "Model provider",
            "ok": bool(config and _check_config_status(config)["api_key_configured"]),
            "detail": (
                f"{config._active_provider_config().display_name} · {config.ai_client.model}"
                if config
                else "unavailable"
            ),
        },
        {"key": "sqlite", "label": "SQLite result store", "ok": store_ok, "detail": store_detail},
        {
            "key": "ast",
            "label": "AST parser",
            "ok": importlib.util.find_spec("tree_sitter") is not None,
            "detail": "optional enhancement",
        },
        {"key": "demo", "label": "Offline demo", "ok": True, "detail": "embedded fixture ready"},
        {
            "key": "web",
            "label": "Web workbench assets",
            "ok": (web_static / "index.html").exists(),
            "detail": str(web_static),
        },
    ]
    if json_output:
        click.echo(
            json.dumps(
                {"ok": all(item["ok"] is True for item in checks), "checks": checks},
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    console = Console()
    console.print(
        Panel.fit(
            "[bold]AI PR Review Assistant · Doctor[/bold]\nCLI-first readiness check",
            border_style="blue",
        )
    )
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Details")
    for item in checks:
        table.add_row(
            str(item["label"]),
            _doctor_status(item["ok"] if isinstance(item["ok"], bool) else None),
            str(item["detail"]),
        )
    console.print(table)
    if not checks[2]["ok"] or not checks[3]["ok"]:
        console.print("\n[yellow]真实 GitHub/模型配置未就绪，但离线演示仍可运行：[/yellow]")
        console.print("  pr-review demo")
        console.print("  pr-review benchmark --strategy all")
    else:
        console.print("\n[green]真实审查环境已就绪。[/green]")


@main.group("local-model")
def local_model_command() -> None:
    """Inspect and validate the local Ollama Chat Copilot model."""


@local_model_command.command("check")
@click.option("--json-output", is_flag=True, help="Emit the result as JSON.")
@click.option("--timeout", "timeout_seconds", default=5, show_default=True, type=int)
@click.pass_context
def local_model_check(ctx: click.Context, json_output: bool, timeout_seconds: int) -> None:
    """Check Ollama availability and installed local models."""
    config = AppConfig.load(_config_path_from_context(ctx))
    provider_config = ModelProviderConfig.from_name("ollama")
    local_slot = (
        config._active_provider_config()
        if config._active_provider_config().name.lower() in {"ollama", "local"}
        else config.local_provider
    )
    provider_config.model_name = local_slot.default_model
    provider_config.base_url = local_slot.base_url
    provider = create_model_provider(provider_config)
    payload: dict[str, object] = {
        "provider": "ollama",
        "base_url": provider_config.base_url,
        "model": provider_config.model_name,
        "available": False,
        "models": [],
        "error": None,
    }
    try:
        payload["available"] = awaitable_result(
            provider.health_check(timeout_seconds=timeout_seconds)
        )
        payload["models"] = awaitable_result(provider.list_models(timeout_seconds=timeout_seconds))
    except Exception as exc:  # noqa: BLE001 - CLI must present actionable diagnostics.
        payload["error"] = str(exc)
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if payload["available"]:
        click.echo(f"Ollama: ready ({provider_config.base_url})")
        click.echo(f"Installed models: {', '.join(payload['models']) or 'none'}")
        click.echo(f"Selected model: {provider_config.model_name}")
    else:
        click.echo(f"Ollama: unavailable ({payload['error'] or 'no response'})")
        raise click.ClickException("请启动 Ollama 后重试。")


def awaitable_result(awaitable: Any) -> Any:
    """Run a provider coroutine from the synchronous Click command."""
    return asyncio.run(awaitable)


def _config_path_from_context(ctx: click.Context | None) -> Path | None:
    if ctx is None or not isinstance(ctx.obj, dict):
        return None
    raw_path = ctx.obj.get("config_path")
    return raw_path if isinstance(raw_path, Path) else None


@main.command("review", hidden=True)
@click.argument("pr_url")
@click.option("--model", default=None, help="Override configured model name.")
@click.option(
    "--mode",
    type=click.Choice(["auto", "quality", "balanced", "cost", "local", "remote"]),
    default="auto",
    help="Hybrid mode: auto=config, quality=remote first, balanced=mixed, cost=local first, local=offline, remote=remote only",
)
@click.option(
    "--max-cost",
    type=float,
    default=None,
    help="Maximum cost per review in USD (overrides config)",
)
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
    mode: str,
    max_cost: float | None,
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

        # 应用混合模式配置
        if mode != "auto":
            mode_map = {
                "quality": "quality_first",
                "balanced": "balanced",
                "cost": "cost_optimized",
                "local": "local_only",
                "remote": "remote_only",
            }
            app_config.preferences.hybrid_strategy = mode_map[mode]

        # 应用成本限制
        if max_cost is not None:
            app_config.preferences.max_cost_per_review = max_cost

        effective_format = infer_output_format(output_format, str(output) if output else None)
        execute_review_flow(
            console,
            pr_url=pr_url,
            model=model,
            app_config=app_config,
            effective_format=effective_format,
            output=output,
            publish_comment=publish_comment,
            dry_run=dry_run,
            only_fetch=only_fetch,
            only_filter=only_filter,
            show_filter_reasons=show_filter_reasons,
            run_review=(
                lambda url, model=None, verbose=False, config=None: run_review(
                    url,
                    model=model,
                    verbose=verbose,
                    config=config,
                    progress_console=(
                        console if effective_format == "terminal" and output is None else None
                    ),
                )
            ),
            render_markdown_report=render_markdown_report,
            render_json_report=render_json_report,
            render_terminal_report=render_terminal_report,
            render_github_comment_report=render_github_comment_report,
            maybe_publish_comment=maybe_publish_comment,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except (PRFetcherError, AIClientError) as exc:
        console.print(f"Error: {exc}", style="bold red")
        raise SystemExit(1) from exc
    except Exception as exc:
        console.print(f"Unexpected error: {exc}", style="bold red")
        raise SystemExit(1) from exc


@main.command("plan")
@click.argument("pr_url")
@click.option("--json-output", is_flag=True, help="Emit the plan as JSON.")
@click.pass_context
def plan_command(ctx: click.Context, pr_url: str, json_output: bool) -> None:
    """Show the planned review scope without calling an AI model."""
    try:
        config = AppConfig.load(_config_path_from_context(ctx))
        artifacts = asyncio.run(ReviewOrchestrator(config).plan_only(pr_url))
        plan = artifacts.review_plan
        payload = {
            "pr": {
                "number": artifacts.pr_data.pr_number,
                "title": artifacts.pr_data.title,
                "url": artifacts.pr_data.url,
                "repository": artifacts.pr_data.repo_full_name,
            },
            "plan": plan.model_dump(mode="json") if plan is not None else None,
            "filter": artifacts.filter_result.to_dict(),
            "run": {"duration_seconds": artifacts.duration_seconds},
        }
        if json_output:
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        console = Console(legacy_windows=False)
        console.print(
            Panel.fit("[bold]Review Plan[/bold]\n审查规划预览（不会调用 AI）", border_style="blue")
        )
        if plan is None:
            console.print("[yellow]No plan was generated.[/yellow]")
            return
        table = Table(box=box.SIMPLE, show_header=False)
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        table.add_row("PR", f"{artifacts.pr_data.repo_full_name}#{artifacts.pr_data.pr_number}")
        table.add_row("Intent", plan.intent)
        table.add_row("Risk", plan.risk_level.upper())
        table.add_row("Priority files", ", ".join(plan.priority_files) or "-")
        table.add_row("Strategies", ", ".join(plan.strategies) or "-")
        table.add_row("Cross-file", "YES" if plan.requires_cross_file_analysis else "NO")
        console.print(table)
        if plan.rationale:
            console.print(
                Panel(
                    "\n".join(f"- {item}" for item in plan.rationale),
                    title="Why this plan",
                    border_style="cyan",
                )
            )
    except (PRFetcherError, AIClientError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc


@main.command("explain")
@click.argument("run_id")
@click.pass_context
def explain_command(ctx: click.Context, run_id: str) -> None:
    """Explain findings and evidence validation for a stored review run."""
    config = AppConfig.load(_config_path_from_context(ctx))
    result = ResultStore(config.result_store).get_result(run_id)
    if result is None:
        raise click.ClickException(f"Review run not found: {run_id}")
    console = Console(legacy_windows=False)
    metadata = ResultStore(config.result_store).get_run_metadata(run_id)
    language_info = metadata.get("language", {}) if isinstance(metadata, dict) else {}
    console.print(
        Panel.fit(f"[bold]Finding Explanation[/bold]\nRun: {run_id}", border_style="blue")
    )
    if language_info:
        console.print(
            f"语言：界面 {language_info.get('ui_language', '-')} · "
            f"审查响应 {language_info.get('response_language', '-')}"
        )
    if not result.findings:
        console.print("No findings were recorded.")
        return
    for finding in result.findings:
        console.print(f"\n[bold yellow]{finding.severity.upper()}[/bold yellow] {finding.title}")
        console.print(f"  Location: {finding.file}:{finding.line_start}-{finding.line_end}")
        console.print(f"  Sources: {', '.join(finding.sources or ['unknown'])}")
        console.print(f"  Evidence: {finding.evidence_status or 'unverified'}")
        if finding.evidence_issues:
            console.print(f"  Issues: {'; '.join(finding.evidence_issues)}")
        console.print(f"  Why: {finding.problem}")
        console.print(f"  Fix: {finding.suggestion}")


@main.command("export-run")
@click.argument("run_id")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["markdown", "json"]),
    default="markdown",
    show_default=True,
)
@click.option("--output", type=click.Path(path_type=Path), required=True)
@click.pass_context
def export_run_command(ctx: click.Context, run_id: str, output_format: str, output: Path) -> None:
    """Export a stored review run without contacting GitHub or a model."""
    config = AppConfig.load(_config_path_from_context(ctx))
    store = ResultStore(config.result_store)
    result = store.get_result(run_id)
    summary = store.get_run_summary(run_id)
    if result is None or summary is None:
        raise click.ClickException(f"Review run not found: {run_id}")

    # Only the run row survives: file names and diffs are not persisted, so the
    # count comes from the stored columns instead of an empty file list.
    from ai_pr_review.models.pr_data import PRData

    metadata_payload: Any = {}
    try:
        metadata_payload = json.loads(str(summary.get("metadata_json") or "{}"))
    except json.JSONDecodeError:
        metadata_payload = {}
    metadata: dict[str, Any] = metadata_payload if isinstance(metadata_payload, dict) else {}
    raw_pr_meta = metadata.get("pr")
    pr_meta: dict[str, Any] = raw_pr_meta if isinstance(raw_pr_meta, dict) else {}
    pr_data = PRData(
        pr_number=int(summary.get("pr_number") or pr_meta.get("number") or 0),
        title=str(pr_meta.get("title") or f"Stored review {run_id}"),
        description=pr_meta.get("description"),
        author=str(pr_meta.get("author") or "unknown"),
        state=str(pr_meta.get("state") or "unknown"),
        head_sha=str(summary.get("head_sha") or ""),
        base_sha=str(pr_meta.get("base_sha") or ""),
        head_ref=str(pr_meta.get("head_ref") or ""),
        base_ref=str(pr_meta.get("base_ref") or ""),
        diff="",
        files=[],
        url=str(summary["pr_url"]),
        created_at=None,
        updated_at=None,
        merged=bool(pr_meta.get("merged", False)),
        owner=str(summary.get("repo_owner") or ""),
        repo=str(summary.get("repo_name") or ""),
    )
    files_changed = int(summary.get("total_files") or 0)
    if output_format == "json":
        payload = {"run": summary, "result": json.loads(result.model_dump_json())}
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output.write_text(
            ReportRenderer(config.report_renderer).render_markdown(
                result, pr_data, files_changed=files_changed
            ),
            encoding="utf-8",
        )
    click.echo(f"Report written to {output}")


@main.command("trace")
@click.argument("pr_url")
@click.pass_context
def trace_command(ctx: click.Context, pr_url: str) -> None:
    """Show a lightweight timing trace for the planning pipeline."""
    try:
        config = AppConfig.load(_config_path_from_context(ctx))
        started = time.perf_counter()
        artifacts = asyncio.run(ReviewOrchestrator(config).plan_only(pr_url))
        elapsed = time.perf_counter() - started
        console = Console(legacy_windows=False)
        console.print(
            Panel.fit("[bold]Review Trace[/bold]\nPlanning pipeline timing", border_style="blue")
        )
        table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
        table.add_column("Stage")
        table.add_column("Status")
        table.add_column("Duration")
        table.add_row("PR fetch + filter + plan", "OK", f"{elapsed:.3f}s")
        table.add_row("AI call", "SKIPPED", "0.000s")
        table.add_row("Evidence validation", "SKIPPED", "0.000s")
        console.print(table)
        console.print(
            f"\nPlan: {artifacts.review_plan.risk_level if artifacts.review_plan else 'none'} risk · {len(artifacts.pr_data.files)} files"
        )
    except (PRFetcherError, AIClientError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc


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
        build_config_show_output(
            config, config_path=config_path, export_config_payload=_export_config_payload
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
    try:
        config_path, example_path, gitignore_path, env_var = run_config_init(
            provider=provider,
            model_name=model_name,
            base_url=base_url,
            api_format=api_format,
            directory=directory,
            force=force,
            local_example=local_example,
            update_gitignore=update_gitignore,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Created project config: {config_path}")
    if example_path is not None and example_path.exists():
        click.echo(f"Created local override example: {example_path}")
    if gitignore_path is not None and gitignore_path.exists():
        click.echo(f"Updated gitignore: {gitignore_path}")
    click.echo(f"Set API key via environment variable: {env_var} or AI_PR_REVIEW_API_KEY")


@config_command.command("test")
@click.pass_context
def config_test(ctx: click.Context) -> None:
    """Validate the resolved provider configuration."""
    config = AppConfig.load(_config_path_from_context(ctx))
    try:
        payload = run_config_test(config, missing_api_key_message=_missing_api_key_message)
    except ConfigValidationError as exc:
        raise click.ClickException(str(exc)) from exc
    provider = payload["provider"]
    click.echo(
        f"Configuration valid: provider={provider.name}, model={provider.model_name}, format={provider.api_format}"
    )
    click.echo(f"Default output format: {payload['output_format']}")
    if payload["risk_warning"] is not None:
        click.echo(payload["risk_warning"])


@config_command.command("health")
@click.option(
    "--discover-models",
    is_flag=True,
    help="Try provider model discovery through the remote /models endpoint.",
)
@click.option(
    "--probe",
    is_flag=True,
    help="Send a minimal chat request to verify real provider connectivity.",
)
@click.pass_context
def config_health(ctx: click.Context, discover_models: bool, probe: bool) -> None:
    """Check whether the configured provider is ready to use."""
    config_path = _config_path_from_context(ctx)
    config = AppConfig.load(config_path)
    try:
        payload = run_config_health(
            config,
            config_path=config_path,
            discover_models=discover_models,
            probe=probe,
            missing_api_key_message=_missing_api_key_message,
        )
    except ConfigValidationError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@config_command.command("model")
@click.option("--name", "model_name", required=True, help="Set active model name.")
@click.pass_context
def config_model(ctx: click.Context, model_name: str) -> None:
    """Update the active model name in the current config."""
    config_path = _config_path_from_context(ctx)
    config = AppConfig.load(config_path)
    updated_model = run_config_model(
        config,
        config_path=config_path,
        model_name=model_name,
        save_key_checker=_active_config_has_saved_api_key,
        set_active_model=_set_active_model,
    )
    click.echo(f"Active model set to: {updated_model}")


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
        payload = run_config_models(
            config,
            config_path=config_path,
            model_name=model_name,
            set_first=set_first,
            missing_api_key_message=_missing_api_key_message,
            save_key_checker=_active_config_has_saved_api_key,
            set_active_model=_set_active_model,
        )
    except ConfigValidationError as exc:
        raise click.ClickException(str(exc)) from exc

    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo("Discovered models:")
    for model in payload["models"]:
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
    run_config_export(
        output,
        config=config,
        config_path=config_path,
        include_secrets=include_secrets,
        export_config_payload=_export_config_payload,
    )
    click.echo(f"Exported configuration to {output}")


@config_command.command("import")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--save-key", is_flag=True, help="Persist imported API key and GitHub token.")
def config_import(input_path: Path, save_key: bool) -> None:
    """Import configuration from JSON file into the active user config path."""
    ctx = click.get_current_context(silent=True)
    config_path = _config_path_from_context(ctx)
    config = AppConfig.load(config_path)
    try:
        run_config_import(input_path, config=config, save_key=save_key, config_path=config_path)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Imported configuration from {input_path}")


@main.command("history")
@click.option("--pr-url", default=None, help="Filter by PR URL.")
@click.option("--limit", default=10, show_default=True, type=int, help="Maximum runs to show.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.option("--table", "as_table", is_flag=True, help="Force the human-friendly table view.")
@click.pass_context
def history_command(
    ctx: click.Context, pr_url: str | None, limit: int, as_json: bool, as_table: bool
) -> None:
    """Show persisted review history (table in a terminal, JSON when piped)."""
    config = AppConfig.load(_config_path_from_context(ctx))
    payload = build_history_output(config, pr_url=pr_url, limit=limit)
    if as_json or (not as_table and not sys.stdout.isatty()):
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    table = Table(title="历史审查记录", box=box.SIMPLE_HEAVY, header_style="bold cyan")
    table.add_column("时间", style="dim")
    table.add_column("仓库 / PR")
    table.add_column("模型", style="cyan")
    table.add_column("风险", justify="right")
    table.add_column("Findings", justify="right")
    table.add_column("成本", justify="right")
    table.add_column("耗时", justify="right")
    for run in payload["runs"]:
        repo = f"{run.get('repo_owner') or ''}/{run.get('repo_name') or ''}".strip("/")
        pr_number = run.get("pr_number") or "?"
        findings = int(run.get("total_findings") or 0)
        risk = (
            "HIGH"
            if (run.get("critical_findings") or run.get("high_findings"))
            else ("MEDIUM" if run.get("medium_findings") else "LOW")
        )
        table.add_row(
            str(run.get("created_at") or "-")[:19],
            f"{repo}#{pr_number}",
            str(run.get("model") or "-"),
            risk,
            str(findings),
            f"${float(run.get('total_cost') or 0):.4f}",
            f"{float(run.get('duration_seconds') or 0):.1f}s",
        )
    console = Console()
    console.print(table)
    stats = payload["statistics"]
    console.print(
        f"共 {stats.get('total_runs', 0)} 次运行 · {stats.get('total_findings', 0)} 个 Finding · "
        f"累计成本 ${float(stats.get('total_cost') or 0):.4f}",
        style="dim",
    )


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
    payload = apply_workspace_preferences(
        config,
        config_path=config_path,
        ui_language=ui_language,
        response_language=response_language,
        chat_layout=chat_layout,
        output_format=output_format,
        save_key_checker=_active_config_has_saved_api_key,
    )
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2))


def _open_tui_frontend(
    *, config_path: Path | None = None, initial_message: str | None = None
) -> bool:
    """Launch the OpenTUI shell and return whether it started successfully."""
    package_root = Path(__file__).resolve().parent
    project_root = package_root.parents[1]
    dev_root = project_root / "frontend" / "tui"
    static_root = package_root / "tui_static"

    runtime = _find_bun_runtime()
    exe_name = "pr-review-tui.exe" if os.name == "nt" else "pr-review-tui"
    prebuilt = static_root / exe_name
    bundle = static_root / "tui.js"
    dev_entry = dev_root / "src" / "main.tsx"
    dev_ready = dev_entry.exists() and (dev_root / "node_modules").exists()

    raw_command = os.getenv("AI_PR_REVIEW_TUI_COMMAND", "").strip()
    if raw_command:
        command = shlex.split(raw_command, posix=False)
        tui_root = dev_root if dev_ready else static_root
    elif runtime is not None and dev_ready:
        # Source is authoritative during development. The ignored compiled exe
        # is often older than the committed bundle/source, so it must not win
        # just because it exists.
        command = [runtime, "--preload", "@opentui/solid/preload", "src/main.tsx"]
        tui_root = dev_root
    elif runtime is not None and bundle.exists():
        command = [runtime, str(bundle)]
        tui_root = static_root
    elif prebuilt.exists():
        # A compiled binary embeds both the JS bundle and the native DLL, so it
        # needs neither node_modules nor a Bun install on the target machine.
        command = [str(prebuilt)]
        tui_root = static_root
    else:
        return False

    env = os.environ.copy()
    # In an installed layout there is no source tree, so the working directory
    # the user launched from is the meaningful project root.
    env["AI_PR_REVIEW_ROOT"] = str(project_root) if dev_ready else str(Path.cwd())
    # The TUI spawns the Python JSONL backend itself; pin it to the interpreter
    # running this CLI so a bare `python` on PATH cannot pick an environment
    # that lacks the package.
    env.setdefault("AI_PR_REVIEW_PYTHON", sys.executable)
    if config_path is not None:
        env["AI_PR_REVIEW_CONFIG"] = str(config_path)
    if initial_message:
        env["AI_PR_REVIEW_INITIAL_MESSAGE"] = initial_message

    try:
        completed = subprocess.run(command, cwd=tui_root, env=env, check=False)
    except (OSError, ValueError) as exc:
        print(f"OpenTUI 启动失败，将回退到纯 Python Chat：{exc}", file=sys.stderr)
        return False
    return completed.returncode == 0


def _find_bun_runtime() -> str | None:
    """Locate the Bun runtime used by the source and bundled launch paths."""
    candidates = [
        os.getenv("BUN_EXECUTABLE", "").strip(),
        str(Path(os.getenv("APPDATA", "")) / "npm" / "node_modules" / "bun" / "bin" / "bun.exe"),
        shutil.which("bun.exe") or "",
        shutil.which("bun") or "",
    ]
    return next(
        (candidate for candidate in candidates if candidate and Path(candidate).exists()),
        None,
    )


@main.command("chat")
@click.option("--message", "message", default=None, help="Send one message and exit.")
@click.option("--model", "model_name", default=None, help="Override model for this chat session.")
@click.option(
    "--layout",
    type=click.Choice(["compact", "split", "plain"]),
    default=None,
    help="Override chat layout for this session.",
)
@click.option(
    "--tui/--plain", "use_tui", default=None, help="Use OpenTUI or the legacy plain Chat."
)
@click.pass_context
def chat_command(
    ctx: click.Context,
    message: str | None,
    model_name: str | None,
    layout: str | None,
    use_tui: bool | None,
) -> None:
    """Open a lightweight terminal chat with the configured model."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass
    console = Console()
    config_path = _config_path_from_context(ctx)
    config = AppConfig.load(config_path)

    # Interactive terminals use the MiMoCode-style OpenTUI shell by default.
    # CliRunner, CI, and explicit --plain retain the legacy Python Chat path.
    interactive = bool(
        getattr(sys.stdin, "isatty", lambda: False)()
        and getattr(sys.stdout, "isatty", lambda: False)()
    )
    should_use_tui = use_tui if use_tui is not None else interactive
    if should_use_tui and model_name is None and message is None:
        if _open_tui_frontend(config_path=config_path):
            return
        if use_tui:
            raise click.ClickException(
                "OpenTUI 未能启动。请安装 Bun，或使用 --plain 回退到纯 Python Chat。"
            )
        console.print("OpenTUI 不可用，将回退到纯 Python Chat。", style="yellow")

    if model_name is not None:
        _set_active_model(config, model_name)
    active_layout = layout or getattr(config.preferences, "chat_layout", "compact")
    # Check configuration status and determine initial state
    config_status = _check_config_status(config)
    needs_setup = not all(config_status.values())

    initial_state = "unconfigured" if needs_setup else "ready"

    # Try to load previous ChatContext
    saved_context = load_chat_context(config_path)
    if saved_context and not needs_setup:
        # Restore previous context
        try:
            chat_context = ChatContext(**saved_context)
            console.print("[dim]已恢复上次会话状态[/dim]")
        except Exception:
            # If restoration fails, create new context
            chat_context = ChatContext(
                session_id=str(config_path or "transient-chat"),
                language=config.preferences.language,
                state=initial_state,
                local_model=(
                    config.ai_client.model
                    if config.ai_client.provider.lower() in {"ollama", "local"}
                    else None
                ),
                remote_model=(
                    config.ai_client.model
                    if config.ai_client.provider.lower() not in {"ollama", "local"}
                    else None
                ),
            )
    else:
        chat_context = ChatContext(
            session_id=str(config_path or "transient-chat"),
            language=config.preferences.language,
            state=initial_state,
            local_model=(
                config.ai_client.model
                if config.ai_client.provider.lower() in {"ollama", "local"}
                else None
            ),
            remote_model=(
                config.ai_client.model
                if config.ai_client.provider.lower() not in {"ollama", "local"}
                else None
            ),
        )

    # Show configuration assistant welcome if needed
    if needs_setup and not message:
        console.print(Markdown(_render_config_assistant_welcome(config)))

    def print_chat_message(local_console: Console, role: str, text: str) -> None:
        _print_chat_message(local_console, role, text, layout=active_layout)

    # Create Action Executor and register handlers
    executor = ActionExecutor()

    def handle_chat(act: ChatAction, ctx: ChatContext) -> ActionResult:
        return _handle_chat_action(act, ctx)

    def handle_start_review(act: ChatAction, ctx: ChatContext) -> ActionResult:
        return asyncio.run(_handle_start_review_action(act, ctx, config, console))

    def handle_create_plan(act: ChatAction, ctx: ChatContext) -> ActionResult:
        return asyncio.run(_handle_create_review_plan_action(act, ctx, config))

    def handle_list_hist(act: ChatAction, ctx: ChatContext) -> ActionResult:
        return _handle_list_history_action(act, ctx, config)

    def handle_explain(act: ChatAction, ctx: ChatContext) -> ActionResult:
        return _handle_explain_finding_action(act, ctx, config)

    def handle_check_env(act: ChatAction, ctx: ChatContext) -> ActionResult:
        return _handle_check_environment_action(act, ctx, config)

    def handle_cancel(act: ChatAction, ctx: ChatContext) -> ActionResult:
        return _handle_cancel_review_action(act, ctx)

    def handle_configure_provider(act: ChatAction, ctx: ChatContext) -> ActionResult:
        return _handle_configure_provider_action(act, ctx, config, console)

    def handle_configure_github(act: ChatAction, ctx: ChatContext) -> ActionResult:
        return _handle_configure_github_action(act, ctx, config, console)

    def handle_analyze_history(act: ChatAction, ctx: ChatContext) -> ActionResult:
        return _handle_analyze_history_action(act, ctx, config)

    executor.register("chat", handle_chat)
    executor.register("start_review", handle_start_review)
    executor.register("create_review_plan", handle_create_plan)
    executor.register("list_history", handle_list_hist)
    executor.register("explain_finding", handle_explain)
    executor.register("check_environment", handle_check_env)
    executor.register("cancel_review", handle_cancel)
    executor.register("configure_provider", handle_configure_provider)
    executor.register("configure_github", handle_configure_github)
    executor.register("analyze_history", handle_analyze_history)

    def send_message(messages: list[dict[str, Any]], user_text: str) -> str | None:
        try:
            # The local model is the Copilot router even when the configured
            # deep-review provider remains a remote API model.
            try:
                action = asyncio.run(_route_local_chat_action(config, user_text, chat_context))
            except Exception:
                action = ChatAction(action="chat", source="local_model_unavailable")

            # If action is not chat, try to execute it
            if action.action != "chat":
                chat_context.current_action = action.action

                # Handle confirmation for high-risk actions
                if action.requires_confirmation and not action.confirmed:
                    preview = _format_chat_action_preview(action)
                    console.print(Markdown(preview))
                    if Confirm.ask("\n是否执行此操作？", default=False):
                        action.confirmed = True
                    else:
                        return "操作已取消。"

                # Execute the action
                try:
                    result = executor.execute(action, chat_context)
                    if result.ok:
                        # Format success message
                        response = f"✓ {result.message}\n\n"
                        if result.data:
                            if action.action == "create_review_plan":
                                data = result.data
                                response += f"**审查计划摘要**\n\n"
                                response += f"- 风险等级: {data.get('risk_level')}\n"
                                response += (
                                    f"- 风险类别: {', '.join(data.get('risk_categories', []))}\n"
                                )
                                response += f"- 优先文件数: {len(data.get('priority_files', []))}\n"
                                response += (
                                    f"- 预计审查文件数: {data.get('estimated_file_reviews')}\n"
                                )
                                response += f"- 策略: {', '.join(data.get('strategies', []))}\n"
                            elif action.action == "start_review":
                                data = result.data
                                response += f"**审查结果**\n\n"
                                response += f"- Run ID: `{data.get('run_id')}`\n"
                                response += f"- 发现问题数: {data.get('finding_count')}\n"
                                response += f"- 成本: ${data.get('cost', 0):.4f}\n"
                                response += f"- 耗时: {data.get('duration', 0):.1f}s\n"
                            elif action.action == "list_history":
                                data = result.data
                                response += f"**历史记录** ({data.get('count')} 条)\n\n"
                                for run in data.get("runs", [])[:5]:
                                    response += f"- {run.get('timestamp', 'N/A')}: {run.get('pr_url', 'N/A')}\n"
                            elif action.action == "check_environment":
                                data = result.data
                                response += f"**环境状态**\n\n"
                                response += f"- 供应商: {data.get('provider')}\n"
                                response += f"- 模型: {data.get('model')}\n"
                                response += (
                                    f"- API Key: {'✓' if data.get('api_key_configured') else '✗'}\n"
                                )
                                response += f"- GitHub Token: {'✓' if data.get('github_token_configured') else '✗'}\n"
                                response += f"- 语言: {data.get('language')}\n"
                            elif action.action == "configure_provider":
                                data = result.data
                                response += f"**配置完成**\n\n"
                                response += f"- 供应商: {data.get('provider')}\n"
                                response += f"- API Key: 已保存\n\n"
                                response += "提示：现在可以配置 GitHub Token 或直接开始审查。\n"
                            elif action.action == "configure_github":
                                response += "**GitHub Token 已配置**\n\n"
                                response += "现在可以审查私有仓库的 PR 了。\n"
                        return response
                    else:
                        return f"✗ 操作失败: {result.message}"
                except Exception as exc:
                    return f"✗ 执行出错: {exc}"

            # Normal chat
            answer = asyncio.run(_send_chat_message(config, messages))
        except AIClientError as exc:
            console.print(Panel(_format_chat_error(exc, config), title="Error", border_style="red"))
            return None
        except click.ClickException as exc:
            console.print(Panel(str(exc), title="Error", border_style="red"))
            return None
        return answer

    def handle_raw_command(command_text: str) -> bool:
        stripped = command_text.strip()
        embedded_url = _extract_github_pr_url(stripped)
        if embedded_url and not stripped.lower().startswith("pr-review"):
            parts = ["pr-review", embedded_url]
        elif stripped.startswith("pr-review "):
            try:
                parts = shlex.split(stripped)
            except ValueError as exc:
                console.print(Panel(f"命令解析失败: {exc}", title="Error", border_style="red"))
                return True
        else:
            return False

        if len(parts) < 2:
            console.print(
                Panel(
                    "请提供 PR URL，例如：pr-review https://github.com/owner/repo/pull/123",
                    title="Error",
                    border_style="red",
                )
            )
            return True

        pr_url = _extract_github_pr_url(parts[1]) or parts[1]
        model_override: str | None = None
        output_format = "terminal"
        output: Path | None = None
        publish_comment = False
        dry_run = False
        only_fetch = False
        only_filter = False
        show_filter_reasons = False

        i = 2
        while i < len(parts):
            token = parts[i]
            if token == "--model" and i + 1 < len(parts):
                model_override = parts[i + 1]
                i += 2
                continue
            if token == "--format" and i + 1 < len(parts):
                output_format = parts[i + 1]
                i += 2
                continue
            if token == "--output" and i + 1 < len(parts):
                output = Path(parts[i + 1])
                i += 2
                continue
            if token == "--publish-comment":
                publish_comment = True
                i += 1
                continue
            if token == "--dry-run":
                dry_run = True
                i += 1
                continue
            if token == "--only-fetch":
                only_fetch = True
                i += 1
                continue
            if token == "--only-filter":
                only_filter = True
                i += 1
                continue
            if token == "--show-filter-reasons":
                show_filter_reasons = True
                i += 1
                continue

            console.print(
                Panel(f"不支持的聊天内命令参数: {token}", title="Error", border_style="red")
            )
            return True

        try:
            effective_format = infer_output_format(output_format, str(output) if output else None)
            execute_review_flow(
                console,
                pr_url=pr_url,
                model=model_override,
                app_config=config,
                effective_format=effective_format,
                output=output,
                publish_comment=publish_comment,
                dry_run=dry_run,
                only_fetch=only_fetch,
                only_filter=only_filter,
                show_filter_reasons=show_filter_reasons,
                run_review=(
                    lambda url, model=None, verbose=False, config=None: run_review(
                        url,
                        model=model,
                        verbose=verbose,
                        config=config,
                        progress_console=(
                            console if effective_format == "terminal" and output is None else None
                        ),
                    )
                ),
                render_markdown_report=render_markdown_report,
                render_json_report=render_json_report,
                render_terminal_report=render_terminal_report,
                render_github_comment_report=render_github_comment_report,
                maybe_publish_comment=maybe_publish_comment,
            )
        except ValueError as exc:
            console.print(Panel(str(exc), title="Error", border_style="red"))
        except (PRFetcherError, AIClientError) as exc:
            console.print(Panel(f"Error: {exc}", title="Review Error", border_style="red"))
        except Exception as exc:
            console.print(Panel(f"Unexpected error: {exc}", title="Error", border_style="red"))
        return True

    run_chat_session(
        console,
        config=config,
        config_path=config_path,
        active_layout=active_layout,
        message=message,
        load_session=load_chat_session,
        save_session=save_chat_session,
        chat_title=_chat_title,
        print_chat_message=print_chat_message,
        slash_handler=_handle_chat_slash_command,
        raw_command_handler=handle_raw_command,
        send_message=send_message,
    )


@main.command("showcase")
@click.option("--json-output", is_flag=True, help="Emit the guided showcase as JSON.")
@click.option("--interactive", is_flag=True, help="Run an interactive local demo menu.")
@click.pass_context
def showcase_command(ctx: click.Context, json_output: bool, interactive: bool) -> None:
    """Print the recommended competition demo path without changing project state."""
    from ai_pr_review.services.showcase_runner import showcase_payload

    config = None
    try:
        config = AppConfig.load(_config_path_from_context(ctx))
    except Exception:
        config = None
    # Shared with the chat backend's `/showcase` command (§12.3); the payload
    # shape and the JSON bytes below are pinned by tests.
    payload = showcase_payload(config)
    steps = payload["steps"]
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    console = Console(legacy_windows=False)
    if interactive:
        console.print(
            Panel.fit("[bold]交互式参赛演示[/bold]\n选择一个场景开始", border_style="blue")
        )
        console.print("1. SQL 注入离线 Demo（推荐）")
        console.print("2. TLS 校验离线 Demo")
        console.print("3. Clean Change 对照 Demo")
        console.print("4. 查看历史审查")
        console.print("5. 退出")
        choice = click.prompt("请选择", type=click.Choice(["1", "2", "3", "4", "5"]), default="1")
        commands = {
            "1": ["demo", "--case", "sql-injection"],
            "2": ["demo", "--case", "tls-disabled"],
            "3": ["demo", "--case", "clean-change"],
            "4": ["history", "--table"],
        }
        if choice == "5":
            console.print("已退出演示。", style="dim")
            return
        console.print("\n[bold cyan]正在执行演示…[/bold cyan]\n")
        subprocess.run([sys.executable, "-m", "ai_pr_review", *commands[choice]], check=False)
        return
    console.print(
        Panel.fit("[bold]参赛演示路径[/bold]\n从离线证据到真实 PR 复盘", border_style="blue")
    )
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
    table.add_column("Step", style="cyan", width=6)
    table.add_column("Command", style="green")
    table.add_column("Purpose")
    for item in steps:
        table.add_row(str(item["step"]), str(item["command"]), str(item["purpose"]))
    console.print(table)
    console.print()
    console.print("[green]Offline demo ready[/green] · ", end="")
    console.print(
        "[green]Real review credentials ready[/green]"
        if payload["real_review_ready"]
        else "[yellow]configure GitHub + model credentials before the real PR step[/yellow]"
    )


@main.command("demo")
@click.option(
    "--case", "case_key", default="sql-injection", show_default=True, help="Offline demo case key."
)
@click.option("--list-cases", is_flag=True, help="List available offline demo cases.")
@click.option("--json-output", is_flag=True, help="Emit the demo result as JSON.")
@click.pass_context
def demo_command(ctx: click.Context, case_key: str, list_cases: bool, json_output: bool) -> None:
    """Run an offline demonstration of planning and evidence validation."""
    # The payload builder is shared with the chat backend's `/demo` command
    # (§12.3). This command stays strictly offline: fixtures, the deterministic
    # rule pipeline and the evidence validator, nothing else.
    from ai_pr_review.services.demo_runner import demo_cases, run_demo

    if list_cases:
        for case in demo_cases():
            click.echo(f"{case['key']}: {case['title']} - {case['description']}")
        return

    demo = run_demo(case_key)

    if json_output:
        click.echo(json.dumps(demo.payload, ensure_ascii=False, indent=2))
        return

    console = Console(legacy_windows=False)
    console.print(
        Panel.fit(
            f"[bold]AI PR Review Assistant - Offline Demo[/bold]\n{demo.title}",
            border_style="blue",
        )
    )
    stages = Table(box=box.SIMPLE, show_header=False)
    stages.add_column("Stage", style="cyan")
    stages.add_column("Status", style="green")
    for stage in [
        "Load PR fixture",
        "Filter changed files",
        "Build ReviewPlan",
        "Run deterministic rules",
        "Validate evidence",
        "Render report",
    ]:
        stages.add_row(stage, "OK")
    console.print(stages)
    console.print(
        Panel.fit(
            f"Risk level: [bold red]{demo.risk_level.upper()}[/bold red]\n"
            f"Priority files: {demo.priority_files}\n"
            f"Findings: {len(demo.findings)}\n"
            f"Evidence validated: {demo.valid_count}/{len(demo.findings)}\n"
            f"Estimated cost: $0.00",
            title="Demo result",
            border_style="green",
        )
    )
    for finding in demo.findings:
        console.print(f"[{finding.severity.upper()}] {finding.title} ({finding.evidence_status})")
        console.print(f"  {finding.file}:{finding.line_start} · {finding.suggestion}")


@main.command("benchmark")
@click.option(
    "--strategy",
    "strategy_name",
    type=click.Choice(["static", "ast", "combined", "all"]),
    default="combined",
    show_default=True,
    help="Analysis strategy to benchmark, or 'all' to compare every strategy.",
)
@click.option("--json-output", is_flag=True, help="Emit the full report as JSON.")
def benchmark_command(strategy_name: str, json_output: bool) -> None:
    """Measure review strategy accuracy against known-defect samples."""
    from ai_pr_review.benchmark import run_all_strategies, run_benchmark

    if strategy_name == "all":
        reports = run_all_strategies()
        if json_output:
            click.echo(
                json.dumps(
                    {name: report.to_dict() for name, report in reports.items()},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        for report in reports.values():
            click.echo(report.render_text())
            click.echo("")
        return

    report = run_benchmark(strategy_name)
    if json_output:
        click.echo(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return
    click.echo(report.render_text())


@main.command("feedback")
@click.argument("run_id")
@click.argument("finding_id")
@click.option(
    "--status",
    type=click.Choice(["accepted", "rejected", "fixed", "needs_review"]),
    required=True,
    help="Record the user's decision for a finding.",
)
@click.option("--note", default="", help="Optional feedback note.")
@click.pass_context
def feedback_command(
    ctx: click.Context,
    run_id: str,
    finding_id: str,
    status: str,
    note: str,
) -> None:
    """Record human feedback for a finding."""
    config = AppConfig.load(_config_path_from_context(ctx))
    store = ResultStore(config.result_store)
    if store.get_result(run_id) is None:
        raise click.ClickException(f"Review run not found: {run_id}")
    store.save_feedback(run_id, finding_id, status, note)
    click.echo(
        json.dumps(
            {"run_id": run_id, "finding_id": finding_id, "status": status}, ensure_ascii=False
        )
    )


@main.command("serve")
@click.option("--host", default="127.0.0.1", show_default=True, help="Web server bind host.")
@click.option("--port", default=8787, show_default=True, type=int, help="Web server port.")
@click.pass_context
def serve_command(ctx: click.Context, host: str, port: int) -> None:
    """Start the local browser workbench."""
    from ai_pr_review.web_server import serve

    explicit_path = _config_path_from_context(ctx)
    config = AppConfig.load(explicit_path)
    # 把解析后的落盘目标交给 Web 设置页（--config > AI_PR_REVIEW_CONFIG > 默认路径），
    # 否则设置页会静默读写默认用户配置。
    serve(config, host=host, port=port, config_path=resolve_config_path(explicit_path))


@main.command("stats")
@click.pass_context
def stats_command(ctx: click.Context) -> None:
    """Show persisted review statistics."""
    config = AppConfig.load(_config_path_from_context(ctx))
    click.echo(json.dumps(build_stats_output(config), ensure_ascii=False, indent=2))


__all__ = [
    "ReviewArtifacts",
    "benchmark_command",
    "build_report_payload",
    "chat_command",
    "config_command",
    "infer_output_format",
    "main",
    "maybe_publish_comment",
    "preferences_command",
    "plan_command",
    "feedback_command",
    "demo_command",
    "serve_command",
    "history_command",
    "stats_command",
    "render_github_comment_report",
    "review_command",
    "render_json_report",
    "render_markdown_report",
    "render_terminal_report",
    "run_review",
]


if __name__ == "__main__":  # pragma: no cover - exercised through the console script
    main()
