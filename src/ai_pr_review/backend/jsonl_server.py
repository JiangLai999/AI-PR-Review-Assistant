"""JSONL backend for the OpenTUI frontend.

The backend deliberately owns domain logic while the TypeScript OpenTUI process owns
terminal rendering. stdout is protocol-only; diagnostics go to stderr.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import uuid
from collections.abc import Awaitable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, cast

from ai_pr_review.config import (
    MODEL_PROVIDER_PRESETS,
    PROVIDER_MODEL_PRESETS,
    AppConfig,
    ConfigValidationError,
    ModelProviderConfig,
    ProviderConfig,
    resolve_config_path,
)
from ai_pr_review.services.model_providers.factory import create_model_provider

# Use the orchestrator's exception class itself. A *subclass* here would NOT
# catch a plain `ReviewCancelled` raised inside `run_review` — `except SubClass`
# never matches a base-class instance, so cancels kept surfacing as
# `review.failed`. Verified by
# `test_orchestrator_cancel_is_reported_as_cancelled_not_failed`.
from ai_pr_review.services.review_orchestrator import ReviewCancelled


@dataclass
class Session:
    session_id: str
    messages: list[dict[str, str]] = field(default_factory=list)


class JsonlBackend:
    def __init__(
        self,
        config_path: Path | None = None,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.config_path = config_path
        self.event_sink = event_sink
        self.config = AppConfig.load(config_path)
        self.sessions: dict[str, Session] = {}
        self.review_cancellations: dict[str, asyncio.Event] = {}
        self.chat_cancellations: dict[str, tuple[asyncio.Task[Any], threading.Event]] = {}
        self.current_report: dict[str, Any] | None = None
        self.review_timeout_seconds = 30 * 60
        self.max_events_per_session = 2048
        self.event_counts: dict[str, int] = {}
        self.runtime_profile = self._infer_runtime_profile()

    def _infer_runtime_profile(self) -> str:
        active = self.config._active_provider_config()
        provider_name = active.name.lower().strip()
        if provider_name in {"ollama", "local"}:
            return "local"
        if getattr(self.config, "_env_provider_override", False):
            # An environment override activates the primary slot for this
            # process without rewriting persisted local_only preferences.
            return "cloud"
        strategy = getattr(self.config.preferences, "hybrid_strategy", "remote_only")
        return {"remote_only": "cloud", "balanced": "hybrid", "local_only": "local"}.get(
            strategy, "cloud"
        )

    def _apply_runtime_profile(self, profile: str) -> dict[str, Any]:
        profile = profile.strip().lower()
        if profile not in {"cloud", "local", "hybrid", "offline"}:
            raise ValueError(f"Unsupported runtime profile: {profile}")
        if profile in {"local", "offline"}:
            # Switching the runtime only moves which persisted slot is active.
            # The remote slot (endpoint, model list, saved key) must survive, so
            # `/model cloud` can switch back without a re-configuration.
            self.config.preferences.hybrid_strategy = "local_only"
        elif profile in {"cloud", "hybrid"}:
            remote = self.config.provider
            if remote.name.lower() in {"ollama", "local"}:
                raise ValueError("请先配置远程 Provider，再选择 Cloud 或 Hybrid。")
            if not remote.api_key and remote.name.lower() in MODEL_PROVIDER_PRESETS:
                # Without a key the switch would "succeed" and then fail on the
                # first request, which reads as a broken TUI rather than as a
                # missing configuration step.
                raise ValueError(
                    "远程 Provider 尚未配置 API Key，请先运行 pr-review config 完成配置。"
                )
            self.config.preferences.hybrid_strategy = (
                "remote_only" if profile == "cloud" else "balanced"
            )
        self.config._sync_runtime_sections()
        self.runtime_profile = profile
        self.config.save(self.config_path, save_key=True)
        return self._config_snapshot()

    def _config_snapshot(self) -> dict[str, Any]:
        # Report the *active* slot so the TUI footer matches what will actually
        # serve the request (`ai_client` is derived from the active slot).
        provider = self.config.ai_client.model_provider
        local = provider.name.lower() in {"ollama", "local"}
        # A malformed saved provider may equal a malformed env override. Do
        # not echo that raw value (which could be a pasted secret) in the TUI.
        unsupported = bool(getattr(self.config, "_ignored_env_overrides", [])) and (
            provider.name.lower() not in MODEL_PROVIDER_PRESETS
        )
        safe_provider_name = "unsupported" if unsupported else provider.name
        safe_provider_display = "Unsupported provider" if unsupported else provider.display_name
        return {
            "runtime_profile": self.runtime_profile,
            "strategy": getattr(self.config.preferences, "hybrid_strategy", "balanced"),
            "provider": safe_provider_name,
            "provider_display": safe_provider_display,
            "model": provider.model_name,
            "base_url": provider.base_url,
            "local": local,
            "ui_language": getattr(self.config.preferences, "ui_language", "zh-CN"),
            "response_language": self.config.preferences.language,
            "output_format": self.config.preferences.output_format,
            "auto_publish_comment": self.config.preferences.auto_publish_comment,
            "chat_layout": getattr(self.config.preferences, "chat_layout", "compact"),
            "api_format": provider.api_format,
            "api_key_configured": bool(provider.api_key or local),
            "github_token_configured": bool(
                self.config.github_token or self.config.pr_fetcher.github_token
            ),
            "configuration_warnings": list(getattr(self.config, "_ignored_env_overrides", [])),
            "result_store_path": self.config.result_store.db_path,
        }

    @staticmethod
    def _provider_model_names(provider_name: str) -> list[str]:
        preset = MODEL_PROVIDER_PRESETS.get(provider_name, {})
        models = list(PROVIDER_MODEL_PRESETS.get(provider_name, {}))
        default_model = str(preset.get("model_name", "")).strip()
        if default_model and default_model not in models:
            models.insert(0, default_model)
        return models

    def _setup_options(self) -> dict[str, Any]:
        """Return provider/model choices for the TUI setup wizard.

        The wizard must not hard-code provider presets: the Python layer owns
        validation, env-var names and model metadata.
        """
        providers: list[dict[str, Any]] = []
        for name, preset in MODEL_PROVIDER_PRESETS.items():
            if name.lower() in {"ollama", "local", "custom"}:
                continue
            providers.append(
                {
                    "name": name,
                    "display_name": str(preset.get("display_name", name)),
                    "base_url": str(preset.get("base_url", "")),
                    "api_format": str(preset.get("api_format", "openai")),
                    "env_var": str(preset.get("env_var", "")),
                    "default_model": str(preset.get("model_name", "")),
                    "models": self._provider_model_names(name),
                }
            )
        # A user may have added a custom model to the active remote slot. Keep
        # it in the list so an unrelated wizard round trip cannot silently
        # replace it with a preset.
        remote_provider_name = self.config.provider.name.lower()
        remote_model = self.config.provider.default_model
        for provider in providers:
            if (
                provider["name"] == remote_provider_name
                and remote_model
                and remote_model not in provider["models"]
            ):
                provider["models"].insert(0, remote_model)
        local_provider = self.config.local_provider
        local_models = list(local_provider.models) or self._provider_model_names("ollama")
        if local_provider.default_model not in local_models:
            local_models.insert(0, local_provider.default_model)
        current = self.config.ai_client.model_provider
        return {
            "providers": providers,
            "api_formats": [
                {"value": "openai", "label": "OpenAI 兼容"},
                {"value": "anthropic", "label": "Anthropic"},
                {"value": "custom", "label": "Custom"},
            ],
            "ui_languages": [
                {"value": "zh-CN", "label": "中文 / Chinese"},
                {"value": "en-US", "label": "English"},
            ],
            "output_formats": [
                {"value": "terminal", "label": "Terminal"},
                {"value": "markdown", "label": "Markdown"},
                {"value": "json", "label": "JSON"},
            ],
            "chat_layouts": [
                {"value": "compact", "label": "紧凑 / Compact"},
                {"value": "split", "label": "分栏 / Split"},
                {"value": "plain", "label": "纯文本 / Plain"},
            ],
            "local": {
                "provider": local_provider.name,
                "display_name": local_provider.display_name,
                "base_url": local_provider.base_url,
                "api_format": local_provider.api_format,
                "default_model": local_provider.default_model,
                "models": local_models,
            },
            "current": {
                "runtime_profile": self.runtime_profile,
                "strategy": self.config.preferences.hybrid_strategy,
                "provider": current.name,
                "provider_display": current.display_name,
                "model": current.model_name,
                "base_url": current.base_url,
                "api_format": current.api_format,
                "api_key_configured": bool(current.api_key),
                "github_token_configured": bool(
                    self.config.github_token or self.config.pr_fetcher.github_token
                ),
                "ui_language": self.config.preferences.ui_language,
                "response_language": self.config.preferences.language,
                "output_format": self.config.preferences.output_format,
                "auto_publish_comment": self.config.preferences.auto_publish_comment,
                "chat_layout": self.config.preferences.chat_layout,
                # The active slot can be local while a fully configured cloud
                # slot is still persisted. The wizard must preselect the remote
                # slot when the user switches back to Cloud/Hybrid.
                "remote_provider": self.config.provider.name,
                "remote_model": self.config.provider.default_model,
                "remote_base_url": self.config.provider.base_url,
                "remote_api_key_configured": bool(self.config.provider.api_key),
                "local_provider": local_provider.name,
                "local_model": local_provider.default_model,
                "local_base_url": local_provider.base_url,
                "local_models": local_models,
            },
        }

    def _apply_setup(self, params: dict[str, Any]) -> dict[str, Any]:
        """Apply the TUI wizard atomically and reload the persisted result."""
        profile = (
            str(params.get("runtime_profile", "")).strip().lower() or self.runtime_profile
        )
        if profile not in {"cloud", "local", "hybrid", "offline"}:
            raise ValueError(f"Unsupported runtime profile: {profile}")

        if profile in {"cloud", "hybrid"}:
            provider_name = (
                str(params.get("provider_name", "")).strip().lower()
                or self.config.provider.name.lower()
            )
            preset = MODEL_PROVIDER_PRESETS.get(provider_name)
            if preset is None:
                raise ConfigValidationError(f"不支持的模型供应商: {provider_name}")
            same_provider = self.config.provider.name.lower() == provider_name
            existing = self.config.provider if same_provider else None

            api_key = str(params.get("api_key", "")).strip()
            if not api_key and existing is not None:
                api_key = existing.api_key
            if not api_key:
                env_var = str(preset.get("env_var", "")).strip()
                api_key = os.getenv(env_var, "").strip() if env_var else ""
            if not api_key and provider_name != "custom":
                env_var = str(preset.get("env_var", "")).strip()
                hint = f"，或设置 {env_var} 环境变量" if env_var else ""
                raise ConfigValidationError(
                    f"请填写 {preset.get('display_name', provider_name)} API Key{hint}。"
                )

            model_name = str(
                params.get("model_name", "")
                or (existing.default_model if existing is not None else "")
                or preset.get("model_name", "")
            ).strip()
            base_url = str(
                params.get("base_url", "")
                or (existing.base_url if existing is not None else "")
                or preset.get("base_url", "")
            ).strip()
            api_format = str(
                params.get("api_format", "")
                or (existing.api_format if existing is not None else "")
                or preset.get("api_format", "openai")
            ).strip()
            provider = ModelProviderConfig.from_name(
                provider_name,
                api_key=api_key,
                model_name=model_name,
                base_url=base_url,
                api_format=api_format,
            )
            provider.validate()
            self.config.provider = ProviderConfig.from_model_provider(provider)
            self.config.preferences.hybrid_strategy = (
                "remote_only" if profile == "cloud" else "balanced"
            )
        else:
            local = self.config.local_provider
            local_name = (
                str(params.get("local_provider", "")).strip().lower() or local.name.lower()
            )
            if local_name not in {"ollama", "local"}:
                raise ConfigValidationError("本地模型目前仅支持 Ollama/Local 预设。")
            model_name = str(
                params.get("local_model", "") or local.default_model or "qwen3.5:4b"
            ).strip()
            base_url = str(
                params.get("local_base_url", "")
                or local.base_url
                or "http://127.0.0.1:11434/v1"
            ).strip()
            provider = ModelProviderConfig.from_name(
                "ollama",
                api_key="",
                model_name=model_name,
                base_url=base_url,
                api_format="openai",
            )
            provider.validate()
            self.config.local_provider = ProviderConfig.from_model_provider(provider)
            self.config.preferences.hybrid_strategy = "local_only"

        github_token = str(params.get("github_token", "")).strip()
        if github_token:
            self._validate_github_token(github_token)
            self.config.github_token = github_token
            self.config.pr_fetcher.github_token = github_token

        preferences = self.config.preferences
        ui_language = str(params.get("ui_language", "")).strip()
        if ui_language:
            if ui_language not in {"zh-CN", "en-US"}:
                raise ConfigValidationError("界面语言仅支持 zh-CN 或 en-US。")
            preferences.ui_language = ui_language
        response_language = str(params.get("response_language", "")).strip()
        if response_language:
            if response_language not in {"zh-CN", "en-US"}:
                raise ConfigValidationError("模型回复语言仅支持 zh-CN 或 en-US。")
            preferences.language = response_language
        output_format = str(params.get("output_format", "")).strip()
        if output_format:
            if output_format not in {"terminal", "markdown", "json"}:
                raise ConfigValidationError("输出格式仅支持 terminal、markdown 或 json。")
            preferences.output_format = output_format
        chat_layout = str(params.get("chat_layout", "")).strip()
        if chat_layout:
            if chat_layout not in {"compact", "split", "plain"}:
                raise ConfigValidationError("Chat 布局仅支持 compact、split 或 plain。")
            preferences.chat_layout = chat_layout
        if "auto_publish_comment" in params:
            auto_publish = params["auto_publish_comment"]
            if not isinstance(auto_publish, bool):
                raise ConfigValidationError("auto_publish_comment 必须是布尔值。")
            preferences.auto_publish_comment = auto_publish

        self.config._sync_runtime_sections()
        self.config.save(self.config_path, save_key=True)
        # Reload through the normal layered loader so the snapshot cannot claim
        # a setting that the next process would not actually read.
        self.config = AppConfig.load(self.config_path)
        self.runtime_profile = self._infer_runtime_profile()
        return self._config_snapshot()

    @staticmethod
    def _validate_github_token(token: str) -> None:
        if not (token.startswith("ghp_") or token.startswith("github_pat_")):
            raise ConfigValidationError(
                "GitHub Token 格式不正确，必须以 ghp_ 或 github_pat_ 开头。"
            )
        if len(token) < 40:
            raise ConfigValidationError("GitHub Token 长度过短，请确认输入是否完整。")

    async def _apply_model(self, model_name: str) -> dict[str, Any]:
        model_name = model_name.strip()
        if not model_name:
            raise ValueError("模型名称不能为空。")
        active = self.config._active_provider_config()
        active.default_model = model_name
        active.ensure_default_model_present()
        self.config._sync_runtime_sections()
        self.config.save(self.config_path, save_key=True)
        return self._config_snapshot()

    async def _model_status(self) -> dict[str, Any]:
        provider_config = self.config.ai_client.model_provider
        local = provider_config.name.lower() in {"ollama", "local"}
        status: dict[str, Any] = {
            "provider": provider_config.name,
            "provider_display": provider_config.display_name,
            "model": provider_config.model_name,
            "base_url": provider_config.base_url,
            "local": local,
            "api_key_configured": bool(provider_config.api_key or local),
            "available": None,
            "models": [],
            "message": "",
        }
        try:
            provider = create_model_provider(provider_config)
            health_check = getattr(provider, "health_check", None)
            if callable(health_check):
                status["available"] = bool(await health_check(timeout_seconds=3))
            else:
                status["available"] = bool(provider_config.api_key)
            list_models = getattr(provider, "list_models", None)
            if callable(list_models):
                status["models"] = await list_models(timeout_seconds=5)
            if status["available"] is True:
                status["message"] = "模型服务可用。"
        except Exception as exc:
            status["available"] = False
            status["message"] = str(exc)
        return status

    @staticmethod
    def _model_status_text(status: dict[str, Any]) -> str:
        availability = (
            "可用"
            if status.get("available")
            else "不可用" if status.get("available") is False else "未检测"
        )
        key = "已配置" if status.get("api_key_configured") else "未配置"
        models = status.get("models") or []
        text = (
            f"{status.get('provider_display', status.get('provider', 'provider'))} / {status.get('model', 'model')}\n"
            f"运行状态：{availability} · API Key：{key}\n"
            f"Endpoint：{status.get('base_url', '')}"
        )
        if models:
            text += "\n本地/远端模型：" + ", ".join(str(model) for model in models[:8])
        if status.get("message"):
            text += "\n提示：" + str(status["message"])
        if status.get("available") is False:
            if status.get("local"):
                text += "\n建议：启动 Ollama，或使用 /model cloud 切换到云端。"
            elif not status.get("api_key_configured"):
                text += "\n建议：配置 API Key，或使用 /model local 切换到本地模型。"
            else:
                text += "\n建议：检查 Endpoint，或使用 Ctrl+P 切换运行时。"
        return text

    @staticmethod
    def _classify_error(exc: Exception) -> dict[str, str]:
        message = str(exc)
        lowered = message.lower()
        if "invalid" in lowered and "pr" in lowered or "github pr url" in lowered:
            return {
                "code": "invalid_pr_url",
                "title": "PR URL 无效",
                "recovery": "请使用 https://github.com/<owner>/<repo>/pull/<number>。",
            }
        if (
            "token" in lowered
            or "authentication" in lowered
            or "401" in lowered
            or "403" in lowered
        ):
            return {
                "code": "github_auth",
                "title": "GitHub 权限或 Token 错误",
                "recovery": "检查 GITHUB_TOKEN 权限，确认仓库和 PR 可访问。",
            }
        if "timeout" in lowered or "timed out" in lowered or "超时" in message:
            return {
                "code": "timeout",
                "title": "请求超时",
                "recovery": "检查网络或切换模型后重试。",
            }
        if "ollama" in lowered or "本地" in message:
            return {
                "code": "local_model_unavailable",
                "title": "本地模型不可用",
                "recovery": "启动 Ollama，或使用 /model cloud 切换到云端。",
            }
        if "api key" in lowered or "key" in lowered and "missing" in lowered:
            return {
                "code": "missing_api_key",
                "title": "API Key 未配置",
                "recovery": "配置 API Key，或使用 /model local 切换到本地模型。",
            }
        if "report" in lowered or "write" in lowered or "permission" in lowered:
            return {
                "code": "storage_error",
                "title": "报告保存失败",
                "recovery": "检查输出目录权限，或更换导出路径。",
            }
        return {"code": "backend_error", "title": "请求失败", "recovery": "检查模型状态后重试。"}

    def _config_text(self) -> str:
        snapshot = self._config_snapshot()
        return (
            f"Provider: {snapshot['provider_display']} ({snapshot['provider']})\n"
            f"Model: {snapshot['model']}\n"
            f"Runtime: {snapshot['runtime_profile']} / {snapshot['strategy']}\n"
            f"Endpoint: {snapshot['base_url']}"
            + "".join(f"\n配置提示：{warning}" for warning in snapshot["configuration_warnings"])
        )

    @staticmethod
    def _truncate(value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        return value[: max(0, limit - 32)] + "\n… [内容已截断]"

    def _bound_report(self, report: dict[str, Any]) -> dict[str, Any]:
        """Bound report text before it crosses the JSONL/UI boundary."""
        bounded = dict(report)
        if isinstance(bounded.get("summary"), str):
            bounded["summary"] = self._truncate(str(bounded["summary"]), 8000)
        findings = bounded.get("findings")
        if isinstance(findings, list):
            bounded["findings"] = []
            for raw in findings:
                if not isinstance(raw, dict):
                    continue
                finding = dict(raw)
                for key, limit in (
                    ("title", 500),
                    ("problem", 6000),
                    ("message", 6000),
                    ("suggestion", 6000),
                    ("code_snippet", 12000),
                ):
                    if isinstance(finding.get(key), str):
                        finding[key] = self._truncate(finding[key], limit)
                bounded["findings"].append(finding)
        return bounded

    def _session_snapshot(self, session: Session) -> dict[str, Any]:
        return {
            "session_id": session.session_id,
            "messages": session.messages,
            "message_count": len(session.messages),
        }

    async def _chat(
        self,
        session: Session,
        text: str,
        on_delta: Callable[[str], Awaitable[None]],
        cancel_event: threading.Event,
    ) -> str:
        provider_config = self.config.ai_client.model_provider
        if not provider_config.api_key and provider_config.name.lower() not in {"ollama", "local"}:
            raise RuntimeError(f"Missing API key for provider: {provider_config.name}")
        provider = create_model_provider(provider_config)
        text = self._truncate(text, 12000)
        history = [*session.messages, {"role": "user", "content": text}]
        chat_options: dict[str, Any] = {
            "system_prompt": (
                "Respond in English unless the user explicitly asks for another language."
                if self.config.preferences.language.lower().startswith("en")
                else "请默认使用中文回答，除非用户明确要求使用其他语言。"
            ),
            "max_tokens": self.config.ai_client.max_tokens,
            "timeout_seconds": self.config.ai_client.timeout_seconds,
        }
        if provider_config.name.lower() in {"ollama", "local"}:
            # Qwen3.5 / DeepSeek-R1 style locally hosted models otherwise spend
            # the whole answer budget in the reasoning channel and return an
            # empty `content`, which Chat surfaces as a connection failure.
            chat_options["reasoning_effort"] = "none"
        response = await provider.stream_chat(
            history,
            on_delta,
            cancel_event=cancel_event,
            **chat_options,
        )
        if cancel_event.is_set():
            raise asyncio.CancelledError
        response_text = self._truncate(response.text, 20000)
        session.messages = [*history, {"role": "assistant", "content": response_text}][-40:]
        return response_text

    def _publish(self, event: dict[str, Any], events: list[dict[str, Any]]) -> None:
        session_id = str(event.get("session_id", ""))
        name = str(event.get("event", ""))
        # Only review progress is rate-limited. Counting chat deltas here used to
        # exhaust the per-session budget, after which a review's `review.stage`
        # frames were silently dropped and the progress bar froze.
        if session_id and name.startswith("review."):
            count = self.event_counts.get(session_id, 0)
            if count >= self.max_events_per_session:
                # Drop only repetitive progress frames; terminal/result events must pass.
                if name in {
                    "review.stage",
                    "review.file_started",
                    "review.file_done",
                }:
                    return
            self.event_counts[session_id] = count + 1
        if self.event_sink is not None:
            self.event_sink(event)
        else:
            events.append(event)

    async def _run_review(
        self,
        pr_url: str,
        session_id: str | None,
        events: list[dict[str, Any]],
        cancel_event: asyncio.Event | None = None,
    ) -> dict[str, Any]:
        """Run the production review pipeline and publish live stage events."""
        from ai_pr_review.cli import build_report_payload, run_review

        self._publish({"event": "review.started", "session_id": session_id, "url": pr_url}, events)

        def check_cancelled() -> None:
            if cancel_event is not None and cancel_event.is_set():
                raise ReviewCancelled("Review cancelled by user")

        def stage_callback(stage: str, detail: str = "") -> None:
            check_cancelled()
            self._publish(
                {
                    "event": "review.stage",
                    "session_id": session_id,
                    "stage": stage,
                    "detail": detail,
                },
                events,
            )

        def file_started(filename: str, active_model: str) -> None:
            check_cancelled()
            self._publish(
                {
                    "event": "review.file_started",
                    "session_id": session_id,
                    "filename": filename,
                    "model": active_model,
                },
                events,
            )

        def file_done(filename: str) -> None:
            check_cancelled()
            self._publish(
                {
                    "event": "review.file_done",
                    "session_id": session_id,
                    "filename": filename,
                },
                events,
            )

        artifacts = await run_review(
            pr_url,
            config=self.config,
            progress_console=None,
            stage_callback=stage_callback,
            progress_callback=file_started,
            file_done_callback=file_done,
            cancel_check=((lambda: cancel_event.is_set()) if cancel_event is not None else None),
        )
        # The orchestrators re-check before persisting, but a cancel racing the
        # very last stage must not be reported as a successful review either.
        check_cancelled()
        payload = build_report_payload(artifacts)
        findings = payload.get("findings", [])
        finding_count = len(findings) if isinstance(findings, list) else 0
        summary = str(payload.get("summary", "审查已完成"))
        payload = self._bound_report(payload)
        self.current_report = payload
        return {
            "text": f"PR 审查完成：{summary}\n发现 {finding_count} 个问题\nRun: {artifacts.run_id}",
            "run_id": artifacts.run_id,
            "summary": summary,
            "finding_count": finding_count,
            "report": payload,
        }

    def _history_text(self, limit: int = 10) -> str:
        from ai_pr_review.services.result_store import ResultStore

        store = ResultStore(self.config.result_store)
        runs = store.list_runs(limit=max(1, min(limit, 50)))
        # A fallback database reads as "my history disappeared"; say so explicitly.
        fallback_note = (
            f"\n注意：历史数据库的原定路径不可写，实际使用 {store.db_path}。"
            if store.using_fallback_path
            else ""
        )
        if not runs:
            return "暂无历史审查记录。" + fallback_note
        lines = ["REVIEW HISTORY"]
        for run in runs:
            lines.append(
                f"{run.get('id', '?')} · {run.get('repo_owner', '?')}/{run.get('repo_name', '?')} "
                f"· findings={run.get('total_findings', 0)} · {run.get('created_at', '')}"
            )
        if fallback_note:
            lines.append(fallback_note.strip())
        return "\n".join(lines)

    def _history_detail(self, run_id: str) -> dict[str, Any]:
        from ai_pr_review.services.result_store import ResultStore

        store = ResultStore(self.config.result_store)
        metadata = store.get_run_metadata(run_id)
        result = store.get_result(run_id)
        runs = store.list_runs(limit=50)
        run = next((item for item in runs if item.get("id") == run_id), None)
        if run is None or result is None:
            return {"text": f"未找到历史 Run：{run_id}", "run": None}
        report: dict[str, Any] = {
            "summary": result.summary,
            "findings": [finding.model_dump(mode="json") for finding in result.findings],
            "counts": {
                "total_findings": len(result.findings),
                "by_severity": {
                    severity: sum(1 for finding in result.findings if finding.severity == severity)
                    for severity in ("critical", "high", "medium", "low", "info")
                },
            },
            "pr": {
                "repository": f"{run.get('repo_owner', '')}/{run.get('repo_name', '')}",
                "url": run.get("pr_url", ""),
                "files_reviewed": run.get("included_files", 0),
                "files_skipped": run.get("excluded_files", 0),
            },
            "run": {
                "id": run_id,
                "duration_seconds": run.get("duration_seconds", 0),
                "total_cost": run.get("total_cost", 0),
            },
        }
        # A run loaded from history becomes the current report, so /report and
        # /export work on it exactly as they do right after a fresh review.
        # Without this they answered "当前会话还没有可导出的审查报告。" even
        # though the report was on screen.
        self.current_report = report
        return {
            "text": f"历史报告：{run_id}\n{result.summary}",
            "run": run,
            "metadata": metadata,
            "report": report,
        }

    def _export_text(self, fmt: str) -> str:
        if self.current_report is None:
            return "当前会话还没有可导出的审查报告。"
        if fmt == "json":
            return json.dumps(self.current_report, ensure_ascii=False, indent=2)
        if fmt in {"md", "markdown"}:
            pr = self.current_report.get("pr", {})
            counts = self.current_report.get("counts", {})
            lines = [
                f"# PR Review: {pr.get('title', 'Pull Request')}",
                "",
                f"- Repository: {pr.get('repository', '')}",
                f"- URL: {pr.get('url', '')}",
                f"- Findings: {counts.get('total_findings', 0)}",
                "",
                "## Summary",
                str(self.current_report.get("summary", "")),
                "",
                "## Findings",
            ]
            for finding in self.current_report.get("findings", []):
                lines.extend(
                    [
                        f"### [{str(finding.get('severity', 'info')).upper()}] {finding.get('title', 'Finding')}",
                        f"- File: `{finding.get('file', '')}:{finding.get('line_start', '?')}-{finding.get('line_end', '?')}`",
                        f"- Problem: {finding.get('problem', finding.get('message', ''))}",
                        f"- Suggestion: {finding.get('suggestion', '')}",
                        "",
                    ]
                )
            return "\n".join(lines)
        return f"不支持的导出格式：{fmt}"

    async def handle(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        request_id = request.get("id")
        method = str(request.get("method", ""))
        params: dict[str, Any] = (
            cast(dict[str, Any], request.get("params"))
            if isinstance(request.get("params"), dict)
            else {}
        )
        events: list[dict[str, Any]] = []

        def result(payload: Any) -> None:
            events.append({"id": request_id, "ok": True, "result": payload})

        def error(message: str, code: str = "backend_error") -> None:
            events.append(
                {"id": request_id, "ok": False, "error": {"code": code, "message": message}}
            )

        try:
            if method == "health":
                result(
                    {"status": "ready", "config_path": str(resolve_config_path(self.config_path))}
                )
            elif method == "config.snapshot":
                result(self._config_snapshot())
            elif method == "config.options":
                result(self._setup_options())
            elif method == "config.setup":
                result(self._apply_setup(params))
            elif method == "model.status":
                status = await self._model_status()
                result(status)
            elif method == "model.apply":
                model_name = str(params.get("model", ""))
                snapshot = await self._apply_model(model_name)
                result({"config": snapshot, "status": await self._model_status()})
            elif method == "config.apply":
                section = str(params.get("section", ""))
                if section != "runtime":
                    error(f"Unsupported config section: {section}", "unsupported_config")
                else:
                    result(self._apply_runtime_profile(str(params.get("value", ""))))
            elif method == "session.create":
                session = Session(session_id=uuid.uuid4().hex)
                self.sessions[session.session_id] = session
                result(self._session_snapshot(session))
            elif method == "session.get":
                existing_session = self.sessions.get(str(params.get("session_id", "")))
                if existing_session is None:
                    error("Session not found", "not_found")
                else:
                    result(self._session_snapshot(existing_session))
            elif method == "chat.send":
                session_id = str(params.get("session_id", ""))
                text = str(params.get("text", "")).strip()
                existing_session = self.sessions.get(session_id)
                if existing_session is None:
                    error("Session not found", "not_found")
                elif not text:
                    error("Message cannot be empty", "invalid_request")
                elif session_id in self.chat_cancellations:
                    error("A Chat request is already running", "busy")
                else:
                    task = asyncio.current_task()
                    assert task is not None
                    chat_stop_event = threading.Event()
                    self.chat_cancellations[session_id] = (task, chat_stop_event)
                    self._publish(
                        {
                            "event": "assistant.started",
                            "session_id": session_id,
                            "request_id": request_id,
                        },
                        events,
                    )

                    async def on_delta(delta: str) -> None:
                        if chat_stop_event.is_set():
                            return
                        self._publish(
                            {
                                "event": "assistant.delta",
                                "session_id": session_id,
                                "request_id": request_id,
                                "text": delta,
                            },
                            events,
                        )

                    try:
                        answer = await self._chat(existing_session, text, on_delta, chat_stop_event)
                    except asyncio.CancelledError:
                        chat_stop_event.set()
                        self._publish(
                            {
                                "event": "assistant.cancelled",
                                "session_id": session_id,
                                "request_id": request_id,
                            },
                            events,
                        )
                        result({"cancelled": True})
                    except Exception as exc:
                        self._publish(
                            {
                                "event": "assistant.failed",
                                "session_id": session_id,
                                "request_id": request_id,
                                "message": str(exc),
                            },
                            events,
                        )
                        raise
                    else:
                        self._publish(
                            {
                                "event": "assistant.finished",
                                "session_id": session_id,
                                "request_id": request_id,
                                "text": answer,
                            },
                            events,
                        )
                        result(
                            {"text": answer, "session": self._session_snapshot(existing_session)}
                        )
                    finally:
                        self.chat_cancellations.pop(session_id, None)
            elif method == "command.execute":
                command = str(params.get("name", "")).strip().lower()
                if command == "status":
                    result({"text": self._config_text(), "config": self._config_snapshot()})
                elif command == "help":
                    result(
                        {
                            "text": "/setup  配置助手\n/status 查看运行状态\n/model  查看当前模型\n/review 开始 PR 审查\n/cancel 取消当前审查\n/retry 重试上一次操作\n/report 查看当前报告\n/export json|markdown 导出当前报告\n/history 查看历史记录\n/exit   退出 Chat"
                        }
                    )
                elif command == "setup":
                    result({"text": "请使用 Ctrl+P 或输入 /setup 打开配置助手。"})
                elif command == "model":
                    raw_args = params.get("args", [])
                    args = (
                        [str(item).lower() for item in raw_args]
                        if isinstance(raw_args, list)
                        else []
                    )
                    if args and args[0] == "status":
                        status = await self._model_status()
                        result({"text": self._model_status_text(status), "status": status})
                    elif args and args[0] in {"local", "cloud", "hybrid", "offline"}:
                        snapshot = self._apply_runtime_profile(args[0])
                        status = await self._model_status()
                        result(
                            {
                                "text": f"运行时已切换为 {args[0]}\n"
                                + self._model_status_text(status),
                                "config": snapshot,
                                "status": status,
                            }
                        )
                    elif args:
                        snapshot = await self._apply_model(args[0])
                        status = await self._model_status()
                        result(
                            {
                                "text": f"模型已切换为 {args[0]}\n"
                                + self._model_status_text(status),
                                "config": snapshot,
                                "status": status,
                            }
                        )
                    else:
                        status = await self._model_status()
                        result({"text": self._model_status_text(status), "status": status})
                elif command == "report":
                    if self.current_report is None:
                        result({"text": "当前会话还没有审查报告。"})
                    else:
                        result(
                            {"text": self._export_text("markdown"), "report": self.current_report}
                        )
                elif command == "export":
                    raw_args = params.get("args", [])
                    args = [str(item) for item in raw_args] if isinstance(raw_args, list) else []
                    fmt = args[0].lower() if args else "markdown"
                    export_text = self._export_text(fmt)
                    output_path = Path(args[1]).expanduser() if len(args) > 1 else None
                    if output_path is not None:
                        if not output_path.is_absolute():
                            output_path = Path.cwd() / output_path
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        output_path.write_text(export_text, encoding="utf-8")
                        result(
                            {
                                "text": f"报告已导出：{output_path}",
                                "format": fmt,
                                "path": str(output_path),
                            }
                        )
                    else:
                        result({"text": export_text, "format": fmt})
                elif command == "history":
                    from ai_pr_review.services.result_store import ResultStore

                    raw_args = params.get("args", [])
                    args = [str(item) for item in raw_args] if isinstance(raw_args, list) else []
                    if args and not args[0].isdigit():
                        result(self._history_detail(args[0]))
                    else:
                        limit = int(args[0]) if args and args[0].isdigit() else 10
                        store = ResultStore(self.config.result_store)
                        runs = store.list_runs(limit=max(1, min(limit, 50)))
                        result(
                            {
                                "text": self._history_text(limit),
                                "runs": runs,
                                "statistics": store.get_statistics(),
                                "fallback_note": (
                                    f"历史库已回退至：{store.db_path}"
                                    if store.using_fallback_path
                                    else ""
                                ),
                            }
                        )
                elif command == "cancel":
                    cancel_session_id = str(params.get("session_id", ""))
                    chat_task = self.chat_cancellations.get(cancel_session_id)
                    review_event = self.review_cancellations.get(cancel_session_id)
                    # Cancel both: a session can have a chat and a review in
                    # flight at once, and the old `elif` left the review with no
                    # cancellation path at all.
                    pending: list[str] = []
                    if chat_task is not None:
                        chat_task[1].set()
                        chat_task[0].cancel()
                        pending.append("对话")
                    if review_event is not None:
                        review_event.set()
                        pending.append("审查")
                    if pending:
                        result(
                            {
                                "cancelled": True,
                                "text": f"已请求取消当前{'与'.join(pending)}。",
                            }
                        )
                    else:
                        result({"cancelled": False, "text": "当前没有正在运行的任务。"})
                elif command == "review":
                    raw_args = params.get("args", [])
                    args = (
                        [str(item).strip() for item in raw_args]
                        if isinstance(raw_args, list)
                        else []
                    )
                    if not args or not args[0]:
                        result({"text": "请提供 PR URL：/review <URL>"})
                    else:
                        review_session_id = str(params.get("session_id", "")) or None
                        if (
                            review_session_id is not None
                            and review_session_id in self.review_cancellations
                        ):
                            # The backend is the authority here, not the TUI's
                            # client-side lock: a second `/review` used to
                            # overwrite the running entry, which left the first
                            # review uncancellable and made whichever finished
                            # first clear the *other* review's event.
                            error("该会话已有审查正在进行，请等待完成或使用 /cancel。", "busy")
                        else:
                            cancel_event = asyncio.Event()
                            if review_session_id is not None:
                                self.review_cancellations[review_session_id] = cancel_event
                            try:
                                review_result = await asyncio.wait_for(
                                    self._run_review(
                                        args[0], review_session_id, events, cancel_event
                                    ),
                                    timeout=self.review_timeout_seconds,
                                )
                            except asyncio.TimeoutError:
                                details = {
                                    "code": "review_timeout",
                                    "title": "审查超时",
                                    "recovery": "检查网络或模型服务后使用 Ctrl+R /retry 重试。",
                                }
                                self._publish(
                                    {
                                        "event": "review.failed",
                                        "session_id": review_session_id,
                                        "message": "审查超过最大运行时间。",
                                        **details,
                                    },
                                    events,
                                )
                                error(
                                    "审查超过最大运行时间。\n" + details["recovery"],
                                    details["code"],
                                )
                            except ReviewCancelled:
                                self._publish(
                                    {
                                        "event": "review.cancelled",
                                        "session_id": review_session_id,
                                        "message": "审查已取消",
                                    },
                                    events,
                                )
                                result({"cancelled": True, "text": "审查已取消"})
                            except Exception as exc:
                                details = self._classify_error(exc)
                                self._publish(
                                    {
                                        "event": "review.failed",
                                        "session_id": review_session_id,
                                        "message": str(exc),
                                        **details,
                                    },
                                    events,
                                )
                                raise
                            else:
                                self._publish(
                                    {
                                        "event": "review.completed",
                                        "session_id": review_session_id,
                                        "run_id": review_result["run_id"],
                                        "finding_count": review_result["finding_count"],
                                    },
                                    events,
                                )
                                result(review_result)
                            finally:
                                # Identity check: only the review that owns the
                                # entry may clear it. A plain `pop` also dropped
                                # whatever another in-flight review had stored.
                                if (
                                    review_session_id is not None
                                    and self.review_cancellations.get(review_session_id)
                                    is cancel_event
                                ):
                                    self.review_cancellations.pop(review_session_id, None)
                                    self.event_counts.pop(review_session_id, None)
                elif command == "new":
                    session = Session(session_id=uuid.uuid4().hex)
                    self.sessions[session.session_id] = session
                    result(self._session_snapshot(session))
                else:
                    error(f"Unsupported command: {command}", "unsupported_command")
            else:
                error(f"Unsupported method: {method}", "unsupported_method")
        except Exception as exc:  # protocol boundary must never crash the process
            print(f"backend request failed: {exc!r}", file=sys.stderr, flush=True)
            details = self._classify_error(exc)
            error(f"{details['title']}：{exc}\n{details['recovery']}", details["code"])
        return events


def write_event(event: dict[str, Any]) -> None:
    # Always emit UTF-8 bytes. The TUI front-end decodes the JSONL stream as
    # UTF-8, while Windows text-mode stdout would otherwise encode payloads as
    # cp936/GBK and every non-ASCII character would arrive as mojibake.
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(payload.encode("utf-8"))
        buffer.flush()
    else:
        sys.stdout.write(payload)
        sys.stdout.flush()


async def serve(config_path: Path | None = None) -> None:
    backend = JsonlBackend(config_path, event_sink=write_event)
    tasks: set[asyncio.Task[None]] = set()

    async def process_request(request: dict[str, Any]) -> None:
        try:
            for event in await backend.handle(request):
                write_event(event)
        except Exception as exc:
            write_event(
                {
                    "id": request.get("id"),
                    "ok": False,
                    "error": {"code": "backend_error", "message": str(exc)},
                }
            )

    loop = asyncio.get_running_loop()
    while True:
        # Read one line at a time off the event loop. Iterating ``sys.stdin``
        # directly (or calling readline synchronously) buffers ahead and stalls
        # the loop, so long-running pipe sessions would never see a response.
        raw_line = await loop.run_in_executor(None, sys.stdin.readline)
        if not raw_line:
            break
        line = raw_line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("request must be a JSON object")
            task = asyncio.create_task(process_request(request))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
        except Exception as exc:
            write_event(
                {"id": None, "ok": False, "error": {"code": "invalid_json", "message": str(exc)}}
            )
    if tasks:
        await asyncio.gather(*tasks)


def main() -> None:
    # The JSONL protocol is UTF-8 in both directions regardless of the console
    # code page, so do not rely on the ambient locale (or on PYTHONUTF8).
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except Exception:
            pass
    # The TUI launches this module without CLI arguments and communicates the
    # config path through AI_PR_REVIEW_CONFIG only. Resolve it into an explicit
    # Path here, otherwise AppConfig.load(None) never applies workspace
    # isolation and /history silently reads the shared per-user database.
    override = os.environ.get("AI_PR_REVIEW_CONFIG", "").strip()
    asyncio.run(serve(Path(override).expanduser() if override else None))


if __name__ == "__main__":
    main()
