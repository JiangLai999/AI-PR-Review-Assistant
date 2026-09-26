"""Live-verify the product Chat pipeline across DeepSeek thinking tiers.

Runs the real `JsonlBackend` (no mocked provider) against the real DeepSeek
endpoint. The key is read only from ``DEEPSEEK_API_KEY`` and is never printed
or written into any report; the temporary config that carries it is deleted on
exit. Progress lines are flushed so long thinking turns are not mistaken for a
stall.
"""  # noqa: RUF001

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_pr_review.backend.jsonl_server import JsonlBackend  # noqa: E402

# 需要长链推理的题：简单题（如"用一句话解释 X"）会让 low/high 的思考长度被随机性
# 主导（实测 190 vs 133），必须用 probe 脚本同款长链题才能拉开档位差异。
PROMPT = (
    "三个箱子，一个全是金币、一个全是银币、一个金银混合，标签全部贴错。"
    "你只能从一个箱子里取出一枚硬币查看。请完整说明如何确定三个箱子的真实内容，"
    "并解释为什么只看标签无法完成、为什么你的方案必然正确。"
)
OFF_MAX_REASONING_CHARS = 50
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
TIERS = ("off", "low", "high", "max")


@dataclass
class TierResult:
    effort: str
    duration_seconds: float
    reasoning_chars_finished: int
    reasoning_chars_deltas: int
    answer_chars_finished: int
    answer_chars_deltas: int
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    used_tokens: int | None
    warning: str | None
    error: str | None = None


def _log(message: str) -> None:
    print(message, flush=True)


