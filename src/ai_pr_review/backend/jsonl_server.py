"""JSONL backend for the OpenTUI frontend.

The backend deliberately owns domain logic while the TypeScript OpenTUI process owns
terminal rendering. stdout is protocol-only; diagnostics go to stderr.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import threading
import time
import uuid
from collections.abc import Awaitable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, cast

from ai_pr_review.config import (
    CHAT_SLOT_VALUES,
    MODEL_PROVIDER_PRESETS,
    PROVIDER_MODEL_PRESETS,
    REPO_CONTEXT_MODES,
    REVIEW_SLOT_VALUES,
    AppConfig,
    ConfigValidationError,
    ModelProviderConfig,
    ProviderConfig,
    resolve_chat_slot,
    resolve_config_path,
    resolve_review_slot,
    sync_review_slot_to_strategy,
)
from ai_pr_review.services.model_providers.factory import create_model_provider
from ai_pr_review.services.review_context import (
    DEFAULT_TOKEN_BUDGET,
    build_review_context,
    build_review_context_meta,
    describe_run,
    wrap_review_context,
)

# Use the orchestrator's exception class itself. A *subclass* here would NOT
# catch a plain `ReviewCancelled` raised inside `run_review` — `except SubClass`
# never matches a base-class instance, so cancels kept surfacing as
# `review.failed`. Verified by
# `test_orchestrator_cancel_is_reported_as_cancelled_not_failed`.
from ai_pr_review.services.review_orchestrator import ReviewCancelled

# Display labels for the orchestrator's stage ids. The labels match
# `cli.stage_labels` and the progress map the TUI already renders, so `stage`
# stays human-readable while `stage_id` carries the stable machine key.
REVIEW_STAGE_LABELS: dict[str, str] = {
    "fetching": "获取 PR 数据",
    "filtering": "过滤变更文件",
    "context": "构建代码上下文",
    "static_rules": "运行静态规则",
    "reviewing": "执行 AI 审查",
    "cross_file": "分析跨文件影响",
    "persisting": "保存审查记录",
}

# (progress when the stage starts, progress when it completes). Both
# orchestrators walk these ids in increasing order; unknown ids keep the
# previous value so the bar never moves backwards.
REVIEW_STAGE_PROGRESS: dict[str, tuple[int, int]] = {
    "fetching": (5, 10),
    "filtering": (10, 20),
    "context": (20, 30),
    "static_rules": (30, 50),
    "reviewing": (70, 90),
    "cross_file": (90, 98),
    "persisting": (98, 100),
}

# Both orchestrators announce the reviewable-file count inside stage details
# ("正在为 4 个文件构建上下文" / "为 4 个文件构建代码上下文" / "共 4 个文件").
# The filtering detail ("共 120 个变更文件") is deliberately not matched: it
# counts every changed file, not the files that will actually be reviewed.
REVIEW_FILE_TOTAL_PATTERN = re.compile(r"(\d+)\s*个文件")

# `review.model_routing` states the configured policy, not per-file decisions
# (the orchestrator chooses a model per file and never reports it back).
REVIEW_ROUTING_REASONS: dict[str, dict[str, str]] = {
    "local_only": {
        "zh-CN": "仅本地模型：全部文件由本地模型审查，代码不会离开本机",
        "en-US": "Local only: every file is reviewed on-device; code never leaves the machine",
    },
    "remote_only": {
        "zh-CN": "仅远程模型：全部文件由远程模型审查",
        "en-US": "Remote only: every file is reviewed by the remote model",
    },
    "hybrid": {
        "zh-CN": "混合策略：低风险文件走本地模型，高风险或复杂文件走远程模型",
        "en-US": (
            "Hybrid: low-risk files use the local model, "
            "risky or complex files use the remote model"
        ),
    },
}


# CHAT/REVIEW 双槽路由（docs/dual-model-roles-plan.md §3、§5.4）。
# 槽位是**角色名**，不是"provider 一定在远端"的断言：`remote` 槽永远是持久化的
# 主 Provider（可能是 Ollama），`local` 槽永远是 `local_provider`。
ROUTE_SLOT_LABELS: dict[str, str] = {"remote": "云端", "local": "本地", "hybrid": "混合"}
# 路由快照里的 `profile`：显式槽位 -> custom，否则由运行模式预设折算（方案 §3.2/§3.4）。
ROUTE_PROFILE_BY_STRATEGY: dict[str, str] = {
    "remote_only": "cloud",
    "local_only": "local",
    "balanced": "hybrid",
}
# 配置助手第 1 步的预设清单（方案 §4.1）。`offline` 是旧值：读取时等价于"本地"，
# 因此不再作为可选项提供，由 `_apply_setup` 继续接受以保持旧载荷兼容。
RUNTIME_PROFILES: tuple[tuple[str, str], ...] = (
    ("cloud", "云端"),
    ("local", "本地"),
    ("hybrid", "混合"),
    ("custom", "自定义"),
)
# 仓库上下文预取范围（config.REPO_CONTEXT_MODES）的展示文案。取值本身由 config 拥有，
# 这里只补 label——与 runtime_profiles / chat_layouts 一样，TUI 不硬编码中文。
REPO_CONTEXT_LABELS: dict[str, str] = {
    "off": "关闭 / Off",
    "tests": "仅测试文件 / Tests only",
    "tests+imports": "测试与依赖 / Tests + imports",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_review_file_total(detail: str) -> int | None:
    match = REVIEW_FILE_TOTAL_PATTERN.search(detail or "")
    return int(match.group(1)) if match else None


# Must match `ResultStore.save_feedback` and the CLI's `feedback --status`
# choice; a drifted list here would silently accept a value the store rejects.
FEEDBACK_STATUSES = frozenset({"accepted", "rejected", "fixed", "needs_review"})


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _optional_int(value: Any) -> int | None:
    """An int, or None when the value is missing/not a number.

    Never invents a number: an unknown per-file count or duration stays null.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# "PR #31" / "pull/31" / "pr 31" —— 用户最常用的指代方式。
_PR_NUMBER_PATTERN = re.compile(r"(?:pull/|pr\s*#?\s*|#)\s*(\d+)", re.IGNORECASE)
# "第 2 个" / "选 2" / "2 号" —— 候选清单的序号选择（复制 run id 很不方便）。
_ORDINAL_PATTERN = re.compile(r"第\s*(\d+)\s*个|选\s*(\d+)|(\d+)\s*号")


def _extract_pr_number(text: str) -> int | None:
    """从用户消息里取 PR 编号；取不到返回 None（绝不猜）。"""
    match = _PR_NUMBER_PATTERN.search(text or "")
    if match is None:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _extract_ordinal(text: str) -> int | None:
    """从用户消息里取候选序号；取不到返回 None。"""
    match = _ORDINAL_PATTERN.search(text or "")
    if match is None:
        return None
    raw = next((group for group in match.groups() if group), None)
    try:
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None