class _EventCapture:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def __call__(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def finished(self) -> dict[str, Any] | None:
        for event in reversed(self.events):
            if event.get("event") == "assistant.finished":
                return event
        return None

    def failed(self) -> dict[str, Any] | None:
        for event in reversed(self.events):
            if event.get("event") == "assistant.failed":
                return event
        return None


def _build_backend(config_path: Path, base_url: str, model: str) -> tuple[JsonlBackend, _EventCapture]:
    """Create the product backend with an isolated config file under workdir."""
    payload: dict[str, Any] = {
        "provider": {
            "name": "deepseek",
            "display_name": "DeepSeek",
            "base_url": base_url,
            "api_format": "openai",
            "models": {
                model: {"name": model, "context_window": 1_048_576, "max_output": 384_000},
                "deepseek-chat": {
                    "name": "deepseek-chat",
                    "context_window": 32_768,
                    "max_output": 4_096,
                },
            },
            "default_model": model,
        },
        "local_provider": {"name": "ollama", "default_model": "qwen3.5:4b"},
        "preferences": {
            "hybrid_strategy": "remote_only",
            "chat_slot": "remote",
            "review_slot": "remote",
            "chat_context_budget": 128_000,
            "chat_reasoning_effort": "auto",
        },
        "ai_client": {
            "provider": "deepseek",
            "model": model,
            "base_url": base_url,
            "api_format": "openai",
            "max_tokens": 2_048,
            "timeout_seconds": 300,
        },
    }
    config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    capture = _EventCapture()
    return JsonlBackend(config_path, event_sink=capture), capture


def _with_key(backend: JsonlBackend, key: str) -> None:
    backend.config.provider.api_key = key
    backend.config.ai_client.api_key = key
    backend.config._sync_runtime_sections()
    backend.config.save(backend.config_path, save_key=True)


async def _create_session(backend: JsonlBackend) -> str:
    """chat.send 要求 session 已存在；probe 与四档各开一个干净会话。"""
    reply = (await backend.handle({"id": "session.create", "method": "session.create"}))[-1]
    if not reply.get("ok"):
        raise RuntimeError(f"session.create failed: {reply.get('error')}")
    return str(reply["result"]["session_id"])


def _reset_persisted_session(workdir: Path) -> None:
    """每档从空历史开始：A2 会把会话落盘到配置目录旁，下一档会把它恢复出来
    （实测不经清理时 prompt_tokens 逐档递增 211→256→303，档位对比被历史污染）。"""
    (workdir / "chat_session.json").unlink(missing_ok=True)


def _set_effort(backend: JsonlBackend, effort: str) -> dict[str, Any]:
    """Set the thinking tier through the product /think command handler."""
    events = asyncio.run(
        backend.handle(
            {
                "id": f"think-{effort}",
                "method": "command.execute",
                "params": {"session_id": "live-verify", "name": "think", "args": [effort]},
            }
        )
    )
    reply = events[-1]
    if not reply.get("ok"):
        raise RuntimeError(f"/think {effort} failed: {reply.get('error')}")
    return reply["result"]


async def _send_turn(
    backend: JsonlBackend, capture: _EventCapture, session_id: str, request_id: str
) -> TierResult:
    capture.events.clear()
    reply = (
        await backend.handle(
            {
                "id": request_id,
                "method": "chat.send",
                "params": {"session_id": session_id, "text": PROMPT},
            }
        )
    )[-1]
    if not reply.get("ok"):
        message = str(reply.get("error", {}).get("message", "unknown error"))
        return TierResult("", 0.0, 0, 0, 0, 0, None, None, None, None, None, error=message)

    finished = capture.finished()
    if finished is None:
        failed = capture.failed()
        return TierResult(
            "", 0.0, 0, 0, 0, 0, None, None, None, None, None,
            error=str((failed or {}).get("message", "assistant.finished missing")),
        )

    usage = finished.get("usage") or {}
    context = finished.get("context") or {}
    reasoning_deltas = "".join(
        str(event.get("text") or "")
        for event in capture.events
        if event.get("event") == "assistant.reasoning_delta"
    )
    answer_deltas = "".join(
        str(event.get("text") or "")
        for event in capture.events
        if event.get("event") == "assistant.delta"
    )
    return TierResult(
        effort=str(backend.config.preferences.chat_reasoning_effort),
        duration_seconds=float(finished.get("duration_seconds") or 0.0),
        reasoning_chars_finished=len(str(finished.get("reasoning") or "")),
        reasoning_chars_deltas=len(reasoning_deltas),
        answer_chars_finished=len(str(finished.get("text") or "")),
        answer_chars_deltas=len(answer_deltas),
        prompt_tokens=int(usage.get("prompt_tokens") or 0) or None,
        completion_tokens=int(usage.get("completion_tokens") or 0) or None,
        total_tokens=int(usage.get("total_tokens") or 0) or None,
        used_tokens=int(context.get("used_tokens") or 0) or None,
        warning=finished.get("warning"),
    )


def _probe_failed_for_model(error: str | None) -> bool:
    """True only for model-not-found style failures; other errors stop the run."""
    if not error:
        return False
    lowered = error.lower()
    # `Session not found` 也含 `not found`——会话缺失不是模型缺失，必须排除，
    # 否则第一次运行会把「没建 session」误判成「模型名不对」并吞掉真实原因。
    if "session" in lowered:
        return False
    return "404" in lowered or "not found" in lowered or "模型不存在" in error


def main() -> int:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        _log("error: DEEPSEEK_API_KEY is not set")
        return 2
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "").strip() or DEFAULT_BASE_URL

    started = time.monotonic()
    summary: dict[str, Any] = {"base_url": base_url, "model": None, "tiers": [], "assertions": {}}
    workdir = Path(tempfile.mkdtemp(prefix="deepseek-live-", dir=ROOT))
    _log(f"workdir: {workdir}")
    try:
        config_path = workdir / "config.json"
        backend, capture = _build_backend(config_path, base_url, "deepseek-flash")
        _with_key(backend, key)

        # --- probe: confirm key/model with a tiny turn before the 4 tiers
        _log("probe: deepseek-flash ...")
        probe_session = asyncio.run(_create_session(backend))
        probe = asyncio.run(_send_turn(backend, capture, probe_session, "probe"))
        if _probe_failed_for_model(probe.error):
            _log("probe: deepseek-flash unavailable, retrying with deepseek-chat ...")
            backend, capture = _build_backend(config_path, base_url, "deepseek-chat")
            _with_key(backend, key)
            probe_session = asyncio.run(_create_session(backend))
            probe = asyncio.run(_send_turn(backend, capture, probe_session, "probe"))
        if probe.error or probe.answer_chars_finished == 0:
            _log(f"probe failed: {probe.error or 'empty answer'}")
            return 1
        model = backend.config.provider.default_model
        summary["model"] = model
        _log(f"probe ok: model={model}")

        # --- four tiers through the product /think command + chat.send
        results: list[TierResult] = []
        for index, effort in enumerate(TIERS, start=1):
            think = _set_effort(backend, effort)
            if think.get("state") != "set":
                _log(f"tier {effort}: /think refused: {think}")
                return 1
            _reset_persisted_session(workdir)
            _log(f"[{index}/4] tier {effort}: sending ...")
            tier_session = asyncio.run(_create_session(backend))
            tier = asyncio.run(
                _send_turn(backend, capture, tier_session, f"turn-{effort}")
            )
            tier.effort = effort
            results.append(tier)
            _log(
                f"tier {effort}: reasoning={tier.reasoning_chars_finished} chars, "
                f"answer={tier.answer_chars_finished} chars, "
                f"duration={tier.duration_seconds:.1f}s"
                + (f", error={tier.error}" if tier.error else "")
            )
            summary["tiers"].append(
                {
                    "effort": tier.effort,
                    "duration_seconds": round(tier.duration_seconds, 2),
                    "reasoning_chars": tier.reasoning_chars_finished,
                    "reasoning_chars_deltas": tier.reasoning_chars_deltas,
                    "answer_chars": tier.answer_chars_finished,
                    "answer_chars_deltas": tier.answer_chars_deltas,
                    "prompt_tokens": tier.prompt_tokens,
                    "completion_tokens": tier.completion_tokens,
                    "total_tokens": tier.total_tokens,
                    "used_tokens": tier.used_tokens,
                    "warning": tier.warning,
                    "error": tier.error,
                }
            )

        by_effort = {item.effort: item for item in results}
        off = by_effort["off"]
        reasoning_cross_checked = all(
            item.reasoning_chars_finished == item.reasoning_chars_deltas for item in results
        )
        answers_cross_checked = all(
            item.answer_chars_finished == item.answer_chars_deltas for item in results
        )
        reasoning_isolated = all(
            item.reasoning_chars_finished == 0
            or item.reasoning_chars_deltas not in (0, item.answer_chars_deltas)
            for item in results
        )
        summary["assertions"] = {
            "off_reasoning_lt_50_and_answer_nonempty": (
                off.reasoning_chars_finished < OFF_MAX_REASONING_CHARS and off.answer_chars_finished > 0
            ),
            "low_lt_high_lt_max_reasoning_chars": (
                by_effort["low"].reasoning_chars_finished
                < by_effort["high"].reasoning_chars_finished
                < by_effort["max"].reasoning_chars_finished
            ),
            "all_answers_nonempty": all(item.answer_chars_finished > 0 for item in results),
            "reasoning_not_inside_answer_deltas": reasoning_isolated,
            "finished_matches_delta_cross_check": reasoning_cross_checked and answers_cross_checked,
            "usage_three_keys_and_prompt_positive": all(
                (item.prompt_tokens or 0) > 0
                and (item.completion_tokens or 0) > 0
                and (item.total_tokens or 0) > 0
                for item in results
            ),
        }
        exit_code = 0 if all(summary["assertions"].values()) else 1
        summary["elapsed_seconds"] = round(time.monotonic() - started, 1)
        summary["call_count"] = (2 if summary["model"] == "deepseek-chat" else 1) + len(results)
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        return exit_code
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