def _review_completed_fields(report: dict[str, Any]) -> dict[str, Any]:
    """Summary fields for `review.completed`, read from the report payload.

    Everything is derived from data the pipeline actually produced. Counts the
    orchestrator does not expose stay at their true value (0) instead of being
    estimated.

    `filtered` is additive (contract §3.7 extension): it repeats the report's
    `run.filtered` block when the run recorded one, so the live TUI can explain
    a 0-finding review without re-reading the report. Runs that recorded no
    filter stats get no `filtered` key rather than a fabricated
    `{"below_threshold": 0}`.
    """
    pr = report.get("pr") if isinstance(report.get("pr"), dict) else {}
    counts = report.get("counts") if isinstance(report.get("counts"), dict) else {}
    run = report.get("run") if isinstance(report.get("run"), dict) else {}
    findings = report.get("findings") if isinstance(report.get("findings"), list) else []

    by_severity = counts.get("by_severity") if isinstance(counts.get("by_severity"), dict) else {}
    severity = {
        level: int(_as_float(by_severity.get(level, 0)))
        for level in ("critical", "high", "medium", "low", "info")
    }
    # `FindingValidator.annotate` stamps `evidence_status`; findings that never
    # reached the validator keep the model default "unverified".
    evidence = {"valid": 0, "needs_review": 0, "invalid": 0, "unverified": 0}
    for finding in findings:
        status = str(finding.get("evidence_status", "")) if isinstance(finding, dict) else ""
        evidence[status if status in evidence else "unverified"] += 1
    fields: dict[str, Any] = {
        "files_reviewed": int(_as_float(pr.get("files_reviewed", 0))),
        "files_skipped": int(_as_float(pr.get("files_skipped", 0))),
        "severity": severity,
        "evidence": evidence,
        "cost": round(_as_float(run.get("total_cost", 0.0)), 6),
        "duration_seconds": round(_as_float(run.get("duration_seconds", 0.0)), 3),
    }
    # Passed through verbatim, not re-derived: `build_report_payload` already
    # normalized it, and the event must not disagree with the report.
    filtered = run.get("filtered")
    if isinstance(filtered, dict) and filtered:
        fields["filtered"] = dict(filtered)
    # The live TUI used to render "发现 N 个问题" for every run, which reads as
    # a contradiction next to a failure summary (PR #31: 14 files all failed,
    # static analysis still produced 4 findings). Pass the summary through so
    # the client can prefer it when the run failed. Additive: absent for
    # reports without one, and existing fields keep their meaning.
    summary = report.get("summary")
    if isinstance(summary, str) and summary.strip():
        fields["summary"] = summary.strip()
    return fields


class _ReviewEventStream:
    """Publishes the review workspace event contract for one review run.

    The orchestrator only reports stage *starts* (`stage_callback`), so stage
    durations are measured here: a stage ends when the next one starts, or when
    the run finishes. Per-file outcomes arrive through `file_result_callback`
    (`file_result`, contract §10.2) and are used verbatim; when an orchestrator
    does not report them, the previous null/measured fallback still applies —
    values are never invented. See `docs/claude-review-actions.md`.
    """

    def __init__(
        self,
        publish: Callable[[dict[str, Any]], None],
        session_id: str | None,
    ) -> None:
        self._publish = publish
        self._session_id = session_id
        self.files_started = 0
        self.files_total: int | None = None
        self.last_stage_id: str | None = None
        self.finished = False
        self._file_starts: dict[str, list[tuple[float, int]]] = {}
        self._file_results: dict[str, list[dict[str, Any]]] = {}
        self._stage: tuple[str, str, float] | None = None
        self._progress = 0

    def stage_id_field(self) -> dict[str, str]:
        """`stage_id` for terminal events, when a stage was running."""
        return {"stage_id": self.last_stage_id} if self.last_stage_id else {}

    def _emit(self, name: str, **payload: Any) -> None:
        if self.finished:
            # `asyncio.gather` does not cancel sibling file tasks, so an
            # in-flight file can still report `file_done` after the run ended.
            return
        self._publish({"event": name, "session_id": self._session_id, **payload})

    def _advance(self, stage_id: str, *, done: bool) -> int:
        span = REVIEW_STAGE_PROGRESS.get(stage_id)
        if span is not None:
            self._progress = max(self._progress, span[1 if done else 0])
        return self._progress

    def started(self, url: str) -> None:
        self._emit("review.started", url=url, started_at=_utc_now())

    def routing(self, routing: dict[str, Any] | None) -> None:
        """Emit `review.model_routing` once, when the backend can name the models."""
        if routing:
            self._emit("review.model_routing", **routing)

    def stage(self, stage_id: str, detail: str = "") -> None:
        now = time.perf_counter()
        self._close_stage(now)
        if self.files_total is None:
            self.files_total = _parse_review_file_total(detail)
        label = REVIEW_STAGE_LABELS.get(stage_id, stage_id)
        self.last_stage_id = stage_id
        self._stage = (stage_id, label, now)
        self._emit(
            "review.stage",
            stage_id=stage_id,
            stage=label,
            status="started",
            detail=detail,
            progress=self._advance(stage_id, done=False),
            started_at=_utc_now(),
        )

    def _close_stage(
        self,
        now: float,
        status: str = "completed",
        message: str | None = None,
        recovery: str | None = None,
    ) -> None:
        if self._stage is None:
            return
        stage_id, label, started_at = self._stage
        self._stage = None
        payload: dict[str, Any] = {
            "stage_id": stage_id,
            "stage": label,
            "status": status,
            "progress": self._advance(stage_id, done=status == "completed"),
            "duration_ms": max(0, round((now - started_at) * 1000)),
        }
        if message is not None:
            payload["message"] = message
        if recovery is not None:
            payload["recovery"] = recovery
        self._emit("review.stage_done", **payload)

    def file_started(self, filename: str, model: str = "") -> None:
        self.files_started += 1
        self._file_starts.setdefault(filename, []).append(
            (time.perf_counter(), self.files_started)
        )
        self._emit(
            "review.file_started",
            filename=filename,
            model=model,
            index=self.files_started,
            total=self.files_total,
            started_at=_utc_now(),
        )

    def file_result(self, payload: dict[str, Any]) -> None:
        """Record the orchestrator's real per-file outcome (contract §10.2).

        `skipped` files never reach `file_started`/`file_done`, so their event is
        published here; `reviewed`/`failed` outcomes are held until the matching
        `file_done` arrives, which keeps exactly one `review.file_done` per file.
        """
        if not isinstance(payload, dict):
            return
        filename = str(payload.get("filename", "") or "")
        if not filename:
            return
        status = str(payload.get("status", "") or "reviewed")
        if status == "skipped":
            self._emit(
                "review.file_done",
                filename=filename,
                index=None,
                total=self.files_total,
                status="skipped",
                findings_count=_optional_int(payload.get("findings_count")),
                duration_ms=_optional_int(payload.get("duration_ms")),
                reason="filtered_by_policy",
            )
            return
        self._file_results.setdefault(filename, []).append(dict(payload))

    def file_done(self, filename: str) -> None:
        starts = self._file_starts.get(filename) or []
        started_at, index = starts.pop(0) if starts else (None, None)
        if not starts:
            self._file_starts.pop(filename, None)
        results = self._file_results.get(filename) or []
        payload = results.pop(0) if results else None
        if not results:
            self._file_results.pop(filename, None)
        measured_ms = (
            None
            if started_at is None
            else max(0, round((time.perf_counter() - started_at) * 1000))
        )
        duration_ms = _optional_int(payload.get("duration_ms")) if payload else None
        if duration_ms is None:
            # Fall back to the backend's own measurement only when the
            # orchestrator reported nothing for this file.
            duration_ms = measured_ms
        event: dict[str, Any] = {
            "filename": filename,
            "index": index,
            "total": self.files_total,
            "status": str(payload.get("status", "") or "reviewed") if payload else "reviewed",
            "findings_count": _optional_int(payload.get("findings_count")) if payload else None,
            "duration_ms": duration_ms,
        }
        error = payload.get("error") if payload else None
        if isinstance(error, str) and error:
            event["error"] = error
        self._emit("review.file_done", **event)

    def complete(self) -> None:
        """Close the last stage after a successful run."""
        self._close_stage(time.perf_counter(), status="completed")
        self.finished = True

    def abort(
        self,
        status: str,
        *,
        message: str | None = None,
        recovery: str | None = None,
    ) -> None:
        """Close the in-flight stage after a cancellation or a failure."""
        self._close_stage(
            time.perf_counter(), status=status, message=message, recovery=recovery
        )
        self.finished = True


@dataclass
class Session:
    session_id: str
    messages: list[dict[str, str]] = field(default_factory=list)
    # Runs already published from this session (§12.2). In-memory only: a
    # repeat publish in a *new* session is a deliberate second comment, not a
    # mistake, and nothing here may survive a restart.
    published_run_ids: set[str] = field(default_factory=set)
    # The run this session is currently discussing (§9.2 A). Chat injects the
    # matching review context into its system prompt; in-memory only, so a
    # restart (or `/context off`) cleanly returns to plain chat.
    current_run_id: str | None = None
    # Runs most recently offered to the user, in display order. Lets the next
    # turn resolve "第 2 个" / "第二个" without asking anyone to copy a UUID.
    # Only ids are kept; nothing here indexes the result store.
    context_candidates: list[str] = field(default_factory=list)


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
        return ROUTE_PROFILE_BY_STRATEGY.get(strategy, "cloud")

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
        # 切运行模式和走配置助手的预设一样，要把显式槽位覆盖清掉（方案 §4.1）。
        self._clear_route_slots()
        self.config._sync_runtime_sections()
        self.runtime_profile = profile
        self.config.save(self.config_path, save_key=True)
        return self._config_snapshot()

    @staticmethod
    def _has_explicit_value(preferences: object, field: str, allowed: tuple[str, ...]) -> bool:
        """字段是否是**合法**的显式取值（docs/dual-model-roles-plan.md §3.3）。

        只有合法值算显式：非法值在 config 层会被回退成"跟随运行模式预设"，
        这里若按"字段非空就算"会让确认页显示 custom、实际却按预设路由。
        """
        value = str(getattr(preferences, field, "") or "").strip().lower()
        return value in allowed

    def _has_explicit_slot(self) -> bool:
        """是否显式指定了任一槽位（方案 §3.3）。"""
        preferences = self.config.preferences
        return self._has_explicit_value(
            preferences, "chat_slot", CHAT_SLOT_VALUES
        ) or self._has_explicit_value(preferences, "review_slot", REVIEW_SLOT_VALUES)

    def _clear_route_slots(self) -> None:
        """清空两个槽位覆盖：运行模式预设是唯一事实来源（方案 §4.1）。

        不清空的话：选了预设却仍被 `resolve_review_slot` 里的"显式优先"规则压住，
        协议上的 `routing.review` 会与实际生效的审查策略互相矛盾。
        """
        self.config.preferences.chat_slot = ""
        self.config.preferences.review_slot = ""

    def _slot_model(self, slot: str) -> str:
        """槽位在路由快照里代表的模型名。

        `hybrid` 没有单一模型，报远端（升级）模型：它是能覆盖全部文件的那个；
        本地模型由 `slot="local"` 表达（与 `ModelSelector` 的 local/remote 槽一致）。
        """
        if slot == "local":
            return str(self.config.local_provider.default_model or "")
        return str(self.config.provider.default_model or "")

    def _routing_snapshot(self) -> dict[str, Any]:
        """`routing` 块：config.snapshot / config.options / model.status 共用（方案 §5.4）。

        只在这里做推导（`resolve_*`），前端只读结果，不得自行由 `hybrid_strategy` 反推。

        `profile` 回答"当前路由来自哪一档预设"，`runtime_profile` 回答"实际哪个槽在生效"
        （后者已按 `_infer_runtime_profile` 把 Ollama 主 Provider 折算成 local）——
        两者在 `custom` 与离线旧值上会不同，这是刻意的。
        """
        chat_slot = resolve_chat_slot(self.config)
        review_slot = resolve_review_slot(self.config)
        profile = (
            "custom"
            if self._has_explicit_slot()
            else ROUTE_PROFILE_BY_STRATEGY.get(
                str(getattr(self.config.preferences, "hybrid_strategy", "") or "")
                .strip()
                .lower(),
                # 未知/缺失的策略与 `resolve_review_slot` 一样按远端处理。
                "cloud",
            )
        )
        return {
            "profile": profile,
            "chat": {
                "slot": chat_slot,
                "label": ROUTE_SLOT_LABELS.get(chat_slot, chat_slot),
                "model": self._slot_model(chat_slot),
            },
            "review": {
                "slot": review_slot,
                "label": ROUTE_SLOT_LABELS.get(review_slot, review_slot),
                "model": self._slot_model(review_slot),
            },
        }

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
            # Workbench Phase 1: the TUI needs this to decide whether a review
            # opens the side panels automatically (auto | always | off).
            "workbench_mode": getattr(self.config.preferences, "workbench_mode", "auto"),
            # 仓库上下文（docs/repo-aware-review-plan.md §4.6）：与 workbench_mode 一样
            # 是"当前档位"，配置助手提交后要能在同一个快照里回显（§5.4 的三个出口同源）。
            "repo_context": self.config.preferences.repo_context,
            "api_format": provider.api_format,
            "api_key_configured": bool(provider.api_key or local),
            "github_token_configured": bool(
                self.config.github_token or self.config.pr_fetcher.github_token
            ),
            "configuration_warnings": list(getattr(self.config, "_ignored_env_overrides", [])),
            "result_store_path": self.config.result_store.db_path,
            # CHAT/REVIEW 双槽路由（方案 §5.4）。既有字段一个都不改名、不删除：
            # provider/model/local 仍然描述"活跃槽"，routing 才是两个槽的真相。
            "routing": self._routing_snapshot(),
        }

    @staticmethod
    def _provider_model_names(provider_name: str) -> list[str]:
        preset = MODEL_PROVIDER_PRESETS.get(provider_name, {})
        models = list(PROVIDER_MODEL_PRESETS.get(provider_name, {}))
        default_model = str(preset.get("model_name", "")).strip()
        if default_model and default_model not in models:
            models.insert(0, default_model)
        return models

    def _repo_context_options(self) -> dict[str, Any]:
        """仓库上下文的当前值与可选值（`config.options` 与 `model.status` 同键同形）。

        `value` 是落盘值（config 层已保证合法：非法值在加载时回退 `tests+imports`），
        `options[].value` 是 `config.setup` 接受的取值，`label` 供 TUI 直接渲染。
        取值清单来自 `config.REPO_CONTEXT_MODES`，后端与前端都不再各存一份。
        """
        return {
            "value": self.config.preferences.repo_context,
            "options": [
                {"value": mode, "label": REPO_CONTEXT_LABELS.get(mode, mode)}
                for mode in REPO_CONTEXT_MODES
            ],
        }

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
            # 运行模式预设由后端定义（第 4 项"自定义"进入路由细化页），
            # 前端只渲染 value/label，不硬编码这一档的存在与否。
            "runtime_profiles": [
                {"value": value, "label": label} for value, label in RUNTIME_PROFILES
            ],
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
            "workbench_modes": [
                {"value": "auto", "label": "自动 / Auto（审查时展开，可 Alt+W 收起）"},
                {"value": "always", "label": "常驻 / Always（一直显示工作台）"},
                {"value": "off", "label": "关闭 / Off（只在状态条里显示进度）"},
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
                # Lets the TUI wizard preselect the current workbench mode.
                "workbench_mode": getattr(self.config.preferences, "workbench_mode", "auto"),
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
            # 确认页/状态栏显示"用户选的是哪一档预设"以及两个槽各用什么模型（方案 §4.1/§5.4）。
            "routing": self._routing_snapshot(),
            # 仓库上下文（docs/repo-aware-review-plan.md §4.6）：配置助手第 5 阶段的三选一，
            # 与 routing 同级，供前端预选并回填到 config.setup。
            "repo_context": self._repo_context_options(),
        }

    @staticmethod
    def _setup_slot(
        params: dict[str, Any],
        key: str,
        allowed: tuple[str, ...],
        current: str,
        label: str,
    ) -> str:
        """读出路由细化页的一个槽位（docs/dual-model-roles-plan.md §4.2）。

        字段缺失（或为 null）= 部分更新，保留已落盘的值；显式空串 = 清除该槽覆盖，
        重新跟随运行模式预设（与 config 层 `""` 的语义一致）。非法值必须报错而不是
        静默回退：这是用户刚刚在细化页做出的选择，悄悄改成别的路由比报错更糟。
        """
        if key not in params or params.get(key) is None:
            return current
        value = str(params[key]).strip().lower()
        if not value:
            return ""
        if value not in allowed:
            raise ConfigValidationError(
                f"{label}槽位仅支持 {'、'.join(allowed[:-1])} 或 {allowed[-1]}。"
            )
        return value

    def _apply_setup(self, params: dict[str, Any]) -> dict[str, Any]:
        """Apply the TUI wizard atomically and reload the persisted result."""
        profile = (
            str(params.get("runtime_profile", "")).strip().lower() or self.runtime_profile
        )
        if profile not in {"cloud", "local", "hybrid", "offline", "custom"}:
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
                # 实测反馈（用户配过 provider 却每次保存都被弹回 API Key 屏）：
                # 只说"请填写"没告诉用户"你现在为什么没有"以及"填了会不会保存"。
                # 明确三件事：两边都没检测到、返回上一屏填写、填写后会落盘。
                raise ConfigValidationError(
                    f"未检测到 {preset.get('display_name', provider_name)} API Key"
                    f"（配置文件与环境变量都没有）。"
                    f"请返回上一屏填写{hint}；填写后会保存到配置文件，下次无需重填。"
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
        elif profile in {"local", "offline"}:
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

        if profile == "custom":
            # 自定义：只写两个槽位（方案 §4.2）。凭据仍归各槽自己的 provider 配置，
            # 这里不碰它们——细化页只决定"用哪个槽"，不决定槽里配了什么。
            # 两个值都校验通过之后才赋值：任一非法就整单失败，内存里也不留半套状态。
            preferences = self.config.preferences
            chat_slot = self._setup_slot(
                params, "chat_slot", CHAT_SLOT_VALUES, preferences.chat_slot, "对话模型"
            )
            review_slot = self._setup_slot(
                params, "review_slot", REVIEW_SLOT_VALUES, preferences.review_slot, "审查模型"
            )
            preferences.chat_slot = chat_slot
            preferences.review_slot = review_slot
        else:
            # 预设是唯一事实来源：清空旧覆盖，否则上一次的 custom 会继续生效（方案 §4.1）。
            # 旧载荷不带这两个字段，行为与改造前完全一致。
            self._clear_route_slots()
        # 显式 review_slot 折算回运行模式预设（方案 §3.2）。预设分支已在上面清空槽位，
        # 因此这一句对它们是无操作；chat_slot 从不反向写回预设。
        sync_review_slot_to_strategy(self.config)

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
        workbench_mode = str(params.get("workbench_mode", "")).strip()
        if workbench_mode:
            # Single source of truth: config.WORKBENCH_MODES owns the vocabulary.
            from ai_pr_review.config import WORKBENCH_MODES

            if workbench_mode not in WORKBENCH_MODES:
                raise ConfigValidationError("审查工作台仅支持 auto、always 或 off。")
            preferences.workbench_mode = workbench_mode
        repo_context = str(params.get("repo_context") or "").strip().lower()
        if repo_context:
            # 取值由 config.REPO_CONTEXT_MODES 定义。非法值必须整单失败：这是用户在
            # 向导里刚刚做出的选择，像加载配置那样静默回退比报错更糟（同 `_setup_slot`）。
            if repo_context not in REPO_CONTEXT_MODES:
                raise ConfigValidationError(
                    "仓库上下文仅支持 off、tests 或 tests+imports。"
                    "（repo_context accepts off, tests or tests+imports.）"
                )
            preferences.repo_context = repo_context
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

    def _apply_slot_model(self, target: ProviderConfig, model_name: str) -> dict[str, Any]:
        """把模型写到某个槽位的 Provider 上并落盘（`model.apply` 的槽位版）。

        模型名原样落盘（不折叠大小写）：`ModelProviderConfig.validate` 与
        `_model_provider_hint` 都按原名匹配，`/MODEL DeepSeek-V3` 曾会被悄悄改成
        小写名再写进配置，用户下次看到的就是另一个 ID。
        """
        model_name = model_name.strip()
        if not model_name:
            raise ValueError("模型名称不能为空。")
        target.default_model = model_name
        target.ensure_default_model_present()
        self.config._sync_runtime_sections()
        self.config.save(self.config_path, save_key=True)
        return self._config_snapshot()

    async def _apply_model(self, model_name: str) -> dict[str, Any]:
        """`model.apply`：改**活跃槽**的模型（既有语义不变）。"""
        return self._apply_slot_model(self.config._active_provider_config(), model_name)

    def _local_slot_config(self) -> ProviderConfig:
        """本地槽位真正承载配置的 Provider（与 `ModelSelector.__init__` 的本地槽一致）。

        主 Provider 自己就是 Ollama/Local 时以它为准：用户自定义的端点与模型列表
        就在主槽里，改用持久化的 `local_provider` 会把人换到默认 Ollama 上。
        """
        if self.config.provider.name.lower() in {"ollama", "local"}:
            return self.config.provider
        return self.config.local_provider

    def _chat_slot_config(self) -> ProviderConfig:
        """聊天槽位真正承载配置的 Provider（`_chat_slot_provider` 的可写版本）。

        判定与 `_chat_slot_provider` 逐条一致；两者共用本函数，避免"读的槽"和
        "/model chat 写的槽"各算一次、越走越远。
        """
        if resolve_chat_slot(self.config) == "remote":
            return self.config.provider
        if self._has_explicit_value(self.config.preferences, "chat_slot", CHAT_SLOT_VALUES):
            return self.config.local_provider
        if getattr(self.config, "_env_provider_override", False):
            return self.config.provider
        return self._local_slot_config()

    def _review_slot_config(self) -> ProviderConfig:
        """审查槽位真正承载配置的 Provider（与 `ModelSelector` 的槽位判定一致）。

        `local` 槽见 `_local_slot_config`；`remote` 与 `hybrid` 都是主 Provider——
        hybrid 没有单一模型，可写的那个是"能覆盖全部文件"的远端/升级模型，与
        `_slot_model("hybrid")` 对外披露的模型一致。
        """
        if resolve_review_slot(self.config) == "local":
            return self._local_slot_config()
        return self.config.provider

    async def _switch_slot_model(self, slot: str, tokens: list[str]) -> dict[str, Any]:
        """`/model chat|review <name>`：把模型写到该槽位实际会用的 Provider（方案 §5.3）。

        写"实际会用的 Provider"而不是"槽位名字对应的 Provider"：否则在
        `local_only` + 主 Provider 就是 Ollama 这类配置里，命令会宣称成功却改不到
        聊天/审查真正使用的那个 provider。
        """
        usage = (
            f"用法：/model {slot} <模型名>。可用写法：/model（查看当前模型）"
            " · /model status · /model chat <模型名> · /model review <模型名>"
            " · /model <模型名>（等同 /model chat）"
            " · /model local|cloud|hybrid|offline（切换运行模式）"
        )
        if not tokens or not tokens[0]:
            raise ValueError(usage)
        if len(tokens) > 1:
            raise ValueError(f"模型名不能包含空格。{usage}")
        model_name = tokens[0]
        # 两个槽的归属都要在写入前算好：`save()` 会把活跃槽重建一个新对象，
        # 写之后再做 `is` 比较必然为假（同一个 provider 会被看成两个）。
        if slot == "chat":
            target = self._chat_slot_config()
            other_target = self._review_slot_config()
            resolved = resolve_chat_slot(self.config)
            heading = "对话模型已切换为"
        else:
            target = self._review_slot_config()
            other_target = self._chat_slot_config()
            resolved = resolve_review_slot(self.config)
            heading = "审查模型已切换为"
        shares_provider = other_target is target
        snapshot = self._apply_slot_model(target, model_name)
        status = await self._model_status()
        label = ROUTE_SLOT_LABELS.get(resolved, resolved)
        lines = [
            f"{heading} {model_name}（{label}槽 · {target.display_name or target.name}）"
        ]
        # 两个槽指向同一个 Provider 时，它们共用一份 default_model：改一个槽必然会
        # 改到另一个槽用的模型。明说比让用户自己发现"聊天模型怎么变了"要好。
        if shares_provider:
            other_label = "审查" if slot == "chat" else "对话"
            lines.append(
                f"注意：{other_label}槽用的是同一个 Provider"
                f"（{target.display_name or target.name}），该槽的模型也会变为 {model_name}。"
            )
        if slot == "review" and resolved == "hybrid":
            local_model = str(self._local_slot_config().default_model or "")
            if local_model:
                lines.append(f"混合策略：低风险文件仍由本地模型 {local_model} 审查。")
        return {"text": "\n".join(lines), "config": snapshot, "status": status}

    async def _model_status(self) -> dict[str, Any]:
        # 顶层字段仍描述"活跃槽"（= `ai_client` 跟随的那个槽）：`model.apply` 协议方法
        # 改的也是活跃槽，两者必须指向同一个 provider，否则状态与随后的写入会互相矛盾。
        # 两个槽各自的模型在下面的 `routing` 里（方案 §5.1 #10 / §5.4）；
        # `/model chat|review <name>` 写的是槽位自己的 provider，不再由顶层字段代言。
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
            "routing": self._routing_snapshot(),
            # 供状态栏显示仓库上下文的当前档位（与 config.options 同键同形）。
            "repo_context": self._repo_context_options(),
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
            # Lets the TUI show which run the conversation is about (§9.2 E)
            # without a second round trip; `None` means plain chat.
            "current_run_id": session.current_run_id,
        }

    def _chat_slot_provider(self) -> ModelProviderConfig:
        """聊天槽位的 provider 配置（docs/dual-model-roles-plan.md §5.1 #4）。

        聊天不再隐含跟随"活跃槽"（`ai_client`）：显式 `chat_slot` 必须能选到与
        审查不同的模型。`remote` 槽 = 持久化的主 Provider，`local` 槽 = `local_provider`
        （与 `ModelSelector` 对两个槽的理解一致）。

        两个例外沿用 `config._active_provider_config()` 与 `ModelSelector.__init__` 的既有判定，
        且只在**没有**显式 `chat_slot` 时生效——它们决定的是"主槽是不是就是本地槽"：
        1. 本进程被 `AI_PR_REVIEW_PROVIDER` 覆盖（显式要求这个进程用云端）；
        2. 主 Provider 自己就是 Ollama/Local（用户自定义的端点/模型就在主槽里）。
        两者如果照旧按 `local_provider` 走，`local_only` 的老用户会从自己配的端点悄悄
        换到默认 Ollama，或者"本进程用云端"的覆盖只对审查生效、对聊天失效。

        槽位判定只有一份，见 `_chat_slot_config`：`/model chat <name>` 必须写到同一个
        provider 上，否则命令改了 A、聊天读的是 B。
        """
        return self._chat_slot_config().to_model_provider()

    def _chat_context_budget(self) -> int:
        """聊天上下文的 token 预算（§9.D；配置缺省时用构建器的默认值）。"""
        raw = getattr(self.config.preferences, "chat_context_budget", DEFAULT_TOKEN_BUDGET)
        try:
            budget = int(raw)
        except (TypeError, ValueError):
            return DEFAULT_TOKEN_BUDGET
        return budget if budget > 0 else DEFAULT_TOKEN_BUDGET

    def _chat_system_prompt(self, session: Session) -> str:
        """语言指令 + （绑定了 Run 时的）审查上下文（§9.2 C）。

        上下文只进 system prompt，不写 `session.messages`：否则历史会随每一轮
        对话重复膨胀并重复计费。构建失败/run 读不到时降级为普通聊天并记 warning，
        绝不因为"解读不了这次审查"而让对话失败。
        """
        language_instruction = (
            "Respond in English unless the user explicitly asks for another language."
            if self.config.preferences.language.lower().startswith("en")
            else "请默认使用中文回答，除非用户明确要求使用其他语言。"
        )
        run_id = session.current_run_id
        if not run_id:
            # 未绑定：给出候选清单，让模型引导用户用「第 N 个」或「PR #N」
            # 选择。实测：工作台里的 run id 复制很不方便，不该让用户去抄。
            note = self._recent_runs_note(session)
            return f"{language_instruction}\n\n{note}" if note else language_instruction
        context = self._review_context_for_chat(run_id)
        if context is None:
            return language_instruction
        return f"{language_instruction}\n\n{wrap_review_context(run_id, context)}"

    def _review_context_for_chat(self, run_id: str) -> str | None:
        """渲染注入用的审查上下文；失败或无记录返回 None（降级，§9.2 C）。"""
        from ai_pr_review.services.result_store import ResultStore

        try:
            store = ResultStore(self.config.result_store)
            context = build_review_context(
                store, run_id, token_budget=self._chat_context_budget()
            )
        except Exception as exc:
            self._warn_context_unavailable(run_id, f"{exc.__class__.__name__}: {exc}")
            return None
        if context is None:
            self._warn_context_unavailable(run_id, "run 不存在或无法读取")
        return context

    @staticmethod
    def _warn_context_unavailable(run_id: str, reason: str) -> None:
        print(
            f"review context unavailable for run {run_id} ({reason}); "
            "falling back to plain chat",
            file=sys.stderr,
            flush=True,
        )

    def _bind_session_run(self, session_id: str | None, run_id: str) -> bool:
        """把会话绑定到某个 Run（§9.2 A）。

        绑定只发生在内存里，且只对**已经存在**的会话生效：没有会话就没有"当前
        绑定的审查"，凭空造一个会话只会让 `/context` 报出一个用户看不见的状态。
        """
        if not session_id or not run_id:
            return False
        session = self.sessions.get(session_id)
        if session is None:
            return False
        session.current_run_id = run_id
        return True

    def _context_status(self, session: Session | None, *, leading: str = "") -> dict[str, Any]:
        """`/context` 的展示体：当前绑定、PR 标识与 token 估算（含裁剪情况）。"""
        budget = self._chat_context_budget()
        run_id = session.current_run_id if session is not None else None
        if not run_id:
            return {
                "text": self._context_text(
                    leading,
                    "审查上下文：未绑定",
                    "完成一次 /review，或用 /context <run_id> 绑定历史 Run，"
                    "聊天即可解读该次审查结果。",
                ),
                "bound": False,
                "run_id": None,
                "token_estimate": None,
                "token_budget": budget,
                "trimmed": [],
            }
        from ai_pr_review.services.result_store import ResultStore

        try:
            store = ResultStore(self.config.result_store)
            run = store.get_run_summary(run_id)
            metadata = store.get_run_metadata(run_id)
            context = build_review_context_meta(store, run_id, token_budget=budget)
        except Exception:
            run, context = None, None
            metadata = {}
        if not run or context is None:
            # 绑定不会因为 Run 被清理就自动消失：用户看到的必须是"读不到"，
            # 而不是悄悄变回"未绑定"。
            return {
                "text": self._context_text(
                    leading,
                    "审查上下文：已绑定",
                    f"Run: {run_id}",
                    "该 Run 当前无法读取（可能已被清理）；对话会降级为普通聊天。",
                    "用法：/context off 解绑。",
                ),
                "bound": True,
                "run_id": run_id,
                "token_estimate": None,
                "token_budget": budget,
                "trimmed": [],
            }
        lines = [f"Run: {run_id}"]
        label = describe_run(run, metadata)
        if label:
            lines.append(f"PR: {label}")
        lines.append(f"token 估算: 约 {context.tokens} tokens（预算 {context.budget}）")
        if context.was_trimmed:
            lines.append(f"已裁剪: {'、'.join(context.trimmed)}（完整内容见 /explain {run_id}）")
        lines.append("用法：/context <run_id> 切换 · /context off 解绑")
        return {
            "text": self._context_text(leading, "审查上下文：已绑定", *lines),
            "bound": True,
            "run_id": run_id,
            "token_estimate": context.tokens,
            "token_budget": context.budget,
            "trimmed": list(context.trimmed),
            "pr": {"url": run.get("pr_url", ""), "label": label},
        }

    @staticmethod
    def _context_text(leading: str, *lines: str) -> str:
        return "\n".join([line for line in (leading, *lines) if line])

    def _context_switch(self, session: Session, run_id: str) -> dict[str, Any]:
        """`/context <run_id>`：确认该 Run 可读后才切换绑定。"""
        from ai_pr_review.services.result_store import ResultStore

        store = ResultStore(self.config.result_store)
        if not store.get_run_summary(run_id):
            raise LookupError(run_id)
        # 原样保留用户输入的 run_id：`/explain` 的 not_found 文案用的也是用户输入，
        # 而不是去猜一个规范化后的 id。
        session.current_run_id = run_id
        return self._context_status(session, leading=f"已切换审查上下文：{run_id}")

    async def _chat(
        self,
        session: Session,
        text: str,
        on_delta: Callable[[str], Awaitable[None]],
        cancel_event: threading.Event,
    ) -> str:
        # 用户实测两点：(1) 新会话问"看看这次审查结果"时 chat 只能回
        # "我无法访问"；(2) 工作台里复制 run id 很不方便。于是按消息里的
        # PR 号 / 候选序号解析绑定（见 `_resolve_context`）——既不静默绑定
        # "最近一次"（会张冠李戴），也不要求用户复制 UUID。
        auto_bound_run = self._resolve_context(session, text)
        provider_config = self._chat_slot_provider()
        # 本地豁免按"选中的 provider 名"判断，而不是按槽位：`remote` 槽也可能是 Ollama
        # 主 Provider（本地模型），而 `local` 槽在环境覆盖下实际指向云端主槽。按槽位判断
        # 会给云端 provider 传 reasoning_effort，还会漏掉它缺 Key 的错误。
        is_local = provider_config.name.lower() in {"ollama", "local"}
        if not provider_config.api_key and not is_local:
            raise RuntimeError(f"Missing API key for provider: {provider_config.name}")
        provider = create_model_provider(provider_config)
        text = self._truncate(text, 12000)
        history = [*session.messages, {"role": "user", "content": text}]
        chat_options: dict[str, Any] = {
            "system_prompt": self._chat_system_prompt(session),
            "max_tokens": self.config.ai_client.max_tokens,
            "timeout_seconds": self.config.ai_client.timeout_seconds,
        }
        if is_local:
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
        # The binding notice is UI-only: the transcript keeps the clean answer
        # so later turns are not fed a machine-generated prefix.
        session.messages = [*history, {"role": "assistant", "content": response_text}][-40:]
        if auto_bound_run:
            return (
                f"（已按你的指代绑定审查 run {auto_bound_run[:8]}；"
                f"用 /context 查看详情，或 /context off 解绑）\n\n{response_text}"
            )
        return response_text

    def _resolve_context(self, session: Session, text: str) -> str | None:
        """按消息内容决定这一轮绑定的审查 run；返回"本轮新绑定"的 run_id。

        解析顺序（**永不静默绑定"最近一次"**：用户问别的 PR 时会张冠李戴，
        而带着错上下文回答比"我无法访问"更糟）：
          ① 已绑定 → 沿用（返回 None，不重复提示）
          ② 消息里出现 PR 号 / PR URL → 匹配该 PR 的最新 run
          ③ 消息形如「第 N 个 / 选 N」→ 从上一轮给出的候选清单里取
          ④ 都不命中 → 不绑定；调用方改用候选清单引导用户选

        全程不需要用户复制 run id（工作台里选中复制并不方便）。
        """
        if session.current_run_id:
            return None
        try:
            from ai_pr_review.services.result_store import ResultStore

            runs = ResultStore(self.config.result_store).list_runs(limit=50)
        except Exception:
            return None
        if not runs:
            return None

        pr_number = _extract_pr_number(text)
        if pr_number is not None:
            for run in runs:
                try:
                    run_pr = int(run.get("pr_number") or 0)
                except (TypeError, ValueError):
                    continue
                if run_pr == pr_number:
                    run_id = str(run.get("id") or "").strip()
                    if run_id:
                        session.current_run_id = run_id
                        return run_id

        ordinal = _extract_ordinal(text)
        if ordinal is not None and session.context_candidates:
            if 1 <= ordinal <= len(session.context_candidates):
                run_id = session.context_candidates[ordinal - 1]
                if run_id:
                    session.current_run_id = run_id
                    return run_id
        return None

    def _recent_runs_note(self, session: Session, limit: int = 3) -> str:
        """未绑定时的候选清单：让用户用序号或 PR 号选，不用复制 run id。"""
        try:
            from ai_pr_review.services.result_store import ResultStore

            runs = ResultStore(self.config.result_store).list_runs(limit=limit)
        except Exception:
            return ""
        if not runs:
            return ""
        session.context_candidates = [
            str(run.get("id") or "").strip()
            for run in runs
            if str(run.get("id") or "").strip()
        ]
        note_lines = [
            "（当前还没有绑定审查上下文。以下是最近几次审查，"
            "用户可以直接说「第 N 个」或「PR #N」来选择，不需要提供 run id：）"
        ]
        for index, run in enumerate(runs, 1):
            note_lines.append(
                f"{index}. PR #{run.get('pr_number')} · {run.get('created_at')} · "
                f"{run.get('total_findings')} 条 findings"
            )
        note_lines.append(
            "如果用户问的是别的审查，请让他说明 PR 编号；不要替他猜是哪一次。"
        )
        return "\n".join(note_lines)

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

    def _review_routing(self) -> dict[str, Any] | None:
        """Describe the model routing policy the next review will follow.

        This mirrors `ModelSelector`'s slot resolution (main provider when it is
        Ollama/Local, otherwise the persisted local slot) so the event states
        the policy that will actually be applied. It is not a per-file decision
        log: the orchestrator picks a model per file and never reports back.
        Returns None when no model can be named, because a routing event full of
        guesses would be worse than no event.
        """
        strategy = (
            str(getattr(self.config.preferences, "hybrid_strategy", "") or "").strip().lower()
        )
        provider = self.config.provider
        provider_is_local = provider.name.lower() in {"ollama", "local"}
        local_slot = provider if provider_is_local else self.config.local_provider
        remote_slot = self.config.ai_client.model_provider if provider_is_local else provider
        local_model = (
            str(getattr(local_slot, "default_model", "") or "").strip()
            or str(getattr(self.config.ai_client, "local_model", "") or "").strip()
            or None
        )
        remote_is_local = str(getattr(remote_slot, "name", "") or "").lower() in {
            "ollama",
            "local",
        }
        remote_model = (
            None
            if remote_is_local
            else (str(getattr(remote_slot, "default_model", "") or "").strip() or None)
        )
        if strategy == "local_only" or remote_model is None:
            bucket, router_model, deep_model = "local_only", None, local_model
        elif strategy == "remote_only":
            bucket, router_model, deep_model = "remote_only", None, remote_model
        else:
            bucket, router_model, deep_model = "hybrid", local_model, remote_model
        if not deep_model:
            return None
        language = (
            "en-US"
            if str(getattr(self.config.preferences, "ui_language", "")).lower().startswith("en")
            else "zh-CN"
        )
        return {
            "runtime_profile": self.runtime_profile,
            "router_model": router_model,
            "deep_model": deep_model,
            "reason": REVIEW_ROUTING_REASONS[bucket][language],
        }

    async def _run_review(
        self,
        pr_url: str,
        session_id: str | None,
        events: list[dict[str, Any]],
        cancel_event: asyncio.Event | None = None,
        stream: _ReviewEventStream | None = None,
    ) -> dict[str, Any]:
        """Run the production review pipeline and publish live workspace events."""
        from ai_pr_review.cli import build_report_payload, run_review

        if stream is None:
            stream = _ReviewEventStream(lambda event: self._publish(event, events), session_id)

        def check_cancelled() -> None:
            if cancel_event is not None and cancel_event.is_set():
                raise ReviewCancelled("Review cancelled by user")

        def stage_callback(stage: str, detail: str = "") -> None:
            check_cancelled()
            stream.stage(stage, detail)

        def file_started(filename: str, active_model: str) -> None:
            check_cancelled()
            stream.file_started(filename, active_model)

        def file_done(filename: str) -> None:
            check_cancelled()
            stream.file_done(filename)

        def file_result(payload: dict[str, Any]) -> None:
            check_cancelled()
            stream.file_result(payload)

        try:
            stream.started(pr_url)
            stream.routing(self._review_routing())
            artifacts = await run_review(
                pr_url,
                config=self.config,
                progress_console=None,
                stage_callback=stage_callback,
                progress_callback=file_started,
                file_done_callback=file_done,
                cancel_check=(
                    (lambda: cancel_event.is_set()) if cancel_event is not None else None
                ),
                file_result_callback=file_result,
            )
            # The orchestrators re-check before persisting, but a cancel racing
            # the very last stage must not be reported as a successful review.
            check_cancelled()
            stream.complete()
        except ReviewCancelled:
            stream.abort("skipped")
            raise
        except BaseException as exc:
            # Also covers the CancelledError raised by `asyncio.wait_for` on
            # timeout: the stage must be closed either way, otherwise the TUI
            # timeline keeps spinning on a run that already ended.
            stream.abort(
                "failed",
                message=str(exc) or exc.__class__.__name__,
                recovery=(
                    self._classify_error(exc)["recovery"] if isinstance(exc, Exception) else None
                ),
            )
            raise

        payload = build_report_payload(artifacts)
        findings = payload.get("findings", [])
        finding_count = len(findings) if isinstance(findings, list) else 0
        summary = str(payload.get("summary", "审查已完成"))
        payload = self._bound_report(payload)
        self.current_report = payload
        # "发现 N 个问题" 在失败 run 上会与 "审查失败" 的 summary 直接矛盾
        # （PR #31 实测：14 个文件模型调用全失败，静态分析仍给出 4 条）。
        # 失败时只回 summary（它已说明来源），成功时保留原有的计数行。
        if summary.startswith("审查失败"):
            text = f"PR 审查完成：{summary}\nRun: {artifacts.run_id}"
        else:
            text = (
                f"PR 审查完成：{summary}\n"
                f"发现 {finding_count} 个问题\n"
                f"Run: {artifacts.run_id}"
            )
        return {
            "text": text,
            "run_id": artifacts.run_id,
            "summary": summary,
            "finding_count": finding_count,
            "report": payload,
        }

    def _publish_ledger(self, session_id: str) -> set[str]:
        """The session's record of already-published runs (§12.2).

        The ledger lives on the session object and never on disk. A publish
        request that arrives without a prior `session.create` creates the
        session on demand: dropping the ledger there would make repeat
        detection vanish exactly when a caller skips the handshake.
        """
        session = self.sessions.get(session_id)
        if session is None:
            session = Session(session_id=session_id)
            if session_id:
                self.sessions[session_id] = session
        return session.published_run_ids

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
        # Imported here (not at module level) for the same reason `_run_review`
        # imports the report builder lazily: the CLI pulls in click/rich.
        from ai_pr_review.cli import report_filtered_section
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
        # Same `run.filtered` block a fresh review reports, from the stats the
        # orchestrator stored (`metadata["filtered_findings"]`), so the TUI's
        # empty-findings hint can explain a stored 0-finding run too. Runs saved
        # before that key existed (or with a malformed one) simply have no block.
        filtered = report_filtered_section(
            metadata.get("filtered_findings") if isinstance(metadata, dict) else None
        )
        if filtered:
            report["run"]["filtered"] = filtered
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

    def _explain_run(self, run_id: str) -> dict[str, Any]:
        """Structured findings/evidence explanation for a stored run (§10.3).

        Deterministic rendering of what the run recorded — no model call, so
        `/explain` answers the same thing on every machine and costs nothing.
        """
        from ai_pr_review.services.result_store import ResultStore

        store = ResultStore(self.config.result_store)
        result = store.get_result(run_id)
        if result is None:
            raise LookupError(run_id)
        metadata = store.get_run_metadata(run_id)
        findings = [finding.model_dump(mode="json") for finding in result.findings]
        language_info = metadata.get("language", {}) if isinstance(metadata, dict) else {}
        lines = [f"Finding 解释 · Run {run_id}", f"摘要：{result.summary}"]
        if language_info:
            lines.append(
                f"语言：界面 {language_info.get('ui_language', '-')} · "
                f"审查响应 {language_info.get('response_language', '-')}"
            )
        if not findings:
            lines.append("该 Run 没有记录任何 Finding。")
        for finding in findings:
            lines.append("")
            lines.append(
                f"[{str(finding.get('severity', 'info')).upper()}] {finding.get('title', '')}"
            )
            lines.append(
                f"  位置：{finding.get('file', '')}:"
                f"{finding.get('line_start', '?')}-{finding.get('line_end', '?')}"
            )
            sources = finding.get("sources") or ["unknown"]
            lines.append(f"  来源：{', '.join(str(source) for source in sources)}")
            lines.append(f"  证据：{finding.get('evidence_status') or 'unverified'}")
            issues = finding.get("evidence_issues") or []
            if issues:
                lines.append(f"  疑点：{'; '.join(str(issue) for issue in issues)}")
            lines.append(f"  原因：{finding.get('problem', '')}")
            lines.append(f"  建议：{finding.get('suggestion', '')}")
        return {
            "text": "\n".join(lines),
            "run_id": run_id,
            "summary": result.summary,
            "findings": findings,
            "metadata": metadata,
        }

    def _record_feedback(
        self,
        run_id: str,
        finding_id: str,
        status: str,
        note: str = "",
    ) -> dict[str, Any]:
        """Persist feedback for a stored finding (§10.3).

        Returns an outcome dict instead of raising so the protocol layer can map
        each failure to an actionable error code.
        """
        from ai_pr_review.services.result_store import ResultStore

        store = ResultStore(self.config.result_store)
        result = store.get_result(run_id)
        if result is None:
            return {"ok": False, "code": "not_found", "message": f"未找到审查记录：{run_id}"}
        known_ids = {finding.finding_id for finding in result.findings if finding.finding_id}
        if finding_id not in known_ids:
            return {
                "ok": False,
                "code": "not_found",
                "message": f"Run {run_id} 中未找到 Finding：{finding_id}",
            }
        try:
            store.save_feedback(run_id, finding_id, status, note)
        except ValueError as exc:
            return {"ok": False, "code": "invalid_request", "message": str(exc)}
        return {
            "ok": True,
            "run_id": run_id,
            "finding_id": finding_id,
            "status": status,
            "note": note,
            "text": f"已记录反馈：{finding_id} → {status}" + (f"（{note}）" if note else ""),
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
                            "text": "/setup  配置助手\n/status 查看运行状态\n/model [chat|review <模型名>] 查看/切换模型\n/review 开始 PR 审查\n/cancel 取消当前审查\n/retry 重试上一次操作\n/report 查看当前报告\n/export json|markdown 导出当前报告\n/history 查看历史记录\n/explain <run_id> 解释 Finding 与证据\n/context [run_id|off] 查看/切换/解除审查上下文绑定\n/feedback <run_id> <finding_id> <status> [note] 记录 Finding 反馈\n/publish [run_id] [--confirm] 预览并发布审查评论到 GitHub\n/demo [case_key|list] 运行离线 Demo\n/showcase 查看参赛演示路径\n/exit   退出 Chat"
                        }
                    )
                elif command == "setup":
                    result({"text": "请使用 Ctrl+P 或输入 /setup 打开配置助手。"})
                elif command == "model":
                    raw_args = params.get("args", [])
                    args = (
                        [str(item).strip() for item in raw_args]
                        if isinstance(raw_args, list)
                        else []
                    )
                    # 子命令与运行模式 token 大小写不敏感（旧行为），但模型名保持原样：
                    # 模型 ID 可以含大写，旧代码的 `item.lower()` 会把它们写坏。
                    head = args[0].lower() if args else ""
                    if head == "status":
                        status = await self._model_status()
                        result({"text": self._model_status_text(status), "status": status})
                    elif head in {"local", "cloud", "hybrid", "offline"}:
                        snapshot = self._apply_runtime_profile(head)
                        status = await self._model_status()
                        result(
                            {
                                "text": f"运行时已切换为 {head}\n"
                                + self._model_status_text(status),
                                "config": snapshot,
                                "status": status,
                            }
                        )
                    elif head in {"chat", "review"}:
                        try:
                            result(await self._switch_slot_model(head, args[1:]))
                        except ValueError as exc:
                            error(str(exc), "invalid_request")
                    elif args:
                        # 兼容旧行为（方案 §5.3）：裸模型名 = `/model chat <name>`。
                        try:
                            result(await self._switch_slot_model("chat", args))
                        except ValueError as exc:
                            error(str(exc), "invalid_request")
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
                        detail = self._history_detail(args[0])
                        # 载入历史报告即绑定该 Run（§9.2 A）：屏幕上正在看的这次审查
                        # 就是接下来对话要解读的对象。
                        if detail.get("run") is not None:
                            self._bind_session_run(
                                str(params.get("session_id", "")), args[0]
                            )
                        result(detail)
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
                elif command == "explain":
                    raw_args = params.get("args", [])
                    args = (
                        [str(item).strip() for item in raw_args]
                        if isinstance(raw_args, list)
                        else []
                    )
                    run_id = args[0] if args else ""
                    if not run_id:
                        error("请提供 Run ID：/explain <run_id>", "invalid_request")
                    else:
                        try:
                            explained = self._explain_run(run_id)
                        except LookupError:
                            error(f"未找到审查记录：{run_id}", "not_found")
                        else:
                            # 解释成功即绑定：用户刚刚点名要看的 Run 就是对话主题。
                            self._bind_session_run(str(params.get("session_id", "")), run_id)
                            result(explained)
                elif command == "context":
                    context_session = self.sessions.get(str(params.get("session_id", "")))
                    raw_args = params.get("args", [])
                    args = (
                        [str(item).strip() for item in raw_args]
                        if isinstance(raw_args, list)
                        else []
                    )
                    if not args:
                        result(self._context_status(context_session))
                    elif context_session is None:
                        # 绑定状态挂在会话上：没有会话就没有"当前绑定"可切换/解除。
                        error("Session not found", "not_found")
                    elif args[0].lower() in {"off", "none"}:
                        context_session.current_run_id = None
                        result(
                            self._context_status(None, leading="已解除审查上下文绑定，回到普通聊天。")
                        )
                    else:
                        try:
                            result(self._context_switch(context_session, args[0]))
                        except LookupError as exc:
                            error(f"未找到审查记录：{exc}", "not_found")
                elif command == "feedback":
                    raw_args = params.get("args", [])
                    args = (
                        [str(item).strip() for item in raw_args]
                        if isinstance(raw_args, list)
                        else []
                    )
                    run_id = args[0] if len(args) > 0 else ""
                    finding_id = args[1] if len(args) > 1 else ""
                    status = args[2].lower() if len(args) > 2 else ""
                    note = args[3] if len(args) > 3 else ""
                    if not run_id or not finding_id or not status:
                        error(
                            "用法：/feedback <run_id> <finding_id> <status> [note]",
                            "invalid_request",
                        )
                    elif status not in FEEDBACK_STATUSES:
                        error(
                            f"无效的反馈状态：{status}；可选："
                            + ", ".join(sorted(FEEDBACK_STATUSES)),
                            "invalid_request",
                        )
                    else:
                        outcome = self._record_feedback(run_id, finding_id, status, note)
                        if outcome["ok"]:
                            result(outcome)
                        else:
                            error(str(outcome["message"]), str(outcome["code"]))
                elif command == "publish":
                    from ai_pr_review.services.publish_service import (
                        PublishError,
                        PublishService,
                        parse_publish_args,
                    )

                    raw_args = params.get("args", [])
                    args = (
                        [str(item).strip() for item in raw_args]
                        if isinstance(raw_args, list)
                        else []
                    )
                    service = PublishService(self.config)
                    ledger = self._publish_ledger(str(params.get("session_id", "")))
                    try:
                        publish_run_id, confirm = parse_publish_args(args)
                        if confirm:
                            # The only branch that reaches GitHub.
                            result(
                                service.publish(
                                    run_id=publish_run_id,
                                    current_report=self.current_report,
                                    published_run_ids=ledger,
                                )
                            )
                        else:
                            result(
                                service.preview(
                                    run_id=publish_run_id,
                                    current_report=self.current_report,
                                    published_run_ids=ledger,
                                )
                            )
                    except PublishError as exc:
                        error(exc.message, exc.code)
                elif command == "demo":
                    from ai_pr_review.services.demo_runner import (
                        UnknownDemoCase,
                        demo_payload,
                    )

                    raw_args = params.get("args", [])
                    args = (
                        [str(item).strip() for item in raw_args]
                        if isinstance(raw_args, list)
                        else []
                    )
                    # Offline by construction: fixtures plus deterministic rules.
                    try:
                        result(demo_payload(args))
                    except UnknownDemoCase as exc:
                        error(str(exc), "invalid_request")
                elif command == "showcase":
                    from ai_pr_review.services.showcase_runner import showcase_payload_with_text

                    # Offline: the payload is derived from the loaded config only.
                    result(showcase_payload_with_text(self.config))
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
                            # Shared with `_run_review` so terminal events can
                            # name the stage that was running when it ended.
                            stream = _ReviewEventStream(
                                lambda event: self._publish(event, events), review_session_id
                            )
                            try:
                                review_result = await asyncio.wait_for(
                                    self._run_review(
                                        args[0],
                                        review_session_id,
                                        events,
                                        cancel_event,
                                        stream,
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
                                        **stream.stage_id_field(),
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
                                        **stream.stage_id_field(),
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
                                        **stream.stage_id_field(),
                                    },
                                    events,
                                )
                                raise
                            else:
                                report = review_result.get("report")
                                # 只有成功落库的审查才会走到这里（取消/超时/失败都在
                                # 上面的 except 分支），绑定因此天然只发生在成功 run 上。
                                self._bind_session_run(
                                    review_session_id, str(review_result["run_id"])
                                )
                                self._publish(
                                    {
                                        "event": "review.completed",
                                        "session_id": review_session_id,
                                        "run_id": review_result["run_id"],
                                        "finding_count": review_result["finding_count"],
                                        **_review_completed_fields(
                                            report if isinstance(report, dict) else {}
                                        ),
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
