from __future__ import annotations

import asyncio
import contextlib
import json
import re
import sqlite3
import threading
import time
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from ai_pr_review.backend.jsonl_server import JsonlBackend, ReviewCancelled
from ai_pr_review.config import AppConfig

# 模型规格的取值边界/来源集合（CONTEXT_WINDOW_RANGE 等）已随 C 组用例迁到
# tests/test_config.py（docs/claude-backend-followup.md §1），本文件不再直接引用。
from ai_pr_review.services.model_catalog import ModelCatalog

# 聊天上下文预算的兜底值（= review_context.DEFAULT_TOKEN_BUDGET）：没有目录数据、
# 也没有用户写过的规格时用它。按模型规格推算的路径要显式造数据才会走到
# （docs/claude-backend-followup.md §4）。
DEFAULT_CHAT_BUDGET = 8_000


def test_jsonl_backend_health_and_config_snapshot(tmp_path: Path) -> None:
    backend = JsonlBackend(tmp_path / "config.json")

    health = asyncio.run(backend.handle({"id": "1", "method": "health", "params": {}}))
    assert health[0]["ok"] is True
    assert health[0]["result"]["status"] == "ready"

    snapshot = asyncio.run(backend.handle({"id": "2", "method": "config.snapshot", "params": {}}))
    assert snapshot[0]["ok"] is True
    assert "provider" in snapshot[0]["result"]
    assert "model" in snapshot[0]["result"]


def test_jsonl_backend_session_lifecycle(tmp_path: Path) -> None:
    backend = JsonlBackend(tmp_path / "config.json")

    created = asyncio.run(backend.handle({"id": "1", "method": "session.create", "params": {}}))
    assert created[0]["ok"] is True
    session_id = created[0]["result"]["session_id"]

    loaded = asyncio.run(
        backend.handle({"id": "2", "method": "session.get", "params": {"session_id": session_id}})
    )
    assert loaded[0]["ok"] is True
    assert loaded[0]["result"]["session_id"] == session_id

    missing = asyncio.run(
        backend.handle({"id": "3", "method": "session.get", "params": {"session_id": "missing"}})
    )
    assert missing[0]["ok"] is False
    assert missing[0]["error"]["code"] == "not_found"


def test_jsonl_backend_runtime_profile_can_be_applied(tmp_path: Path) -> None:
    backend = JsonlBackend(tmp_path / "config.json")

    applied = asyncio.run(
        backend.handle(
            {
                "id": "1",
                "method": "config.apply",
                "params": {"section": "runtime", "value": "local"},
            }
        )
    )

    assert applied[0]["ok"] is True
    assert applied[0]["result"]["runtime_profile"] == "local"
    assert applied[0]["result"]["provider"] == "ollama"
    assert (tmp_path / "config.json").exists()


def test_jsonl_backend_review_command_requires_url(tmp_path: Path) -> None:
    backend = JsonlBackend(tmp_path / "config.json")

    response = asyncio.run(
        backend.handle(
            {"id": "1", "method": "command.execute", "params": {"name": "review", "args": []}}
        )
    )

    assert response[0]["ok"] is True
    assert "PR URL" in response[0]["result"]["text"]


def test_jsonl_backend_error_classification() -> None:
    details = JsonlBackend._classify_error(RuntimeError("Ollama timeout"))
    assert details["code"] == "timeout"

    details = JsonlBackend._classify_error(RuntimeError("GitHub Token invalid (401)"))
    assert details["code"] == "github_auth"


def test_jsonl_backend_model_apply_persists_model(tmp_path: Path) -> None:
    backend = JsonlBackend(tmp_path / "config.json")

    response = asyncio.run(
        backend.handle({"id": "1", "method": "model.apply", "params": {"model": "qwen3.5:4b"}})
    )

    assert response[0]["ok"] is True
    assert response[0]["result"]["config"]["model"] == "qwen3.5:4b"
    assert (tmp_path / "config.json").exists()


def test_jsonl_backend_bounded_report_text(tmp_path: Path) -> None:
    backend = JsonlBackend(tmp_path / "config.json")
    bounded = backend._bound_report(
        {
            "summary": "s" * 10_000,
            "findings": [{"title": "t" * 1_000, "problem": "p" * 8_000}],
        }
    )

    assert len(bounded["summary"]) < 10_000
    assert len(bounded["findings"][0]["title"]) < 1_000
    assert "内容已截断" in bounded["summary"]


def test_jsonl_backend_history_and_export_without_report(tmp_path: Path) -> None:
    backend = JsonlBackend(tmp_path / "config.json")

    history = asyncio.run(
        backend.handle(
            {"id": "1", "method": "command.execute", "params": {"name": "history", "args": []}}
        )
    )
    assert history[0]["ok"] is True
    assert "暂无历史审查记录" in history[0]["result"]["text"]

    export = asyncio.run(
        backend.handle(
            {"id": "2", "method": "command.execute", "params": {"name": "export", "args": ["json"]}}
        )
    )
    assert export[0]["ok"] is True
    assert "没有可导出" in export[0]["result"]["text"]


def test_history_run_becomes_the_current_report_for_report_and_export(tmp_path: Path) -> None:
    """A run opened from history must be exportable.

    The report was on screen but the backend still answered「当前会话还没有可导出的
    审查报告。」because `current_report` was only ever set by a fresh review.
    """
    from ai_pr_review.services.prompt_assembler import Finding, ReviewResult
    from ai_pr_review.services.result_store import ResultStore

    async def run() -> None:
        backend = JsonlBackend(tmp_path / "config.json")
        run_id = ResultStore(backend.config.result_store).save_result(
            "https://github.com/example/repo/pull/7",
            ReviewResult(
                summary="stored summary",
                findings=[
                    Finding(
                        severity="high",
                        category="security",
                        file="a.py",
                        line_start=1,
                        line_end=1,
                        title="stored finding",
                        problem="p",
                        suggestion="s",
                        confidence=0.9,
                        code_snippet="x",
                    )
                ],
            ),
        )

        opened = await backend.handle(
            {
                "id": "1",
                "method": "command.execute",
                "params": {"name": "history", "args": [run_id]},
            }
        )
        assert opened[0]["result"]["report"]["findings"][0]["title"] == "stored finding"

        report = await backend.handle(
            {"id": "2", "method": "command.execute", "params": {"name": "report", "args": []}}
        )
        assert "stored finding" in report[0]["result"]["text"]
        assert "还没有" not in report[0]["result"]["text"]

        export = await backend.handle(
            {
                "id": "3",
                "method": "command.execute",
                "params": {"name": "export", "args": ["markdown"]},
            }
        )
        assert "stored finding" in export[0]["result"]["text"]

    asyncio.run(run())


def test_jsonl_backend_responds_on_live_pipe() -> None:
    """The server must answer while stdin stays open.

    Iterating ``sys.stdin`` buffers ahead, so a long-lived pipe would swallow
    requests until EOF and leave the TUI stuck on "连接中". This guards the
    readline-based event loop in ``serve``.
    """
    import json
    import queue
    import subprocess
    import sys
    import threading

    process = subprocess.Popen(
        [sys.executable, "-m", "ai_pr_review.backend.jsonl_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    lines: queue.Queue[str] = queue.Queue()

    def read_line() -> None:
        assert process.stdout is not None
        line = process.stdout.readline()
        if line:
            lines.put(line)

    try:
        threading.Thread(target=read_line, daemon=True).start()
        assert process.stdin is not None
        process.stdin.write(json.dumps({"id": "1", "method": "health", "params": {}}) + "\n")
        process.stdin.flush()

        event = json.loads(lines.get(timeout=30))
        assert event["id"] == "1"
        assert event["ok"] is True
        assert event["result"]["status"] == "ready"
    finally:
        process.kill()
        process.wait(timeout=10)


def test_jsonl_backend_emits_live_deltas_and_finished(monkeypatch, tmp_path: Path) -> None:
    from ai_pr_review.services.model_providers.base import ProviderResponse

    async def run() -> None:
        published = []
        backend = JsonlBackend(tmp_path / "config.json", event_sink=published.append)
        backend.config.provider.api_key = "test-key"
        backend.config._sync_runtime_sections()
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]

        class FakeProvider:
            async def stream_chat(self, messages, on_delta, **kwargs):
                await on_delta("first")
                assert published[-1]["event"] == "assistant.delta"
                await asyncio.sleep(0)
                await on_delta(" second")
                return ProviderResponse(text="first second")

        monkeypatch.setattr(
            "ai_pr_review.backend.jsonl_server.create_model_provider", lambda config: FakeProvider()
        )
        frames = await backend.handle(
            {
                "id": "turn",
                "method": "chat.send",
                "params": {"session_id": session["session_id"], "text": "hello"},
            }
        )
        assert [item["event"] for item in published] == [
            "assistant.started",
            "assistant.delta",
            "assistant.delta",
            "assistant.finished",
        ]
        assert all(item["request_id"] == "turn" for item in published)
        assert frames[0]["result"]["text"] == "first second"
        assert frames[0]["result"]["session"]["message_count"] == 2

    asyncio.run(run())


def test_jsonl_backend_can_cancel_inflight_chat(monkeypatch, tmp_path: Path) -> None:
    async def run() -> None:
        published = []
        backend = JsonlBackend(tmp_path / "config.json", event_sink=published.append)
        backend.config.provider.api_key = "test-key"
        backend.config._sync_runtime_sections()
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        started = asyncio.Event()

        class SlowProvider:
            async def stream_chat(self, messages, on_delta, **kwargs):
                await on_delta("partial")
                started.set()
                await asyncio.Event().wait()

        monkeypatch.setattr(
            "ai_pr_review.backend.jsonl_server.create_model_provider", lambda config: SlowProvider()
        )
        task = asyncio.create_task(
            backend.handle(
                {
                    "id": "turn",
                    "method": "chat.send",
                    "params": {"session_id": session["session_id"], "text": "hello"},
                }
            )
        )
        await asyncio.wait_for(started.wait(), 1)
        cancel = await backend.handle(
            {
                "id": "cancel",
                "method": "command.execute",
                "params": {"name": "cancel", "session_id": session["session_id"]},
            }
        )
        result = await asyncio.wait_for(task, 1)
        assert cancel[0]["result"]["cancelled"] is True
        assert result[0]["result"]["cancelled"] is True
        assert published[-1]["event"] == "assistant.cancelled"
        assert backend.chat_cancellations == {}
        assert backend.sessions[session["session_id"]].messages == []

    asyncio.run(run())


def test_review_cancelled_after_pipeline_returns_is_not_reported_completed(
    monkeypatch, tmp_path: Path
) -> None:
    """取消若落在最后一个阶段回调之后，不能报成 `review.completed`。"""

    async def fake_run_review(
        pr_url,
        *,
        config,
        progress_console,
        stage_callback,
        progress_callback,
        file_done_callback,
        cancel_check=None,
        file_result_callback=None,
    ):
        assert cancel_check is not None, "取消检查必须透传到编排器"
        assert cancel_check() is False
        cancel_event.set()  # 模拟：所有阶段回调都已结束，用户此时才按取消
        return object()

    async def run() -> None:
        backend = JsonlBackend(tmp_path / "config.json", event_sink=published.append)
        monkeypatch.setattr("ai_pr_review.cli.run_review", fake_run_review)
        with pytest.raises(ReviewCancelled):
            await backend._run_review(
                "https://github.com/example/repo/pull/1", "session-1", events, cancel_event
            )

    published: list[dict] = []
    events: list[dict] = []
    cancel_event = asyncio.Event()
    asyncio.run(run())

    # 没有阶段被启动，因此不产生 review.stage_done；关键是绝不能报成完成。
    events_published = [event["event"] for event in published]
    assert events_published[0] == "review.started"
    assert "review.completed" not in events_published
    assert "review.failed" not in events_published
    assert set(events_published) <= {"review.started", "review.model_routing"}


def test_cancel_covers_chat_and_review_in_same_session(tmp_path: Path) -> None:
    """同一 session 上 chat 与 review 并存时，两个都必须能取消。"""

    async def run() -> None:
        backend = JsonlBackend(tmp_path / "config.json")
        session_id = "shared-session"
        review_event = asyncio.Event()
        backend.review_cancellations[session_id] = review_event
        chat_flag = threading.Event()
        chat_task = asyncio.create_task(asyncio.sleep(30))
        backend.chat_cancellations[session_id] = (chat_task, chat_flag)

        responses = await backend.handle(
            {
                "id": "cancel",
                "method": "command.execute",
                "params": {"name": "cancel", "session_id": session_id},
            }
        )
        assert responses[0]["result"]["cancelled"] is True
        assert chat_flag.is_set()
        assert chat_task.cancelling() > 0
        assert review_event.is_set()

        chat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await chat_task

    asyncio.run(run())


def test_orchestrator_cancel_is_reported_as_cancelled_not_failed(
    monkeypatch, tmp_path: Path
) -> None:
    """编排器抛出的取消必须走 `review.cancelled`。

    修复前 `jsonl_server.ReviewCancelled` 与编排器的 `ReviewCancelled` 是两个
    互不相关的类，取消会被 `except Exception` 接住并误报成 `review.failed`。
    这里的假 run_review 抛的是**基类**，因此只有真正的子类化才能让断言通过。
    """
    from ai_pr_review.services.review_orchestrator import ReviewCancelled as OrchestratorCancelled

    async def fake_run_review(pr_url, **kwargs):
        raise OrchestratorCancelled()

    async def run() -> None:
        published: list[dict] = []
        backend = JsonlBackend(tmp_path / "config.json", event_sink=published.append)
        monkeypatch.setattr("ai_pr_review.cli.run_review", fake_run_review)

        responses = await backend.handle(
            {
                "id": "review",
                "method": "command.execute",
                "params": {
                    "name": "review",
                    "args": ["https://github.com/example/repo/pull/1"],
                    "session_id": "session-1",
                },
            }
        )

        events = [event["event"] for event in published]
        assert "review.cancelled" in events
        assert "review.failed" not in events
        assert responses[0]["result"]["cancelled"] is True
        assert backend.review_cancellations == {}

    asyncio.run(run())


def test_second_review_in_the_same_session_is_rejected_as_busy(monkeypatch, tmp_path: Path) -> None:
    """同 session 的第二个 `/review` 必须被拒绝，且不能顶掉第一个的取消句柄。

    修复前后端没有 busy 守卫：第二个请求会覆盖 `review_cancellations[session_id]`，
    第一个审查从此无法取消，而先结束的那个还会在 `finally` 里 pop 掉第二个的 Event。
    """

    async def run() -> None:
        from ai_pr_review.services.review_orchestrator import (
            ReviewCancelled as OrchestratorCancelled,
        )

        published: list[dict] = []
        backend = JsonlBackend(tmp_path / "config.json", event_sink=published.append)
        started = asyncio.Event()
        cancel_seen = asyncio.Event()
        calls: list[str] = []

        async def fake_run_review(pr_url, **kwargs):
            calls.append(pr_url)
            check = kwargs["cancel_check"]
            assert check is not None, "取消检查必须透传到编排器"
            if len(calls) == 1:
                started.set()
                while not check():
                    await asyncio.sleep(0.01)
                cancel_seen.set()
            raise OrchestratorCancelled()

        monkeypatch.setattr("ai_pr_review.cli.run_review", fake_run_review)

        def review_request(request_id: str, pr_url: str) -> dict:
            return {
                "id": request_id,
                "method": "command.execute",
                "params": {"name": "review", "args": [pr_url], "session_id": "session-1"},
            }

        first = asyncio.create_task(
            backend.handle(review_request("review-1", "https://github.com/example/repo/pull/1"))
        )
        await asyncio.wait_for(started.wait(), 1)
        running_event = backend.review_cancellations["session-1"]

        second = await backend.handle(
            review_request("review-2", "https://github.com/example/repo/pull/2")
        )
        assert second[0]["ok"] is False
        assert second[0]["error"]["code"] == "busy"
        # 第一个审查的取消句柄必须原样保留，否则之后的 /cancel 找不到它
        assert backend.review_cancellations["session-1"] is running_event
        assert calls == ["https://github.com/example/repo/pull/1"]
        assert [event["event"] for event in published].count("review.started") == 1

        cancel = await backend.handle(
            {
                "id": "cancel",
                "method": "command.execute",
                "params": {"name": "cancel", "session_id": "session-1"},
            }
        )
        assert cancel[0]["result"]["cancelled"] is True
        first_events = await asyncio.wait_for(first, 1)
        assert first_events[0]["result"]["cancelled"] is True
        assert cancel_seen.is_set()
        assert backend.review_cancellations == {}

        # busy 守卫不能把会话永久锁死：上一次结束后必须能再次发起审查
        third = await backend.handle(
            review_request("review-3", "https://github.com/example/repo/pull/3")
        )
        assert third[0]["result"]["cancelled"] is True
        assert backend.review_cancellations == {}

    asyncio.run(run())


def test_finishing_review_does_not_clear_another_reviews_cancel_event(
    monkeypatch, tmp_path: Path
) -> None:
    """结束清理必须按身份进行：先结束的审查不能 pop 掉别人的 Event。

    busy 守卫已经拦住了「第二个 `/review` 顶掉第一个」，这里固定兜底的
    身份校验：只要槽位里不是自己的 Event，就不许清空它。
    """

    async def run() -> None:
        from ai_pr_review.services.review_orchestrator import (
            ReviewCancelled as OrchestratorCancelled,
        )

        published: list[dict] = []
        backend = JsonlBackend(tmp_path / "config.json", event_sink=published.append)
        foreign_event = asyncio.Event()

        async def fake_run_review(pr_url, **kwargs):
            # 模拟「第二个审查已经占住同一个槽位」（旧代码里它会覆盖第一个的句柄）
            backend.review_cancellations["session-1"] = foreign_event
            raise OrchestratorCancelled()

        monkeypatch.setattr("ai_pr_review.cli.run_review", fake_run_review)

        responses = await backend.handle(
            {
                "id": "review",
                "method": "command.execute",
                "params": {
                    "name": "review",
                    "args": ["https://github.com/example/repo/pull/1"],
                    "session_id": "session-1",
                },
            }
        )

        assert responses[0]["result"]["cancelled"] is True
        # 旧实现在 finally 里无条件 pop，会把 foreign_event 一起清掉
        assert backend.review_cancellations.get("session-1") is foreign_event

    asyncio.run(run())


def test_failed_review_frees_the_session_busy_slot(monkeypatch, tmp_path: Path) -> None:
    """审查以普通错误（非取消）结束时，busy 槽位也必须释放。

    反例：槽位只在 `finally` 里释放。若失败路径漏掉这次清理，会话会被永久判为
    busy —— 用户看到「该会话已有审查正在进行」，但实际没有任何审查在跑，
    `/cancel` 也找不到可取消的任务，只能重启 TUI。取消路径已有用例覆盖，
    失败路径此前没有。
    """

    async def run() -> None:
        from ai_pr_review.services.review_orchestrator import (
            ReviewCancelled as OrchestratorCancelled,
        )

        published: list[dict] = []
        backend = JsonlBackend(tmp_path / "config.json", event_sink=published.append)
        calls: list[str] = []

        async def fake_run_review(pr_url, **kwargs):
            calls.append(pr_url)
            if len(calls) == 1:
                raise RuntimeError("模型供应商网络请求失败。")
            raise OrchestratorCancelled()

        monkeypatch.setattr("ai_pr_review.cli.run_review", fake_run_review)

        def review_request(request_id: str, pr_url: str) -> dict:
            return {
                "id": request_id,
                "method": "command.execute",
                "params": {"name": "review", "args": [pr_url], "session_id": "session-1"},
            }

        failed = await backend.handle(
            review_request("review-1", "https://github.com/example/repo/pull/1")
        )
        assert failed[0]["ok"] is False
        assert "review.failed" in [event["event"] for event in published]
        assert backend.review_cancellations == {}

        # 同一 session 必须能立刻重试，而不是被判为 busy
        retried = await backend.handle(
            review_request("review-2", "https://github.com/example/repo/pull/2")
        )
        assert retried[0]["ok"] is True
        assert retried[0]["result"]["cancelled"] is True
        assert calls == [
            "https://github.com/example/repo/pull/1",
            "https://github.com/example/repo/pull/2",
        ]
        assert backend.review_cancellations == {}

    asyncio.run(run())


def test_runtime_switch_does_not_carry_cloud_key_to_local(tmp_path: Path) -> None:
    backend = JsonlBackend(tmp_path / "config.json")
    backend.config.provider.api_key = "cloud-only-secret"
    backend.config.ai_client.api_key = "cloud-only-secret"
    backend.config._sync_runtime_sections()

    selected = backend._apply_runtime_profile("local")
    assert selected["provider"] == "ollama"
    # 云端 Key 不能泄漏进本地槽位
    assert backend.config.local_provider.api_key == ""
    assert backend.config.ai_client.model_provider.name == "ollama"
    assert backend.config.ai_client.api_key == ""
    # 云端槽位必须原样保留，否则 `/model local` 会永久摧毁远程配置
    assert backend.config.provider.name == "anthropic"
    assert backend.config.provider.api_key == "cloud-only-secret"

    restarted = JsonlBackend(tmp_path / "config.json")
    assert restarted.runtime_profile == "local"
    assert restarted.config.ai_client.model_provider.name == "ollama"
    assert restarted.config.local_provider.api_key == ""
    assert restarted.config.provider.api_key == "cloud-only-secret"

    # 而且必须能无损切回云端
    restored = restarted._apply_runtime_profile("cloud")
    assert restored["provider"] == "anthropic"
    assert restored["local"] is False
    assert restarted.config.ai_client.model_provider.name == "anthropic"
    assert restarted.config.ai_client.api_key == "cloud-only-secret"


def test_offline_profile_never_uses_remote_provider(tmp_path: Path) -> None:
    backend = JsonlBackend(tmp_path / "config.json")
    selected = backend._apply_runtime_profile("offline")
    assert selected["provider"] == "ollama"
    assert selected["strategy"] == "local_only"
    assert backend.config.ai_client.model_provider.name == "ollama"

    refused = asyncio.run(
        backend.handle(
            {
                "id": "cloud",
                "method": "config.apply",
                "params": {"section": "runtime", "value": "hybrid"},
            }
        )
    )
    assert refused[0]["ok"] is False
    assert backend.config.ai_client.model_provider.name == "ollama"


def test_loading_local_provider_discards_stale_remote_client_key(
    tmp_path: Path, monkeypatch
) -> None:
    import json

    from ai_pr_review.config import ModelProviderConfig, ProviderConfig

    for name in (
        "AI_PR_REVIEW_API_KEY",
        "AI_PR_REVIEW_PROVIDER",
        "ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    local = ProviderConfig.from_model_provider(ModelProviderConfig.from_name("ollama"))
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "provider": local.to_dict(),
                "ai_client": {
                    "provider": "deepseek",
                    "api_key": "stale-cloud-key",
                    "model": "deepseek-chat",
                },
            }
        ),
        encoding="utf-8",
    )
    restarted = JsonlBackend(config_path)
    assert restarted.config.provider.name == "ollama"
    assert restarted.config.ai_client.model_provider.name == "ollama"
    assert restarted.config.ai_client.api_key == ""


def test_provider_env_override_rebuilds_endpoint_and_model(tmp_path: Path, monkeypatch) -> None:
    backend = JsonlBackend(tmp_path / "config.json")
    backend._apply_runtime_profile("local")
    monkeypatch.setenv("AI_PR_REVIEW_PROVIDER", "deepseek")
    for name in ("AI_PR_REVIEW_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    restarted = JsonlBackend(tmp_path / "config.json")
    assert restarted.config.provider.name == "deepseek"
    assert restarted.config.provider.default_model == "deepseek-chat"
    assert restarted.config.provider.base_url.startswith("https://")
    assert restarted.config.ai_client.model_provider.name == "deepseek"
    assert restarted.config.ai_client.api_key == ""


def test_explicit_config_path_isolates_history_store(tmp_path: Path) -> None:
    first = JsonlBackend(tmp_path / "one" / "config.json")
    second = JsonlBackend(tmp_path / "two" / "config.json")

    first_history = asyncio.run(
        first.handle(
            {"id": "1", "method": "command.execute", "params": {"name": "history", "args": []}}
        )
    )
    second_history = asyncio.run(
        second.handle(
            {"id": "2", "method": "command.execute", "params": {"name": "history", "args": []}}
        )
    )

    assert "暂无历史审查记录" in first_history[0]["result"]["text"]
    assert "暂无历史审查记录" in second_history[0]["result"]["text"]
    assert first.config.result_store.db_path != second.config.result_store.db_path
    assert str(tmp_path / "one" / "results.db") == first.config.result_store.db_path
    assert str(tmp_path / "two" / "results.db") == second.config.result_store.db_path


def test_explicit_result_store_path_is_preserved(tmp_path: Path) -> None:
    custom_db = tmp_path / "shared" / "history.db"
    config_path = tmp_path / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps({"result_store": {"db_path": str(custom_db)}}, ensure_ascii=False),
        encoding="utf-8",
    )
    backend = JsonlBackend(config_path)
    assert backend.config.result_store.db_path == str(custom_db)


def test_env_config_path_isolates_history_store(tmp_path: Path) -> None:
    """The TUI passes the config path only through AI_PR_REVIEW_CONFIG."""
    import os
    import queue
    import subprocess
    import sys
    import threading

    config_path = tmp_path / "workspace" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["AI_PR_REVIEW_CONFIG"] = str(config_path)
    env["PYTHONIOENCODING"] = "utf-8"
    process = subprocess.Popen(
        [sys.executable, "-m", "ai_pr_review.backend.jsonl_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
    )
    lines: queue.Queue[str] = queue.Queue()

    def read_line() -> None:
        assert process.stdout is not None
        line = process.stdout.readline()
        if line:
            lines.put(line)

    try:
        threading.Thread(target=read_line, daemon=True).start()
        assert process.stdin is not None
        process.stdin.write(
            json.dumps({"id": "1", "method": "config.snapshot", "params": {}}) + "\n"
        )
        process.stdin.flush()
        event = json.loads(lines.get(timeout=30))
        assert event["ok"] is True
        expected = str(config_path.parent.resolve() / "results.db")
        assert event["result"]["result_store_path"] == expected
    finally:
        process.kill()
        process.wait(timeout=10)


def test_derived_db_path_is_not_frozen_into_config(tmp_path: Path) -> None:
    backend = JsonlBackend(tmp_path / "config.json")
    backend._apply_runtime_profile("local")

    saved = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert "db_path" not in saved.get("result_store", {})

    reloaded = JsonlBackend(tmp_path / "config.json")
    assert reloaded.config.result_store.db_path == str(tmp_path.resolve() / "results.db")


def test_explicit_platform_default_db_path_survives_save(tmp_path: Path) -> None:
    """An explicit path is not a derived default, even when they have equal values."""
    from ai_pr_review.config import AppConfig, _default_result_store_path

    default_db = _default_result_store_path()
    config_path = tmp_path / "workspace" / "config.json"
    config_path.parent.mkdir()
    config_path.write_text(
        json.dumps({"result_store": {"db_path": str(default_db)}}), encoding="utf-8"
    )

    config = AppConfig.load(config_path)
    assert config.result_store.db_path == str(default_db)
    config.save(config_path)
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["result_store"]["db_path"] == str(default_db)
    assert AppConfig.load(config_path).result_store.db_path == str(default_db)


def test_invalid_provider_override_is_visible_in_tui_snapshot_without_echoing_value(
    tmp_path: Path, monkeypatch
) -> None:
    from ai_pr_review.config import AppConfig

    monkeypatch.setenv("AI_PR_REVIEW_PROVIDER", "not-a-provider-with-private-value")
    with pytest.warns(RuntimeWarning, match="不受支持"):
        backend = JsonlBackend(tmp_path / "config.json")
    snapshot = backend._config_snapshot()
    assert snapshot["provider"] != "not-a-provider-with-private-value"
    assert len(snapshot["configuration_warnings"]) == 1
    assert "已忽略" in snapshot["configuration_warnings"][0]
    assert "private-value" not in snapshot["configuration_warnings"][0]


def test_matching_invalid_provider_override_is_still_rejected(tmp_path: Path, monkeypatch) -> None:
    from ai_pr_review.config import AppConfig

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "provider": {
                    "name": "legacy-unsupported-provider",
                    "display_name": "legacy-unsupported-provider",
                    "base_url": "https://example.invalid/v1",
                    "api_format": "openai",
                    "default_model": "legacy-model",
                    "models": {"legacy-model": {"name": "legacy-model"}},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AI_PR_REVIEW_PROVIDER", "legacy-unsupported-provider")
    with pytest.warns(RuntimeWarning, match="不受支持"):
        config = AppConfig.load(config_path)
    assert getattr(config, "_env_provider_override", False) is False
    assert config._ignored_env_overrides
    assert "legacy-unsupported-provider" not in config._ignored_env_overrides[0]
    with pytest.warns(RuntimeWarning, match="不受支持"):
        backend = JsonlBackend(config_path)
    snapshot = backend._config_snapshot()
    assert snapshot["provider"] == "unsupported"
    assert "legacy-unsupported-provider" not in json.dumps(snapshot)


def test_matching_provider_env_override_activates_cloud_only_for_process(
    tmp_path: Path, monkeypatch
) -> None:
    config_path = tmp_path / "config.json"
    backend = JsonlBackend(config_path)
    backend._apply_runtime_profile("local")
    monkeypatch.setenv("AI_PR_REVIEW_PROVIDER", backend.config.provider.name)

    restarted = JsonlBackend(config_path)
    assert restarted.config.preferences.hybrid_strategy == "local_only"
    assert restarted.config.ai_client.provider == backend.config.provider.name
    assert restarted.runtime_profile == "cloud"
    assert restarted._config_snapshot()["local"] is False

    monkeypatch.delenv("AI_PR_REVIEW_PROVIDER")
    restored = JsonlBackend(config_path)
    assert restored.runtime_profile == "local"
    assert restored.config.ai_client.provider == "ollama"


def test_config_setup_persists_cloud_key_and_survives_local_round_trip(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.json"
    backend = JsonlBackend(config_path)

    configured = asyncio.run(
        backend.handle(
            {
                "id": "1",
                "method": "config.setup",
                "params": {
                    "runtime_profile": "cloud",
                    "provider_name": "deepseek",
                    "api_key": "sk-test-not-real",
                    "model_name": "deepseek-flash",
                },
            }
        )
    )
    assert configured[0]["ok"] is True
    cloud_snapshot = configured[0]["result"]
    assert cloud_snapshot["runtime_profile"] == "cloud"
    assert cloud_snapshot["provider"] == "deepseek"
    assert cloud_snapshot["model"] == "deepseek-flash"
    assert cloud_snapshot["api_key_configured"] is True

    local = asyncio.run(
        backend.handle(
            {
                "id": "2",
                "method": "config.setup",
                "params": {
                    "runtime_profile": "local",
                    "local_model": "qwen3.5:4b",
                },
            }
        )
    )
    assert local[0]["ok"] is True
    assert local[0]["result"]["local"] is True
    assert local[0]["result"]["provider"] == "ollama"

    # The remote slot and its key must survive the local switch; switching back
    # without re-entering the key is the exact regression users hit in Chat.
    restarted = JsonlBackend(config_path)
    assert restarted.config.provider.api_key == "sk-test-not-real"
    reloaded_cloud = asyncio.run(
        restarted.handle(
            {
                "id": "3",
                "method": "config.setup",
                "params": {"runtime_profile": "cloud"},
            }
        )
    )
    assert reloaded_cloud[0]["ok"] is True
    assert reloaded_cloud[0]["result"]["provider"] == "deepseek"
    assert reloaded_cloud[0]["result"]["model"] == "deepseek-flash"
    assert reloaded_cloud[0]["result"]["api_key_configured"] is True


def test_config_setup_requires_a_key_for_a_new_cloud_provider(tmp_path: Path) -> None:
    from ai_pr_review.config import ConfigValidationError

    backend = JsonlBackend(tmp_path / "config.json")
    with pytest.raises(ConfigValidationError, match="API Key"):
        backend._apply_setup(
            {
                "runtime_profile": "cloud",
                "provider_name": "openai",
                "model_name": "gpt-4o-mini",
            }
        )


def test_config_options_expose_cloud_and_local_model_choices(tmp_path: Path) -> None:
    backend = JsonlBackend(tmp_path / "config.json")
    options = backend._setup_options()
    providers = {item["name"]: item for item in options["providers"]}

    assert "deepseek" in providers
    assert "ollama" not in providers
    assert "deepseek-flash" in providers["deepseek"]["models"]
    assert {item["value"] for item in options["api_formats"]} >= {"openai", "anthropic", "custom"}
    assert {item["value"] for item in options["ui_languages"]} == {"zh-CN", "en-US"}
    assert {item["value"] for item in options["output_formats"]} == {"terminal", "markdown", "json"}
    assert {item["value"] for item in options["chat_layouts"]} == {"compact", "split", "plain"}
    assert options["local"]["provider"] == "ollama"
    assert options["local"]["models"]

    backend._apply_setup(
        {
            "runtime_profile": "cloud",
            "provider_name": "deepseek",
            "api_key": "sk-test-not-real",
            "model_name": "deepseek-flash",
        }
    )
    backend._apply_setup({"runtime_profile": "local", "local_model": "qwen3.5:4b"})
    local_options = backend._setup_options()
    assert local_options["current"]["provider"] == "ollama"
    assert local_options["current"]["remote_provider"] == "deepseek"
    assert local_options["current"]["remote_model"] == "deepseek-flash"
    assert local_options["current"]["remote_api_key_configured"] is True


def test_config_setup_persists_github_and_interface_preferences(tmp_path: Path) -> None:
    from ai_pr_review.config import AppConfig, ConfigValidationError

    config_path = tmp_path / "config.json"
    backend = JsonlBackend(config_path)
    github_token = "ghp_" + "x" * 40

    response = asyncio.run(
        backend.handle(
            {
                "id": "1",
                "method": "config.setup",
                "params": {
                    "runtime_profile": "cloud",
                    "provider_name": "deepseek",
                    "api_key": "sk-test-not-real",
                    "model_name": "deepseek-flash",
                    "base_url": "https://api.deepseek.com/v1",
                    "api_format": "openai",
                    "github_token": github_token,
                    "ui_language": "en-US",
                    "response_language": "en-US",
                    "output_format": "markdown",
                    "auto_publish_comment": True,
                    "chat_layout": "split",
                },
            }
        )
    )

    assert response[0]["ok"] is True
    snapshot = response[0]["result"]
    assert snapshot["github_token_configured"] is True
    assert snapshot["ui_language"] == "en-US"
    assert snapshot["response_language"] == "en-US"
    assert snapshot["output_format"] == "markdown"
    assert snapshot["auto_publish_comment"] is True
    assert snapshot["chat_layout"] == "split"

    reloaded = AppConfig.load(config_path)
    assert reloaded.github_token == github_token
    assert reloaded.preferences.ui_language == "en-US"
    assert reloaded.preferences.language == "en-US"
    assert reloaded.preferences.output_format == "markdown"
    assert reloaded.preferences.auto_publish_comment is True
    assert reloaded.preferences.chat_layout == "split"

    with pytest.raises(ConfigValidationError, match="GitHub Token"):
        backend._apply_setup({"runtime_profile": "cloud", "github_token": "bad-token"})


# ---------------------------------------------------------------------------
# Review workspace event contract (docs/review-workspace-contract.md §3)
# ---------------------------------------------------------------------------


def _review_request(request_id: str = "review") -> dict:
    return {
        "id": request_id,
        "method": "command.execute",
        "params": {
            "name": "review",
            "args": ["https://github.com/example/repo/pull/31"],
            "session_id": "session-1",
        },
    }


def _finding(
    *,
    severity: str = "high",
    filename: str = "src/module_0.py",
    evidence_status: str = "valid",
) -> Any:
    from ai_pr_review.services.prompt_assembler import Finding

    return Finding(
        severity=severity,
        category="correctness",
        file=filename,
        line_start=1,
        line_end=1,
        title=f"{severity} finding",
        problem="problem",
        suggestion="suggestion",
        confidence=0.8,
        code_snippet="x = 1",
        evidence_status=evidence_status,
    )


def _review_artifacts(
    *,
    included: int = 2,
    excluded: int = 1,
    findings: list[Any] | None = None,
    total_cost: float = 0.0124,
    duration_seconds: float = 42.3,
    filtered_findings: dict[str, Any] | None = None,
) -> Any:
    """Build real artifacts so `build_report_payload` is exercised for real."""
    from ai_pr_review.models.pr_data import FileDiff, FileStatus, PRData
    from ai_pr_review.services.filter_pipeline import (
        FilterPipelineResult,
        FilterReason,
        FilterReasonCode,
        FilterResult,
    )
    from ai_pr_review.services.prompt_assembler import ReviewResult
    from ai_pr_review.services.review_orchestrator import ReviewArtifacts

    files = [
        FileDiff(
            filename=f"src/module_{index}.py",
            status=FileStatus.MODIFIED,
            additions=3,
            deletions=1,
            changes=4,
        )
        for index in range(included + excluded)
    ]
    results = [FilterResult(file=file, included=True) for file in files[:included]]
    results.extend(
        FilterResult(
            file=file,
            included=False,
            reasons=[
                FilterReason(
                    code=FilterReasonCode.EXCLUDED_BY_PATTERN,
                    action="exclude",
                    message="命中黑名单规则",
                )
            ],
        )
        for file in files[included:]
    )
    return ReviewArtifacts(
        pr_data=PRData(
            pr_number=31,
            title="Review workspace contract",
            author="octocat",
            state="open",
            head_sha="a" * 40,
            base_sha="b" * 40,
            head_ref="feature",
            base_ref="main",
            url="https://github.com/example/repo/pull/31",
            owner="example",
            repo="repo",
            files=files,
        ),
        filter_result=FilterPipelineResult(results=results),
        review_result=ReviewResult(summary="审查完成", findings=findings or []),
        total_cost=total_cost,
        duration_seconds=duration_seconds,
        run_id="run-31",
        validation_summary={"valid": 1, "needs_review": 1, "invalid": 1},
        filtered_findings=filtered_findings or {},
    )


def test_review_stage_events_report_ids_progress_and_measured_durations(
    monkeypatch, tmp_path: Path
) -> None:
    """契约 §3.2/§3.3：阶段事件必须带 stage_id/status/progress/started_at，
    `review.stage_done` 的 duration_ms 由后端实测，且顺序为 started → 各阶段 → completed。
    """
    stages = ("fetching", "filtering", "context", "static_rules", "reviewing", "persisting")

    async def run() -> list[dict]:
        published: list[dict] = []
        backend = JsonlBackend(tmp_path / "config.json", event_sink=published.append)
        # 固定为本地策略，让路由事件的内容可预测
        backend._apply_runtime_profile("local")

        async def fake_run_review(pr_url, **kwargs):
            stage_callback = kwargs["stage_callback"]
            for stage in stages:
                stage_callback(stage, f"{stage} 详情")
                await asyncio.sleep(0.02)
            return _review_artifacts()

        monkeypatch.setattr("ai_pr_review.cli.run_review", fake_run_review)
        responses = await backend.handle(_review_request())
        assert responses[0]["ok"] is True
        return published

    published = asyncio.run(run())
    assert [event["event"] for event in published] == [
        "review.started",
        "review.model_routing",
        *[name for stage in stages for name in ("review.stage", "review.stage_done")],
        "review.completed",
    ]

    started = published[0]
    assert started["url"] == "https://github.com/example/repo/pull/31"
    assert started["started_at"]

    stage_events = [event for event in published if event["event"] == "review.stage"]
    assert [event["stage_id"] for event in stage_events] == list(stages)
    assert [event["stage"] for event in stage_events] == [
        "获取 PR 数据",
        "过滤变更文件",
        "构建代码上下文",
        "运行静态规则",
        "执行 AI 审查",
        "保存审查记录",
    ]
    assert all(event["status"] == "started" for event in stage_events)
    assert all(event["started_at"] for event in stage_events)
    assert [event["progress"] for event in stage_events] == [5, 10, 20, 30, 70, 98]
    assert stage_events[4]["detail"] == "reviewing 详情"

    done_events = [event for event in published if event["event"] == "review.stage_done"]
    assert [event["stage_id"] for event in done_events] == list(stages)
    assert all(event["status"] == "completed" for event in done_events)
    # 实测时长：每个阶段之间真的等待了 20ms（最后一个阶段紧随结束，不做下界断言）
    assert all(event["duration_ms"] >= 15 for event in done_events[:-1])
    assert all(event["duration_ms"] >= 0 for event in done_events)
    assert done_events[-1]["progress"] == 100

    progress = [
        event["progress"]
        for event in published
        if event["event"] in {"review.stage", "review.stage_done"}
    ]
    assert progress == sorted(progress)

    completed = published[-1]
    assert completed["run_id"] == "run-31"
    # 原有字段保持可用（这份 fixture 没有任何 finding）
    assert completed["finding_count"] == 0


def test_review_file_events_report_index_total_and_never_fake_findings_count(
    monkeypatch, tmp_path: Path
) -> None:
    """契约 §3.4/§3.5：文件事件带 index/total；每文件 findings_count 未知时为 null。

    当前 orchestrator 不暴露每文件 finding 数，因此必须是 null，不能编造 0。
    """

    async def run() -> list[dict]:
        published: list[dict] = []
        backend = JsonlBackend(tmp_path / "config.json", event_sink=published.append)

        async def fake_run_review(pr_url, **kwargs):
            stage_callback = kwargs["stage_callback"]
            progress_callback = kwargs["progress_callback"]
            file_done_callback = kwargs["file_done_callback"]
            stage_callback("context", "正在为 2 个文件构建上下文")
            progress_callback("src/a.py", "本地/qwen3.5:4b")
            await asyncio.sleep(0.02)
            file_done_callback("src/a.py")
            progress_callback("src/b.py", "远程/deepseek-chat")
            file_done_callback("src/b.py")
            return _review_artifacts(included=2, excluded=1)

        monkeypatch.setattr("ai_pr_review.cli.run_review", fake_run_review)
        await backend.handle(_review_request())
        return published

    published = asyncio.run(run())
    file_started = [event for event in published if event["event"] == "review.file_started"]
    assert [event["filename"] for event in file_started] == ["src/a.py", "src/b.py"]
    assert [event["index"] for event in file_started] == [1, 2]
    assert all(event["total"] == 2 for event in file_started)
    assert all(event["started_at"] for event in file_started)
    # 旧字段保持可用：模型标签仍逐个文件上报
    assert [event["model"] for event in file_started] == [
        "本地/qwen3.5:4b",
        "远程/deepseek-chat",
    ]

    file_done = [event for event in published if event["event"] == "review.file_done"]
    assert [event["filename"] for event in file_done] == ["src/a.py", "src/b.py"]
    assert [event["index"] for event in file_done] == [1, 2]
    assert all(event["total"] == 2 for event in file_done)
    assert all(event["status"] == "reviewed" for event in file_done)
    assert all("findings_count" in event and event["findings_count"] is None for event in file_done)
    assert all(event["duration_ms"] is not None for event in file_done)
    assert file_done[0]["duration_ms"] >= 15


def test_review_file_total_is_null_when_the_orchestrator_never_reports_it(
    monkeypatch, tmp_path: Path
) -> None:
    """过滤阶段报的是「变更文件数」，不能拿来当审查文件总数。"""

    async def run() -> list[dict]:
        published: list[dict] = []
        backend = JsonlBackend(tmp_path / "config.json", event_sink=published.append)

        async def fake_run_review(pr_url, **kwargs):
            kwargs["stage_callback"]("filtering", "共 120 个变更文件，正在过滤")
            kwargs["progress_callback"]("src/a.py", "")
            kwargs["file_done_callback"]("src/a.py")
            return _review_artifacts()

        monkeypatch.setattr("ai_pr_review.cli.run_review", fake_run_review)
        await backend.handle(_review_request())
        return published

    published = asyncio.run(run())
    file_started = next(event for event in published if event["event"] == "review.file_started")
    file_done = next(event for event in published if event["event"] == "review.file_done")
    assert file_started["total"] is None
    assert file_done["total"] is None


def test_review_file_done_uses_real_status_findings_count_and_duration(
    monkeypatch, tmp_path: Path
) -> None:
    """契约 §3.5/§10.2：file_result_callback 的真实结果必须进入 review.file_done。

    旧回调缺席时保留 null 兜底（见上一个测试）；这里覆盖 reviewed / failed /
    skipped 三种真实结果，以及被过滤文件不触发 file_started 的事实。
    """

    async def run() -> list[dict]:
        published: list[dict] = []
        backend = JsonlBackend(tmp_path / "config.json", event_sink=published.append)

        async def fake_run_review(pr_url, **kwargs):
            file_result_callback = kwargs["file_result_callback"]
            file_done_callback = kwargs["file_done_callback"]
            progress_callback = kwargs["progress_callback"]
            kwargs["stage_callback"]("context", "正在为 2 个文件构建上下文")
            # 被过滤的文件：只有结果回调，没有 started / done
            file_result_callback(
                {
                    "filename": "docs/readme.md",
                    "status": "skipped",
                    "findings_count": None,
                    "duration_ms": 0,
                    "error": None,
                }
            )
            progress_callback("src/a.py", "本地/qwen3.5:4b")
            await asyncio.sleep(0.02)
            file_result_callback(
                {
                    "filename": "src/a.py",
                    "status": "reviewed",
                    "findings_count": 2,
                    "duration_ms": 4200,
                    "error": None,
                }
            )
            file_done_callback("src/a.py")
            progress_callback("src/b.py", "本地/qwen3.5:4b")
            file_result_callback(
                {
                    "filename": "src/b.py",
                    "status": "failed",
                    "findings_count": None,
                    "duration_ms": 17,
                    "error": "model call failed for src/b.py",
                }
            )
            file_done_callback("src/b.py")
            return _review_artifacts(included=2, excluded=1)

        monkeypatch.setattr("ai_pr_review.cli.run_review", fake_run_review)
        await backend.handle(_review_request())
        return published

    published = asyncio.run(run())
    file_done = [event for event in published if event["event"] == "review.file_done"]
    assert [event["filename"] for event in file_done] == [
        "docs/readme.md",
        "src/a.py",
        "src/b.py",
    ]

    skipped, reviewed, failed = file_done
    assert skipped["status"] == "skipped"
    assert skipped["findings_count"] is None
    assert skipped["reason"] == "filtered_by_policy"
    assert skipped["index"] is None

    assert reviewed["status"] == "reviewed"
    assert reviewed["findings_count"] == 2
    # 实测值来自编排器，而不是后端自己掐的表
    assert reviewed["duration_ms"] == 4200
    assert "error" not in reviewed
    assert reviewed["index"] == 1

    assert failed["status"] == "failed"
    assert failed["findings_count"] is None
    assert failed["duration_ms"] == 17
    assert failed["error"] == "model call failed for src/b.py"
    assert failed["index"] == 2

    # 被过滤的文件不产生 file_started
    started = [event for event in published if event["event"] == "review.file_started"]
    assert [event["filename"] for event in started] == ["src/a.py", "src/b.py"]


def test_review_file_done_falls_back_to_measured_duration_when_payload_omits_it(
    monkeypatch, tmp_path: Path
) -> None:
    """编排器只报部分字段时，缺的字段各自兜底，不能整体丢弃。"""

    async def run() -> list[dict]:
        published: list[dict] = []
        backend = JsonlBackend(tmp_path / "config.json", event_sink=published.append)

        async def fake_run_review(pr_url, **kwargs):
            kwargs["stage_callback"]("context", "正在为 1 个文件构建上下文")
            kwargs["progress_callback"]("src/a.py", "")
            await asyncio.sleep(0.02)
            kwargs["file_result_callback"]({"filename": "src/a.py", "status": "reviewed"})
            kwargs["file_done_callback"]("src/a.py")
            return _review_artifacts(included=1, excluded=0)

        monkeypatch.setattr("ai_pr_review.cli.run_review", fake_run_review)
        await backend.handle(_review_request())
        return published

    published = asyncio.run(run())
    done = next(event for event in published if event["event"] == "review.file_done")
    assert done["status"] == "reviewed"
    assert done["findings_count"] is None
    assert done["duration_ms"] is not None and done["duration_ms"] >= 15


def test_review_stage_progress_table_stays_monotonic_for_both_orchestrators() -> None:
    from ai_pr_review.backend.jsonl_server import REVIEW_STAGE_LABELS, REVIEW_STAGE_PROGRESS

    standard = ("fetching", "filtering", "context", "reviewing", "cross_file", "persisting")
    hybrid = ("fetching", "filtering", "context", "static_rules", "reviewing", "persisting")
    for order in (standard, hybrid):
        progress: list[int] = []
        for stage_id in order:
            assert stage_id in REVIEW_STAGE_LABELS
            start, done = REVIEW_STAGE_PROGRESS[stage_id]
            assert start <= done
            progress.extend((start, done))
        assert progress == sorted(progress)


def test_review_file_total_parsing_covers_both_orchestrators() -> None:
    from ai_pr_review.backend.jsonl_server import _parse_review_file_total

    assert _parse_review_file_total("正在为 4 个文件构建上下文") == 4
    assert _parse_review_file_total("为 7 个文件构建代码上下文") == 7
    assert _parse_review_file_total("开始智能分级审查，共 6 个文件") == 6
    assert _parse_review_file_total("共 120 个变更文件，正在过滤") is None
    assert _parse_review_file_total("开始逐文件审查（并发 4）") is None


def test_review_completed_carries_severity_evidence_files_cost_and_duration(
    monkeypatch, tmp_path: Path
) -> None:
    """契约 §3.7：review.completed 增加汇总字段，且原有字段保持可用。"""
    findings = [
        _finding(severity="critical", evidence_status="valid"),
        _finding(severity="high", evidence_status="needs_review"),
        _finding(severity="medium", evidence_status="invalid"),
        _finding(severity="low", evidence_status="unverified"),
    ]

    async def run() -> list[dict]:
        published: list[dict] = []
        backend = JsonlBackend(tmp_path / "config.json", event_sink=published.append)

        async def fake_run_review(pr_url, **kwargs):
            return _review_artifacts(
                included=18,
                excluded=4,
                findings=findings,
                total_cost=0.0124,
                duration_seconds=42.3,
            )

        monkeypatch.setattr("ai_pr_review.cli.run_review", fake_run_review)
        await backend.handle(_review_request())
        return published

    published = asyncio.run(run())
    completed = next(event for event in published if event["event"] == "review.completed")
    assert completed["run_id"] == "run-31"
    assert completed["finding_count"] == 4
    assert completed["files_reviewed"] == 18
    assert completed["files_skipped"] == 4
    assert completed["severity"] == {
        "critical": 1,
        "high": 1,
        "medium": 1,
        "low": 1,
        "info": 0,
    }
    assert completed["evidence"] == {
        "valid": 1,
        "needs_review": 1,
        "invalid": 1,
        "unverified": 1,
    }
    assert completed["cost"] == pytest.approx(0.0124)
    assert completed["duration_seconds"] == pytest.approx(42.3)

    # 未经过 validator 的 finding（缺 evidence_status）计入 unverified，而不是被丢掉
    from ai_pr_review.backend.jsonl_server import _review_completed_fields

    fallback = _review_completed_fields(
        {"findings": [{"severity": "high"}], "counts": {"by_severity": {"high": 1}}}
    )
    assert fallback["evidence"] == {
        "valid": 0,
        "needs_review": 0,
        "invalid": 0,
        "unverified": 1,
    }


def test_review_completed_carries_the_filtered_block(monkeypatch, tmp_path: Path) -> None:
    """契约 §3.7 加法扩展：事件带上报告 `run.filtered` 的同一份过滤披露。

    TUI 据此在实时审查的 0 findings 场景解释「候选被门槛过滤」，无需再取报告。
    """

    async def run() -> list[dict]:
        published: list[dict] = []
        backend = JsonlBackend(tmp_path / "config.json", event_sink=published.append)

        async def fake_run_review(pr_url, **kwargs):
            return _review_artifacts(
                filtered_findings={
                    "before": 6,
                    "after": 2,
                    "below_threshold": 4,
                    "duplicates": 0,
                    "threshold": 0.7,
                    "severity_sorted": True,
                }
            )

        monkeypatch.setattr("ai_pr_review.cli.run_review", fake_run_review)
        await backend.handle(_review_request())
        return published

    published = asyncio.run(run())
    completed = next(event for event in published if event["event"] == "review.completed")

    assert completed["filtered"] == {
        "threshold": 0.7,
        "below_threshold": 4,
        "duplicates": 0,
    }
    # 原有字段名与语义不变（加法式扩展）
    assert completed["run_id"] == "run-31"
    assert completed["finding_count"] == 0
    assert completed["files_reviewed"] == 2
    assert completed["files_skipped"] == 1
    assert completed["severity"] == {
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
        "info": 0,
    }
    assert completed["evidence"] == {
        "valid": 0,
        "needs_review": 0,
        "invalid": 0,
        "unverified": 0,
    }
    assert completed["cost"] == pytest.approx(0.0124)
    assert completed["duration_seconds"] == pytest.approx(42.3)


def test_review_completed_omits_filtered_when_the_run_recorded_nothing(
    monkeypatch, tmp_path: Path
) -> None:
    """没有过滤统计时事件不带 `filtered`，也不伪造 `below_threshold: 0`。"""

    async def run() -> list[dict]:
        published: list[dict] = []
        backend = JsonlBackend(tmp_path / "config.json", event_sink=published.append)

        async def fake_run_review(pr_url, **kwargs):
            return _review_artifacts()  # filtered_findings={}

        monkeypatch.setattr("ai_pr_review.cli.run_review", fake_run_review)
        await backend.handle(_review_request())
        return published

    completed = next(event for event in asyncio.run(run()) if event["event"] == "review.completed")
    assert "filtered" not in completed

    from ai_pr_review.backend.jsonl_server import _review_completed_fields

    # 直接喂坏形状的 run 段：不抛异常、不补 0，只是没有该键
    for report in (
        {},
        {"run": {}},
        {"run": {"filtered": "not-a-dict"}},
        {"run": {"filtered": {}}},
    ):
        assert "filtered" not in _review_completed_fields(report)


def test_history_report_carries_the_filtered_block_from_run_metadata(tmp_path: Path) -> None:
    """`/history <run_id>` 的报告也带 `run.filtered`（TUI 对历史 run 同样要解释 0 findings）。"""
    backend = JsonlBackend(tmp_path / "config.json")
    run_id = _save_publishable_run(
        backend,
        findings=0,
        metadata={
            "filtered_findings": {
                "before": 3,
                "after": 0,
                "below_threshold": 3,
                "duplicates": 0,
                "threshold": 0.85,
            }
        },
    )
    legacy_run_id = _save_publishable_run(backend, findings=0)

    async def run() -> tuple[dict, dict]:
        opened = await backend.handle(
            {
                "id": "1",
                "method": "command.execute",
                "params": {"name": "history", "args": [run_id]},
            }
        )
        legacy = await backend.handle(
            {
                "id": "2",
                "method": "command.execute",
                "params": {"name": "history", "args": [legacy_run_id]},
            }
        )
        return opened[0]["result"]["report"], legacy[0]["result"]["report"]

    report, legacy_report = asyncio.run(run())

    assert report["run"]["filtered"] == {
        "threshold": 0.85,
        "below_threshold": 3,
        "duplicates": 0,
    }
    # 旧 run 没有该 metadata：省略而不是编造
    assert "filtered" not in legacy_report["run"]


def test_review_model_routing_states_the_configured_policy(tmp_path: Path) -> None:
    backend = JsonlBackend(tmp_path / "config.json")

    backend.config.preferences.hybrid_strategy = "balanced"
    # 固定槽位，避免环境变量改写 Provider 后断言漂移
    backend.config.provider.name = "deepseek"
    backend.config.provider.default_model = "deepseek-chat"
    backend.config.local_provider.default_model = "qwen3.5:4b"
    hybrid = backend._review_routing()
    assert hybrid is not None
    assert hybrid["runtime_profile"] == backend.runtime_profile
    assert hybrid["router_model"] == "qwen3.5:4b"
    assert hybrid["deep_model"] == "deepseek-chat"
    assert hybrid["reason"]

    backend.config.preferences.hybrid_strategy = "remote_only"
    remote = backend._review_routing()
    assert remote is not None
    assert remote["router_model"] is None
    assert remote["deep_model"] == "deepseek-chat"

    backend.config.preferences.hybrid_strategy = "local_only"
    local = backend._review_routing()
    assert local is not None
    assert local["router_model"] is None
    assert local["deep_model"] == "qwen3.5:4b"


def test_review_model_routing_follows_the_ui_language(tmp_path: Path) -> None:
    backend = JsonlBackend(tmp_path / "config.json")
    backend.config.preferences.ui_language = "en-US"
    backend.config.preferences.hybrid_strategy = "balanced"
    backend.config.provider.name = "deepseek"
    backend.config.provider.default_model = "deepseek-chat"
    routing = backend._review_routing()
    assert routing is not None
    assert routing["reason"].startswith("Hybrid")


def test_review_model_routing_is_emitted_once_per_review(monkeypatch, tmp_path: Path) -> None:
    async def run() -> list[dict]:
        published: list[dict] = []
        backend = JsonlBackend(tmp_path / "config.json", event_sink=published.append)

        async def fake_run_review(pr_url, **kwargs):
            kwargs["stage_callback"]("fetching", "正在读取 PR 元数据与变更内容")
            kwargs["stage_callback"]("filtering", "共 3 个变更文件，正在过滤")
            return _review_artifacts()

        monkeypatch.setattr("ai_pr_review.cli.run_review", fake_run_review)
        await backend.handle(_review_request())
        return published

    published = asyncio.run(run())
    names = [event["event"] for event in published]
    assert names.count("review.model_routing") == 1
    # 路由必须在阶段开始前就已知，TUI 才能在审查进行中显示它
    assert names.index("review.model_routing") < names.index("review.stage")


def test_failed_review_marks_the_running_stage_failed(monkeypatch, tmp_path: Path) -> None:
    """契约 §3.3/§3.8：失败时 stage_done 带 failed + message，review.failed 带 stage_id。"""

    async def run() -> list[dict]:
        published: list[dict] = []
        backend = JsonlBackend(tmp_path / "config.json", event_sink=published.append)

        async def fake_run_review(pr_url, **kwargs):
            kwargs["stage_callback"]("reviewing", "开始逐文件审查（并发 2）")
            raise RuntimeError("模型供应商网络请求失败。")

        monkeypatch.setattr("ai_pr_review.cli.run_review", fake_run_review)
        responses = await backend.handle(_review_request())
        assert responses[0]["ok"] is False
        return published

    published = asyncio.run(run())
    stage_done = next(event for event in published if event["event"] == "review.stage_done")
    assert stage_done["stage_id"] == "reviewing"
    assert stage_done["status"] == "failed"
    assert stage_done["message"] == "模型供应商网络请求失败。"
    assert stage_done["duration_ms"] >= 0
    # 失败阶段不能把进度推到该阶段的完成值
    assert stage_done["progress"] == 70

    failed = next(event for event in published if event["event"] == "review.failed")
    assert failed["stage_id"] == "reviewing"
    assert failed["code"] == "backend_error"
    assert failed["recovery"]


def test_cancelled_review_marks_the_running_stage_skipped(monkeypatch, tmp_path: Path) -> None:
    """取消不是失败：阶段标记为 skipped，review.cancelled 带上 stage_id。"""

    async def run() -> list[dict]:
        from ai_pr_review.services.review_orchestrator import (
            ReviewCancelled as OrchestratorCancelled,
        )

        published: list[dict] = []
        backend = JsonlBackend(tmp_path / "config.json", event_sink=published.append)

        async def fake_run_review(pr_url, **kwargs):
            kwargs["stage_callback"]("reviewing", "开始逐文件审查（并发 2）")
            # 与 /cancel 命令一样，设置后端登记的取消句柄
            backend.review_cancellations["session-1"].set()
            assert kwargs["cancel_check"]() is True
            raise OrchestratorCancelled()

        monkeypatch.setattr("ai_pr_review.cli.run_review", fake_run_review)
        responses = await backend.handle(_review_request())
        assert responses[0]["result"]["cancelled"] is True
        return published

    published = asyncio.run(run())
    stage_done = next(event for event in published if event["event"] == "review.stage_done")
    assert stage_done["stage_id"] == "reviewing"
    assert stage_done["status"] == "skipped"
    assert "message" not in stage_done

    cancelled = next(event for event in published if event["event"] == "review.cancelled")
    assert cancelled["stage_id"] == "reviewing"
    assert "review.failed" not in [event["event"] for event in published]


def test_cancel_command_interrupts_a_review_that_is_inside_a_model_call(
    monkeypatch, tmp_path: Path
) -> None:
    """`/cancel` 必须打断正在飞的模型调用，出来的是 `review.cancelled` 而不是 failed。

    这里接的是**真实编排器** + 每个文件都睡 30s 的桩客户端：取消时文件已经进入
    模型调用，只有逐文件阶段的取消检查 + 任务取消能让它在 1 秒内结束。
    """
    from ai_pr_review.models.pr_data import FileDiff, FileStatus, PRData
    from ai_pr_review.services.context_builder import FileContext
    from ai_pr_review.services.filter_pipeline import FilterPipelineResult
    from ai_pr_review.services.prompt_assembler import ReviewResult
    from ai_pr_review.services.review_orchestrator import ReviewOrchestrator

    started: list[str] = []
    cancelled: list[str] = []
    saved: list[Any] = []

    class StubPRFetcher:
        def __init__(self, *args, **kwargs):
            pass

        def fetch(self, pr_url: str) -> PRData:
            return PRData(
                pr_number=31,
                title="Cancel in flight",
                description="",
                author="alice",
                state="open",
                head_sha="head123",
                base_sha="base123",
                head_ref="feature",
                base_ref="main",
                diff="diff",
                files=[
                    FileDiff(
                        filename=f"src/file_{index}.py",
                        status=FileStatus.MODIFIED,
                        additions=1,
                        deletions=0,
                        changes=1,
                        patch="@@ -1 +1 @@\n-old\n+new",
                    )
                    for index in range(4)
                ],
                url=pr_url,
                merged=False,
                owner="owner",
                repo="repo",
            )

        def fetch_file_content(self, owner, repo, file_path, ref) -> str:
            return "def run():\n    return True\n"

    class StubFilterPipeline:
        def __init__(self, *args, **kwargs):
            pass

        def filter_pr_data(self, pr_data: PRData):
            result = FilterPipelineResult()
            result.results = [
                type("FilterResult", (), {"file": file_diff, "included": True})()
                for file_diff in pr_data.files
            ]
            return pr_data, result

    class StubContextBuilder:
        def __init__(self, *args, **kwargs):
            pass

        def build_context(self, file_path: str, diff: str, full_content: str) -> FileContext:
            return FileContext(
                file_path=file_path,
                language="python",
                diff=diff,
                diff_with_context=diff,
                imports=[],
                functions=[],
                classes=[],
                parse_mode="regex",
            )

    class StubPromptAssembler:
        def __init__(self, *args, **kwargs):
            pass

        def build_system_prompt(self, language: str) -> str:
            return "system"

        def build_user_prompt(self, file_context: FileContext, review_plan=None) -> str:
            return file_context.file_path

    class SleepingAIClient:
        def __init__(self, *args, **kwargs):
            self.total_run_cost = 0.0

        async def review_code(self, system_prompt: str, user_prompt: str) -> ReviewResult:
            started.append(user_prompt)
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                # 底层调用真的被中止：真实 HTTP 客户端在这里断开连接。
                cancelled.append(user_prompt)
                raise
            return ReviewResult(summary=f"reviewed {user_prompt}", findings=[])

    class RecordingResultStore:
        def __init__(self, *args, **kwargs):
            pass

        def save_result(self, *args, **kwargs) -> str:
            saved.append((args, kwargs))
            return "run-should-not-exist"

    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.PRFetcher", StubPRFetcher)
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.FilterPipeline", StubFilterPipeline
    )
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.ContextBuilder", StubContextBuilder
    )
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.PromptAssembler", StubPromptAssembler
    )
    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.AIClient", SleepingAIClient)
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.ResultStore", RecordingResultStore
    )

    async def fake_run_review(
        pr_url,
        *,
        config,
        progress_console,
        stage_callback,
        progress_callback,
        file_done_callback,
        cancel_check=None,
        file_result_callback=None,
    ):
        """真实编排器，接后端透传下来的取消检查与回调（生产路径就是这样接的）。"""
        return await ReviewOrchestrator(config).review(
            pr_url,
            stage_callback=stage_callback,
            progress_callback=progress_callback,
            file_done_callback=file_done_callback,
            cancel_check=cancel_check,
            file_result_callback=file_result_callback,
        )

    monkeypatch.setattr("ai_pr_review.cli.run_review", fake_run_review)

    async def run() -> tuple[list[dict], list[dict], list[dict], float]:
        published: list[dict] = []
        backend = JsonlBackend(tmp_path / "config.json", event_sink=published.append)
        review_task = asyncio.create_task(backend.handle(_review_request()))
        # 等真的有文件进入模型调用再取消
        for _ in range(200):
            if started:
                break
            await asyncio.sleep(0.01)
        assert started, "取消前应当已经有文件在模型调用里"
        started_at = time.perf_counter()
        cancel_response = await backend.handle(
            {
                "id": "cancel",
                "method": "command.execute",
                "params": {"name": "cancel", "session_id": "session-1"},
            }
        )
        responses = await asyncio.wait_for(review_task, 5)
        return published, cancel_response, responses, time.perf_counter() - started_at

    published, cancel_response, responses, elapsed = asyncio.run(run())

    # 模型调用睡 30s：1 秒内结束只能是被取消打断的
    assert elapsed < 1.0, f"取消用了 {elapsed:.2f}s，说明还在等模型调用返回"
    # /cancel 命令本身如实报告"取消已生效"
    assert cancel_response[0]["result"]["cancelled"] is True
    # 审查命令返回取消语义，而不是失败
    assert responses[0]["result"]["cancelled"] is True
    events = [event["event"] for event in published]
    assert "review.file_started" in events, "取消前应当已经上报过文件开始"
    assert "review.cancelled" in events
    assert "review.failed" not in events
    assert "review.completed" not in events
    # 在飞的调用真的被中止了；取消后不落库、不为没有结论的文件报结果
    assert sorted(cancelled) == sorted(started)
    assert saved == []
    assert not [event for event in published if event["event"] == "review.file_done"]


def test_review_event_stream_drops_events_after_the_run_finished() -> None:
    """`gather` 不会取消同批文件任务，迟到的 file_done 不能落到已结束的审查上。"""
    from ai_pr_review.backend.jsonl_server import _ReviewEventStream

    published: list[dict] = []
    stream = _ReviewEventStream(published.append, "session-1")
    stream.started("https://github.com/example/repo/pull/31")
    stream.stage("fetching", "正在读取 PR 元数据与变更内容")
    stream.file_started("src/a.py")
    stream.complete()
    stream.file_done("src/a.py")
    stream.abort("failed", message="late")
    stream.stage("filtering", "共 3 个变更文件，正在过滤")

    assert [event["event"] for event in published] == [
        "review.started",
        "review.stage",
        "review.file_started",
        "review.stage_done",
    ]
    assert stream.finished is True


def test_review_event_stream_keeps_progress_for_unknown_stages() -> None:
    from ai_pr_review.backend.jsonl_server import _ReviewEventStream

    published: list[dict] = []
    stream = _ReviewEventStream(published.append, "session-1")
    stream.stage("fetching", "")
    stream.stage("mystery_stage", "")
    stream.complete()

    assert [event["event"] for event in published] == [
        "review.stage",
        "review.stage_done",
        "review.stage",
        "review.stage_done",
    ]
    assert published[2]["stage_id"] == "mystery_stage"
    assert published[2]["stage"] == "mystery_stage"
    # 未知阶段沿用上一个已到达的进度（此处为 fetching 的完成值），不会倒退
    assert published[2]["progress"] == published[1]["progress"]
    assert stream.stage_id_field() == {"stage_id": "mystery_stage"}


def test_local_chat_disables_reasoning_channel(monkeypatch, tmp_path: Path) -> None:
    from ai_pr_review.services.model_providers.base import ProviderResponse

    async def run() -> None:
        backend = JsonlBackend(tmp_path / "config.json", event_sink=lambda event: None)
        backend._apply_setup({"runtime_profile": "local", "local_model": "qwen3.5:4b"})
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        captured: dict[str, object] = {}

        class FakeProvider:
            async def stream_chat(self, messages, on_delta, **kwargs):
                captured.update(kwargs)
                await on_delta("本地模型正常")
                return ProviderResponse(text="本地模型正常")

        monkeypatch.setattr(
            "ai_pr_review.backend.jsonl_server.create_model_provider",
            lambda config: FakeProvider(),
        )
        response = await backend.handle(
            {
                "id": "turn",
                "method": "chat.send",
                "params": {"session_id": session["session_id"], "text": "你好"},
            }
        )

        assert response[0]["ok"] is True
        assert captured["reasoning_effort"] == "none"

    asyncio.run(run())


# ---------------------------------------------------------------------------
# explain / feedback 审查动作（docs/review-workspace-contract.md §10.3）
# ---------------------------------------------------------------------------


def _store_run(backend: JsonlBackend, **finding_kwargs: Any) -> str:
    """Persist a real run so explain/feedback read from the real ResultStore."""
    from ai_pr_review.services.prompt_assembler import ReviewResult
    from ai_pr_review.services.result_store import ResultStore

    finding = _finding(**finding_kwargs)
    finding.finding_id = "finding-abc123"
    finding.evidence_issues = ["行号与 diff 不一致"]
    finding.sources = ["static_rule", "ai_analysis"]
    run_id = ResultStore(backend.config.result_store).save_result(
        "https://github.com/example/repo/pull/31",
        ReviewResult(
            summary="审查完成，发现 1 个问题",
            findings=[finding],
        ),
        metadata={
            "language": {"ui_language": "zh-CN", "response_language": "zh-CN"},
        },
    )
    return run_id


def test_command_explain_returns_structured_findings_and_evidence(tmp_path: Path) -> None:
    """契约 §10.3：explain <run_id> 返回结构化 findings/证据说明。"""
    from ai_pr_review.services.result_store import ResultStore

    async def run() -> None:
        backend = JsonlBackend(tmp_path / "config.json")
        run_id = _store_run(backend, severity="critical", evidence_status="needs_review")

        response = await backend.handle(
            {
                "id": "1",
                "method": "command.execute",
                "params": {"name": "explain", "args": [run_id]},
            }
        )
        assert response[0]["ok"] is True
        payload = response[0]["result"]
        assert payload["run_id"] == run_id
        assert payload["findings"][0]["finding_id"] == "finding-abc123"
        assert payload["findings"][0]["evidence_status"] == "needs_review"
        assert payload["metadata"]["language"]["response_language"] == "zh-CN"
        text = payload["text"]
        assert "[CRITICAL] critical finding" in text
        assert "src/module_0.py:1-1" in text
        assert "static_rule, ai_analysis" in text
        assert "needs_review" in text
        assert "行号与 diff 不一致" in text
        assert "suggestion" in text
        # 不查库失败时不能返回半成品
        assert ResultStore(backend.config.result_store).get_result(run_id) is not None

    asyncio.run(run())


def test_command_explain_rejects_missing_and_unknown_run(tmp_path: Path) -> None:
    async def run() -> None:
        backend = JsonlBackend(tmp_path / "config.json")

        missing_args = await backend.handle(
            {"id": "1", "method": "command.execute", "params": {"name": "explain", "args": []}}
        )
        assert missing_args[0]["ok"] is False
        assert missing_args[0]["error"]["code"] == "invalid_request"
        assert "run_id" in missing_args[0]["error"]["message"]

        unknown = await backend.handle(
            {
                "id": "2",
                "method": "command.execute",
                "params": {"name": "explain", "args": ["no-such-run"]},
            }
        )
        assert unknown[0]["ok"] is False
        assert unknown[0]["error"]["code"] == "not_found"
        assert "no-such-run" in unknown[0]["error"]["message"]

    asyncio.run(run())


def test_command_feedback_persists_and_rejects_invalid_arguments(tmp_path: Path) -> None:
    """契约 §10.3：feedback 复用 ResultStore，非法 run/finding/status 给出明确错误。"""
    from ai_pr_review.services.result_store import ResultStore

    async def run() -> None:
        backend = JsonlBackend(tmp_path / "config.json")
        run_id = _store_run(backend)

        recorded = await backend.handle(
            {
                "id": "1",
                "method": "command.execute",
                "params": {
                    "name": "feedback",
                    "args": [run_id, "finding-abc123", "accepted", "确认是真实问题"],
                },
            }
        )
        assert recorded[0]["ok"] is True
        assert recorded[0]["result"]["status"] == "accepted"
        assert recorded[0]["result"]["note"] == "确认是真实问题"
        stored = ResultStore(backend.config.result_store).list_feedback(run_id)
        assert [(item["finding_id"], item["status"], item["note"]) for item in stored] == [
            ("finding-abc123", "accepted", "确认是真实问题")
        ]

        # 状态大小写无关，但非法值必须报错并列出可选值
        upper = await backend.handle(
            {
                "id": "2",
                "method": "command.execute",
                "params": {"name": "feedback", "args": [run_id, "finding-abc123", "FIXED"]},
            }
        )
        assert upper[0]["ok"] is True
        assert upper[0]["result"]["status"] == "fixed"

        bad_status = await backend.handle(
            {
                "id": "3",
                "method": "command.execute",
                "params": {"name": "feedback", "args": [run_id, "finding-abc123", "maybe"]},
            }
        )
        assert bad_status[0]["ok"] is False
        assert bad_status[0]["error"]["code"] == "invalid_request"
        assert "maybe" in bad_status[0]["error"]["message"]
        assert "needs_review" in bad_status[0]["error"]["message"]

        bad_run = await backend.handle(
            {
                "id": "4",
                "method": "command.execute",
                "params": {"name": "feedback", "args": ["no-such-run", "finding-abc123", "fixed"]},
            }
        )
        assert bad_run[0]["ok"] is False
        assert bad_run[0]["error"]["code"] == "not_found"
        assert "no-such-run" in bad_run[0]["error"]["message"]

        bad_finding = await backend.handle(
            {
                "id": "5",
                "method": "command.execute",
                "params": {"name": "feedback", "args": [run_id, "missing-finding", "fixed"]},
            }
        )
        assert bad_finding[0]["ok"] is False
        assert bad_finding[0]["error"]["code"] == "not_found"
        assert "missing-finding" in bad_finding[0]["error"]["message"]

        usage = await backend.handle(
            {
                "id": "6",
                "method": "command.execute",
                "params": {"name": "feedback", "args": [run_id, "finding-abc123"]},
            }
        )
        assert usage[0]["ok"] is False
        assert usage[0]["error"]["code"] == "invalid_request"
        assert "/feedback" in usage[0]["error"]["message"]

        # 非法参数不能留下任何反馈记录
        assert len(ResultStore(backend.config.result_store).list_feedback(run_id)) == 2

    asyncio.run(run())


def test_feedback_statuses_match_cli_choice_and_result_store(tmp_path: Path) -> None:
    """契约 §10.3：反馈状态必须与 CLI --status 选项、ResultStore 允许值一致。"""
    from ai_pr_review.backend.jsonl_server import FEEDBACK_STATUSES
    from ai_pr_review.cli import feedback_command
    from ai_pr_review.config import ResultStoreConfig
    from ai_pr_review.services.result_store import ResultStore

    status_option = next(param for param in feedback_command.params if param.name == "status")
    assert set(status_option.type.choices) == set(FEEDBACK_STATUSES)

    store = ResultStore(ResultStoreConfig(db_path=str(tmp_path / "results.db")))
    for status in sorted(FEEDBACK_STATUSES):
        # 每个允许值都必须被 store 接受
        store.save_feedback("run-x", "finding-x", status, "")
    with pytest.raises(ValueError):
        store.save_feedback("run-x", "finding-x", "definitely-not-a-status", "")


# ---------------------------------------------------------------------------
# §12.2 publish / §12.3 demo + showcase
# ---------------------------------------------------------------------------

PUBLISHED_PR_URL = "https://github.com/owner/repo/pull/31"


class _FakeGitHub:
    """Stands in for `PRFetcher`: records the comment instead of posting it."""

    def __init__(self) -> None:
        self.posted: list[str] = []
        self.targets: list[tuple[str, str, int]] = []
        self.fail_with: Exception | None = None

    def _get_pull_request(self, owner: str, repo: str, number: int) -> "_FakeGitHub":
        self.targets.append((owner, repo, number))
        return self

    def create_issue_comment(self, body: str) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.posted.append(body)


@pytest.fixture
def fake_github(monkeypatch: pytest.MonkeyPatch) -> _FakeGitHub:
    """Replace the GitHub client so a "publish" stays offline and observable."""
    import ai_pr_review.services.publish_service as publish_service

    fake = _FakeGitHub()
    monkeypatch.setattr(publish_service, "PRFetcher", lambda **kwargs: fake)
    return fake


def _reply(events: list[dict[str, Any]]) -> dict[str, Any]:
    return next(event for event in events if "ok" in event)


def _execute(
    backend: JsonlBackend,
    name: str,
    args: list[Any],
    session_id: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"name": name, "args": args}
    if session_id is not None:
        params["session_id"] = session_id
    return _reply(
        asyncio.run(backend.handle({"id": "cmd", "method": "command.execute", "params": params}))
    )


def _new_session(backend: JsonlBackend) -> str:
    events = asyncio.run(backend.handle({"id": "s", "method": "session.create", "params": {}}))
    return str(_reply(events)["result"]["session_id"])


def _offline_model_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """`model.status` 不许联网：换成没有 health_check / list_models 的桩。"""

    class OfflineProvider:
        """No health_check / list_models: model.status must not touch the network."""

    monkeypatch.setattr(
        "ai_pr_review.backend.jsonl_server.create_model_provider",
        lambda config: OfflineProvider(),
    )


def _save_publishable_run(
    backend: JsonlBackend,
    *,
    pr_url: str = PUBLISHED_PR_URL,
    findings: int = 2,
    metadata: dict[str, Any] | None = None,
    total_files: int = 4,
) -> str:
    from ai_pr_review.services.prompt_assembler import Finding, ReviewResult
    from ai_pr_review.services.result_store import ResultStore

    return ResultStore(backend.config.result_store).save_result(
        pr_url,
        ReviewResult(
            summary="stored summary",
            findings=[
                Finding(
                    severity="high",
                    category="security",
                    file=f"src/module_{index}.py",
                    line_start=index + 1,
                    line_end=index + 1,
                    title=f"stored finding {index}",
                    problem="problem",
                    suggestion="suggestion",
                    confidence=0.9,
                    code_snippet="x = 1",
                    evidence_status="valid",
                )
                for index in range(findings)
            ],
        ),
        head_sha="head-sha",
        total_files=total_files,
        included_files=2,
        excluded_files=1,
        metadata=metadata,
    )


def test_publish_preview_never_talks_to_github(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_github: _FakeGitHub
) -> None:
    """§12.2: preview is a local read — no PR lookup, no comment."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    backend = JsonlBackend(tmp_path / "config.json")
    run_id = _save_publishable_run(backend)
    session_id = _new_session(backend)

    reply = _execute(backend, "publish", [run_id], session_id)

    assert reply["ok"] is True
    payload = reply["result"]
    assert payload["status"] == "preview"
    assert payload["requires_confirmation"] is True
    assert payload["run_id"] == run_id
    assert payload["repository"] == "owner/repo"
    assert payload["pr_number"] == 31
    assert payload["url"] == PUBLISHED_PR_URL
    assert payload["findings"] == 2
    assert payload["comment_chars"] == len(payload["comment_body"])
    assert payload["already_published"] is False
    assert "owner/repo#31" in payload["text"]
    assert "/publish --confirm" in payload["text"]
    assert fake_github.posted == []
    assert fake_github.targets == []


def test_publish_confirm_posts_exactly_one_comment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_github: _FakeGitHub
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    backend = JsonlBackend(tmp_path / "config.json")
    run_id = _save_publishable_run(backend)
    session_id = _new_session(backend)

    preview = _execute(backend, "publish", [run_id], session_id)["result"]
    reply = _execute(backend, "publish", [run_id, "--confirm"], session_id)

    assert reply["ok"] is True
    payload = reply["result"]
    assert payload["status"] == "published"
    assert "requires_confirmation" not in payload
    assert payload["comment_body"] == preview["comment_body"]
    assert fake_github.targets == [("owner", "repo", 31)]
    assert fake_github.posted == [payload["comment_body"]]
    assert "owner/repo#31" in payload["text"]
    assert payload["already_published"] is False


def test_publish_without_run_id_uses_the_current_session_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_github: _FakeGitHub
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    backend = JsonlBackend(tmp_path / "config.json")
    run_id = _save_publishable_run(backend)
    session_id = _new_session(backend)

    _execute(backend, "history", [run_id], session_id)  # loads the report
    assert backend.current_report is not None

    reply = _execute(backend, "publish", [], session_id)

    assert reply["ok"] is True
    assert reply["result"]["run_id"] == run_id


def test_publish_without_a_report_is_invalid_request(tmp_path: Path) -> None:
    backend = JsonlBackend(tmp_path / "config.json")

    reply = _execute(backend, "publish", ["--confirm"])

    assert reply["ok"] is False
    assert reply["error"]["code"] == "invalid_request"
    assert "/review" in reply["error"]["message"]


def test_publish_requires_a_github_token(tmp_path: Path, fake_github: _FakeGitHub) -> None:
    backend = JsonlBackend(tmp_path / "config.json")
    run_id = _save_publishable_run(backend)

    for args in ([run_id, "--confirm"], [run_id]):
        reply = _execute(backend, "publish", args)
        assert reply["ok"] is False
        assert reply["error"]["code"] == "missing_credentials"
        assert "pr-review config" in reply["error"]["message"]
    assert fake_github.posted == []
    assert fake_github.targets == []


def test_publish_unknown_run_is_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_github: _FakeGitHub
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    backend = JsonlBackend(tmp_path / "config.json")

    reply = _execute(backend, "publish", ["does-not-exist", "--confirm"])

    assert reply["ok"] is False
    assert reply["error"]["code"] == "not_found"
    assert "does-not-exist" in reply["error"]["message"]
    assert fake_github.posted == []


def test_publish_rejects_a_run_whose_url_is_not_a_github_pr(tmp_path: Path) -> None:
    """`not_publishable` wins over a missing token — a token would not help."""
    backend = JsonlBackend(tmp_path / "config.json")
    run_id = _save_publishable_run(
        backend, pr_url="https://gitlab.com/owner/repo/-/merge_requests/31"
    )

    reply = _execute(backend, "publish", [run_id, "--confirm"])

    assert reply["ok"] is False
    assert reply["error"]["code"] == "not_publishable"
    assert "gitlab.com" in reply["error"]["message"]


def test_publish_api_failure_is_reported_and_never_marks_the_run_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_github: _FakeGitHub
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    backend = JsonlBackend(tmp_path / "config.json")
    run_id = _save_publishable_run(backend)
    session_id = _new_session(backend)
    fake_github.fail_with = RuntimeError("422 Validation Failed")

    reply = _execute(backend, "publish", [run_id, "--confirm"], session_id)

    assert reply["ok"] is False
    assert reply["error"]["code"] == "publish_failed"
    assert "422 Validation Failed" in reply["error"]["message"]
    assert fake_github.posted == []

    # A failed post must not enter the ledger: the retry is a first publish.
    fake_github.fail_with = None
    retry = _execute(backend, "publish", [run_id, "--confirm"], session_id)
    assert retry["ok"] is True
    assert retry["result"]["status"] == "published"
    assert retry["result"]["already_published"] is False


def test_repeat_publish_in_one_session_warns_and_posts_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_github: _FakeGitHub
) -> None:
    """§12.2: never silently skip, never claim success without posting."""
    from ai_pr_review.services.publish_service import REPEAT_PUBLISH_WARNING

    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    backend = JsonlBackend(tmp_path / "config.json")
    run_id = _save_publishable_run(backend)
    session_id = _new_session(backend)

    first = _execute(backend, "publish", [run_id, "--confirm"], session_id)["result"]
    second = _execute(backend, "publish", [run_id, "--confirm"], session_id)["result"]

    assert first["already_published"] is False
    assert second["already_published"] is True
    assert second["status"] == "published"
    assert REPEAT_PUBLISH_WARNING in second["text"]
    assert len(fake_github.posted) == 2

    # The preview says the same thing as the confirm step.
    preview = _execute(backend, "publish", [run_id], session_id)["result"]
    assert preview["already_published"] is True
    assert REPEAT_PUBLISH_WARNING in preview["text"]


def test_repeat_publish_warning_literal_stays_in_publish_text_not_comment_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_github: _FakeGitHub
) -> None:
    """§13.5 F：警告属发布预览/结果 text，不是 GitHub 评论正文；文案字面冻结。"""
    from ai_pr_review.services.publish_service import REPEAT_PUBLISH_WARNING

    # 字面冻结：常量被改写时本用例必须变红，而不是跟着常量一起绿。
    assert REPEAT_PUBLISH_WARNING == (
        "注意：该 Run 在本会话中已发布过一次，再次确认会再创建一条评论。"
    )

    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    backend = JsonlBackend(tmp_path / "config.json")
    run_id = _save_publishable_run(backend)
    session_id = _new_session(backend)

    first = _execute(backend, "publish", [run_id, "--confirm"], session_id)["result"]
    assert first["already_published"] is False
    assert REPEAT_PUBLISH_WARNING not in first["text"]
    assert REPEAT_PUBLISH_WARNING not in first["comment_body"]

    second = _execute(backend, "publish", [run_id, "--confirm"], session_id)["result"]
    assert second["already_published"] is True
    assert REPEAT_PUBLISH_WARNING in second["text"]
    assert REPEAT_PUBLISH_WARNING not in second["comment_body"]
    assert second["comment_body"] == first["comment_body"]

    preview = _execute(backend, "publish", [run_id], session_id)["result"]
    assert preview["already_published"] is True
    assert REPEAT_PUBLISH_WARNING in preview["text"]
    assert REPEAT_PUBLISH_WARNING not in preview["comment_body"]


def test_publish_ledger_is_per_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_github: _FakeGitHub
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    backend = JsonlBackend(tmp_path / "config.json")
    run_id = _save_publishable_run(backend)
    first_session = _new_session(backend)
    second_session = _new_session(backend)

    _execute(backend, "publish", [run_id, "--confirm"], first_session)
    other = _execute(backend, "publish", [run_id, "--confirm"], second_session)

    assert other["result"]["already_published"] is False
    assert backend.sessions[first_session].published_run_ids == {run_id}
    assert backend.sessions[second_session].published_run_ids == {run_id}


def test_publish_rejects_an_unknown_flag(tmp_path: Path) -> None:
    backend = JsonlBackend(tmp_path / "config.json")

    reply = _execute(backend, "publish", ["--force"])

    assert reply["ok"] is False
    assert reply["error"]["code"] == "invalid_request"
    assert "/publish" in reply["error"]["message"]


def test_publish_comment_is_regenerated_from_the_stored_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_github: _FakeGitHub
) -> None:
    """The body comes from `render_github_comment`, never from a stored string."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    backend = JsonlBackend(tmp_path / "config.json")
    run_id = _save_publishable_run(backend)
    session_id = _new_session(backend)

    body = _execute(backend, "publish", [run_id], session_id)["result"]["comment_body"]

    assert body.startswith("## 🤖")
    assert "stored summary" in body
    assert "stored finding 0" in body and "stored finding 1" in body
    # The file-count line uses the count the run recorded (total_files=4) — the
    # per-file list is gone from the database and must not read as 0.
    assert re.search(r"4\s*(个变更文件|files changed)", body)
    # v2 header carries provenance so a reader can find the run again.
    assert "run `" in body and "提交 `" in body


def test_publish_reports_the_stored_pr_title_and_never_invents_an_author(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_github: _FakeGitHub
) -> None:
    """§12.2: `pr_title` comes from metadata, the author is an honest placeholder."""
    from ai_pr_review.services.publish_service import UNKNOWN_PR_AUTHOR

    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    backend = JsonlBackend(tmp_path / "config.json")
    # The default template never prints the title/author, so use a template that
    # does — otherwise the placeholder rule would be unobservable.
    backend.config.report_renderer.github_comment_template = (
        "title={pr_title}|author={author}|files={files_changed}"
    )
    with_title = _save_publishable_run(
        backend, metadata={"pr_title": "Real stored title"}, total_files=7
    )
    without_title = _save_publishable_run(backend)  # run saved before pr_title existed

    titled_body = _execute(backend, "publish", [with_title])["result"]["comment_body"]
    historical_body = _execute(backend, "publish", [without_title])["result"]["comment_body"]

    assert titled_body == f"title=Real stored title|author={UNKNOWN_PR_AUTHOR}|files=7"
    assert historical_body == f"title=|author={UNKNOWN_PR_AUTHOR}|files=4"


def test_new_runs_record_the_pr_title_in_metadata(tmp_path: Path) -> None:
    """Newly saved runs must carry `pr_title` so a later publish is not blank."""
    from ai_pr_review.services.result_store import ResultStore

    backend = JsonlBackend(tmp_path / "config.json")
    run_id = _save_publishable_run(backend, metadata={"pr_title": "Add authentication"})

    metadata = ResultStore(backend.config.result_store).get_run_metadata(run_id)
    assert metadata["pr_title"] == "Add authentication"


def test_pr_author_metadata_survives_the_database_round_trip(tmp_path: Path) -> None:
    """P6：`pr_author` 与 `pr_title` 一样走 metadata JSON，历史库照旧可读。"""
    from ai_pr_review.services.result_store import ResultStore

    backend = JsonlBackend(tmp_path / "config.json")
    run_id = _save_publishable_run(backend, metadata={"pr_author": "alice"})

    metadata = ResultStore(backend.config.result_store).get_run_metadata(run_id)

    assert metadata["pr_author"] == "alice"


def test_publish_mentions_the_stored_pr_author(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_github: _FakeGitHub
) -> None:
    """新 Run 记下 pr_author 后，历史重新渲染的评论头部能看到 @作者。"""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    backend = JsonlBackend(tmp_path / "config.json")
    run_id = _save_publishable_run(backend, metadata={"pr_author": "alice"})
    session_id = _new_session(backend)

    body = _execute(backend, "publish", [run_id], session_id)["result"]["comment_body"]

    assert "@alice" in body


def test_publish_of_a_run_without_pr_author_never_mentions_an_unknown_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_github: _FakeGitHub
) -> None:
    """缺 metadata 的旧 Run 用占位符，但不能渲染成 @unknown——那是个不存在的用户名。"""
    from ai_pr_review.services.publish_service import UNKNOWN_PR_AUTHOR

    # 字面冻结：占位符被改写时本用例必须变红，而不是跟着常量一起绿。
    assert UNKNOWN_PR_AUTHOR == "unknown"

    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    backend = JsonlBackend(tmp_path / "config.json")
    run_id = _save_publishable_run(backend)
    session_id = _new_session(backend)

    body = _execute(backend, "publish", [run_id], session_id)["result"]["comment_body"]

    assert "@unknown" not in body
    assert "@alice" not in body


def test_publish_marks_the_stored_review_time_in_beijing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_github: _FakeGitHub
) -> None:
    """`created_at` 是 SQLite 的 UTC 时间却没有时区标记；发布必须转成**北京时间**。

    2026-09-27 用户实测反馈：UTC+8 的读者看到 06:39:28 会读成本地时间
    （实际发生在 14:39:28）——所以评论里统一渲染北京时间并显式标注。
    """
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    backend = JsonlBackend(tmp_path / "config.json")
    run_id = _save_publishable_run(backend)
    session_id = _new_session(backend)

    body = _execute(backend, "publish", [run_id], session_id)["result"]["comment_body"]

    assert re.search(r"审查于 \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} 北京时间", body)


def test_reviewed_at_formatter_converts_to_beijing_and_never_raises() -> None:
    """格式化规则本身：裸时间戳按 UTC 解释→转北京时间；带时区的按其偏移；坏值原样返回。"""
    from ai_pr_review.services.publish_service import format_reviewed_at

    # 裸时间戳（SQLite）按 UTC 解释 → +8 小时
    assert format_reviewed_at("2026-09-25 06:39:28") == "2026-09-25 14:39:28 北京时间"
    assert format_reviewed_at("2026-09-25T06:39:28Z") == "2026-09-25 14:39:28 北京时间"
    # 已带 +08:00 的时间本身就是北京时间：不重复偏移
    assert format_reviewed_at("2026-09-25T06:39:28+08:00") == "2026-09-25 06:39:28 北京时间"
    # 解析失败/缺失一律原样返回：坏数据不能让 /publish 崩，也不能被静默改写
    assert format_reviewed_at("not a timestamp") == "not a timestamp"
    assert format_reviewed_at(None) == ""
    assert format_reviewed_at("") == ""


def test_publish_keeps_an_unparseable_stored_time_verbatim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_github: _FakeGitHub
) -> None:
    """坏时间戳不能让发布失败：原样出现在评论里，读者看得见异常。"""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    backend = JsonlBackend(tmp_path / "config.json")
    run_id = _save_publishable_run(backend)
    with contextlib.closing(sqlite3.connect(backend.config.result_store.db_path)) as connection:
        connection.execute(
            "UPDATE runs SET created_at = ? WHERE id = ?", ("not a timestamp", run_id)
        )
        connection.commit()

    body = _execute(backend, "publish", [run_id])["result"]["comment_body"]

    assert "审查于 not a timestamp" in body


def test_fork_metadata_survives_the_database_round_trip(tmp_path: Path) -> None:
    """P6 §4.5：`fork` 写在 metadata JSON 里，不加数据库列，历史库照旧可读。"""
    from ai_pr_review.services.result_store import ResultStore

    backend = JsonlBackend(tmp_path / "config.json")
    stored = {"is_fork": True, "head_repo": "contributor/repo"}
    run_id = _save_publishable_run(backend, metadata={"fork": stored})

    metadata = ResultStore(backend.config.result_store).get_run_metadata(run_id)

    assert metadata["fork"] == stored


def test_publish_preview_links_a_fork_run_to_the_pr_files_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_github: _FakeGitHub
) -> None:
    """P6 §4.5：fork 的 head commit 不在 base 仓库，`blob/<sha>` 必然 404。"""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    backend = JsonlBackend(tmp_path / "config.json")
    fork_run = _save_publishable_run(
        backend, metadata={"fork": {"is_fork": True, "head_repo": "contributor/repo"}}
    )

    fork_body = _execute(backend, "publish", [fork_run])["result"]["comment_body"]

    assert "https://github.com/owner/repo/pull/31/files" in fork_body
    assert "/blob/head-sha/" not in fork_body
    assert fake_github.posted == []  # 预览不发帖


def test_publish_preview_links_a_fork_with_a_deleted_repository_to_the_pr_files_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_github: _FakeGitHub
) -> None:
    """fork 仓库被删除时只剩 is_fork=True，链接形式不能因此退回 blob。"""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    backend = JsonlBackend(tmp_path / "config.json")
    deleted_fork = _save_publishable_run(
        backend, metadata={"fork": {"is_fork": True, "head_repo": None}}
    )

    body = _execute(backend, "publish", [deleted_fork])["result"]["comment_body"]

    assert "https://github.com/owner/repo/pull/31/files" in body
    assert "/blob/head-sha/" not in body


def test_publish_preview_keeps_blob_links_for_a_same_repository_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_github: _FakeGitHub
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    backend = JsonlBackend(tmp_path / "config.json")
    same_repo_run = _save_publishable_run(
        backend, metadata={"fork": {"is_fork": False, "head_repo": "owner/repo"}}
    )

    body = _execute(backend, "publish", [same_repo_run])["result"]["comment_body"]

    assert "https://github.com/owner/repo/blob/head-sha/src/module_0.py" in body
    assert "/pull/31/files" not in body


def test_publish_preview_keeps_blob_links_for_a_run_without_fork_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_github: _FakeGitHub
) -> None:
    """字段加入之前保存的 Run 没有 `fork` 键：保持它当初的 blob 行为。"""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    backend = JsonlBackend(tmp_path / "config.json")
    historical_run = _save_publishable_run(backend)  # metadata=None

    body = _execute(backend, "publish", [historical_run])["result"]["comment_body"]

    assert "https://github.com/owner/repo/blob/head-sha/src/module_0.py" in body
    assert "/pull/31/files" not in body


# ---------------------------------------------------------------------------
# 评论审计行：门槛 / 被过滤条数（claude-p6-comment-filter-line）
# ---------------------------------------------------------------------------


def test_publish_discloses_the_post_process_filter_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_github: _FakeGitHub
) -> None:
    """run metadata 的 filtered_findings 落进评论 stats 块的最后一行。"""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    backend = JsonlBackend(tmp_path / "config.json")
    run_id = _save_publishable_run(
        backend,
        metadata={
            "filtered_findings": {
                "before": 3,
                "after": 2,
                "below_threshold": 1,
                "duplicates": 0,
                "severity_sorted": True,
            }
        },
    )
    session_id = _new_session(backend)

    body = _execute(backend, "publish", [run_id], session_id)["result"]["comment_body"]

    # included_files=2 / total_files=4；门槛取本次配置值（默认 0.6）。
    assert "> 已审查 2/4 个文件 · 置信度门槛 0.60 · 低于门槛过滤 1 条 · 去重 0 条" in body
    assert fake_github.posted == []  # 预览不发帖


def test_publish_explains_a_zero_finding_run_that_the_threshold_filtered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_github: _FakeGitHub
) -> None:
    """用户实测场景：候选全部低于门槛 → 评论 0 条，但读者要看得出这是过滤造成的。"""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    backend = JsonlBackend(tmp_path / "config.json")
    run_id = _save_publishable_run(
        backend,
        findings=0,
        metadata={
            "filtered_findings": {
                "before": 3,
                "after": 0,
                "below_threshold": 3,
                "duplicates": 0,
                "severity_sorted": True,
            }
        },
    )

    body = _execute(backend, "publish", [run_id])["result"]["comment_body"]

    assert "**0 个问题**" in body
    assert "> 已审查 2/4 个文件 · 置信度门槛 0.60 · 低于门槛过滤 3 条 · 去重 0 条" in body


def test_publish_uses_the_configured_threshold_for_a_recorded_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_github: _FakeGitHub
) -> None:
    """门槛不是写死的 0.6：评论显示的是这台机器上生效的配置值。"""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    backend = JsonlBackend(tmp_path / "config.json")
    backend.config.post_processor.confidence_threshold = 0.75
    run_id = _save_publishable_run(
        backend,
        metadata={"filtered_findings": {"below_threshold": 1, "duplicates": 0}},
    )

    body = _execute(backend, "publish", [run_id])["result"]["comment_body"]

    assert "置信度门槛 0.75" in body


def test_publish_prefers_the_threshold_recorded_by_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_github: _FakeGitHub
) -> None:
    """Run 自己记了门槛时, 评论显示当时的门槛, 而不是今天配置里的值。"""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    backend = JsonlBackend(tmp_path / "config.json")
    backend.config.post_processor.confidence_threshold = 0.75
    run_id = _save_publishable_run(
        backend,
        metadata={"filtered_findings": {"below_threshold": 2, "duplicates": 0, "threshold": 0.6}},
    )

    body = _execute(backend, "publish", [run_id])["result"]["comment_body"]

    assert "置信度门槛 0.60" in body
    assert "0.75" not in body


def test_publish_of_a_run_without_filter_metadata_keeps_the_audit_line_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_github: _FakeGitHub
) -> None:
    """字段加入之前保存的 Run 没有过滤数据：整行省略，不臆造 0 条被过滤。"""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    backend = JsonlBackend(tmp_path / "config.json")
    run_id = _save_publishable_run(backend)  # metadata=None

    body = _execute(backend, "publish", [run_id])["result"]["comment_body"]

    assert "置信度门槛" not in body
    assert "低于门槛过滤" not in body
    assert "去重" not in body


def test_publish_discloses_only_the_filter_counts_the_run_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_github: _FakeGitHub
) -> None:
    """只记了部分计数：只显示已有片段，没记录的那段不显示也不填 0。"""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    backend = JsonlBackend(tmp_path / "config.json")
    run_id = _save_publishable_run(
        backend,
        metadata={
            "filtered_findings": {
                "before": 3,
                "after": 1,
                "duplicates": 2,
                "severity_sorted": True,
            }
        },
    )

    body = _execute(backend, "publish", [run_id])["result"]["comment_body"]

    assert "> 已审查 2/4 个文件 · 置信度门槛 0.60 · 去重 2 条" in body
    assert "低于门槛过滤" not in body


def test_publish_tolerates_a_malformed_filter_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_github: _FakeGitHub
) -> None:
    """坏数据不能让 /publish 崩，也不能被读成「0 条被过滤」这种假事实。"""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    backend = JsonlBackend(tmp_path / "config.json")
    run_id = _save_publishable_run(backend, metadata={"filtered_findings": "not-a-dict"})

    body = _execute(backend, "publish", [run_id])["result"]["comment_body"]

    assert "置信度门槛" not in body
    assert "低于门槛过滤" not in body
    assert "去重" not in body


def test_demo_list_returns_case_keys_and_text(tmp_path: Path) -> None:
    backend = JsonlBackend(tmp_path / "config.json")

    reply = _execute(backend, "demo", ["list"])

    assert reply["ok"] is True
    cases = reply["result"]["cases"]
    assert [case["key"] for case in cases] == ["sql-injection", "tls-disabled", "clean-change"]
    assert all(case["title"] and case["description"] for case in cases)
    assert "sql-injection" in reply["result"]["text"]


def test_demo_case_payload_matches_the_cli_json_object(tmp_path: Path) -> None:
    """§12.3: the backend returns exactly what `--json-output` prints, plus text."""
    from ai_pr_review.services.demo_runner import demo_case_payload

    backend = JsonlBackend(tmp_path / "config.json")

    reply = _execute(backend, "demo", ["sql-injection"])

    assert reply["ok"] is True
    payload = reply["result"]
    assert "text" in payload and payload["text"]
    assert {key: value for key, value in payload.items() if key != "text"} == (
        demo_case_payload("sql-injection")
    )


def test_demo_defaults_to_the_sql_injection_case(tmp_path: Path) -> None:
    backend = JsonlBackend(tmp_path / "config.json")

    default = _execute(backend, "demo", [])["result"]
    explicit = _execute(backend, "demo", ["sql-injection"])["result"]

    assert default["case"]["key"] == "sql-injection"
    assert default == explicit


def test_demo_unknown_case_lists_the_available_keys(tmp_path: Path) -> None:
    backend = JsonlBackend(tmp_path / "config.json")

    reply = _execute(backend, "demo", ["nope"])

    assert reply["ok"] is False
    assert reply["error"]["code"] == "invalid_request"
    for key in ("sql-injection", "tls-disabled", "clean-change"):
        assert key in reply["error"]["message"]


def test_showcase_payload_matches_the_cli_json_object(tmp_path: Path) -> None:
    from ai_pr_review.services.showcase_runner import showcase_payload

    backend = JsonlBackend(tmp_path / "config.json")

    reply = _execute(backend, "showcase", [])

    assert reply["ok"] is True
    payload = reply["result"]
    assert "text" in payload and payload["text"]
    assert {key: value for key, value in payload.items() if key != "text"} == (
        showcase_payload(backend.config)
    )


def test_demo_and_showcase_commands_are_strictly_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§12.3: no model call, no GitHub call, no writes."""
    import ai_pr_review.services.model_providers.factory as factory_module
    import ai_pr_review.services.pr_fetcher as pr_fetcher_module
    import ai_pr_review.services.publish_service as publish_service

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("offline command built a network client")

    monkeypatch.setattr(pr_fetcher_module, "PRFetcher", _explode)
    monkeypatch.setattr(publish_service, "PRFetcher", _explode)
    monkeypatch.setattr(factory_module, "create_model_provider", _explode)

    backend = JsonlBackend(tmp_path / "config.json")
    store_path = Path(backend.config.result_store.db_path)
    before = {path.name for path in tmp_path.iterdir()}

    for args in (["list"], ["sql-injection"], []):
        assert _execute(backend, "demo", args)["ok"] is True
    assert _execute(backend, "showcase", [])["ok"] is True

    # Nothing was written, and no history database appeared.
    assert {path.name for path in tmp_path.iterdir()} == before
    assert not store_path.exists()


# ---------------------------------------------------------------------------
# CHAT/REVIEW 双槽路由（docs/dual-model-roles-plan.md §5.1 / §5.4）
# ---------------------------------------------------------------------------


def _chat_send(session_id: str, text: str = "你好") -> dict[str, Any]:
    return {
        "id": "turn",
        "method": "chat.send",
        "params": {"session_id": session_id, "text": text},
    }


def _stub_provider(monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]) -> None:
    """把 create_model_provider 换成 stub，并记下它收到的 provider 配置。"""
    from ai_pr_review.services.model_providers.base import ProviderResponse

    class FakeProvider:
        async def stream_chat(self, messages, on_delta, **kwargs):
            captured["options"] = kwargs
            await on_delta("stub")
            return ProviderResponse(text="stub")

    def factory(config):
        captured["config"] = config
        return FakeProvider()

    monkeypatch.setattr("ai_pr_review.backend.jsonl_server.create_model_provider", factory)


def test_chat_uses_the_local_slot_provider_when_chat_slot_is_local(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """方案 §5.1 #4：聊天按 `resolve_chat_slot` 选槽，不再固定跟"活跃槽"。

    这里刻意让活跃槽（`ai_client`，跟随 hybrid_strategy=remote_only）停在远端：
    聊天仍必须走 `local_provider`，否则"聊本地、审云端"这个组合根本无法配置。
    """

    async def run() -> None:
        backend = JsonlBackend(tmp_path / "config.json", event_sink=lambda event: None)
        backend._apply_setup(
            {"runtime_profile": "custom", "chat_slot": "local", "review_slot": "remote"}
        )
        # 活跃槽（ai_client）此刻停在远端——这正是本用例要制造的分歧：
        # 聊天若还跟着 ai_client 走就会选中下面那个远端模型。
        assert backend.config.ai_client.model_provider.name == backend.config.provider.name
        assert backend.config.ai_client.model_provider.name != "ollama"
        backend.config.provider.default_model = "remote-slot-model"
        backend.config.local_provider.default_model = "local-slot-model"
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        response = await backend.handle(_chat_send(session["session_id"]))

        assert response[0]["ok"] is True
        selected = captured["config"]
        assert selected.name == "ollama"
        assert selected.model_name == "local-slot-model"
        assert selected.base_url == backend.config.local_provider.base_url
        assert selected.api_format == backend.config.local_provider.api_format
        # 本地槽沿用既有的"关掉思考通道"处理。
        assert captured["options"]["reasoning_effort"] == "none"

    asyncio.run(run())


def test_chat_uses_the_remote_slot_provider_when_chat_slot_is_remote(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """反向：活跃槽是本地（review_slot=local -> local_only）时，聊天仍要打远端。"""

    async def run() -> None:
        backend = JsonlBackend(tmp_path / "config.json", event_sink=lambda event: None)
        backend._apply_setup(
            {"runtime_profile": "custom", "chat_slot": "remote", "review_slot": "local"}
        )
        # 活跃槽此刻是本地（local_only）：聊天若跟着 ai_client 走就会选中本地模型。
        assert backend.config.ai_client.model_provider.name == "ollama"
        backend.config.provider.default_model = "remote-slot-model"
        backend.config.local_provider.default_model = "local-slot-model"
        backend.config.provider.api_key = "test-key"
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        response = await backend.handle(_chat_send(session["session_id"]))

        assert response[0]["ok"] is True
        selected = captured["config"]
        assert selected.name == backend.config.provider.name
        assert selected.name != "ollama"
        assert selected.model_name == "remote-slot-model"
        assert selected.api_key == "test-key"
        assert "reasoning_effort" not in captured["options"]

    asyncio.run(run())


def test_chat_without_a_key_on_the_remote_slot_is_a_missing_api_key(tmp_path: Path) -> None:
    """远端槽缺 Key 时报 `missing_api_key`，绝不静默回退到已配置好的本地槽。"""

    async def run() -> None:
        backend = JsonlBackend(tmp_path / "config.json", event_sink=lambda event: None)
        backend._apply_setup(
            {"runtime_profile": "custom", "chat_slot": "remote", "review_slot": "local"}
        )
        backend.config.provider.api_key = ""
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]

        response = await backend.handle(_chat_send(session["session_id"]))

        # 协议边界不抛异常：`_chat` 里的 RuntimeError 经 _classify_error 变成事件。
        assert response[0]["ok"] is False
        assert response[0]["error"]["code"] == "missing_api_key"
        assert (
            f"Missing API key for provider: {backend.config.provider.name}"
            in response[0]["error"]["message"]
        )
        # 失败的聊天不能把会话留在"繁忙"状态（否则后续每次聊天都被拒）。
        assert backend.chat_cancellations == {}

    asyncio.run(run())


@pytest.mark.parametrize(
    ("review_slot", "strategy"),
    [("remote", "remote_only"), ("local", "local_only"), ("hybrid", "balanced")],
)
def test_custom_setup_writes_slots_and_folds_hybrid_strategy(
    review_slot: str, strategy: str, tmp_path: Path
) -> None:
    """方案 §3.2/§4.2：custom 写两个槽位，并把 review_slot 折算回 hybrid_strategy。"""
    from ai_pr_review.config import AppConfig

    config_path = tmp_path / "config.json"
    backend = JsonlBackend(config_path)

    snapshot = backend._apply_setup(
        {"runtime_profile": "custom", "chat_slot": "local", "review_slot": review_slot}
    )

    assert snapshot["routing"]["profile"] == "custom"
    assert snapshot["routing"]["review"]["slot"] == review_slot
    assert backend.config.preferences.hybrid_strategy == strategy

    reloaded = AppConfig.load(config_path)
    assert reloaded.preferences.chat_slot == "local"
    assert reloaded.preferences.review_slot == review_slot
    assert reloaded.preferences.hybrid_strategy == strategy


def test_custom_setup_keeps_the_slot_it_was_not_given(tmp_path: Path) -> None:
    """部分更新：载荷里的槽位覆盖旧值，没提到的槽位保持已落盘的选择。"""
    backend = JsonlBackend(tmp_path / "config.json")
    backend._apply_setup({"runtime_profile": "local", "local_model": "qwen3.5:4b"})
    assert backend.config.preferences.hybrid_strategy == "local_only"

    # 只传 review_slot：chat_slot 保持空（= 跟随预设）。
    backend._apply_setup({"runtime_profile": "custom", "review_slot": "remote"})
    assert backend.config.preferences.review_slot == "remote"
    assert backend.config.preferences.chat_slot == ""
    assert backend.config.preferences.hybrid_strategy == "remote_only"

    # 反过来只传 chat_slot：review_slot 必须留在上一次的值。
    backend._apply_setup({"runtime_profile": "custom", "chat_slot": "local"})
    assert backend.config.preferences.chat_slot == "local"
    assert backend.config.preferences.review_slot == "remote"
    assert backend.config.preferences.hybrid_strategy == "remote_only"

    # 显式空串 = 清除该槽覆盖，重新跟随预设（与 config 层的 "" 语义一致）。
    backend._apply_setup({"runtime_profile": "custom", "chat_slot": ""})
    assert backend.config.preferences.chat_slot == ""
    assert backend.config.preferences.review_slot == "remote"


def test_custom_setup_rejects_invalid_slots_and_writes_nothing(tmp_path: Path) -> None:
    from ai_pr_review.config import ConfigValidationError

    config_path = tmp_path / "config.json"
    backend = JsonlBackend(config_path)

    with pytest.raises(ConfigValidationError, match="对话模型槽位仅支持 remote 或 local"):
        backend._apply_setup({"runtime_profile": "custom", "chat_slot": "cloud"})
    with pytest.raises(ConfigValidationError, match="审查模型槽位仅支持 remote、local 或 hybrid"):
        backend._apply_setup({"runtime_profile": "custom", "review_slot": "balanced"})
    # hybrid 只属于审查槽：聊天没有"按复杂度分流"这一档。
    with pytest.raises(ConfigValidationError, match="对话模型槽位"):
        backend._apply_setup({"runtime_profile": "custom", "chat_slot": "hybrid"})

    # 校验失败必须整单失败：磁盘和内存里都不能留下半套配置。
    assert config_path.exists() is False
    assert backend.config.preferences.chat_slot == ""
    assert backend.config.preferences.review_slot == ""


def test_switching_to_a_preset_clears_both_slot_overrides(tmp_path: Path) -> None:
    """方案 §4.1：预设是唯一事实来源，选预设必须清掉上一次的槽位覆盖。"""
    from ai_pr_review.config import AppConfig

    config_path = tmp_path / "config.json"
    backend = JsonlBackend(config_path)
    backend._apply_setup(
        {"runtime_profile": "custom", "chat_slot": "local", "review_slot": "hybrid"}
    )
    assert AppConfig.load(config_path).preferences.chat_slot == "local"

    snapshot = backend._apply_setup(
        {
            "runtime_profile": "cloud",
            "provider_name": "deepseek",
            "api_key": "sk-test-not-real",
            "model_name": "deepseek-flash",
            # 预设载荷即使带了槽位也必须被清空（旧载荷根本不带这两个字段）。
            "chat_slot": "local",
            "review_slot": "local",
        }
    )

    assert backend.config.preferences.chat_slot == ""
    assert backend.config.preferences.review_slot == ""
    reloaded = AppConfig.load(config_path)
    assert (reloaded.preferences.chat_slot, reloaded.preferences.review_slot) == ("", "")
    assert snapshot["routing"] == {
        "profile": "cloud",
        "chat": {"slot": "remote", "label": "云端", "model": "deepseek-flash"},
        "review": {"slot": "remote", "label": "云端", "model": "deepseek-flash"},
    }


def test_config_options_expose_routing_and_the_custom_preset(tmp_path: Path) -> None:
    """方案 §4.1/§5.4：选项里必须能拿到"用哪一档预设"和两个槽各自的模型。"""
    backend = JsonlBackend(tmp_path / "config.json")
    backend.config.provider.default_model = "remote-model"
    backend.config.local_provider.default_model = "local-model"

    options = backend._setup_options()
    profiles = {item["value"]: item["label"] for item in options["runtime_profiles"]}
    assert profiles["custom"] == "自定义"
    assert {"cloud", "local", "hybrid"} <= set(profiles)
    # 默认预设是 balanced（= hybrid），两个槽都还没有显式覆盖。
    assert options["routing"] == {
        "profile": "hybrid",
        "chat": {"slot": "remote", "label": "云端", "model": "remote-model"},
        "review": {"slot": "hybrid", "label": "混合", "model": "remote-model"},
    }

    backend._apply_setup(
        {"runtime_profile": "custom", "chat_slot": "local", "review_slot": "local"}
    )
    custom = backend._setup_options()["routing"]
    assert custom == {
        "profile": "custom",
        "chat": {"slot": "local", "label": "本地", "model": "local-model"},
        "review": {"slot": "local", "label": "本地", "model": "local-model"},
    }


def test_config_and_model_snapshots_carry_routing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """方案 §5.4：三个协议出口都带 routing，且既有字段一个都不改名、不删除。"""

    async def run() -> None:
        backend = JsonlBackend(tmp_path / "config.json", event_sink=lambda event: None)
        backend.config.provider.default_model = "remote-model"
        backend.config.local_provider.default_model = "local-model"
        backend.config.provider.api_key = "test-key"
        backend._apply_setup(
            {"runtime_profile": "custom", "chat_slot": "local", "review_slot": "remote"}
        )

        class OfflineProvider:
            """No health_check / list_models: model.status must not touch the network."""

        monkeypatch.setattr(
            "ai_pr_review.backend.jsonl_server.create_model_provider",
            lambda config: OfflineProvider(),
        )

        snapshot = (await backend.handle({"id": "1", "method": "config.snapshot", "params": {}}))[
            0
        ]["result"]
        expected = {
            "profile": "custom",
            "chat": {"slot": "local", "label": "本地", "model": "local-model"},
            "review": {"slot": "remote", "label": "云端", "model": "remote-model"},
        }
        assert snapshot["routing"] == expected
        # 既有字段仍然描述"活跃槽"（review_slot=remote -> remote_only -> 远端），
        # 而 routing 才是两个槽各自的真相。
        assert snapshot["provider"] == backend.config.provider.name
        assert snapshot["provider"] != "ollama"
        assert snapshot["model"] == "remote-model"
        assert snapshot["runtime_profile"] == "cloud"

        options = (await backend.handle({"id": "2", "method": "config.options", "params": {}}))[0][
            "result"
        ]
        assert options["routing"] == expected

        status = (await backend.handle({"id": "3", "method": "model.status", "params": {}}))[0][
            "result"
        ]
        assert status["routing"] == expected
        # 顶层字段与 model.apply 写入的对象保持一致（仍是活跃槽）。
        assert status["model"] == "remote-model"

    asyncio.run(run())


def test_env_provider_override_keeps_chat_on_the_overridden_primary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`AI_PR_REVIEW_PROVIDER` 要求"本进程用云端"：聊天也必须跟随，不能被本地槽吃掉。

    这条路径改造前是由 `ai_client` 兜住的（既有用例
    `test_provider_env_override_rebuilds_endpoint_and_model` 只断言到配置层）。
    """
    config_path = tmp_path / "config.json"
    backend = JsonlBackend(config_path)
    backend._apply_runtime_profile("local")  # 落盘 hybrid_strategy=local_only
    monkeypatch.setenv("AI_PR_REVIEW_PROVIDER", "deepseek")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    async def run() -> None:
        restarted = JsonlBackend(config_path, event_sink=lambda event: None)
        assert restarted.config.provider.name == "deepseek"
        restarted.config.provider.api_key = "test-key"
        session = (await restarted.handle({"id": "s", "method": "session.create"}))[0]["result"]
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        response = await restarted.handle(_chat_send(session["session_id"]))

        assert response[0]["ok"] is True
        assert captured["config"].name == "deepseek"
        assert captured["config"].name != "ollama"
        # 云端 provider 不能因为"选的是本地槽"而被塞 reasoning_effort。
        assert "reasoning_effort" not in captured["options"]

    asyncio.run(run())


def test_local_chat_slot_keeps_a_primary_ollama_endpoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """主 Provider 自己就是 Ollama 时，"本地槽"就是主槽：自定义端点/模型不能丢。"""

    async def run() -> None:
        backend = JsonlBackend(tmp_path / "config.json", event_sink=lambda event: None)
        backend.config.provider.name = "ollama"
        backend.config.provider.base_url = "http://127.0.0.1:9999/v1"
        backend.config.provider.default_model = "primary-ollama-model"
        backend.config.preferences.hybrid_strategy = "local_only"
        backend.config._sync_runtime_sections()
        # 两个槽的端点确实不同，否则这条用例分辨不出选错槽。
        assert backend.config.local_provider.base_url != backend.config.provider.base_url
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        response = await backend.handle(_chat_send(session["session_id"]))

        assert response[0]["ok"] is True
        assert captured["config"].base_url == "http://127.0.0.1:9999/v1"
        assert captured["config"].model_name == "primary-ollama-model"

    asyncio.run(run())


def test_runtime_switch_clears_the_slot_overrides(tmp_path: Path) -> None:
    """`/model cloud|local|hybrid|offline` 与配置助手的预设一样，必须清掉槽位覆盖。"""
    backend = JsonlBackend(tmp_path / "config.json")
    backend._apply_setup(
        {"runtime_profile": "custom", "chat_slot": "local", "review_slot": "local"}
    )
    assert backend.config.preferences.review_slot == "local"
    backend.config.provider.api_key = "test-key"

    snapshot = backend._apply_runtime_profile("cloud")

    assert backend.config.preferences.chat_slot == ""
    assert backend.config.preferences.review_slot == ""
    # 否则 routing.review 会宣称"本地"，而实际生效的审查策略是 remote_only。
    assert snapshot["routing"]["profile"] == "cloud"
    assert snapshot["routing"]["review"]["slot"] == "remote"


# ---------------------------------------------------------------------------
# 仓库上下文配置助手（docs/repo-aware-review-plan.md §4.6）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["off", "tests", "tests+imports"])
def test_config_setup_persists_each_repo_context_mode(mode: str, tmp_path: Path) -> None:
    """三态都要能写进配置并落盘；配置助手不再需要手工改配置文件。"""
    from ai_pr_review.config import AppConfig

    config_path = tmp_path / "config.json"
    backend = JsonlBackend(config_path)

    snapshot = backend._apply_setup({"runtime_profile": "local", "repo_context": mode})

    assert backend.config.preferences.repo_context == mode
    # config.snapshot 里是纯值（与 workbench_mode 等偏好一致）；
    # `{"value", "options"}` 那种带可选值的形状只在 config.options / model.status。
    assert snapshot["repo_context"] == mode
    assert backend._setup_options()["repo_context"]["value"] == mode
    assert AppConfig.load(config_path).preferences.repo_context == mode


def test_config_setup_rejects_an_invalid_repo_context_and_writes_nothing(tmp_path: Path) -> None:
    """向导里的选择非法必须报错整单失败，而不是像加载配置那样静默回退。"""
    from ai_pr_review.config import AppConfig, ConfigValidationError

    config_path = tmp_path / "config.json"
    backend = JsonlBackend(config_path)
    backend._apply_setup({"runtime_profile": "local", "repo_context": "tests"})

    with pytest.raises(ConfigValidationError) as excinfo:
        backend._apply_setup({"runtime_profile": "local", "repo_context": "everything"})

    message = str(excinfo.value)
    assert "仓库上下文仅支持" in message
    assert "repo_context accepts off, tests or tests+imports" in message
    # 内存与磁盘都保持上一次的合法值。
    assert backend.config.preferences.repo_context == "tests"
    assert AppConfig.load(config_path).preferences.repo_context == "tests"


def test_config_setup_without_repo_context_keeps_the_stored_value(tmp_path: Path) -> None:
    """部分更新：载荷不带该字段（旧 TUI 载荷）时保持已落盘的值，不重置成默认。"""
    from ai_pr_review.config import AppConfig

    config_path = tmp_path / "config.json"
    backend = JsonlBackend(config_path)
    backend._apply_setup({"runtime_profile": "local", "repo_context": "off"})

    backend._apply_setup({"runtime_profile": "local", "local_model": "qwen3.5:4b"})

    assert backend.config.preferences.repo_context == "off"
    assert AppConfig.load(config_path).preferences.repo_context == "off"


def test_config_options_and_model_status_expose_repo_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`config.options` 与 `model.status` 同键同形，取值清单来自 config.REPO_CONTEXT_MODES。"""
    from ai_pr_review.config import REPO_CONTEXT_MODES

    _offline_model_provider(monkeypatch)
    backend = JsonlBackend(tmp_path / "config.json")

    options = backend._setup_options()["repo_context"]
    assert options["value"] == "tests+imports"  # 默认档位
    assert [item["value"] for item in options["options"]] == list(REPO_CONTEXT_MODES)
    assert all(item["label"] for item in options["options"])

    backend._apply_setup({"runtime_profile": "local", "repo_context": "tests"})

    assert backend._setup_options()["repo_context"]["value"] == "tests"
    status = _execute(backend, "model", ["status"])["result"]["status"]
    assert status["repo_context"] == backend._setup_options()["repo_context"]
    assert status["repo_context"]["value"] == "tests"


# ---------------------------------------------------------------------------
# L2 符号定位开关的配置入口（docs/mimo-l2-symbol-locator.md）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (False, False),
        (True, True),
        (0, False),
        (1, True),
        ("off", False),
        ("on", True),
        (" FALSE ", False),
        ("True", True),
    ],
)
def test_config_setup_persists_symbol_locate(raw: Any, expected: bool, tmp_path: Path) -> None:
    """布尔与 config 层接受的字符串/数字写法都要能落盘，回显随值变化。"""
    from ai_pr_review.config import AppConfig

    config_path = tmp_path / "config.json"
    backend = JsonlBackend(config_path)

    backend._apply_setup({"runtime_profile": "local", "symbol_locate": raw})

    assert backend.config.preferences.symbol_locate is expected
    assert backend._setup_options()["symbol_locate"]["value"] is expected
    assert AppConfig.load(config_path).preferences.symbol_locate is expected


def test_config_setup_symbol_locate_does_not_touch_other_preferences(tmp_path: Path) -> None:
    """开关是加法式的：同一次提交里的既有偏好一个都不改。"""
    config_path = tmp_path / "config.json"
    backend = JsonlBackend(config_path)
    backend._apply_setup({"runtime_profile": "local", "repo_context": "tests"})

    snapshot = backend._apply_setup({"runtime_profile": "local", "symbol_locate": False})

    assert snapshot["repo_context"] == "tests"
    assert snapshot["workbench_mode"] == "auto"
    assert snapshot["chat_layout"] == "compact"
    assert backend.config.preferences.symbol_locate is False


@pytest.mark.parametrize("raw", ["maybe", "yes please", "tru", "", 2, -1, 2.0, [], {}])
def test_config_setup_rejects_an_invalid_symbol_locate_and_writes_nothing(
    raw: Any, tmp_path: Path
) -> None:
    """非法开关值整单失败：既不像加载配置那样静默回退成 true，也不能悄悄写成别的值。

    （`""` 也在非法之列：对布尔开关来说"部分更新"的写法是**不传**或传 `null`，
    空串是发送方的真实错误，静默当 `true` 会把一个坏载荷变成"看起来成功"。）
    """
    from ai_pr_review.config import AppConfig, ConfigValidationError

    config_path = tmp_path / "config.json"
    backend = JsonlBackend(config_path)
    backend._apply_setup({"runtime_profile": "local", "symbol_locate": False})

    with pytest.raises(ConfigValidationError) as excinfo:
        backend._apply_setup({"runtime_profile": "local", "symbol_locate": raw})

    message = str(excinfo.value)
    assert "符号定位仅支持" in message
    assert "symbol_locate accepts true or false" in message
    # 内存与磁盘都保持上一次的合法值。
    assert backend.config.preferences.symbol_locate is False
    assert AppConfig.load(config_path).preferences.symbol_locate is False


@pytest.mark.parametrize(
    "payload",
    [
        {"runtime_profile": "local", "local_model": "qwen3.5:4b"},
        {"runtime_profile": "local", "symbol_locate": None},
    ],
)
def test_config_setup_without_symbol_locate_keeps_the_stored_value(
    payload: dict[str, Any], tmp_path: Path
) -> None:
    """部分更新：字段缺失或为 `null` 时保持已落盘的值，不重置成默认的 true。"""
    from ai_pr_review.config import AppConfig

    config_path = tmp_path / "config.json"
    backend = JsonlBackend(config_path)
    backend._apply_setup({"runtime_profile": "local", "symbol_locate": False})

    backend._apply_setup(payload)

    assert backend.config.preferences.symbol_locate is False
    assert AppConfig.load(config_path).preferences.symbol_locate is False


def test_config_options_and_model_status_expose_symbol_locate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`config.options` 与 `model.status` 同键同形；默认为开启，关掉后两处同步。"""
    _offline_model_provider(monkeypatch)
    backend = JsonlBackend(tmp_path / "config.json")

    options = backend._setup_options()["symbol_locate"]
    assert options["value"] is True  # 默认开启（config.DEFAULT_SYMBOL_LOCATE）
    assert [item["value"] for item in options["options"]] == [True, False]
    assert all(item["label"] for item in options["options"])

    backend._apply_setup({"runtime_profile": "local", "symbol_locate": False})

    assert backend._setup_options()["symbol_locate"]["value"] is False
    status = _execute(backend, "model", ["status"])["result"]["status"]
    assert status["symbol_locate"] == backend._setup_options()["symbol_locate"]
    assert status["symbol_locate"]["value"] is False


def test_protocol_config_options_and_setup_carry_symbol_locate(tmp_path: Path) -> None:
    """协议层：`config.options` 暴露开关，`config.setup` 接受布尔与字符串写法，非法值返回错误事件。"""
    backend = JsonlBackend(tmp_path / "config.json")

    options = asyncio.run(backend.handle({"id": "1", "method": "config.options", "params": {}}))[0]
    assert options["ok"] is True
    assert options["result"]["symbol_locate"]["value"] is True
    assert [item["value"] for item in options["result"]["symbol_locate"]["options"]] == [
        True,
        False,
    ]
    # 加法式扩展：既有出口一个都没被挤掉。
    assert options["result"]["repo_context"]["value"] == "tests+imports"
    assert options["result"]["current"]["workbench_mode"] == "auto"

    disabled = asyncio.run(
        backend.handle(
            {
                "id": "2",
                "method": "config.setup",
                "params": {"runtime_profile": "local", "symbol_locate": False},
            }
        )
    )[0]
    assert disabled["ok"] is True
    assert backend.config.preferences.symbol_locate is False

    enabled = asyncio.run(
        backend.handle(
            {
                "id": "3",
                "method": "config.setup",
                "params": {"runtime_profile": "local", "symbol_locate": "on"},
            }
        )
    )[0]
    assert enabled["ok"] is True
    assert backend.config.preferences.symbol_locate is True

    # 非法值经协议边界返回错误事件而不是抛穿（沿用既有错误映射），且不改内存。
    rejected = asyncio.run(
        backend.handle(
            {
                "id": "4",
                "method": "config.setup",
                "params": {"runtime_profile": "local", "symbol_locate": "sometimes"},
            }
        )
    )[0]
    assert rejected["ok"] is False
    assert "符号定位仅支持" in rejected["error"]["message"]
    assert backend.config.preferences.symbol_locate is True


def test_symbol_locate_vocabulary_matches_the_config_layer() -> None:
    """`_coerce_symbol_locate` 与 `config.normalize_symbol_locate` 必须逐值同口径。

    后端重列了一份解析表（理由见 `jsonl_server.py` 的注释）：config 层对非法值只告警回退，
    向导层要报错。这个用例把两张表钉在一起——config 层不告警的写法，向导必须接受且解析成
    同一个布尔；config 层告警的写法，向导必须拒绝。
    """
    import warnings

    from ai_pr_review.config import ConfigValidationError, normalize_symbol_locate

    samples: list[Any] = [
        True,
        False,
        0,
        1,
        2,
        -1,
        0.0,
        1.0,
        "true",
        "false",
        " TRUE ",
        "Off",
        "yes",
        "no",
        "on",
        "1",
        "0",
        "maybe",
        "tru",
        "",
        " ",
        None,
        [],
        {},
    ]
    for raw in samples:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            expected = normalize_symbol_locate(raw)
        config_rejects = any("symbol_locate" in str(item.message) for item in caught)
        try:
            parsed = JsonlBackend._coerce_symbol_locate(raw)
        except ConfigValidationError:
            backend_rejects = True
        else:
            backend_rejects = False
            assert parsed is expected, raw
        assert backend_rejects is config_rejects, raw


def test_symbol_locate_switch_reaches_the_orchestrator_predicate(tmp_path: Path) -> None:
    """落盘字段就是消费方读的那个：`ReviewOrchestrator._symbol_locate_enabled()`。

    配置入口的意义在于"改得动真正的开关"——这里用 `AppConfig.load()` 重新读回落盘结果，
    确认编排器看到的就是向导刚写入的值（消费逻辑本身由 `tests/test_symbol_locator.py` 覆盖）。
    """
    from ai_pr_review.config import AppConfig
    from ai_pr_review.services.review_orchestrator import ReviewOrchestrator

    config_path = tmp_path / "config.json"
    backend = JsonlBackend(config_path)
    backend._apply_setup({"runtime_profile": "local", "symbol_locate": False})

    orchestrator = ReviewOrchestrator.__new__(ReviewOrchestrator)
    orchestrator._config = AppConfig.load(config_path)

    assert orchestrator._symbol_locate_enabled() is False

    backend._apply_setup({"runtime_profile": "local", "symbol_locate": True})
    orchestrator._config = AppConfig.load(config_path)
    assert orchestrator._symbol_locate_enabled() is True


# ---------------------------------------------------------------------------
# `/model` 子命令（docs/dual-model-roles-plan.md §5.3）
# ---------------------------------------------------------------------------


def test_model_command_without_arguments_keeps_reporting_the_current_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """无参 `/model` 与 `/model status` 保持现状，不被新子命令挤掉。"""
    _offline_model_provider(monkeypatch)
    backend = JsonlBackend(tmp_path / "config.json")

    reply = _execute(backend, "model", [])

    assert reply["ok"] is True
    assert reply["result"]["text"]
    assert reply["result"]["status"]["routing"] == backend._routing_snapshot()

    status_reply = _execute(backend, "model", ["status"])
    assert status_reply["ok"] is True
    assert status_reply["result"]["text"] == reply["result"]["text"]


def test_model_command_chat_writes_the_provider_chat_actually_uses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`/model chat <name>` 改的就是聊天真正会用的 provider（显式本地槽）。"""
    from ai_pr_review.config import AppConfig

    _offline_model_provider(monkeypatch)
    config_path = tmp_path / "config.json"
    backend = JsonlBackend(config_path)
    backend.config.provider.default_model = "remote-model"
    backend.config.local_provider.default_model = "local-model"
    backend._apply_setup(
        {"runtime_profile": "custom", "chat_slot": "local", "review_slot": "remote"}
    )

    reply = _execute(backend, "model", ["chat", "chat-model"])

    assert reply["ok"] is True
    assert backend.config.local_provider.default_model == "chat-model"
    # 审查槽指向另一个 provider：不能被顺手改掉。
    assert backend.config.provider.default_model == "remote-model"
    assert reply["result"]["config"]["routing"]["chat"]["model"] == "chat-model"
    assert reply["result"]["config"]["routing"]["review"]["model"] == "remote-model"
    assert AppConfig.load(config_path).preferences.chat_slot == "local"
    assert AppConfig.load(config_path).local_provider.default_model == "chat-model"


def test_model_command_review_writes_the_provider_review_actually_uses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`/model review <name>` 改的是审查槽的 provider，本地槽原样保留。"""
    from ai_pr_review.config import AppConfig

    _offline_model_provider(monkeypatch)
    config_path = tmp_path / "config.json"
    backend = JsonlBackend(config_path)
    backend.config.provider.default_model = "remote-model"
    backend.config.local_provider.default_model = "local-model"
    backend._apply_setup(
        {"runtime_profile": "custom", "chat_slot": "local", "review_slot": "remote"}
    )

    reply = _execute(backend, "model", ["review", "review-model"])

    assert reply["ok"] is True
    assert backend.config.provider.default_model == "review-model"
    assert backend.config.local_provider.default_model == "local-model"
    assert reply["result"]["config"]["routing"]["review"]["model"] == "review-model"
    assert reply["result"]["config"]["routing"]["chat"]["model"] == "local-model"
    assert AppConfig.load(config_path).provider.default_model == "review-model"


def test_protocol_config_options_and_setup_carry_repo_context(tmp_path: Path) -> None:
    """协议层（不只是私有方法）：config.options 暴露可选值，config.setup 接受该字段。"""
    from ai_pr_review.config import REPO_CONTEXT_MODES

    backend = JsonlBackend(tmp_path / "config.json")

    options = asyncio.run(backend.handle({"id": "1", "method": "config.options", "params": {}}))[0]
    assert options["ok"] is True
    assert options["result"]["repo_context"]["value"] == "tests+imports"
    assert [item["value"] for item in options["result"]["repo_context"]["options"]] == list(
        REPO_CONTEXT_MODES
    )

    applied = asyncio.run(
        backend.handle(
            {
                "id": "2",
                "method": "config.setup",
                "params": {"runtime_profile": "local", "repo_context": "off"},
            }
        )
    )[0]
    assert applied["ok"] is True
    assert applied["result"]["repo_context"] == "off"

    # 非法值经协议边界返回错误事件而不是抛穿（沿用既有错误映射）。
    rejected = asyncio.run(
        backend.handle(
            {
                "id": "3",
                "method": "config.setup",
                "params": {"runtime_profile": "local", "repo_context": "everything"},
            }
        )
    )[0]
    assert rejected["ok"] is False
    assert "仓库上下文仅支持" in rejected["error"]["message"]


def test_model_command_review_local_slot_writes_the_local_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`_review_slot_config` 的本地分支：review 槽解析为 local 时写 `local_provider`。"""
    _offline_model_provider(monkeypatch)
    backend = JsonlBackend(tmp_path / "config.json")
    backend.config.provider.default_model = "remote-model"
    backend.config.local_provider.default_model = "local-model"
    backend._apply_setup(
        {"runtime_profile": "custom", "chat_slot": "remote", "review_slot": "local"}
    )

    reply = _execute(backend, "model", ["review", "local-review-model"])

    assert reply["ok"] is True
    assert backend.config.local_provider.default_model == "local-review-model"
    assert backend.config.provider.default_model == "remote-model"
    assert reply["result"]["config"]["routing"]["review"] == {
        "slot": "local",
        "label": "本地",
        "model": "local-review-model",
    }
    # 两个槽用的不是同一个 Provider：不出现"连带改到另一个槽"的提示。
    assert "注意" not in reply["result"]["text"]


def test_model_command_chat_with_a_primary_ollama_writes_the_primary_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """主 Provider 自己就是 Ollama 时聊天槽就是主槽：`/model chat` 必须改到它。

    这条正是 `_local_slot_config` 存在的理由——用户自定义的端点与模型列表在主槽里，
    写到预设的 `local_provider` 上等于"命令说成功、聊天没变化"。
    """
    _offline_model_provider(monkeypatch)
    backend = JsonlBackend(tmp_path / "config.json")
    backend.config.provider.name = "ollama"
    backend.config.provider.display_name = "Ollama (Local)"
    backend.config.provider.base_url = "http://127.0.0.1:9999/v1"
    backend.config.provider.default_model = "primary-ollama-model"
    backend.config.local_provider.default_model = "preset-local-model"
    backend.config.preferences.hybrid_strategy = "local_only"
    backend.config._sync_runtime_sections()

    reply = _execute(backend, "model", ["chat", "custom-endpoint-model"])

    assert reply["ok"] is True
    assert backend.config.provider.default_model == "custom-endpoint-model"
    assert backend.config.provider.base_url == "http://127.0.0.1:9999/v1"
    assert backend.config.local_provider.default_model == "preset-local-model"
    assert "对话模型已切换为 custom-endpoint-model" in reply["result"]["text"]
    # 已知边界（docs/claude-repo-config.md §6.4）：`routing.chat.model` 仍按槽位名报
    # `local_provider` 的模型，与实际被写入的主槽不一致——`_slot_model` 的既有行为，
    # 本任务刻意没改（改它会影响状态栏对既有配置的显示）。此断言把该差异钉住。
    assert reply["result"]["config"]["routing"]["chat"]["model"] == "preset-local-model"


def test_model_command_review_in_hybrid_writes_the_upgrade_model_and_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """hybrid 没有单一模型：写"能覆盖全部文件"的升级模型，并说明本地模型不变。"""
    _offline_model_provider(monkeypatch)
    backend = JsonlBackend(tmp_path / "config.json")
    backend.config.local_provider.default_model = "local-model"
    backend._apply_setup({"runtime_profile": "custom", "review_slot": "hybrid"})

    reply = _execute(backend, "model", ["review", "deep-model"])

    assert reply["ok"] is True
    assert backend.config.provider.default_model == "deep-model"
    assert backend.config.local_provider.default_model == "local-model"
    assert reply["result"]["config"]["routing"]["review"]["slot"] == "hybrid"
    assert reply["result"]["config"]["routing"]["review"]["model"] == "deep-model"
    assert "混合策略：低风险文件仍由本地模型 local-model 审查" in reply["result"]["text"]


def test_model_command_warns_when_both_slots_share_one_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """两个槽指向同一个 Provider 时共用一个 default_model，必须明说会连带改到另一个槽。"""
    _offline_model_provider(monkeypatch)
    backend = JsonlBackend(tmp_path / "config.json")

    reply = _execute(backend, "model", ["chat", "shared-model"])

    assert reply["ok"] is True
    assert "注意：审查槽用的是同一个 Provider" in reply["result"]["text"]
    assert reply["result"]["config"]["routing"]["review"]["model"] == "shared-model"


def test_model_command_bare_name_keeps_switching_the_chat_slot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """兼容旧行为：裸模型名等同 `/model chat <name>`，且模型名不再被折叠成小写。"""
    _offline_model_provider(monkeypatch)
    backend = JsonlBackend(tmp_path / "config.json")
    backend.config.local_provider.default_model = "local-model"
    backend._apply_setup(
        {"runtime_profile": "custom", "chat_slot": "local", "review_slot": "remote"}
    )

    reply = _execute(backend, "model", ["Qwen3.5:4B-Instruct"])

    assert reply["ok"] is True
    assert backend.config.local_provider.default_model == "Qwen3.5:4B-Instruct"
    assert reply["result"]["config"]["routing"]["chat"]["model"] == "Qwen3.5:4B-Instruct"
    assert "对话模型已切换为 Qwen3.5:4B-Instruct" in reply["result"]["text"]


def test_model_command_rejects_incomplete_or_overspecified_subcommands(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """缺模型名 / 多写参数都要 actionable：说清可用写法，且不写任何配置。"""
    config_path = tmp_path / "config.json"
    backend = JsonlBackend(config_path)

    for args in (["chat"], ["review"], ["chat", "a", "b"], ["chat", ""]):
        reply = _execute(backend, "model", args)
        assert reply["ok"] is False, args
        assert reply["error"]["code"] == "invalid_request", args
        assert "/model chat <模型名>" in reply["error"]["message"], args
        assert "/model review <模型名>" in reply["error"]["message"], args

    assert config_path.exists() is False


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


async def _execute_async(
    backend: JsonlBackend,
    name: str,
    args: list[Any],
    session_id: str | None = None,
) -> dict[str, Any]:
    """`_execute` 的协程版：用例本身已经跑在事件循环里时不能再嵌套 `asyncio.run`。"""
    params: dict[str, Any] = {"name": name, "args": args}
    if session_id is not None:
        params["session_id"] = session_id
    events = await backend.handle({"id": "cmd", "method": "command.execute", "params": params})
    return _reply(events)


async def _new_session_async(backend: JsonlBackend) -> str:
    events = await backend.handle({"id": "s", "method": "session.create", "params": {}})
    return str(_reply(events)["result"]["session_id"])


# ---------------------------------------------------------------------------


def _context_finding(
    *,
    severity: str,
    confidence: float,
    filename: str,
    line_start: int,
    line_end: int,
) -> Any:
    """写一条字段齐全的 finding，供 §9 的渲染断言引用具体文本。"""
    from ai_pr_review.services.prompt_assembler import Finding

    return Finding(
        severity=severity,
        category="correctness",
        file=filename,
        line_start=line_start,
        line_end=line_end,
        title=f"{severity} 问题",
        problem="问题描述",
        suggestion="修复建议",
        confidence=confidence,
        code_snippet="if x == 1:\n    pass",
        evidence_status="needs_review",
        evidence_issues=["行号与 diff 不一致"],
        sources=["ai_analysis"],
        finding_id=f"finding-{severity}",
    )


def _store_context_run(
    backend: JsonlBackend,
    *,
    findings: list[Any] | None = None,
    metadata: dict[str, Any] | None = None,
    summary: str = "审查完成，发现 3 个问题",
) -> str:
    """落库一个信息完整的 run（PR 标题/作者/证据校验/过滤计数），返回 run_id。

    `metadata` 显式传入时**整体替换**默认值：需要"什么都没记录"的 run 时传 `{}`。
    """
    from ai_pr_review.services.prompt_assembler import ReviewResult
    from ai_pr_review.services.result_store import ResultStore

    if findings is None:
        findings = [
            _context_finding(
                severity="medium",
                confidence=0.75,
                filename="src/medium.py",
                line_start=5,
                line_end=5,
            ),
            _context_finding(
                severity="critical",
                confidence=0.9,
                filename="src/critical.py",
                line_start=12,
                line_end=20,
            ),
            _context_finding(
                severity="high",
                confidence=0.8,
                filename="src/high.py",
                line_start=1,
                line_end=3,
            ),
        ]
    if metadata is None:
        metadata = {
            "pr_title": "Review workspace contract",
            "pr_author": "octocat",
            "validation_summary": {"valid": 1, "needs_review": 1, "invalid": 1},
            "filtered_findings": {"threshold": 0.7, "below_threshold": 2, "duplicates": 1},
        }
    return ResultStore(backend.config.result_store).save_result(
        "https://github.com/example/repo/pull/31",
        ReviewResult(summary=summary, findings=findings),
        head_sha="a" * 40,
        total_files=3,
        included_files=2,
        excluded_files=1,
        total_cost=0.0124,
        duration_seconds=42.31,
        model="deepseek-flash",
        metadata=metadata,
    )


def _context_store(backend: JsonlBackend) -> Any:
    from ai_pr_review.services.result_store import ResultStore

    return ResultStore(backend.config.result_store)


def _review_request_for(session_id: str, request_id: str = "review") -> dict[str, Any]:
    return {
        "id": request_id,
        "method": "command.execute",
        "params": {
            "name": "review",
            "args": ["https://github.com/example/repo/pull/31"],
            "session_id": session_id,
        },
    }


def test_review_context_renders_l1_to_l4_with_stable_format(tmp_path: Path) -> None:
    """§9.2 B：L1 摘要 / L2 清单 / L3 全文 / L4 过滤计数，层标记与字段逐字可冻结。"""
    from ai_pr_review.services.review_context import build_review_context, estimate_tokens

    backend = JsonlBackend(tmp_path / "config.json")
    run_id = _store_context_run(backend)

    context = build_review_context(_context_store(backend), run_id)

    assert context is not None
    assert estimate_tokens(context) > 0
    # L1：运行摘要从不缺席，PR/作者/模型/成本/证据校验都在
    assert "[L1 运行摘要]" in context
    assert f"Run: {run_id}" in context
    assert "PR: example/repo #31 · Review workspace contract" in context
    assert "作者: octocat" in context
    assert "URL: https://github.com/example/repo/pull/31" in context
    assert "模型: deepseek-flash" in context
    assert "耗时 42.3s · 成本 $0.0124" in context
    assert "统计: 共 3 条 · critical 1 · high 1 · medium 1 · low 0 · info 0" in context
    assert "文件: 审查 2 · 跳过 1（共 3）" in context
    assert "证据校验: valid 1 · needs_review 1 · invalid 1" in context
    assert "摘要: 审查完成，发现 3 个问题" in context
    # L2：严重度 / 文件:行 / 置信度 / 证据状态 / 标题，按严重度排序
    assert "[L2 FINDINGS 清单] 共 3 条（按严重度排序）" in context
    listed = [line for line in context.splitlines() if re.match(r"^\d+\. \[", line)]
    assert listed[0] == (
        "1. [critical] src/critical.py:12-20 · 置信度 90% · 证据 needs_review · critical 问题"
    )
    assert listed[1].startswith("2. [high] src/high.py:1-3 · 置信度 80%")
    # 单行 finding 不写成 5-5，与评论里的 `文件:行` 口径一致
    assert listed[2].startswith("3. [medium] src/medium.py:5 · 置信度 75%")
    # L3：与 L2 同一编号，含原因/建议/代码片段/证据疑点
    assert "[L3 重点 FINDING 全文] 前 3 条（按严重度排序）" in context
    assert "#1 [critical] critical 问题" in context
    assert "   位置: src/critical.py:12-20" in context
    assert "   置信度 90% · 证据: needs_review" in context
    assert "   原因: 问题描述" in context
    assert "   建议: 修复建议" in context
    assert "   代码:\n     if x == 1:\n         pass" in context
    assert "   疑点: 行号与 diff 不一致" in context
    # L4：门槛与计数照抄 run 记录，不重算
    assert "[L4 被过滤 FINDING] 门槛 0.70 · 低于门槛 2 条 · 去重 1 条" in context


def test_review_context_l3_covers_every_finding_not_just_top_three(tmp_path: Path) -> None:
    """2026-09-26：L3 此前硬编码只给前 3 条全文——12 条 finding 时第 4-12 条
    只有标题级信息，用户追问「第 6 条为什么判 medium」模型答不了。
    现在 L3 覆盖全部（预算不足时仍按原链条逐条降级）。"""
    from ai_pr_review.services.prompt_assembler import Finding
    from ai_pr_review.services.review_context import build_review_context

    backend = JsonlBackend(tmp_path / "config.json")
    findings = [
        Finding(
            severity="critical" if index == 1 else "high" if index == 2 else "medium",
            category="correctness",
            file=f"src/m{index}.py",
            line_start=index,
            line_end=index,
            title=f"标题 {index}",
            problem=f"问题描述 {index}",
            suggestion=f"修复建议 {index}",
            confidence=0.9 - index * 0.01,
            code_snippet="if x == 1:\n    pass",
            evidence_status="valid",
        )
        for index in range(1, 13)
    ]
    run_id = _store_context_run(backend, findings=findings, summary="审查完成，发现 12 个问题")

    context = build_review_context(_context_store(backend), run_id)

    assert context is not None
    # 标题按实际条数渲染：12 条都在 L3 里（此前是"前 3 条"）
    assert "[L3 重点 FINDING 全文] 前 12 条（按严重度排序）" in context
    # 此前只能看到标题的第 6 条，现在有原因与建议全文
    assert "问题描述 6" in context
    assert "修复建议 6" in context
    # 末条也在：证明不是"只保前 N 条"的截断
    assert "问题描述 12" in context
    assert "修复建议 12" in context


def test_review_context_never_invents_unrecorded_layers(tmp_path: Path) -> None:
    """缺什么就少哪一段：没有 filtered_findings 就没有 L4，也不写"被过滤 0 条"。"""
    from ai_pr_review.services.review_context import build_review_context

    backend = JsonlBackend(tmp_path / "config.json")
    run_id = _store_context_run(backend, findings=[], metadata={}, summary="没有问题的 PR")

    context = build_review_context(_context_store(backend), run_id)

    assert context is not None
    assert "[L4" not in context
    assert "被过滤" not in context
    assert "[L3 " not in context
    assert "[L2 FINDINGS 清单]\n（该 Run 没有记录任何 Finding）" in context
    # 没记录过的字段不编造：没有标题/作者/证据校验，就没有对应行
    assert "作者:" not in context
    assert "证据校验" not in context
    assert "PR: example/repo #31\n" in context
    # 统计里的 0 是实测的 0（result.findings 为空），可以出现
    assert "统计: 共 0 条" in context


def test_review_context_budget_drops_l4_then_l3_then_l2_but_keeps_l1(tmp_path: Path) -> None:
    """§9.D：裁剪顺序 L4 → L3（减条目）→ L2（只留 high/critical）；L1 永不裁剪。"""
    from ai_pr_review.services.review_context import (
        build_review_context,
        build_review_context_meta,
        estimate_tokens,
    )

    backend = JsonlBackend(tmp_path / "config.json")
    run_id = _store_context_run(backend)
    store = _context_store(backend)
    full = build_review_context(store, run_id, token_budget=10**9)
    assert full is not None
    full_tokens = estimate_tokens(full)
    l1 = full.split("\n\n[L2")[0]
    for marker in (
        "[L1 运行摘要]",
        "[L2 FINDINGS 清单]",
        "[L3 重点 FINDING 全文]",
        "[L4 被过滤 FINDING]",
    ):
        assert marker in full

    # 差一点预算：L4 先消失，L2/L3 原样保留
    tight = build_review_context_meta(store, run_id, token_budget=full_tokens - 1)
    assert tight is not None
    assert tight.trimmed == ("L4",)
    assert tight.text.startswith(l1)
    assert "[L4 被过滤 FINDING]" not in tight.text
    assert "[L3 重点 FINDING 全文] 前 3 条" in tight.text
    assert "[L2 FINDINGS 清单] 共 3 条（按严重度排序）" in tight.text

    # 再收紧：L3 开始减条目，但 L2 仍是全量
    trimmed_l3 = build_review_context_meta(store, run_id, token_budget=full_tokens - 40)
    assert trimmed_l3.trimmed == ("L4", "L3")
    assert trimmed_l3.text.startswith(l1)
    blocks = re.findall(r"^#\d+ \[", trimmed_l3.text, flags=re.MULTILINE)
    assert 1 <= len(blocks) < 3
    assert "[L2 FINDINGS 清单] 共 3 条（按严重度排序）" in trimmed_l3.text

    # 极端预算：只剩 L1 + 仅 critical/high 的 L2，L1 逐字不变
    minimal = build_review_context_meta(store, run_id, token_budget=1)
    assert minimal is not None
    assert minimal.trimmed == ("L4", "L3", "L2")
    assert minimal.text.startswith(l1)
    assert "[L3 " not in minimal.text
    assert "[L4 " not in minimal.text
    assert "（预算受限，仅保留 critical/high）" in minimal.text
    assert "1. [critical] src/critical.py:12-20" in minimal.text
    assert "3. [medium]" not in minimal.text
    # 裁剪提示点名被裁的层，并给出查看完整内容的命令
    assert "已按 L4 → L3 → L2 顺序裁剪 L4、L3、L2" in minimal.text
    assert f"/explain {run_id}" in minimal.text


def test_review_context_returns_none_when_the_run_or_store_is_unreadable(tmp_path: Path) -> None:
    """读不到就返回 None（由调用方降级），不抛异常、不返回半成品。"""
    from ai_pr_review.services.review_context import build_review_context, build_review_context_meta

    class ExplodingStore:
        def get_run_summary(self, run_id: str) -> dict:
            raise sqlite3.OperationalError("database is locked")

    class MissingResultStore:
        def get_run_summary(self, run_id: str) -> dict:
            return {"id": run_id}

        def get_result(self, run_id: str) -> None:
            return None

        def get_run_metadata(self, run_id: str) -> dict:
            return {}

    assert build_review_context(ExplodingStore(), "run-x") is None
    assert build_review_context_meta(MissingResultStore(), "run-x") is None

    backend = JsonlBackend(tmp_path / "config.json")
    store = _context_store(backend)
    assert build_review_context(store, "no-such-run") is None
    assert build_review_context_meta(store, "") is None


def test_review_completion_binds_the_session_but_failure_and_cancel_do_not(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """§9.2 A：只有成功落库的审查才绑定当前 Run。"""

    async def run() -> None:
        from ai_pr_review.services.review_orchestrator import (
            ReviewCancelled as OrchestratorCancelled,
        )

        backend = JsonlBackend(tmp_path / "config.json", event_sink=lambda event: None)
        session_id = await _new_session_async(backend)

        async def ok_review(pr_url, **kwargs):
            return _review_artifacts(findings=[_finding()])

        monkeypatch.setattr("ai_pr_review.cli.run_review", ok_review)
        response = await backend.handle(_review_request_for(session_id))
        assert response[0]["ok"] is True
        assert backend.sessions[session_id].current_run_id == "run-31"

        # 失败：不绑定（否则 chat 会去解读一个不存在的 run）
        failed_session = await _new_session_async(backend)

        async def failing_review(pr_url, **kwargs):
            raise RuntimeError("模型服务不可用")

        monkeypatch.setattr("ai_pr_review.cli.run_review", failing_review)
        response = await backend.handle(_review_request_for(failed_session))
        assert response[0]["ok"] is False
        assert backend.sessions[failed_session].current_run_id is None

        # 取消：同样不绑定
        cancelled_session = await _new_session_async(backend)

        async def cancelled_review(pr_url, **kwargs):
            raise OrchestratorCancelled()

        monkeypatch.setattr("ai_pr_review.cli.run_review", cancelled_review)
        response = await backend.handle(_review_request_for(cancelled_session))
        assert response[0]["result"]["cancelled"] is True
        assert backend.sessions[cancelled_session].current_run_id is None

    asyncio.run(run())


def test_context_command_reports_switches_and_clears_the_binding(tmp_path: Path) -> None:
    """§9.2 A/E：/context 的查看、切换、off 三态，以及未知 run / 无会话的错误面。"""

    async def run() -> None:
        backend = JsonlBackend(tmp_path / "config.json", event_sink=lambda event: None)
        session_id = await _new_session_async(backend)
        run_id = _store_context_run(backend)

        # 未绑定：文案必须明确说清楚，并给出绑定方法
        unbound = (await _execute_async(backend, "context", [], session_id))["result"]
        assert unbound["bound"] is False
        assert unbound["run_id"] is None
        assert unbound["token_estimate"] is None
        assert unbound["token_budget"] == DEFAULT_CHAT_BUDGET
        # 该进程没有同步过目录、用户也没写过规格：来源如实报兜底（§4）。
        assert unbound["budget_source"] == "fallback"
        assert "审查上下文：未绑定" in unbound["text"]
        assert "/context <run_id>" in unbound["text"]

        # 切换绑定：报 run_id、PR 与 token 估算
        bound = (await _execute_async(backend, "context", [run_id], session_id))["result"]
        assert bound["bound"] is True
        assert bound["run_id"] == run_id
        assert bound["token_estimate"] > 0
        assert bound["token_budget"] == DEFAULT_CHAT_BUDGET
        assert bound["budget_source"] == "fallback"
        assert bound["trimmed"] == []
        assert "已切换审查上下文" in bound["text"]
        assert f"Run: {run_id}" in bound["text"]
        assert "PR: example/repo #31 · Review workspace contract" in bound["text"]
        assert "token 估算: 约" in bound["text"]

        # 无参查看与切换结果一致
        status = (await _execute_async(backend, "context", [], session_id))["result"]
        assert status["run_id"] == run_id
        assert status["token_estimate"] == bound["token_estimate"]

        # 会话快照也带上绑定，TUI 无需再问一次
        snapshot = await backend.handle(
            {"id": "get", "method": "session.get", "params": {"session_id": session_id}}
        )
        assert snapshot[0]["result"]["current_run_id"] == run_id

        # 未知 run：报 not_found，且不改动已有绑定
        missing = await _execute_async(backend, "context", ["no-such-run"], session_id)
        assert missing["ok"] is False
        assert missing["error"]["code"] == "not_found"
        assert backend.sessions[session_id].current_run_id == run_id

        # off：解绑并回到未绑定文案
        off = (await _execute_async(backend, "context", ["off"], session_id))["result"]
        assert off["bound"] is False
        assert off["run_id"] is None
        assert backend.sessions[session_id].current_run_id is None
        assert "已解除审查上下文绑定" in off["text"]
        assert (await _execute_async(backend, "context", [], session_id))["result"][
            "bound"
        ] is False

        # 没有会话：查看仍可回答"未绑定"，但切换/解绑没有绑定可操作
        assert (await _execute_async(backend, "context", []))["result"]["bound"] is False
        assert (await _execute_async(backend, "context", ["off"]))["ok"] is False
        assert (await _execute_async(backend, "context", [run_id]))["error"]["code"] == "not_found"

    asyncio.run(run())


def test_history_and_explain_bind_the_run_only_on_success(tmp_path: Path) -> None:
    """§9.2 A：`/history <run_id>` 与 `/explain <run_id>` 成功后绑定；列表与未找到不绑定。"""

    async def run() -> None:
        backend = JsonlBackend(tmp_path / "config.json", event_sink=lambda event: None)
        run_id = _store_context_run(backend)

        history_session = await _new_session_async(backend)
        assert (await _execute_async(backend, "history", [run_id], history_session))["ok"] is True
        assert backend.sessions[history_session].current_run_id == run_id

        explain_session = await _new_session_async(backend)
        assert (await _execute_async(backend, "explain", [run_id], explain_session))["ok"] is True
        assert backend.sessions[explain_session].current_run_id == run_id

        listing_session = await _new_session_async(backend)
        assert (await _execute_async(backend, "history", [], listing_session))["ok"] is True
        assert backend.sessions[listing_session].current_run_id is None
        # 未找到的历史：返回 ok=True 的详情（run 为 None），但绝不能绑定
        assert (await _execute_async(backend, "history", ["no-such-run"], listing_session))[
            "ok"
        ] is True
        assert backend.sessions[listing_session].current_run_id is None
        assert (await _execute_async(backend, "explain", ["no-such-run"], listing_session))[
            "ok"
        ] is False
        assert backend.sessions[listing_session].current_run_id is None
        # 已有绑定的会话跑一次列表，不会顺手解绑
        assert (await _execute_async(backend, "history", [], history_session))["ok"] is True
        assert backend.sessions[history_session].current_run_id == run_id

    asyncio.run(run())


def test_chat_injects_the_bound_review_context_into_the_system_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """§9.2 C：绑定后 system_prompt = 语言指令 + 上下文 + 诚实约束，且不写进对话历史。"""

    async def run() -> None:
        backend = JsonlBackend(tmp_path / "config.json", event_sink=lambda event: None)
        backend.config.provider.api_key = "test-key"
        backend.config._sync_runtime_sections()
        run_id = _store_context_run(backend)
        session_id = await _new_session_async(backend)
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        # 未绑定：只有语言指令
        response = await backend.handle(_chat_send(session_id))
        assert response[0]["ok"] is True
        plain_prompt = captured["options"]["system_prompt"]
        assert "请默认使用中文回答" in plain_prompt
        assert "<review_context" not in plain_prompt

        await _execute_async(backend, "context", [run_id], session_id)
        response = await backend.handle(_chat_send(session_id, "第 2 条 finding 的文件与行号？"))

        assert response[0]["ok"] is True
        prompt = captured["options"]["system_prompt"]
        # 注入必须排在语言指令之后
        assert prompt.index("请默认使用中文回答") < prompt.index("<review_context")
        assert f'<review_context run_id="{run_id}">' in prompt
        assert "[L1 运行摘要]" in prompt
        assert "PR: example/repo #31 · Review workspace contract" in prompt
        assert "src/critical.py:12-20" in prompt
        assert "证据校验: valid 1 · needs_review 1 · invalid 1" in prompt
        assert "[L4 被过滤 FINDING] 门槛 0.70" in prompt
        # 诚实约束三条
        assert "只依据上面的审查上下文回答" in prompt
        assert "必须给出「文件:行」与严重度" in prompt
        assert "需要查看源码" in prompt
        assert "不得臆测" in prompt
        # 上下文只进 system prompt：对话历史里只有正常的 user/assistant 轮次
        messages = backend.sessions[session_id].messages
        assert [message["role"] for message in messages] == [
            "user",
            "assistant",
            "user",
            "assistant",
        ]
        assert all("<review_context" not in message["content"] for message in messages)

        # 预算收紧到 1 token：仍然可用，但注入内容被裁剪且明说裁剪了哪些层
        backend.config.preferences.chat_context_budget = 1
        await backend.handle(_chat_send(session_id, "再说一次"))
        trimmed_prompt = captured["options"]["system_prompt"]
        assert "[L1 运行摘要]" in trimmed_prompt
        assert "[L4 被过滤 FINDING]" not in trimmed_prompt
        assert "已按 L4 → L3 → L2 顺序裁剪" in trimmed_prompt

    asyncio.run(run())


def test_chat_degrades_to_plain_chat_when_context_cannot_be_built(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """§9.2 C：构建失败/无记录时降级为普通聊天，记 warning，对话不得中断。"""

    async def run() -> None:
        backend = JsonlBackend(tmp_path / "config.json", event_sink=lambda event: None)
        backend.config.provider.api_key = "test-key"
        backend.config._sync_runtime_sections()
        run_id = _store_context_run(backend)
        session_id = await _new_session_async(backend)
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)
        await _execute_async(backend, "context", [run_id], session_id)

        # (1) 绑定后 run 被清理：读不到，但要如实说明，而不是悄悄变回未绑定
        backend.sessions[session_id].current_run_id = "no-such-run"
        response = await backend.handle(_chat_send(session_id))
        assert response[0]["ok"] is True
        assert "<review_context" not in captured["options"]["system_prompt"]
        status = (await _execute_async(backend, "context", [], session_id))["result"]
        assert status["bound"] is True
        assert status["run_id"] == "no-such-run"
        assert status["token_estimate"] is None
        assert "无法读取" in status["text"]

        # (2) 构建器抛异常
        def exploding_builder(store, run_id, **kwargs):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(
            "ai_pr_review.backend.jsonl_server.build_review_context", exploding_builder
        )
        backend.sessions[session_id].current_run_id = run_id
        response = await backend.handle(_chat_send(session_id))
        assert response[0]["ok"] is True
        assert response[0]["result"]["text"] == "stub"
        assert "<review_context" not in captured["options"]["system_prompt"]

        # (3) 构建器返回 None
        monkeypatch.setattr(
            "ai_pr_review.backend.jsonl_server.build_review_context",
            lambda store, run_id, **kwargs: None,
        )
        response = await backend.handle(_chat_send(session_id))
        assert response[0]["ok"] is True
        assert "<review_context" not in captured["options"]["system_prompt"]
        # 降级不影响正常对话历史：三轮问答各留下 user/assistant
        assert len(backend.sessions[session_id].messages) == 6

    asyncio.run(run())

    warnings = capsys.readouterr().err
    assert warnings.count("falling back to plain chat") == 3
    assert "no-such-run" in warnings
    assert "database is locked" in warnings


def test_chat_context_budget_preference_is_read_defensively(tmp_path: Path) -> None:
    """预算显式配置优先（§9.D）；非法值退回默认，绝不因此放大预算。

    没配时也不凭空放大：模型规格不可信（没目录、没用户规格）就退回 `DEFAULT_CHAT_BUDGET`。
    """
    backend = JsonlBackend(tmp_path / "config.json")
    assert backend._chat_context_budget_plan() == (DEFAULT_CHAT_BUDGET, "fallback")
    backend.config.preferences.chat_context_budget = 1200
    assert backend._chat_context_budget_plan() == (1200, "config")
    backend.config.preferences.chat_context_budget = 0
    assert backend._chat_context_budget_plan() == (8000, "fallback")
    backend.config.preferences.chat_context_budget = "abc"
    assert backend._chat_context_budget_plan() == (8000, "fallback")


def test_review_context_budget_trim_never_claims_an_empty_run(tmp_path: Path) -> None:
    """预算把 L2 收窄到 critical/high 后，不能把"有 finding 但被裁"说成"什么都没发现"。"""
    from ai_pr_review.services.review_context import build_review_context_meta

    backend = JsonlBackend(tmp_path / "config.json")
    findings = [
        _context_finding(
            severity="medium",
            confidence=0.8,
            filename="src/medium.py",
            line_start=3,
            line_end=4,
        )
    ]
    run_id = _store_context_run(backend, findings=findings, summary="只有一个中危问题")

    minimal = build_review_context_meta(_context_store(backend), run_id, token_budget=1)

    assert minimal is not None
    assert minimal.trimmed == ("L4", "L3", "L2")
    assert "没有记录任何 Finding" not in minimal.text
    assert "预算受限：该 Run 没有 critical/high 的 Finding" in minimal.text
    # 统计行仍是实测的 1 条
    assert "统计: 共 1 条" in minimal.text


def test_help_lists_the_context_command(tmp_path: Path) -> None:
    backend = JsonlBackend(tmp_path / "config.json")
    help_text = _execute(backend, "help", [])["result"]["text"]
    assert "/context [run_id|off] 查看/切换/解除审查上下文绑定" in help_text


def _seed_run(backend: JsonlBackend, pr_number: int, summary: str) -> str:
    """存一条历史 run（pr_number 由 pr_url 解析），返回 run_id。"""
    from ai_pr_review.services.prompt_assembler import ReviewResult
    from ai_pr_review.services.result_store import ResultStore

    store = ResultStore(backend.config.result_store)
    return store.save_result(
        f"https://github.com/o/r/pull/{pr_number}",
        ReviewResult(summary=summary, findings=[]),
    )


def _chat_ready_backend(tmp_path: Path) -> JsonlBackend:
    """既有 stub provider、又通过 `_chat` 的 Key 校验的后端。"""
    backend = JsonlBackend(tmp_path / "config.json", event_sink=lambda event: None)
    # `_stub_provider` 不会真的发请求，但 `_chat` 仍要求非本地槽有 Key。
    backend.config.provider.api_key = "test-key"
    backend.config.ai_client.api_key = "test-key"
    return backend


def test_chat_binds_context_from_a_pr_number_in_the_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """实测反馈：工作台里复制 run id 很不方便——用户只要说「PR #31」就够了。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        old_run = _seed_run(backend, 29, "旧审查")
        new_run = _seed_run(backend, 31, "新审查")
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        response = await backend.handle(_chat_send(session["session_id"], "看看 PR #31 的审查结果"))

        assert response[0]["ok"] is True
        bound = backend.sessions[session["session_id"]].current_run_id
        assert bound == new_run, f"应绑定 #31 的 run，实际 {bound}（#29 的 run 是 {old_run}）"
        assert new_run[:8] in str(response[0]["result"].get("text", ""))
        # 该 run 的上下文确实进了 system prompt
        assert "新审查" in captured["options"]["system_prompt"]

    asyncio.run(run())


def test_chat_binds_context_from_the_candidate_ordinal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """候选清单说「第 2 个」也能选中，同样不需要复制 run id。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        _seed_run(backend, 27, "最早")
        _seed_run(backend, 29, "居中")
        _seed_run(backend, 31, "最新")
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)
        session_id = session["session_id"]

        # 第一轮：未绑定 → system prompt 携带候选清单，并记下顺序
        await backend.handle(_chat_send(session_id, "帮我看看审查"))
        candidates = backend.sessions[session_id].context_candidates
        assert len(candidates) >= 2
        assert backend.sessions[session_id].current_run_id is None  # 不静默绑定
        assert "PR #" in captured["options"]["system_prompt"]

        # 第二轮：说「第 2 个」→ 绑定候选里的第 2 个
        await backend.handle(_chat_send(session_id, "第 2 个"))
        assert backend.sessions[session_id].current_run_id == candidates[1]

    asyncio.run(run())


def test_chat_without_a_reference_never_silently_binds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """没有指代就不绑定：带着错的上下文回答比「我无法访问」更糟。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        _seed_run(backend, 31, "最新审查")
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        response = await backend.handle(_chat_send(session["session_id"], "今天天气怎么样"))

        assert backend.sessions[session["session_id"]].current_run_id is None
        assert "已按你的指代绑定" not in str(response[0]["result"].get("text", ""))
        # 但候选清单仍注入，模型可以主动问"你指哪一次"
        assert "最近几次审查" in captured["options"]["system_prompt"]

    asyncio.run(run())


def test_chat_switches_binding_when_another_pr_is_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """显式指代换 PR 时必须切过去。

    实测反馈：绑定 #31 之后问「那 PR29 呢」，旧实现直接返回（已绑定就不再
    解析），模型只能回"我看不到 #29"。显式说了 PR 号就是在换对象。
    """

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        first = _seed_run(backend, 27, "第一次")
        second = _seed_run(backend, 31, "第二次")
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        session_id = session["session_id"]
        backend.sessions[session_id].current_run_id = first
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        await backend.handle(_chat_send(session_id, "那 PR #31 呢"))

        assert backend.sessions[session_id].current_run_id == second
        assert "第二次" in captured["options"]["system_prompt"]

    asyncio.run(run())


def test_chat_lists_other_runs_even_when_one_is_already_bound(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """已绑定时也要把"还有哪些审查"告诉模型，用户续问别的 PR 才切得动。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        first = _seed_run(backend, 27, "第一次")
        _seed_run(backend, 31, "第二次")
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        session_id = session["session_id"]
        backend.sessions[session_id].current_run_id = first
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        await backend.handle(_chat_send(session_id, "还有什么审查"))

        prompt = captured["options"]["system_prompt"]
        assert "历史里还有这些审查" in prompt
        assert "PR #31" in prompt
        # 序号选择针对这份清单
        assert backend.sessions[session_id].context_candidates

    asyncio.run(run())


def test_history_command_reports_whether_the_session_was_really_bound(
    tmp_path: Path,
) -> None:
    """`bound` 必须反映真实结果。

    实测 bug：TUI 打开历史 run 时漏传 session_id → `_bind_session_run` 静默
    返回 False，而界面照样显示"已绑定"。现在返回 bound，前端据此提示。
    """

    async def run() -> None:
        backend = JsonlBackend(tmp_path / "config.json", event_sink=lambda event: None)
        run_id = _seed_run(backend, 31, "供绑定用")
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        session_id = session["session_id"]

        bound_response = await backend.handle(
            {
                "id": "h1",
                "method": "command.execute",
                "params": {"name": "history", "args": [run_id], "session_id": session_id},
            }
        )
        assert bound_response[0]["ok"] is True
        assert bound_response[0]["result"]["bound"] is True
        assert backend.sessions[session_id].current_run_id == run_id

        # 不带 session_id：绑定不会发生，且必须如实回报 false
        backend.sessions[session_id].current_run_id = None
        unbound_response = await backend.handle(
            {
                "id": "h2",
                "method": "command.execute",
                "params": {"name": "history", "args": [run_id]},
            }
        )
        assert unbound_response[0]["ok"] is True
        assert unbound_response[0]["result"]["bound"] is False
        assert backend.sessions[session_id].current_run_id is None

    asyncio.run(run())


# ---------------------------------------------------------------------------
# 按需读仓库文件（docs/claude-chat-repo-files.md）
# ---------------------------------------------------------------------------


def _seed_run_with_head(
    backend: JsonlBackend,
    *,
    pr_number: int = 31,
    head_sha: str = "b" * 40,
    owner: str = "example",
    repo: str = "repo",
    excluded_files: int | None = None,
) -> str:
    """落库一条带 head_sha 的 run（读源码要靠它定位文件版本）。

    ``excluded_files`` 是审查阶段按规则跳过的文件数（B 段的"另有 N 个被跳过"）。
    """
    from ai_pr_review.services.prompt_assembler import ReviewResult
    from ai_pr_review.services.result_store import ResultStore

    return ResultStore(backend.config.result_store).save_result(
        f"https://github.com/{owner}/{repo}/pull/{pr_number}",
        ReviewResult(summary="审查完成", findings=[]),
        head_sha=head_sha,
        excluded_files=excluded_files,
    )


class _StubRepoFetcher:
    """`PRFetcher` 替身：记录 (owner, repo, path, ref) 并按路径返回内容。

    B/C（docs/claude-repo-structure-context.md）另走两个方法：变更清单与目录树。
    三者各自记录调用、各自可注入失败——"文件内容没被拉"与"清单没被拉"才分得开。
    """

    def __init__(
        self,
        contents: dict[str, str | None] | None = None,
        error: Exception | None = None,
        *,
        changed_files: list[str] | None = None,
        tree_paths: list[str] | None = None,
        inventory_error: Exception | None = None,
    ) -> None:
        self.contents = contents or {}
        self.error = error
        self.changed_files = changed_files or []
        self.tree_paths = tree_paths or []
        self.inventory_error = inventory_error
        self.calls: list[tuple[str, str, str, str]] = []
        self.changed_files_calls: list[str] = []
        self.tree_calls: list[tuple[str, str, str]] = []

    def fetch_file_content(self, owner: str, repo: str, file_path: str, ref: str) -> str | None:
        self.calls.append((owner, repo, file_path, ref))
        if self.error is not None:
            raise self.error
        return self.contents.get(file_path)

    def fetch_changed_file_paths(self, pr_url: str) -> list[str]:
        self.changed_files_calls.append(pr_url)
        if self.inventory_error is not None:
            raise self.inventory_error
        return list(self.changed_files)

    def fetch_repo_tree_paths(self, owner: str, repo: str, ref: str) -> list[str]:
        self.tree_calls.append((owner, repo, ref))
        if self.inventory_error is not None:
            raise self.inventory_error
        return list(self.tree_paths)


def _point_repo_cache_at(
    monkeypatch: pytest.MonkeyPatch, backend: JsonlBackend, root: Path
) -> None:
    """把聊天读源码的缓存钉到 tmp_path，别写进用户真实的 %LOCALAPPDATA%。"""
    from ai_pr_review.services.repo_context import FileSystemRepoCache

    monkeypatch.setattr(
        backend,
        "_chat_repo_cache",
        lambda owner, repo, sha: FileSystemRepoCache(owner, repo, sha, root=root),
    )


def test_mentioned_repo_paths_hits_common_forms_and_ignores_the_rest() -> None:
    """只认源码扩展名；URL 与 PR 链接不得被当成文件路径。"""
    from ai_pr_review.backend.jsonl_server import _mentioned_repo_paths

    # 实测里最常见的问法：带目录的路径、反引号包裹、Windows 分隔符
    assert _mentioned_repo_paths("website/js/main.js 里的 tab.html 从哪来") == [
        "website/js/main.js"
    ]
    assert _mentioned_repo_paths("看下 `src/a.py` 和 src/b.ts") == ["src/a.py", "src/b.ts"]
    assert _mentioned_repo_paths(r"frontend\tui\src\main.tsx 做了什么") == [
        "frontend/tui/src/main.tsx"
    ]
    assert _mentioned_repo_paths("see src/main.js:120 for details") == ["src/main.js"]
    # 裸文件名也认（实测："main.js 里的 tab.html 从哪来"）
    assert _mentioned_repo_paths("main.js 是干嘛的") == ["main.js"]

    # GitHub PR URL / 普通网址：都不是文件路径
    assert _mentioned_repo_paths("https://github.com/example/repo/pull/31") == []
    assert _mentioned_repo_paths("github.com/o/r/pull/31") == []
    assert _mentioned_repo_paths("看看 https://cdn.example.com/vendor/app.js 的写法") == []
    assert _mentioned_repo_paths("https://github.com/o/r/blob/main/src/app.js#L10") == []
    # 非源码扩展名（.md/.html/.txt）与版本号、缩写
    assert _mentioned_repo_paths("docs/design.md 说了什么") == []
    assert _mentioned_repo_paths("index.html 是入口吗") == []
    assert _mentioned_repo_paths("版本 1.2.3 和 e.g. 这类写法") == []
    assert _mentioned_repo_paths("") == []

    # 去重（大小写不敏感）+ 最多 2 条
    assert _mentioned_repo_paths("src/x.py 与 src/x.py") == ["src/x.py"]
    assert _mentioned_repo_paths("a.py b.py c.py d.py") == ["a.py", "b.py"]


def test_chat_injects_the_mentioned_repo_file_from_the_run_head(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """实测反馈：绑定 run 后问 "website/js/main.js 里的 tab.html 从哪来"，
    模型只能答"需要查看源码"——它手上只有 findings。现在按 head 提交取回文件原文。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        run_id = _seed_run_with_head(backend)
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        session_id = session["session_id"]
        backend.sessions[session_id].current_run_id = run_id
        fetcher = _StubRepoFetcher(
            {"website/js/main.js": "const host = document.getElementById('tabs');\n"}
        )
        monkeypatch.setattr(backend, "_chat_pr_fetcher", lambda: fetcher)
        _point_repo_cache_at(monkeypatch, backend, tmp_path / "cache")
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        response = await backend.handle(
            _chat_send(session_id, "website/js/main.js 里的 tab.html 从哪来？")
        )

        assert response[0]["ok"] is True
        # (owner, repo, path, ref) 全部来自这条 run 的元数据与 head 提交
        assert fetcher.calls == [("example", "repo", "website/js/main.js", "b" * 40)]
        prompt = captured["options"]["system_prompt"]
        assert "## 用户提到的仓库文件（来自本次 PR 的 head 提交）" in prompt
        assert f"（run {run_id[:8]} · example/repo @ {'b' * 8}）" in prompt
        assert "### website/js/main.js" in prompt
        assert "document.getElementById('tabs')" in prompt
        assert "3. 引用代码时必须给出「文件:行」" in prompt
        # 只进本轮 system prompt：对话历史里不得出现源码，否则每轮都在重复计费
        messages = backend.sessions[session_id].messages
        assert [message["role"] for message in messages] == ["user", "assistant"]
        assert all("document.getElementById" not in message["content"] for message in messages)

    asyncio.run(run())


def test_chat_without_a_mentioned_path_never_fetches_repo_file_content(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """没点名文件就不拉文件内容（未绑定同理）：不为源码多付一次请求。

    B（docs/claude-repo-structure-context.md）之后，**绑定 run 本身**会带来一次变更
    清单拉取（只在首轮，之后命中进程内缓存）。这里把"文件内容"与"清单"分开断言，
    别让两种请求混进同一个 `calls` 计数里。
    """

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        run_id = _seed_run_with_head(backend)
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        session_id = session["session_id"]
        fetcher = _StubRepoFetcher(error=AssertionError("不该被调用"))
        monkeypatch.setattr(backend, "_chat_pr_fetcher", lambda: fetcher)
        _point_repo_cache_at(monkeypatch, backend, tmp_path / "cache")
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        # (1) 已绑定但消息里没有路径：只注入 B 的变更清单，不读任何文件内容
        backend.sessions[session_id].current_run_id = run_id
        assert (await backend.handle(_chat_send(session_id, "这次审查结论是什么")))[0]["ok"] is True
        prompt = captured["options"]["system_prompt"]
        assert "## 本次 PR 变更文件" in prompt
        assert fetcher.changed_files_calls == ["https://github.com/example/repo/pull/31"]
        # (2) 有路径但没绑定 run：什么都不注入、什么都不拉
        backend.sessions[session_id].current_run_id = None
        assert (await backend.handle(_chat_send(session_id, "src/a.py 是干嘛的")))[0]["ok"] is True

        assert fetcher.calls == []
        assert "## 用户提到的仓库文件" not in captured["options"]["system_prompt"]
        assert "## 本次 PR 变更文件" not in captured["options"]["system_prompt"]
        assert fetcher.changed_files_calls == ["https://github.com/example/repo/pull/31"]

    asyncio.run(run())


def test_chat_says_it_could_not_read_a_file_instead_of_inventing_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """文件不存在：明写 "(未能读取 …)"，绝不编造内容，对话照常。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        run_id = _seed_run_with_head(backend)
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        session_id = session["session_id"]
        backend.sessions[session_id].current_run_id = run_id
        fetcher = _StubRepoFetcher({"src/real.py": "print('hi')\n"})
        monkeypatch.setattr(backend, "_chat_pr_fetcher", lambda: fetcher)
        _point_repo_cache_at(monkeypatch, backend, tmp_path / "cache")
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        response = await backend.handle(
            _chat_send(session_id, "src/missing.py 和 src/real.py 分别是什么？")
        )

        assert response[0]["ok"] is True
        assert response[0]["result"]["text"] == "stub"
        prompt = captured["options"]["system_prompt"]
        assert "(未能读取 src/missing.py：该提交的仓库里不存在，或当前 Token 无权访问)" in prompt
        # 读到的那个照常注入
        assert "### src/real.py" in prompt
        assert "print('hi')" in prompt

    asyncio.run(run())


def test_chat_survives_a_failing_repo_file_fetch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """拉取抛异常：写明简短原因，绝不中断对话（读源码是增益）。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        run_id = _seed_run_with_head(backend)
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        session_id = session["session_id"]
        backend.sessions[session_id].current_run_id = run_id
        fetcher = _StubRepoFetcher(error=RuntimeError("token=ghp_should_not_leak"))
        monkeypatch.setattr(backend, "_chat_pr_fetcher", lambda: fetcher)
        _point_repo_cache_at(monkeypatch, backend, tmp_path / "cache")
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        response = await backend.handle(_chat_send(session_id, "src/fail.py 怎么回事"))

        assert response[0]["ok"] is True
        assert response[0]["result"]["text"] == "stub"
        prompt = captured["options"]["system_prompt"]
        assert "(未能读取 src/fail.py：拉取失败（RuntimeError）)" in prompt
        # 异常文案里不得夹带 token / URL 之类的细节（这里只报异常类名）
        assert "ghp_should_not_leak" not in prompt

        # 整个收集过程炸掉（例如历史库读不了）：降级为空串，仍是普通聊天
        def exploding(run_id: str, paths: list[str]) -> str:
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(backend, "_collect_repo_files", exploding)
        response = await backend.handle(_chat_send(session_id, "src/fail.py 再看一次"))
        assert response[0]["ok"] is True
        assert "## 用户提到的仓库文件" not in captured["options"]["system_prompt"]

    asyncio.run(run())


def test_chat_reuses_the_l1_prefetch_cache_for_mentioned_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """同一个 head 提交下重复问同一个文件：第二轮命中缓存，不再打 GitHub。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        run_id = _seed_run_with_head(backend)
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        session_id = session["session_id"]
        backend.sessions[session_id].current_run_id = run_id
        fetcher = _StubRepoFetcher({"src/cached.py": "VALUE = 1\n"})
        monkeypatch.setattr(backend, "_chat_pr_fetcher", lambda: fetcher)
        _point_repo_cache_at(monkeypatch, backend, tmp_path / "cache")
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        for _ in range(2):
            response = await backend.handle(
                _chat_send(session_id, "src/cached.py 里的 VALUE 是多少")
            )
            assert response[0]["ok"] is True

        assert fetcher.calls == [("example", "repo", "src/cached.py", "b" * 40)]
        assert captured["options"]["system_prompt"].count("### src/cached.py") == 1

    asyncio.run(run())


def test_chat_truncates_mentioned_files_per_file_and_in_total(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """单文件 8000 字符、多文件合计 12000 字符：超限处必须明说截断了。"""
    from ai_pr_review.backend.jsonl_server import (
        CHAT_REPO_FILE_MAX_CHARS,
        CHAT_REPO_FILES_TOTAL_CHARS,
    )

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        run_id = _seed_run_with_head(backend)
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        session_id = session["session_id"]
        backend.sessions[session_id].current_run_id = run_id
        first = "A" * (CHAT_REPO_FILE_MAX_CHARS + 500)
        second = "B" * CHAT_REPO_FILES_TOTAL_CHARS
        fetcher = _StubRepoFetcher({"src/big.py": first, "src/second.py": second})
        monkeypatch.setattr(backend, "_chat_pr_fetcher", lambda: fetcher)
        _point_repo_cache_at(monkeypatch, backend, tmp_path / "cache")
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        response = await backend.handle(
            _chat_send(session_id, "src/big.py 和 src/second.py 讲了什么")
        )

        assert response[0]["ok"] is True
        prompt = captured["options"]["system_prompt"]
        assert f"… [内容已截断，仅显示前 {CHAT_REPO_FILE_MAX_CHARS} 个字符]" in prompt
        # 第一个文件占满单文件上限后，第二个文件只能拿到剩下的总量预算
        injected = prompt.split("### src/second.py", 1)[1]
        assert len(injected.split("\n\n", 1)[0]) < CHAT_REPO_FILES_TOTAL_CHARS
        assert "B" in injected
        # 两个文件都在，且没有出现"超总量"的失败文案
        assert (
            f"(未能读取 src/second.py：本轮注入已达 {CHAT_REPO_FILES_TOTAL_CHARS} 字符上限)"
            not in prompt
        )

    asyncio.run(run())


def test_chat_reports_a_run_without_a_head_sha_instead_of_guessing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """老 run 没存 head_sha：写明原因（无法定位版本），且不去打 GitHub。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        run_id = _seed_run(backend, 31, "没有 head_sha 的旧审查")
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        session_id = session["session_id"]
        backend.sessions[session_id].current_run_id = run_id
        fetcher = _StubRepoFetcher(error=AssertionError("不该被调用"))
        monkeypatch.setattr(backend, "_chat_pr_fetcher", lambda: fetcher)
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        response = await backend.handle(_chat_send(session_id, "src/a.py 是什么"))

        assert response[0]["ok"] is True
        prompt = captured["options"]["system_prompt"]
        assert "(未能读取 src/a.py：该 Run 未记录仓库 / head 提交，无法定位文件)" in prompt
        assert fetcher.calls == []

        # Run 被清理：原因文案不同（不是"仓库里没有"，而是"读不到这次运行"）
        backend.sessions[session_id].current_run_id = "no-such-run"
        response = await backend.handle(_chat_send(session_id, "src/a.py 是什么"))
        assert response[0]["ok"] is True
        prompt = captured["options"]["system_prompt"]
        assert "(未能读取 src/a.py：该 Run 不存在或已被清理，无法定位文件)" in prompt
        assert fetcher.calls == []

    asyncio.run(run())


def test_chat_falls_back_to_the_findings_files_when_the_user_just_asks_for_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """实测反馈：绑定 #31 之后说"对应的仓库代码"，chat 回了"我无法读取仓库"。

    消息里没有文件名，但"对应"指的就是这次审查点名的文件——此时应当拿
    findings 的 file 兜底（findings 指名 website/index.html 这类 .html 也要能读）。
    """

    async def run() -> None:
        from ai_pr_review.services.prompt_assembler import Finding, ReviewResult
        from ai_pr_review.services.result_store import ResultStore

        backend = _chat_ready_backend(tmp_path)
        run_id = ResultStore(backend.config.result_store).save_result(
            "https://github.com/example/repo/pull/31",
            ReviewResult(
                summary="审查完成",
                findings=[
                    Finding(
                        severity="critical",
                        category="security",
                        title="硬编码凭据",
                        file="website/index.html",
                        line_start=237,
                        line_end=237,
                        problem="疑似硬编码",
                        suggestion="移入环境变量",
                        confidence=0.91,
                        code_snippet='export GITHUB_TOKEN="your_github_token"',
                    )
                ],
            ),
            head_sha="b" * 40,
        )
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        session_id = session["session_id"]
        backend.sessions[session_id].current_run_id = run_id
        fetcher = _StubRepoFetcher(
            {"website/index.html": '<pre><code>export GITHUB_TOKEN="your_github_token"'}
        )
        monkeypatch.setattr(backend, "_chat_pr_fetcher", lambda: fetcher)
        _point_repo_cache_at(monkeypatch, backend, tmp_path / "cache")
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        response = await backend.handle(_chat_send(session_id, "对应的仓库代码"))

        assert response[0]["ok"] is True
        assert fetcher.calls == [("example", "repo", "website/index.html", "b" * 40)]
        prompt = captured["options"]["system_prompt"]
        assert "### website/index.html" in prompt, "应兜底到 findings 点名的文件"
        assert "your_github_token" in prompt, "注入的应是真实读取到的内容"

    asyncio.run(run())


# ---------------------------------------------------------------------------
# A1-A3（docs/chat-experience-plan.md 组 A 第一批）：
# 按 finding 行号取窗口 / 会话落盘 / 历史窗口与预算
# ---------------------------------------------------------------------------


def _seed_run_with_findings(
    backend: JsonlBackend,
    findings: list[tuple[str, int, int]],
    *,
    pr_number: int = 31,
    head_sha: str = "b" * 40,
) -> str:
    """落库一条 head_sha 齐全、且**点名了具体文件与行号**的 run（A1 取窗口的依据）。"""
    from ai_pr_review.services.prompt_assembler import Finding, ReviewResult
    from ai_pr_review.services.result_store import ResultStore

    return ResultStore(backend.config.result_store).save_result(
        f"https://github.com/example/repo/pull/{pr_number}",
        ReviewResult(
            summary="审查完成",
            findings=[
                Finding(
                    severity="critical",
                    category="security",
                    title=f"{path}:{line_start} 的问题",
                    file=path,
                    line_start=line_start,
                    line_end=line_end,
                    problem="问题描述",
                    suggestion="修复建议",
                    confidence=0.9,
                    code_snippet="",
                )
                for path, line_start, line_end in findings
            ],
        ),
        head_sha=head_sha,
    )


def test_chat_injects_a_line_window_around_the_finding_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A1 实测根因：index.html 的 finding 在 237 行，旧实现只注入前 ~200 行。

    用户实测时模型把整轮输出花在"数行号"上——因为它手上的内容里根本没有那一行。
    现在被 finding 点名的文件取 finding 行号 ± 80 行的窗口，并在文件头标注范围。
    """

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        run_id = _seed_run_with_findings(backend, [("website/index.html", 237, 237)])
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        session_id = session["session_id"]
        backend.sessions[session_id].current_run_id = run_id
        content = "\n".join(f"<div>row {index}</div>" for index in range(1, 413))
        fetcher = _StubRepoFetcher({"website/index.html": content})
        monkeypatch.setattr(backend, "_chat_pr_fetcher", lambda: fetcher)
        _point_repo_cache_at(monkeypatch, backend, tmp_path / "cache")
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        # 消息里没有文件名：走"对应的仓库代码"兜底到 findings 点名的文件（.html 不在
        # SOURCE_EXTENSIONS 里，显式路径那条路认不出它）。
        response = await backend.handle(_chat_send(session_id, "对应的仓库代码"))

        assert response[0]["ok"] is True
        prompt = captured["options"]["system_prompt"]
        assert "### website/index.html" in prompt
        # 标注必须给出窗口范围与文件总行数（方案 §A1 的文案）
        assert "（显示第 157-317 行，文件共 412 行）" in prompt
        # 注入内容真的覆盖 finding 所在行，且不是从文件头截断的
        assert "<div>row 237</div>" in prompt
        assert "<div>row 157</div>" in prompt
        assert "<div>row 1</div>" not in prompt
        assert "<div>row 412</div>" not in prompt

    asyncio.run(run())


def test_chat_head_truncates_a_file_no_finding_names_and_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A1：没被本次 finding 点名的文件仍是头部截断，但必须写明"只给了前 M 行"。

    旧实现只写"仅显示前 8000 个字符"，模型无法知道自己看到的占全文多少——这正是
    "数行号"的另一半原因。
    """

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        # 这条 run 的 finding 在别的文件上：本次提到的文件属于"未被点名"。
        run_id = _seed_run_with_findings(backend, [("src/flagged.py", 12, 14)])
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        session_id = session["session_id"]
        backend.sessions[session_id].current_run_id = run_id
        content = "\n".join(f"row {index} " + "x" * 40 for index in range(1, 600))
        fetcher = _StubRepoFetcher({"src/plain.py": content})
        monkeypatch.setattr(backend, "_chat_pr_fetcher", lambda: fetcher)
        _point_repo_cache_at(monkeypatch, backend, tmp_path / "cache")
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        response = await backend.handle(_chat_send(session_id, "src/plain.py 讲了什么"))

        assert response[0]["ok"] is True
        prompt = captured["options"]["system_prompt"]
        assert "### src/plain.py" in prompt
        note = re.search(r"（文件共 599 行，此处仅显示前 (\d+) 行）", prompt)
        assert note is not None, "未被点名的文件也必须标注文件总行数与实际给出的行数"
        assert 0 < int(note.group(1)) < 599
        assert "row 1 " in prompt
        assert "row 599 " not in prompt
        # 没被点名 → 不出现窗口文案
        assert "显示第" not in prompt

    asyncio.run(run())


def test_chat_names_the_findings_that_fall_outside_the_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """同一文件里相隔很远的 finding：窗口取首个，其余的只点名行号（不假装给全）。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        run_id = _seed_run_with_findings(
            backend, [("src/big.py", 237, 237), ("src/big.py", 900, 905)]
        )
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        session_id = session["session_id"]
        backend.sessions[session_id].current_run_id = run_id
        content = "\n".join(f"line {index}" for index in range(1, 1001))
        fetcher = _StubRepoFetcher({"src/big.py": content})
        monkeypatch.setattr(backend, "_chat_pr_fetcher", lambda: fetcher)
        _point_repo_cache_at(monkeypatch, backend, tmp_path / "cache")
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        response = await backend.handle(_chat_send(session_id, "src/big.py 的问题在哪几行"))

        assert response[0]["ok"] is True
        prompt = captured["options"]["system_prompt"]
        assert "（显示第 157-317 行，文件共 1000 行；另有 finding 在第 900 行）" in prompt
        assert "line 237" in prompt
        assert "line 900" not in prompt, "窗口外的内容不该被顺带注入"

    asyncio.run(run())


def test_chat_keeps_the_finding_line_when_the_window_overflows_the_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A1：窗口本身超预算时"窗口内再截断"，但**必须先保住 finding 那一行**。

    否则行很长的文件（HTML 常见）会重演同一个 bug：截断把要修的那一行又切掉了。
    """

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        run_id = _seed_run_with_findings(backend, [("website/index.html", 237, 237)])
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        session_id = session["session_id"]
        backend.sessions[session_id].current_run_id = run_id
        content = "\n".join(f"L{index:04d}|" + "y" * 200 for index in range(1, 413))
        fetcher = _StubRepoFetcher({"website/index.html": content})
        monkeypatch.setattr(backend, "_chat_pr_fetcher", lambda: fetcher)
        _point_repo_cache_at(monkeypatch, backend, tmp_path / "cache")
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        response = await backend.handle(_chat_send(session_id, "对应的仓库代码"))

        assert response[0]["ok"] is True
        prompt = captured["options"]["system_prompt"]
        assert "L0237|" in prompt, "finding 所在行必须在注入内容里"
        assert "；窗口 157-317 行已按预算截断）" in prompt
        assert "… [内容已截断" in prompt
        # 标注里的实际范围比窗口窄（如实描述真正注入的内容）
        note = re.search(r"（显示第 (\d+)-(\d+) 行，文件共 412 行；窗口 157-317", prompt)
        assert note is not None
        assert 157 <= int(note.group(1)) <= 237 <= int(note.group(2)) <= 317

    asyncio.run(run())


# ---------------------------------------------------------------------------
# A2/B/C（docs/claude-repo-structure-context.md）：
# finding 文件放开 / PR 变更清单 / 仓库目录树
# ---------------------------------------------------------------------------


def test_chat_findings_fallback_covers_every_named_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A2：12 条 finding 涉及 3 个文件 → 三个文件全部进入注入（旧实现写死 limit=2）。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        run_id = _seed_run_with_findings(
            backend,
            [("src/a.py", line, line) for line in range(1, 6)]
            + [("src/b.py", line, line) for line in range(10, 15)]
            + [("src/c.py", line, line) for line in range(1, 3)],
        )
        assert backend._findings_file_paths(run_id) == ["src/a.py", "src/b.py", "src/c.py"]

        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        session_id = session["session_id"]
        backend.sessions[session_id].current_run_id = run_id
        fetcher = _StubRepoFetcher(
            {path: f"print('{path}')\n" for path in ("src/a.py", "src/b.py", "src/c.py")}
        )
        monkeypatch.setattr(backend, "_chat_pr_fetcher", lambda: fetcher)
        _point_repo_cache_at(monkeypatch, backend, tmp_path / "cache")
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        # 消息里没有文件名：走"对应的仓库代码"兜底到 findings 点名的文件
        response = await backend.handle(_chat_send(session_id, "对应的仓库代码"))

        assert response[0]["ok"] is True
        prompt = captured["options"]["system_prompt"]
        for path in ("src/a.py", "src/b.py", "src/c.py"):
            assert f"### {path}" in prompt, f"{path} 被本次 finding 点名，必须进入注入"

    asyncio.run(run())


def test_chat_findings_fallback_flags_the_file_over_the_char_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A2：三个文件都被点名，但 12000 字符预算只装得下前两个——第三个必须被**如实标注**
    "本轮注入已达上限"，而不是静默消失（否则模型会以为这个文件"没什么可看的"）。"""

    async def run() -> None:
        from ai_pr_review.backend.jsonl_server import CHAT_REPO_FILES_TOTAL_CHARS

        backend = _chat_ready_backend(tmp_path)
        run_id = _seed_run_with_findings(
            backend, [("src/a.py", 1, 1), ("src/b.py", 1, 1), ("src/c.py", 1, 1)]
        )
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        session_id = session["session_id"]
        backend.sessions[session_id].current_run_id = run_id
        # 单行超长文件：第一个占满 8000 的单文件上限，第二个吃掉剩余总量预算
        huge = "A" * 9000
        fetcher = _StubRepoFetcher({"src/a.py": huge, "src/b.py": huge, "src/c.py": huge})
        monkeypatch.setattr(backend, "_chat_pr_fetcher", lambda: fetcher)
        _point_repo_cache_at(monkeypatch, backend, tmp_path / "cache")
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        response = await backend.handle(_chat_send(session_id, "对应的仓库代码"))

        assert response[0]["ok"] is True
        prompt = captured["options"]["system_prompt"]
        assert "### src/a.py" in prompt
        assert "… [内容已截断" in prompt
        assert f"(未能读取 src/c.py：本轮注入已达 {CHAT_REPO_FILES_TOTAL_CHARS} 字符上限)" in prompt

    asyncio.run(run())


def test_chat_injects_the_pr_changed_file_list_every_turn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """B：绑定 run 后每轮注入变更清单（含"另有 N 个被审查跳过"）；首轮拉一次，
    之后命中进程内缓存——同一 run 的 head 提交不会变。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        run_id = _seed_run_with_head(backend, excluded_files=12)
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        session_id = session["session_id"]
        backend.sessions[session_id].current_run_id = run_id
        fetcher = _StubRepoFetcher(changed_files=["src/a.py", "src/b.ts", "docs/design.md"])
        monkeypatch.setattr(backend, "_chat_pr_fetcher", lambda: fetcher)
        _point_repo_cache_at(monkeypatch, backend, tmp_path / "cache")
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        for text in ("这次审查结论是什么", "再说说这次审查的结论"):
            response = await backend.handle(_chat_send(session_id, text))

            assert response[0]["ok"] is True
            prompt = captured["options"]["system_prompt"]
            assert "## 本次 PR 变更文件（共 3 个，另有 12 个被本次审查跳过）" in prompt
            assert "- src/a.py" in prompt
            assert "- docs/design.md" in prompt
            assert "不得臆测" in prompt

        assert fetcher.changed_files_calls == ["https://github.com/example/repo/pull/31"]

    asyncio.run(run())


def test_chat_cools_down_and_recovers_when_the_changed_list_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """B：拉清单失败 → 标注「未能读取变更文件清单」，对话照常、不泄漏异常文案；
    冷却期内不重复打网络，冷却过后自动重试（一次网络抖动不该锁死整个会话）。"""

    async def run() -> None:
        import ai_pr_review.backend.jsonl_server as jsonl

        backend = _chat_ready_backend(tmp_path)
        run_id = _seed_run_with_head(backend)
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        session_id = session["session_id"]
        backend.sessions[session_id].current_run_id = run_id
        fetcher = _StubRepoFetcher(inventory_error=RuntimeError("token=ghp_should_not_leak"))
        monkeypatch.setattr(backend, "_chat_pr_fetcher", lambda: fetcher)
        _point_repo_cache_at(monkeypatch, backend, tmp_path / "cache")
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        for _ in range(2):
            response = await backend.handle(_chat_send(session_id, "这次审查结论是什么"))
            assert response[0]["ok"] is True
        prompt = captured["options"]["system_prompt"]
        assert "（未能读取变更文件清单：RuntimeError）" in prompt
        assert "ghp_should_not_leak" not in prompt
        assert len(fetcher.changed_files_calls) == 1, "冷却期内不该重复打网络"

        # 冷却过后网络恢复：下一轮自动重试并注入
        monkeypatch.setattr(jsonl, "CHAT_INVENTORY_RETRY_SECONDS", 0.0)
        fetcher.inventory_error = None
        fetcher.changed_files = ["src/a.py"]
        response = await backend.handle(_chat_send(session_id, "这次审查结论是什么"))

        assert response[0]["ok"] is True
        assert "## 本次 PR 变更文件（共 1 个）" in captured["options"]["system_prompt"]
        assert len(fetcher.changed_files_calls) == 2

    asyncio.run(run())


def test_chat_truncates_the_changed_file_list_over_the_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """B：变更文件超过上限时只列前 N 个，其余折叠成一行计数（不静默丢弃）。"""

    async def run() -> None:
        from ai_pr_review.backend.jsonl_server import CHAT_PR_FILES_LIMIT

        backend = _chat_ready_backend(tmp_path)
        run_id = _seed_run_with_head(backend)
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        session_id = session["session_id"]
        backend.sessions[session_id].current_run_id = run_id
        fetcher = _StubRepoFetcher(
            changed_files=[f"src/f{index:03d}.py" for index in range(CHAT_PR_FILES_LIMIT + 10)]
        )
        monkeypatch.setattr(backend, "_chat_pr_fetcher", lambda: fetcher)
        _point_repo_cache_at(monkeypatch, backend, tmp_path / "cache")
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        response = await backend.handle(_chat_send(session_id, "这次审查结论是什么"))

        assert response[0]["ok"] is True
        prompt = captured["options"]["system_prompt"]
        assert f"- src/f{CHAT_PR_FILES_LIMIT - 1:03d}.py" in prompt
        assert f"- src/f{CHAT_PR_FILES_LIMIT:03d}.py" not in prompt
        assert f"…（另有 10 个未列出，仅列出前 {CHAT_PR_FILES_LIMIT} 个）" in prompt

    asyncio.run(run())


def test_chat_never_fetches_inventory_without_a_bound_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """未绑定 run：变更清单与目录树都不注入、都不打 GitHub（哪怕消息里全是结构关键词）。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        session_id = session["session_id"]
        fetcher = _StubRepoFetcher(changed_files=["a.py"], tree_paths=["a.py"])
        monkeypatch.setattr(backend, "_chat_pr_fetcher", lambda: fetcher)
        _point_repo_cache_at(monkeypatch, backend, tmp_path / "cache")
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        response = await backend.handle(
            _chat_send(session_id, "这个仓库的目录结构、文件列表给我看看")
        )

        assert response[0]["ok"] is True
        prompt = captured["options"]["system_prompt"]
        assert "## 本次 PR 变更文件" not in prompt
        assert "## 仓库目录树" not in prompt
        assert fetcher.changed_files_calls == []
        assert fetcher.tree_calls == []

    asyncio.run(run())


def test_chat_injects_the_repo_tree_only_when_the_user_asks_about_structure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """C：目录树按意图触发——普通问题不注入（也不打 GitHub），问到结构才注入（且只拉一次）。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        run_id = _seed_run_with_head(backend)
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        session_id = session["session_id"]
        backend.sessions[session_id].current_run_id = run_id
        fetcher = _StubRepoFetcher(tree_paths=["src/app.py", "src/pkg/mod.py", "README.md"])
        monkeypatch.setattr(backend, "_chat_pr_fetcher", lambda: fetcher)
        _point_repo_cache_at(monkeypatch, backend, tmp_path / "cache")
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        # (1) 普通问题：不注入、不打 GitHub
        response = await backend.handle(_chat_send(session_id, "这次审查的结论是什么"))
        assert response[0]["ok"] is True
        assert fetcher.tree_calls == []
        assert "## 仓库目录树" not in captured["options"]["system_prompt"]

        # (2) 问到结构：注入目录树（head 提交 + 嵌套格式）
        response = await backend.handle(_chat_send(session_id, "这个仓库的目录结构是怎样的？"))
        assert response[0]["ok"] is True
        prompt = captured["options"]["system_prompt"]
        assert "## 仓库目录树（head 提交 bbbbbbbb · 深度 ≤3 · 最多 200 行）" in prompt
        assert "src/" in prompt
        assert "  pkg/" in prompt
        assert "    mod.py" in prompt
        assert "README.md" in prompt
        assert fetcher.tree_calls == [("example", "repo", "b" * 40)]

        # (3) 再问一次结构：命中进程内缓存，不再拉
        response = await backend.handle(_chat_send(session_id, "还有哪些文件"))
        assert response[0]["ok"] is True
        assert len(fetcher.tree_calls) == 1

    asyncio.run(run())


def test_chat_reports_a_repo_tree_it_could_not_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """C：tree 拉取失败 / 老 run 没记 head_sha → 各自的降级文案，对话照常。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        run_id = _seed_run_with_head(backend)
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        session_id = session["session_id"]
        backend.sessions[session_id].current_run_id = run_id
        fetcher = _StubRepoFetcher(inventory_error=RuntimeError("boom-detail-should-not-leak"))
        monkeypatch.setattr(backend, "_chat_pr_fetcher", lambda: fetcher)
        _point_repo_cache_at(monkeypatch, backend, tmp_path / "cache")
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        response = await backend.handle(_chat_send(session_id, "仓库目录结构是什么"))

        assert response[0]["ok"] is True
        prompt = captured["options"]["system_prompt"]
        assert "（未能读取仓库目录树：RuntimeError）" in prompt
        assert "boom-detail-should-not-leak" not in prompt

        # 老 run 没记 head_sha：写明原因，且不再打 GitHub
        old_run = _seed_run(backend, 29, "旧审查")
        backend.sessions[session_id].current_run_id = old_run
        fetcher.tree_calls.clear()
        response = await backend.handle(_chat_send(session_id, "仓库目录结构是什么"))

        assert response[0]["ok"] is True
        assert (
            "（未能读取仓库目录树：该 Run 未记录仓库 / head 提交）"
            in captured["options"]["system_prompt"]
        )
        assert fetcher.tree_calls == []

    asyncio.run(run())


def test_chat_session_is_persisted_and_restored_by_a_new_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A2 → 契约 v1 §A：会话落盘（role/content/timestamp），backend 重启后接着聊。

    只存对话本身：system prompt（含审查上下文与注入的源码）每轮现算，绝不落盘——
    落了盘会让历史重复膨胀、重复计费，还会让注入的源码在后续轮次里"阴魂不散"。
    恢复路径从"`session.create` 自动续上那唯一一个会话"改成
    `session.list`（拿到 current）→ `session.switch`（载入历史），见 A 组协议。
    """

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        session_id = session["session_id"]
        assert session["messages"] == []
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        response = await backend.handle(_chat_send(session_id, "第一个问题"))
        assert response[0]["ok"] is True

        # 契约 v1 的存储布局：`<config 同目录>/sessions/<id>.json`（不再是单文件）
        session_path = tmp_path / "sessions" / f"{session_id}.json"
        document = json.loads(session_path.read_text(encoding="utf-8"))
        assert document["id"] == session_id
        payload = document["messages"]
        assert [message["role"] for message in payload] == ["user", "assistant"]
        assert payload[0]["content"] == "第一个问题"
        assert payload[1]["content"] == "stub"
        assert all(
            set(message) <= {"role", "content", "timestamp", "duration_seconds"}
            for message in payload
        ), "落盘字段仅限 role/content/timestamp（assistant 另有既有格式的 duration_seconds）"
        assert all(message["timestamp"] for message in payload)
        assert "请默认使用中文回答" not in session_path.read_text(encoding="utf-8")

        # 新实例（TUI 重启）：`session.list` 指出当前会话，`session.switch` 载入它的历史。
        # 本例没有绑定过 run，恢复后仍是普通聊天（绑定随会话走见单独的用例）。
        restarted = _chat_ready_backend(tmp_path)
        listing = (await restarted.handle({"id": "s", "method": "session.list"}))[0]["result"]
        assert listing["current"] == session_id
        assert [item["id"] for item in listing["sessions"]] == [session_id]
        restored = (
            await restarted.handle(
                {"id": "s", "method": "session.switch", "params": {"session_id": session_id}}
            )
        )[0]["result"]
        assert [message["role"] for message in restored["messages"]] == ["user", "assistant"]
        assert restored["messages"][0]["content"] == "第一个问题"
        assert restored["session"]["id"] == session_id
        assert restarted.sessions[session_id].current_run_id is None

    asyncio.run(run())


def test_new_command_creates_and_switches_without_dropping_the_old_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """契约 v1：`/new` = `session.create`（**新建并切换**），旧会话一条不丢。

    旧实现在这里 `clear_chat_session`——新会话要开，代价却是把唯一的会话删掉。现在
    `/new` 只是切换：旧会话留在 `sessions/` 里，`/sessions` 随时切得回去。
    """

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        session_id = session["session_id"]
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)
        await backend.handle(_chat_send(session_id, "第一轮"))
        old_path = tmp_path / "sessions" / f"{session_id}.json"
        assert old_path.exists()

        reply = await _execute_async(backend, "new", [])
        new_id = reply["result"]["session_id"]
        assert reply["result"]["messages"] == []
        assert reply["result"]["session"]["id"] == new_id
        assert new_id != session_id, "`/new` 必须真的新建，而不是复用/清空当前会话"
        assert old_path.exists(), "旧会话必须留在盘上（`/sessions` 要能切回去）"
        assert (
            json.loads(old_path.read_text(encoding="utf-8"))["messages"][0]["content"] == "第一轮"
        ), "旧会话的历史必须原样保留"

        listing = (await backend.handle({"id": "s", "method": "session.list"}))[0]["result"]
        assert listing["current"] == new_id
        assert {item["id"] for item in listing["sessions"]} == {session_id, new_id}

        # 重启后旧会话照样切得回来——"/new 没删东西"必须在**新进程**里也成立。
        restarted = _chat_ready_backend(tmp_path)
        restored = (
            await restarted.handle(
                {"id": "s", "method": "session.switch", "params": {"session_id": session_id}}
            )
        )[0]["result"]
        assert restored["messages"][0]["content"] == "第一轮"

    asyncio.run(run())


# ---------------------------------------------------------------------------
# 会话协议 v1（docs/session-and-compaction-plan.md §A3；四条线共用的字段名不可改）
# ---------------------------------------------------------------------------


def test_session_list_returns_the_contract_shape(tmp_path: Path) -> None:
    """`session.list` → `{sessions: [{id,title,updated_at,message_count,current}], current}`。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        created = await backend.handle({"id": "s", "method": "session.create", "params": {}})
        session_id = created[0]["result"]["session_id"]

        reply = (await backend.handle({"id": "s", "method": "session.list", "params": {}}))[0]
        assert reply["ok"] is True
        listing = reply["result"]
        assert set(listing) == {"sessions", "current"}
        assert listing["current"] == session_id
        item = listing["sessions"][0]
        # 列表项**恰好**这五个键：多出来的字段会让契约的"同键同形"失效。
        assert set(item) == {"id", "title", "updated_at", "message_count", "current"}
        assert item["id"] == session_id
        assert item["current"] is True
        assert item["message_count"] == 0

        # 空列表也要是合法的列表（TUI 走空态文案，不是错误分支）
        backend.session_store.delete(session_id)
        empty = (await backend.handle({"id": "s", "method": "session.list", "params": {}}))[0]
        assert empty["result"] == {"sessions": [], "current": ""}

    asyncio.run(run())


def test_session_switch_persists_the_outgoing_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """契约 v1：`session.switch` **先落盘当前会话**，再载入目标并激活。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        first = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)
        await backend.handle(_chat_send(first["session_id"], "第一个会话说过的话"))
        second = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]

        # 模拟"内存里有一轮还没落盘"：切换前它必须被写回磁盘
        backend.sessions[second["session_id"]].messages = [
            {"role": "user", "content": "只存在内存里的一句", "timestamp": "2026-01-01"}
        ]
        switched = (
            await backend.handle(
                {
                    "id": "s",
                    "method": "session.switch",
                    "params": {"session_id": first["session_id"]},
                }
            )
        )[0]["result"]
        assert switched["session"]["id"] == first["session_id"]
        assert switched["session"]["current"] is True
        assert switched["messages"][0]["content"] == "第一个会话说过的话"
        assert backend.session_store.current_id() == first["session_id"]
        persisted = json.loads(
            (tmp_path / "sessions" / f"{second['session_id']}.json").read_text(encoding="utf-8")
        )
        assert persisted["messages"][0]["content"] == "只存在内存里的一句", "切换必须先落盘"

        missing = (
            await backend.handle(
                {"id": "s", "method": "session.switch", "params": {"session_id": "s99"}}
            )
        )[0]
        assert missing["ok"] is False
        assert missing["error"]["code"] == "not_found"

    asyncio.run(run())


def test_session_switch_restores_the_review_binding(tmp_path: Path) -> None:
    """契约 v1：`current_run_id`（review 绑定）**随会话走**——切回来还在。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        first = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        second = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        run_id = _seed_run(backend, 31, "新审查")

        backend.sessions[first["session_id"]].current_run_id = run_id
        backend._persist_session(backend.sessions[first["session_id"]])
        assert backend.session_store.get(first["session_id"])["current_run_id"] == run_id

        # 切走再切回：内存里的 Session 被复用，绑定原样还在
        await backend.handle(
            {"id": "s", "method": "session.switch", "params": {"session_id": second["session_id"]}}
        )
        back = (
            await backend.handle(
                {
                    "id": "s",
                    "method": "session.switch",
                    "params": {"session_id": first["session_id"]},
                }
            )
        )[0]["result"]
        assert backend.sessions[first["session_id"]].current_run_id == run_id
        assert back["session"]["current_run_id"] == run_id

        # 新进程（TUI 重启）从盘上载入，绑定同样恢复
        restarted = _chat_ready_backend(tmp_path)
        resumed = (
            await restarted.handle(
                {
                    "id": "s",
                    "method": "session.switch",
                    "params": {"session_id": first["session_id"]},
                }
            )
        )[0]["result"]
        assert restarted.sessions[first["session_id"]].current_run_id == run_id
        assert resumed["session"]["current_run_id"] == run_id

    asyncio.run(run())


def test_session_rename_and_delete_over_the_protocol(tmp_path: Path) -> None:
    """`session.rename` → `{id,title}`；`session.delete` → `{deleted, next}`（删当前自动切换）。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        first = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        second = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]

        renamed = (
            await backend.handle(
                {
                    "id": "s",
                    "method": "session.rename",
                    "params": {"session_id": first["session_id"], "title": "  标题带空格  "},
                }
            )
        )[0]
        assert renamed["result"] == {"id": first["session_id"], "title": "标题带空格"}
        listing = (await backend.handle({"id": "s", "method": "session.list"}))[0]["result"]
        titles = {item["id"]: item["title"] for item in listing["sessions"]}
        assert titles[first["session_id"]] == "标题带空格"

        blank = (
            await backend.handle(
                {
                    "id": "s",
                    "method": "session.rename",
                    "params": {"session_id": first["session_id"], "title": "   "},
                }
            )
        )[0]
        assert blank["ok"] is False and blank["error"]["code"] == "invalid_request"

        # 删**当前**会话：自动切到最近一个（本例是 first，因为 rename 刷新了 updated_at）
        deleted = (
            await backend.handle(
                {
                    "id": "s",
                    "method": "session.delete",
                    "params": {"session_id": second["session_id"]},
                }
            )
        )[0]["result"]
        assert deleted == {"deleted": second["session_id"], "next": first["session_id"]}
        assert backend.session_store.current_id() == first["session_id"]
        assert second["session_id"] not in backend.sessions, "内存里那份也要丢"

        unknown = (
            await backend.handle(
                {"id": "s", "method": "session.delete", "params": {"session_id": "s99"}}
            )
        )[0]
        assert unknown["ok"] is False and unknown["error"]["code"] == "not_found"
        # 非法 id（路径穿越）与"不存在"同义：不能漏出内部 ValueError
        for method in ("session.delete", "session.switch", "session.get", "session.rename"):
            bad = (
                await backend.handle(
                    {
                        "id": "s",
                        "method": method,
                        "params": {"session_id": "../escape", "title": "x"},
                    }
                )
            )[0]
            assert bad["ok"] is False, method
            assert bad["error"]["code"] in {"not_found", "invalid_request"}, (method, bad)

    asyncio.run(run())


def test_session_create_switches_and_keeps_the_legacy_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`session.create` 既给契约 v1 的 `session`，也保留旧的顶层键（TUI 现行代码在读）。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        created = (await backend.handle({"id": "s", "method": "session.create", "params": {}}))[0]
        result = created["result"]
        assert result["session_id"] == result["session"]["id"]
        assert result["session"]["current"] is True
        assert result["messages"] == []
        assert "title" in result["session"]

        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)
        sent = await backend.handle(_chat_send(result["session_id"], "记一笔"))
        assert sent[0]["ok"] is True
        listing = (await backend.handle({"id": "s", "method": "session.list"}))[0]["result"]
        assert listing["sessions"][0]["title"] == "记一笔", "首条用户消息要变成默认标题"

    asyncio.run(run())


def test_legacy_chat_session_json_is_migrated_when_the_backend_starts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """契约 v1 §A：旧 `chat_session.json` **首次启动**迁移为 legacy 会话。

    这里走真正的启动函数 `serve()`（把 stdin 换成空流让它读到 EOF 立刻收尾）——
    只测 `migrate_legacy()` 本身证明不了"启动时确实会调用它"。
    """
    import io

    from ai_pr_review.backend.jsonl_server import serve

    config_path = tmp_path / "config.json"
    (tmp_path / "chat_session.json").write_text(
        json.dumps(
            [
                {"role": "user", "content": "迁移前的问题", "timestamp": "2026-01-01T00:00:00"},
                {
                    "role": "assistant",
                    "content": "迁移前的回答",
                    "timestamp": "2026-01-01T00:00:01",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    monkeypatch.setattr("sys.stdout", io.StringIO())
    asyncio.run(serve(config_path))

    backend = JsonlBackend(config_path, event_sink=lambda event: None)
    listing = asyncio.run(backend.handle({"id": "s", "method": "session.list"}))[0]["result"]
    assert [item["title"] for item in listing["sessions"]] == ["legacy"]
    assert listing["current"] == "s1"
    restored = asyncio.run(
        backend.handle({"id": "s", "method": "session.switch", "params": {"session_id": "s1"}})
    )[0]["result"]
    assert restored["messages"][0]["content"] == "迁移前的问题"
    assert (tmp_path / "chat_session.json").exists(), "迁移只读旧文件，CLI 仍要用它"

    # 第二次启动不会再多出一个 legacy 会话
    asyncio.run(serve(config_path))
    again = asyncio.run(
        JsonlBackend(config_path, event_sink=lambda event: None).handle(
            {"id": "s", "method": "session.list"}
        )
    )[0]["result"]
    assert len(again["sessions"]) == 1


def test_chat_history_window_is_80_messages_and_the_trim_is_announced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A3：历史窗口 40 → 80 条；裁剪时**明确告知**，不再静默丢弃（旧实现用户只看到模型失忆）。"""
    from ai_pr_review.backend.jsonl_server import CHAT_HISTORY_MESSAGE_LIMIT

    assert CHAT_HISTORY_MESSAGE_LIMIT == 80

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        session_id = session["session_id"]
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        texts: list[str] = []
        for index in range(41):  # 40 轮 = 80 条（正好到上限），第 41 轮触发裁剪
            response = await backend.handle(_chat_send(session_id, f"第 {index} 问"))
            assert response[0]["ok"] is True
            texts.append(str(response[0]["result"]["text"]))

        # 满 80 条之前不得出现提示（不制造噪音）
        assert all("对话历史超过" not in text for text in texts[:40])
        messages = backend.sessions[session_id].messages
        assert len(messages) == CHAT_HISTORY_MESSAGE_LIMIT
        # 82 条 → 丢最旧 2 条，并在**回答之后**明说（提示是后缀，不能挤在回答前面）
        assert texts[40].endswith(
            "\n\n（对话历史超过 80 条，最旧的 2 条已不进入本轮上下文；/new 可开始新会话）"
        )
        assert texts[40].startswith("stub")
        # 提示只进 UI：落盘的 transcript 仍是干净的一问一答
        payload = json.loads(
            (tmp_path / "sessions" / f"{session_id}.json").read_text(encoding="utf-8")
        )["messages"]
        assert len(payload) == CHAT_HISTORY_MESSAGE_LIMIT
        assert all("对话历史超过" not in message["content"] for message in payload)

    asyncio.run(run())


def test_chat_context_budget_can_be_set_in_the_config_file(tmp_path: Path) -> None:
    """A3：`chat_context_budget` 可配（字段现已进 `PreferencesConfig`，值仍以文件为准）。

    `AppConfig.load` 会过滤未知键、也会把非法值归一化成默认值，所以后端另外读一次文件
    字面量：为的是把"没配"和"配坏了"分开——配坏了照旧退回默认，绝不因为读不懂配置
    就把预算放大（docs/claude-backend-followup.md §4.4）。
    """
    config_path = tmp_path / "config.json"

    def write_budget(value: Any) -> None:
        config_path.write_text(
            json.dumps({"preferences": {"chat_context_budget": value}}), encoding="utf-8"
        )

    write_budget(1200)
    backend = JsonlBackend(config_path)
    assert backend._chat_context_budget_plan() == (1200, "config")
    # 生效到真正用预算的地方（/context 的 token 预算展示）
    assert backend._context_status(None)["token_budget"] == 1200
    assert backend._context_status(None)["budget_source"] == "config"

    for bad in (0, -5, "abc", None, [1200]):
        write_budget(bad)
        assert JsonlBackend(config_path)._chat_context_budget_plan() == (8000, "fallback")

    # 配置文件不存在/读不动：不抛，退回兜底预算。
    assert JsonlBackend(tmp_path / "missing.json")._chat_context_budget_plan() == (
        DEFAULT_CHAT_BUDGET,
        "fallback",
    )


def test_chat_context_budget_follows_a_user_written_spec(tmp_path: Path) -> None:
    """§4：没显式配置时，预算按**聊天槽**模型写过的规格窗口推算，并报出来源。

    系数 0.5：预算是"注入审查上下文"的额度，system prompt 骨架、对话历史与回答同样
    占同一个窗口，只给一半才不会为了塞满上下文把回答挤没；上限 200_000 与
    `preferences.chat_context_budget` 的合法上界一致（再大只是每轮多花钱）。
    """
    # 中转站模型（没有内置预设）：用户在助手里填的 200_000/16_384 就是唯一真源。
    backend = _relay_backend_with_spec(tmp_path, context_window=200_000, max_output=16_384)
    assert backend._chat_context_budget_plan() == (100_000, "model_spec")

    # 1M 窗口按上限截到 200_000，不是 524_288。
    backend.config.provider.set_model_spec("relay-model", context_window=1_048_576)
    assert backend._chat_context_budget_plan() == (200_000, "model_spec")

    # 小窗口模型（8_192）算出来 4_096，比默认 8_000 更小——这类模型本来就不该按
    # 8_000 塞上下文（那会连回答一起挤掉）。
    small = _relay_backend_with_spec(tmp_path / "small", context_window=8_192, max_output=1_024)
    assert small._chat_context_budget_plan() == (4_096, "model_spec")


def test_chat_context_budget_follows_the_catalog_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """目录同步过（配置助手打开过）之后，预算按目录命中的模型窗口重算（§4.2）。

    这条路径只在**本次进程**取过数时生效：目录不可用时退回 8000（现状），
    不拿预设表当用户的规格（见下一条用例）。
    """

    async def run() -> None:
        backend = _deepseek_backend(tmp_path)
        # 没有目录：退回兜底（deepseek-flash 的 1M 只是我们写的预设，不算用户规格）。
        assert backend._chat_context_budget_plan() == (8_000, "fallback")

        calls = _stub_catalog(monkeypatch)
        await backend.handle({"id": "1", "method": "config.options", "params": {}})
        assert calls["fetch"] == 1
        assert backend._catalog_state is not None

        # 生效值仍是落盘/预设的值（§2.8 目录不覆盖生效值）：1_048_576 的一半 =
        # 524_288 被上限截到 200_000。
        assert backend._chat_context_budget_plan() == (200_000, "model_spec")
        # 只碰进程内索引，不因为算预算再取一次数。
        assert calls["fetch"] == 1

    asyncio.run(run())


def test_chat_context_budget_falls_back_for_an_unknown_model(tmp_path: Path) -> None:
    """模型规格不可信时退回默认 8000（现状），来源如实报 `fallback`。

    `deepseek-chat` 的条目是 `from_model_provider` 写的 `32_768/4_096` 兜底值，
    按它推算会把预算从 8_000 抬到 16_384——凭空猜测，与 §2.8"不猜"相反。
    预设表同样不参与放大：那是我们自己填的数字，不是用户的选择（§4.3）。
    """
    from ai_pr_review.config import ModelProviderConfig, ProviderConfig

    backend = JsonlBackend(tmp_path / "config.json")
    backend.config.provider = ProviderConfig.from_model_provider(
        ModelProviderConfig.from_name("deepseek")
    )
    backend.config._sync_runtime_sections()
    assert backend.config.provider.default_model == "deepseek-chat"
    assert backend._chat_context_window() is None
    assert backend._chat_context_budget_plan() == (8_000, "fallback")

    # 有预设、但条目与预设一致（= 我们自动写的）时同样不放大。
    preset_backed = JsonlBackend(tmp_path / "preset.json")
    preset_backed.config.provider = ProviderConfig.from_model_provider(
        ModelProviderConfig.from_name("deepseek", model_name="deepseek-flash", api_key="k")
    )
    preset_backed.config._sync_runtime_sections()
    assert preset_backed._chat_max_output() == 384_000  # 封顶这条路径信任预设
    assert preset_backed._chat_context_window() is None  # 放大这条路径不信任预设
    assert preset_backed._chat_context_budget_plan() == (8_000, "fallback")

    # 用户显式填过规格（哪怕模型不在预设表里）就重新可信 —— 中转站的 B3 路径。
    backend.config.provider.set_model_spec("deepseek-chat", context_window=64_000)
    assert backend._chat_context_window() == 64_000
    assert backend._chat_context_budget_plan() == (32_000, "model_spec")


def test_chat_context_budget_source_vocabulary_is_pinned(tmp_path: Path) -> None:
    """来源取值三选一；`/context` 与 `config.snapshot` 两处出口都带它（前端只渲染不推导）。

    `assistant.finished.context` 是契约 v1 冻结的五键，**不**承载来源（§4.5）。
    """
    from ai_pr_review.backend import jsonl_server

    assert jsonl_server.CHAT_BUDGET_SOURCES == ("config", "model_spec", "fallback")

    backend = JsonlBackend(tmp_path / "config.json")
    status = backend._context_status(None)
    assert status["budget_source"] == "fallback"
    assert status["token_budget"] == backend._chat_context_budget_plan()[0]
    snapshot = backend._config_snapshot()
    assert snapshot["chat_context_budget_source"] == "fallback"
    assert snapshot["chat_context_budget"] == DEFAULT_CHAT_BUDGET

    backend.config.preferences.chat_context_budget = 4_000
    assert backend._context_status(None)["budget_source"] == "config"
    assert backend._config_snapshot()["chat_context_budget_source"] == "config"


def test_chat_reasoning_stream_is_separated_from_answer_and_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """C5/C4：思考只走独立事件，绝不进入正文或 session.messages。"""
    from ai_pr_review.services.model_providers.base import ProviderResponse

    async def run() -> None:
        published: list[dict[str, Any]] = []
        backend = JsonlBackend(tmp_path / "config.json", event_sink=published.append)
        backend.config.provider.api_key = "test-key"
        backend.config._sync_runtime_sections()
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]

        class ThinkingProvider:
            async def stream_chat(self, messages, on_delta, **kwargs):
                await kwargs["on_reasoning"]("internal thought")
                await on_delta("visible answer")
                return ProviderResponse(
                    text="visible answer",
                    usage={
                        "prompt_tokens": 20,
                        "completion_tokens": 10,
                        "total_tokens": 30,
                    },
                    reasoning="internal thought",
                )

        monkeypatch.setattr(
            "ai_pr_review.backend.jsonl_server.create_model_provider",
            lambda config: ThinkingProvider(),
        )
        response = await backend.handle(
            {
                "id": "turn",
                "method": "chat.send",
                "params": {"session_id": session["session_id"], "text": "hello"},
            }
        )
        by_event: dict[str, Any] = {item["event"]: item for item in published}
        reasoning_event = published[1]
        assert reasoning_event["event"] == "assistant.reasoning_delta"
        assert reasoning_event["request_id"] == "turn"
        assert reasoning_event["text"] == "internal thought"
        assert by_event["assistant.delta"]["text"] == "visible answer"
        finished = by_event["assistant.finished"]
        assert finished["reasoning"] == "internal thought"
        assert isinstance(finished["duration_seconds"], float)
        assert finished["usage"] == {
            "prompt_tokens": 20,
            "completion_tokens": 10,
            "total_tokens": 30,
        }
        assert finished["context"]["used_tokens"] == 20
        # 契约 v1 扩展（2026-09-26）：`context` 六键，新增 `budget_source`
        # （config|model_spec|fallback）；订阅事件的消费方不必再发 `/context`。
        # 2026-09-27 再扩一键 `pressure`（low|medium|high|critical|null，契约 v1 §C）。
        assert set(finished["context"]) == {
            "used_tokens",
            "budget_tokens",
            "used_percent",
            "trimmed_messages",
            "compacted",
            "budget_source",
            "pressure",
        }
        # 20 / 8000 = 0.25% → 最低档
        assert finished["context"]["pressure"] == "low"
        assert finished["context"]["budget_tokens"] == DEFAULT_CHAT_BUDGET
        assert finished["warning"] is None
        assert response[0]["result"]["text"] == "visible answer"
        assert backend.sessions[session["session_id"]].messages[-1]["content"] == "visible answer"

    asyncio.run(run())


def test_think_persists_for_a_supported_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """C6：`/think` 写入偏好并落盘。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        reply = await _execute_async(backend, "think", ["low"])
        assert reply["ok"] is True
        assert reply["result"]["kind"] == "think"
        assert reply["result"]["state"] == "set"
        assert reply["result"]["effort"] == "low"
        payload = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
        assert payload["preferences"]["chat_reasoning_effort"] == "low"

    asyncio.run(run())


def test_think_is_unsupported_for_ollama(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """C6：本地 OpenAI 兼容端点置灰，不写偏好。"""

    async def run() -> None:
        backend = JsonlBackend(tmp_path / "config.json")
        backend._apply_setup({"runtime_profile": "local", "local_model": "qwen3.5:4b"})
        reply = await _execute_async(backend, "think", ["max"])
        assert reply["ok"] is True
        assert reply["result"]["state"] == "unsupported"
        # 2026-09-26 用户裁定"不开放"：本地固定快速模式是产品决策，不是端点限制
        # （实测流式 think=false 生效，见 docs/chat-live-verification.md）。
        assert "本地模型固定使用快速模式" in reply["result"]["reason"]
        payload = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
        assert payload["preferences"]["chat_reasoning_effort"] == "auto"

    asyncio.run(run())


def test_chat_reasoning_params_follow_the_provider_spec(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """C6 → 数据驱动：档位参数按**供应商规格**注入（`services/reasoning_specs.py`）。

    默认后端是 anthropic 预设里的 claude-sonnet-4-20250514（`max_output = 8_192`）：
    官方只认 `thinking: {type, budget_tokens}`（调研 §3.1），`reasoning_effort` 对它无效
    ——正是"界面切换了、参数没生效"的那一类供应商。预算字段走 provider 配置的
    `extra_params`（OpenAI 兼容与 Anthropic 两家 provider 都会把它并进请求体：
    openai.py 的 `{**self.config.extra_params}` / anthropic.py 的
    `messages.create(**self.config.extra_params)`）。

    预留之后还要过模型规格的 `max_output`（§2）：`4_096 + 12_000` 会被封顶到 8_192，
    再按官方约束 `budget_tokens < max_tokens` 与回答额度收敛。
    """

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)
        base_budget = backend.config.ai_client.max_tokens
        assert backend._chat_max_output() == 8_192

        await _execute_async(backend, "think", ["off"])
        await backend.handle(_chat_send(session["session_id"]))
        # off = thinking disabled（官方关闭方式），不再发 reasoning_effort。
        assert "reasoning_effort" not in captured["options"]
        assert captured["config"].extra_params["thinking"] == {"type": "disabled"}
        # off 档没有预留，4_096 本来就在规格之内：请求体与改造前一致。
        assert captured["options"]["max_tokens"] == base_budget

        await _execute_async(backend, "think", ["max"])
        await backend.handle(_chat_send(session["session_id"], "again"))
        assert "reasoning_effort" not in captured["options"]
        # 8_192 - 4_096（回答额度）= 4_096 才是留给思考的空间：12_000 的上限被它收敛。
        assert captured["config"].extra_params["thinking"] == {
            "type": "enabled",
            "budget_tokens": 4_096,
        }
        assert captured["options"]["max_tokens"] == 8_192
        assert captured["options"]["max_tokens"] < base_budget + 12_000

    asyncio.run(run())


def test_chat_injects_deepseek_reasoning_params_at_the_wire(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """真 provider + stub `urlopen`：规格表算出的参数必须真的出现在请求体里。

    `_chat` 把参数拆到两条通道——`reasoning_effort` 走 kwargs 白名单，`thinking` 走
    provider 配置的 `extra_params`；只断言 kwargs 会漏掉后半句，而"参数没生效"正是
    本次要修的 bug。DeepSeek 四档是**既有行为**（off 关、low/high/max 直传并预留）。
    """

    async def run() -> None:
        from ai_pr_review.config import ModelProviderConfig, ProviderConfig

        backend = JsonlBackend(tmp_path / "config.json", event_sink=lambda event: None)
        backend.config.provider = ProviderConfig.from_model_provider(
            ModelProviderConfig.from_name(
                "deepseek", api_key="test-key", model_name="deepseek-flash"
            )
        )
        backend.config._sync_runtime_sections()
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        payloads: list[dict[str, Any]] = []

        class StreamResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def __iter__(self):
                yield b'data: {"choices":[{"delta":{"content":"ok"}}]}\n'
                yield b"data: [DONE]\n"

        def fake_urlopen(req, **kwargs):
            payloads.append(json.loads(req.data.decode()))
            return StreamResponse()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        base_budget = backend.config.ai_client.max_tokens

        backend.config.preferences.chat_reasoning_effort = "high"
        response = await backend.handle(_chat_send(session["session_id"]))
        assert response[0]["ok"] is True
        assert payloads[0]["thinking"] == {"type": "enabled"}
        assert payloads[0]["reasoning_effort"] == "high"
        # 预留照旧（deepseek-flash 的规格上限 384_000 不会封顶）。
        assert payloads[0]["max_tokens"] == base_budget + 8_000

        backend.config.preferences.chat_reasoning_effort = "off"
        await backend.handle(_chat_send(session["session_id"], "again"))
        assert payloads[1]["thinking"] == {"type": "disabled"}
        assert "reasoning_effort" not in payloads[1]
        assert payloads[1]["max_tokens"] == base_budget

    asyncio.run(run())


def _relay_backend_with_spec(
    tmp_path: Path, *, context_window: int | None = None, max_output: int | None = None
) -> JsonlBackend:
    """聊天槽 = 中转站模型，并按参数写入显式规格（`set_model_spec` 只写非 None 的项）。"""
    from ai_pr_review.config import AIClientConfig, ProviderConfig

    backend = JsonlBackend(tmp_path / "config.json")
    backend.config.ai_client = AIClientConfig(
        provider="custom",
        api_key="relay-key",
        model="relay-model",
        base_url="https://relay.example.com/v1",
        api_format="openai",
    )
    backend.config.provider = ProviderConfig.from_model_provider(
        backend.config.ai_client.model_provider
    )
    backend.config.provider.set_model_spec(
        "relay-model", context_window=context_window, max_output=max_output
    )
    backend.config._sync_runtime_sections()
    return backend


def test_chat_max_tokens_follows_the_model_spec(tmp_path: Path) -> None:
    """§2：chat 的输出额度封顶到规格 `max_output`（回答 + 思考共用这一个额度）。

    等价于 `min(ai_client.max_tokens, max_output - 思考预算) + 思考预算`：改造前
    `4_096 + 8_000 = 12_096` 会原样发给一个 `max_output = 3_000` 的模型，云端端点直接拒收。
    """
    base = JsonlBackend(tmp_path / "config.json").config.ai_client.max_tokens
    assert base == 4_096

    backend = _relay_backend_with_spec(tmp_path, context_window=200_000, max_output=3_000)
    assert backend._chat_max_tokens(reasoning_budget=0) == 3_000
    assert backend._chat_max_tokens(reasoning_budget=8_000) == 3_000
    # 只读规格，绝不改用户的 ai_client 配置（审查链路继续用它）。
    assert backend.config.ai_client.max_tokens == base

    # 思考预算 ≥ max_output：总额度就是 max_output（绝不出现负数，也不越过规格）。
    assert backend._chat_max_tokens(reasoning_budget=12_000) == 3_000

    # 规格足够大时不封顶：预留照旧全额生效。
    roomy = _relay_backend_with_spec(tmp_path, context_window=200_000, max_output=64_000)
    assert roomy._chat_max_tokens(reasoning_budget=12_000) == base + 12_000


def test_chat_max_tokens_leaves_untrusted_specs_and_local_endpoints_alone(
    tmp_path: Path,
) -> None:
    """规格不可信或端点是本地时保持现状（§2.3）。

    - `deepseek-chat` 那条 `32_768/4_096` 只是 `from_model_provider` 给不认识的模型写的
      dataclass 兜底，不是"知道这个模型"——拿它封顶会让回答额度凭 4_096 缩水；
    - Ollama 这类本地端点不会因超限报错，且 §C6 的实测结论（预留不足时思考吃满额度、
      答案为空）正是靠这份预留换来的。
    """
    from ai_pr_review.config import ModelProviderConfig, ProviderConfig

    base = JsonlBackend(tmp_path / "config.json").config.ai_client.max_tokens

    untrusted = JsonlBackend(tmp_path / "untrusted.json")
    untrusted.config.provider = ProviderConfig.from_model_provider(
        ModelProviderConfig.from_name("deepseek")
    )
    untrusted.config._sync_runtime_sections()
    assert untrusted._chat_slot_provider().model_name == "deepseek-chat"
    assert untrusted._chat_max_output() is None
    assert untrusted._chat_max_tokens(reasoning_budget=12_000) == base + 12_000

    local = JsonlBackend(tmp_path / "local.json")
    local.config.preferences.chat_slot = "local"
    local.config._sync_runtime_sections()
    assert local._chat_slot_provider().name == "ollama"
    # 本地模型的预设规格对**封顶**是可信的……
    assert local._chat_max_output() == 1_024
    # ……但输出额度不封顶：1_024 是我们自己写死的猜测，不是端点限制。
    assert local._chat_max_tokens(reasoning_budget=8_000) == base + 8_000


def test_chat_spec_never_trusts_auto_written_or_malformed_entries(tmp_path: Path) -> None:
    """回归：自动写入的条目、以及手改坏了的条目，都不得被当成"用户的规格"。

    两条真实路径（2026-09-26 复检发现）：

    1. `config import` 的 payload 没带 `models` 时，`ensure_default_model_present()` 会给
       默认模型补一条 `32_768/4_096`。若把它当"用户规格"，预算会凭 32_768 翻到 16_384、
       封顶还会把默认安装的回答额度砍到 4_096（连思考预留一起吃掉）；
    2. 手改配置写下 `max_output: null` 时，`int(None)` 会让 `config.snapshot` /
       `model.status` 这些**零网络**出口直接抛 TypeError（TUI 启动就探测失败）。
    """
    from ai_pr_review.config import ModelProviderConfig, ProviderConfig, ProviderModelConfig

    # (1) 预设模型 + 兜底条目（= import 少了 models 时 ensure_default_model_present 补的那条）
    backend = JsonlBackend(tmp_path / "config.json")
    backend.config.provider = ProviderConfig.from_model_provider(
        ModelProviderConfig.from_name("anthropic")
    )
    preset_model = backend.config.provider.default_model
    backend.config.provider.models[preset_model] = ProviderModelConfig(name=preset_model)
    backend.config._sync_runtime_sections()
    assert (
        backend.config.provider.models[preset_model].context_window,
        backend.config.provider.models[preset_model].max_output,
    ) == (32_768, 4_096)
    # 兜底数字既不算"用户写过"（预算退回 8_000），也不能反过来砍额度（封顶改用预设值）。
    assert backend._chat_context_window() is None
    assert backend._chat_context_budget_plan() == (8_000, "fallback")
    assert backend._chat_max_output() == 8_192
    assert backend._chat_max_tokens(reasoning_budget=12_000) == 8_192

    # (2) 落盘条目里混进 null：所有出口都必须活着（退回"不可信"），不得抛异常。
    malformed = JsonlBackend(tmp_path / "malformed.json")
    malformed.config.provider = ProviderConfig.from_model_provider(
        ModelProviderConfig.from_name("deepseek")
    )
    malformed.config.provider.models["deepseek-chat"].context_window = None  # type: ignore[assignment]
    malformed.config.provider.models["deepseek-chat"].max_output = None  # type: ignore[assignment]
    malformed.config._sync_runtime_sections()
    assert malformed._chat_context_window() is None
    assert malformed._chat_max_output() is None
    assert malformed._chat_context_budget_plan() == (8_000, "fallback")
    assert malformed._chat_max_tokens(reasoning_budget=8_000) == 4_096 + 8_000
    assert malformed._config_snapshot()["chat_context_budget"] == 8_000
    assert malformed._context_status(None)["token_budget"] == 8_000


def test_chat_request_body_is_capped_by_the_model_spec(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """端到端：规格改了，`stream_chat` 收到的 `max_tokens` 必须跟着变（§2 的初衷）。"""

    async def run() -> None:
        backend = JsonlBackend(tmp_path / "config.json", event_sink=lambda event: None)
        backend.config.provider.api_key = "test-key"
        backend.config._sync_runtime_sections()
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        await _execute_async(backend, "think", ["high"])
        # /think 会保存并重载配置，因此规格写在它之后。
        backend.config.ai_client.api_key = "test-key"
        backend.config.provider.set_model_spec(
            backend.config.provider.default_model, max_output=3_000
        )
        backend.config._sync_runtime_sections()

        await backend.handle(_chat_send(session["session_id"]))

        assert captured["options"]["max_tokens"] == 3_000
        # anthropic：预算必须 ≥1_024 且 < max_tokens。`max_tokens - 1 = 2_999` 挤不下
        # high 档的 8_000（回答额度 4_096 也已超过 2_999），退回官方下限 1_024——
        # 既不发会被 400 拒收的值，也不假装档位没生效。
        assert captured["config"].extra_params["thinking"]["budget_tokens"] == 1_024

    asyncio.run(run())


def test_chat_skips_reasoning_params_for_unsupported_and_unknown_providers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """置灰的供应商不注入任何思考参数，也不预留思考额度（不编造参数）。

    两类：官方文档就没有该参数（baichuan，调研 §3.11）、以及**未收录**的供应商名
    （规格表查不到 → unknown 兜底，绝不按"看起来像 OpenAI 兼容"就透传）。
    """

    async def run() -> None:
        from ai_pr_review.config import AIClientConfig, ModelProviderConfig, ProviderConfig

        backend = JsonlBackend(tmp_path / "config.json", event_sink=lambda event: None)
        backend.config.provider = ProviderConfig.from_model_provider(
            ModelProviderConfig.from_name("baichuan", api_key="test-key")
        )
        backend.config._sync_runtime_sections()
        backend.config.preferences.chat_reasoning_effort = "max"
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)
        base_budget = backend.config.ai_client.max_tokens

        await backend.handle(_chat_send(session["session_id"]))
        assert "reasoning_effort" not in captured["options"]
        assert captured["config"].extra_params == {}
        assert captured["options"]["max_tokens"] == base_budget  # 没有思考预留

        unknown = JsonlBackend(tmp_path / "unknown.json", event_sink=lambda event: None)
        unknown.config.ai_client = AIClientConfig(
            provider="mystery-llm",
            api_key="relay-key",
            model="mystery-1",
            base_url="https://mystery.example.com/v1",
            api_format="openai",
        )
        unknown.config.provider = ProviderConfig.from_model_provider(
            unknown.config.ai_client.model_provider
        )
        unknown.config._sync_runtime_sections()
        unknown.config.preferences.chat_reasoning_effort = "high"
        unknown_session = (await unknown.handle({"id": "s", "method": "session.create"}))[0][
            "result"
        ]
        captured.clear()
        _stub_provider(monkeypatch, captured)

        await unknown.handle(_chat_send(unknown_session["session_id"]))
        assert "reasoning_effort" not in captured["options"]
        assert captured["config"].extra_params == {}
        assert captured["options"]["max_tokens"] == base_budget

    asyncio.run(run())


def test_chat_passes_reasoning_effort_through_for_relay_providers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """C 组（中转/自定义端点）：无自有思考参数 → 透传 `reasoning_effort`（四档含 off）。"""

    async def run() -> None:
        backend = _relay_backend_with_spec(tmp_path)
        backend.config.preferences.chat_reasoning_effort = "high"
        session = (await backend.handle({"id": "s", "method": "session.create"}))[0]["result"]
        captured: dict[str, Any] = {}
        _stub_provider(monkeypatch, captured)

        await backend.handle(_chat_send(session["session_id"]))
        assert captured["config"].extra_params == {}  # 透传走 kwargs，不占 extra_params
        assert captured["options"]["reasoning_effort"] == "high"
        # 透传端点接的常是推理模型：思考额度照旧预留（与改造前的行为一致）。
        assert captured["options"]["max_tokens"] == 4_096 + 8_000

        backend.config.preferences.chat_reasoning_effort = "off"
        await backend.handle(_chat_send(session["session_id"], "again"))
        assert captured["options"]["reasoning_effort"] == "none"

    asyncio.run(run())


def test_think_reports_transparent_state_for_relay_providers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`/think` 第三态：透传型端点已切换档位，但必须提示"是否生效取决于上游"。"""

    async def run() -> None:
        backend = _relay_backend_with_spec(tmp_path)
        reply = await _execute_async(backend, "think", ["low"])
        assert reply["ok"] is True
        result = reply["result"]
        assert result["kind"] == "think"
        assert result["state"] == "transparent"
        assert result["effort"] == "low"  # 契约 v1 字段保持不变（前端读 effort）
        assert "取决于上游" in result["reason"]
        payload = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
        assert payload["preferences"]["chat_reasoning_effort"] == "low"

    asyncio.run(run())


def test_think_is_unsupported_for_vendors_without_reasoning_params(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """官方文档没有该参数的供应商：置灰 + 给出原因与官方 URL，且不写偏好。"""

    async def run() -> None:
        from ai_pr_review.config import ModelProviderConfig, ProviderConfig

        backend = JsonlBackend(tmp_path / "config.json", event_sink=lambda event: None)
        backend.config.provider = ProviderConfig.from_model_provider(
            ModelProviderConfig.from_name("baichuan", api_key="test-key")
        )
        backend.config._sync_runtime_sections()

        reply = await _execute_async(backend, "think", ["max"])
        assert reply["ok"] is True
        result = reply["result"]
        assert result["state"] == "unsupported"
        assert "thinking/reasoning" in result["reason"]
        assert result["doc_url"] == "https://platform.baichuan-ai.com/docs"
        # 置灰时**不落盘**：档位偏好保持原值，连配置文件都不该被写出来。
        assert not (tmp_path / "config.json").exists()

        # 未收录的供应商名同样置灰（unknown 兜底，不许"猜一个参数"）。
        backend.config.provider.name = "mystery-llm"
        backend.config._sync_runtime_sections()
        unknown = await _execute_async(backend, "think", ["high"])
        assert unknown["result"]["state"] == "unsupported"
        assert "未收录" in unknown["result"]["reason"]

    asyncio.run(run())


def test_chat_usage_falls_back_to_estimated_context() -> None:
    """A5：provider 没给 usage 时用确定性估算，warning 仍只看预算/裁剪。"""
    from ai_pr_review.services.model_providers.base import ProviderResponse

    backend = JsonlBackend(Path("does-not-matter.json"))
    usage = backend._chat_usage_payload(ProviderResponse(text="stub"))
    assert usage is None
    context = backend._chat_context_payload(
        wire_history=[{"role": "user", "content": "abcd"}],
        answer="",
        usage=usage,
        trimmed_messages=2,
        compacted=False,
    )
    assert context["used_tokens"] == 10
    assert context["budget_tokens"] == DEFAULT_CHAT_BUDGET
    assert context["trimmed_messages"] == 2
    # 契约 v1 扩展后：预算来源随 `context` 一起下发给事件消费方（§4.5 枚举不变）。
    assert context["budget_source"] in {"config", "model_spec", "fallback"}


def test_history_defaults_to_review_runs_and_chat_mode_stays_available(tmp_path: Path) -> None:
    """2026-09-27 用户反馈后调整：默认 `/history` 列**审查列表**（"history" 的直觉
    含义）；`--chat` 看对话消息；`--runs` 保留为兼容别名（既有习惯/脚本不受影响）。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        session_id = await _new_session_async(backend)
        backend.sessions[session_id].messages = [
            {"role": "user", "content": "x" * 80, "timestamp": "2026-01-01T00:00:00+00:00"},
            {"role": "assistant", "content": "answer", "timestamp": "2026-01-01T00:00:01+00:00"},
        ]

        # 默认：审查列表（不带对话载荷的 kind 字段）
        runs_default = await _execute_async(backend, "history", [])
        assert "runs" in runs_default["result"]
        assert "kind" not in runs_default["result"]

        # --runs：兼容别名，与默认一致
        runs_alias = await _execute_async(backend, "history", ["--runs"])
        assert "runs" in runs_alias["result"]
        assert "kind" not in runs_alias["result"]

        # --chat：对话消息列表（A7 能力保留，改由显式参数打开）
        chat_history = await _execute_async(backend, "history", ["--chat"], session_id)
        assert chat_history["result"]["kind"] == "history"
        assert chat_history["result"]["items"][0]["excerpt"].endswith("…")
        assert chat_history["result"]["items"][0]["in_window"] is True

    asyncio.run(run())


def test_compact_replaces_old_messages_with_a_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A6 → 契约 v1 §B：按 **token 预算 + 对话轮**保留尾部原文，旧的一段换成 XML 摘要。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        session_id = await _new_session_async(backend)
        # 每条约 100 token（400 字符）的长消息：12 轮远超尾部预算，必须真的压起来。
        # （旧实现按条数保 10 轮，这样的会话会被判成"没什么可压"。）
        backend.sessions[session_id].messages = [
            {"role": role, "content": f"old {index} " + "x" * 400, "timestamp": "2026-01-01"}
            for index in range(12)
            for role in ("user", "assistant")
        ]
        assert backend._compaction_tail_budget() < backend._messages_tokens(
            backend.sessions[session_id].messages
        )

        prompts: list[str] = []

        class SummaryProvider:
            async def chat(self, messages, **kwargs):
                from ai_pr_review.services.model_providers.base import ProviderResponse

                prompts.append(str(kwargs.get("system_prompt", "")))
                return ProviderResponse(text="earlier facts")

        monkeypatch.setattr(
            "ai_pr_review.backend.jsonl_server.create_model_provider",
            lambda config: SummaryProvider(),
        )
        reply = await _execute_async(backend, "compact", ["保留 API 细节"], session_id)
        result = reply["result"]
        assert result["trigger"] == "manual"
        assert result["replaced_messages"] > 0
        assert result["kept_turns"] >= 1
        assert result["summary_chars"] > 0
        assert "保留 API 细节" in prompts[0], "用户指令必须进摘要提示词"

        messages = backend.sessions[session_id].messages
        summary = messages[0]["content"]
        assert messages[0]["role"] == "system"
        # 契约 v1 的 XML 结构：三个属性 + 正文 + 文件清单 + 闭合标签
        assert summary.startswith(
            f'<conversation-summary trigger="manual" '
            f'replaced_messages="{result["replaced_messages"]}" '
            f'kept_turns="{result["kept_turns"]}">'
        )
        assert summary.endswith("</conversation-summary>")
        assert "earlier facts" in summary
        assert "## 已压缩对话涉及的文件" in summary
        assert "- （无）" in summary, "这次压缩没涉及任何文件，清单要如实写'无'"
        # **不拆散一轮**：摘要之后的原文必须从一条 user 开始（不能留下半轮 assistant）
        assert messages[1]["role"] == "user"
        assert len(messages) == 1 + 2 * result["kept_turns"]
        # 保留的原文是**原样**的尾部：最后一条仍是最后一轮的回答
        assert messages[-1]["content"].startswith("old 11 ")
        # 落盘的是压缩后的历史（不是压缩前的）
        payload = json.loads(
            (tmp_path / "sessions" / f"{session_id}.json").read_text(encoding="utf-8")
        )["messages"]
        assert payload == messages

    asyncio.run(run())


def test_compact_failure_preserves_history(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A6：摘要失败时原历史一字不动（契约 v1 §B 的"摘要失败保留原历史"）。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        session_id = await _new_session_async(backend)
        from ai_pr_review.services.model_providers.base import ProviderResponse

        # 长消息：必须**真的走到**模型调用那一步，否则"失败被吞掉"这件事根本没被验证
        # （按条数保 10 轮的旧实现下，22 条短消息会被判成"没什么可压"直接返回）。
        original = [
            {"role": role, "content": f"old {index} " + "x" * 400, "timestamp": "2026-01-01"}
            for index in range(12)
            for role in ("user", "assistant")
        ]
        backend.sessions[session_id].messages = original

        class FailingProvider:
            async def chat(self, messages, **kwargs):
                raise RuntimeError("summary failed")

        monkeypatch.setattr(
            "ai_pr_review.backend.jsonl_server.create_model_provider",
            lambda config: FailingProvider(),
        )
        reply = await _execute_async(backend, "compact", [], session_id)
        assert reply["ok"] is False
        assert "summary failed" in reply["error"]["message"]
        assert backend.sessions[session_id].messages == original

    asyncio.run(run())


# ---------------------------------------------------------------------------
# 压缩保留策略的边界（契约 v1 §B；docs/session-and-compaction-plan.md §B2/B5）
# ---------------------------------------------------------------------------


def _long_turn(index: int) -> list[dict[str, Any]]:
    """一轮长消息（user + assistant），每条约 100 token（400 字符）。"""
    return [
        {"role": "user", "content": f"问 {index} " + "x" * 400, "timestamp": "2026-01-01"},
        {"role": "assistant", "content": f"答 {index} " + "y" * 400, "timestamp": "2026-01-01"},
    ]


def test_compaction_tail_keeps_whole_turns_never_half_of_one(tmp_path: Path) -> None:
    """**不拆散一轮**：一轮 = user + 其后的 assistant，保留的原文必须从 user 开始。"""
    backend = JsonlBackend(tmp_path / "config.json")
    messages = [*_long_turn(1), *_long_turn(2), *_long_turn(3)]
    # 预算刚好两轮：第三轮（最新）先保住，第二轮再保住，第一轮越界
    one_turn = backend._messages_tokens(_long_turn(1))
    backend._compaction_tail_budget = lambda: one_turn * 2  # type: ignore[method-assign]

    old, kept, kept_turns = backend._split_compaction_tail(messages)
    assert kept == [*_long_turn(2), *_long_turn(3)]
    assert kept[0]["role"] == "user"
    assert old == _long_turn(1)
    assert kept_turns == 2


def test_compaction_tail_keeps_at_least_one_turn_when_the_budget_is_tiny(tmp_path: Path) -> None:
    """极端配置兜底：预算比一轮还小 → 那一轮**整轮**留下（不清空对话、也不切半轮）。"""
    backend = JsonlBackend(tmp_path / "config.json")
    backend._compaction_tail_budget = lambda: 1  # type: ignore[method-assign]
    messages = [*_long_turn(1), *_long_turn(2), *_long_turn(3)]

    old, kept, kept_turns = backend._split_compaction_tail(messages)
    assert kept == _long_turn(3), "至少要留一整轮"
    assert [message["role"] for message in kept] == ["user", "assistant"]
    assert old == [*_long_turn(1), *_long_turn(2)]
    assert kept_turns == 1


def test_compaction_tail_keeps_everything_when_the_history_fits(tmp_path: Path) -> None:
    """短消息多轮全保留：没超预算就**什么都不用压**（旧实现按条数硬砍 10 轮）。"""
    backend = JsonlBackend(tmp_path / "config.json")
    messages = [
        {"role": role, "content": f"短 {index}", "timestamp": "2026-01-01"}
        for index in range(20)
        for role in ("user", "assistant")
    ]
    old, kept, kept_turns = backend._split_compaction_tail(messages)
    assert old == []
    assert kept == messages
    assert kept_turns == 20


def test_compact_is_a_no_op_and_calls_no_model_when_nothing_exceeds_the_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """装得下就别压：`/compact` 返回全零，历史一字不动，**也不多花一次模型调用**。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        session_id = await _new_session_async(backend)
        original = [
            {"role": role, "content": f"短 {index}", "timestamp": "2026-01-01"}
            for index in range(20)
            for role in ("user", "assistant")
        ]
        backend.sessions[session_id].messages = list(original)

        class ExplodingProvider:
            async def chat(self, messages, **kwargs):
                raise AssertionError("预算装得下就不该调摘要模型")

        monkeypatch.setattr(
            "ai_pr_review.backend.jsonl_server.create_model_provider",
            lambda config: ExplodingProvider(),
        )
        reply = await _execute_async(backend, "compact", [], session_id)
        assert reply["result"]["replaced_messages"] == 0
        assert reply["result"]["kept_turns"] == 20
        assert reply["result"]["trigger"] == "manual"
        assert backend.sessions[session_id].messages == original

    asyncio.run(run())


def test_compact_summary_lists_files_from_the_messages_and_the_bound_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """契约 v1 §B：清单 = 被压缩消息里的路径（含次数）+ 该会话绑定 run 的 finding 文件。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        session_id = await _new_session_async(backend)
        run_id = _store_context_run(
            backend
        )  # findings: src/medium.py、src/critical.py、src/high.py
        backend.sessions[session_id].current_run_id = run_id
        backend._compaction_tail_budget = lambda: 10  # type: ignore[method-assign]
        backend.sessions[session_id].messages = [
            {
                "role": "user",
                "content": "看看 website/index.html 和 website/js/main.js 的引用关系",
                "timestamp": "2026-01-01",
            },
            {
                "role": "assistant",
                "content": "website/index.html 里的 tab.html 来自 website/js/main.js",
                "timestamp": "2026-01-01",
            },
            *_long_turn(2),
            *_long_turn(3),
        ]

        class SummaryProvider:
            async def chat(self, messages, **kwargs):
                from ai_pr_review.services.model_providers.base import ProviderResponse

                return ProviderResponse(text="摘要正文")

        monkeypatch.setattr(
            "ai_pr_review.backend.jsonl_server.create_model_provider",
            lambda config: SummaryProvider(),
        )
        reply = await _execute_async(backend, "compact", [], session_id)
        summary = backend.sessions[session_id].messages[0]["content"]
        assert "## 已压缩对话涉及的文件" in summary
        assert "- website/index.html（讨论过 2 次）" in summary
        assert "- website/js/main.js（讨论过 2 次）" in summary
        assert (
            "- src/critical.py（本次审查点名）" in summary
        ), "finding 文件（没被讨论过）也要进清单"
        # URL 不是仓库文件：清单里不许出现 tps:// 这种碎片
        assert "tps://" not in summary and "http" not in summary
        assert reply["result"]["files"][0] == "- website/index.html（讨论过 2 次）"

    asyncio.run(run())


def test_compact_truncates_the_summary_input_and_annotates_the_omission(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """§B5 安全网：待摘要正文截断到**可用窗口 × 0.6**，省略条数写进摘要（确定性标注）。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        session_id = await _new_session_async(backend)
        monkeypatch.setattr(backend, "_chat_effective_window", lambda: 300)  # 摘要可用 180 token
        backend._compaction_tail_budget = lambda: 10  # type: ignore[method-assign]
        backend.sessions[session_id].messages = [
            message for index in range(6) for message in _long_turn(index)
        ]
        prompts: list[str] = []
        instructions: list[str] = []

        class SummaryProvider:
            async def chat(self, messages, **kwargs):
                from ai_pr_review.services.model_providers.base import ProviderResponse

                prompts.append(str(messages[0]["content"]))
                instructions.append(str(kwargs.get("system_prompt", "")))
                return ProviderResponse(text="摘要正文")

        monkeypatch.setattr(
            "ai_pr_review.backend.jsonl_server.create_model_provider",
            lambda config: SummaryProvider(),
        )
        reply = await _execute_async(backend, "compact", [], session_id)
        result = reply["result"]
        assert result["omitted_messages"] > 0, "窗口装不下就一定要丢最旧的"
        # 丢的是**最旧**的：留在正文里的必须是最新的那几条（§B5 的计量单位是"条"）
        assert "答 4 " in prompts[0]
        assert "问 0 " not in prompts[0] and "答 0 " not in prompts[0]
        assert (
            f"更早的 {result['omitted_messages']} 条消息已" in instructions[0]
        ), "提示词要说明丢了多少条，模型才不至于假装看过"
        summary = backend.sessions[session_id].messages[0]["content"]
        assert f"（更早的 {result['omitted_messages']} 条消息已省略，未参与本次摘要）" in summary

    asyncio.run(run())


def test_pressure_bands_and_null_when_the_percent_is_uncomputable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """契约 v1 §C：`<50 low`、`50–79 medium`、`80–99 high`、`>=100 critical`；算不出为 null。"""
    backend = JsonlBackend(tmp_path / "config.json")
    monkeypatch.setattr(backend, "_chat_context_budget_plan", lambda: (100, "config"))

    def payload(prompt_tokens: int | None) -> dict[str, Any]:
        usage = (
            None
            if prompt_tokens is None
            else {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": 0,
                "total_tokens": prompt_tokens,
            }
        )
        return backend._chat_context_payload(
            wire_history=[{"role": "user", "content": "x"}],
            answer="",
            usage=usage,
            trimmed_messages=0,
            compacted=False,
        )

    expected = {
        49: "low",
        50: "medium",
        79: "medium",
        80: "high",
        99: "high",
        100: "critical",
        500: "critical",
    }
    for prompt_tokens, band in expected.items():
        assert payload(prompt_tokens)["pressure"] == band, prompt_tokens

    # 预算算不出来（0）→ 百分比与压力都是 null，绝不能显示成"很轻松"
    monkeypatch.setattr(backend, "_chat_context_budget_plan", lambda: (0, "fallback"))
    uncomputable = payload(None)
    assert uncomputable["used_percent"] is None
    assert uncomputable["pressure"] is None


def test_auto_compaction_is_off_by_default_and_runs_only_when_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """契约 v1 §C：默认**只提示**（pressure 随事件下发）；`compaction_auto=true` 才真压。"""
    published: list[dict[str, Any]] = []

    async def run() -> None:
        from ai_pr_review.services.model_providers.base import ProviderResponse

        backend = JsonlBackend(tmp_path / "config.json", event_sink=published.append)
        backend.config.provider.api_key = "test-key"
        backend.config.ai_client.api_key = "test-key"
        session_id = await _new_session_async(backend)
        summaries: list[str] = []

        class Provider:
            async def stream_chat(self, messages, on_delta, **kwargs):
                await on_delta("stub")
                # prompt 9000 > 预算 8000 → used_percent 112.5 → critical
                return ProviderResponse(
                    text="stub",
                    usage={"prompt_tokens": 9000, "completion_tokens": 1, "total_tokens": 9001},
                )

            async def chat(self, messages, **kwargs):
                summaries.append(str(messages[0]["content"]))
                return ProviderResponse(text="摘要正文")

        monkeypatch.setattr(
            "ai_pr_review.backend.jsonl_server.create_model_provider",
            lambda config: Provider(),
        )
        await backend.handle(_chat_send(session_id, "第一轮"))
        finished = [event for event in published if event["event"] == "assistant.finished"][-1]
        assert finished["context"]["pressure"] == "critical"
        assert finished["context"]["compacted"] is False
        assert summaries == [], "默认关闭：只提示，不静默消耗一次模型调用"

        # 打开开关 + 把尾部预算压到一轮都装不下 → 自动压缩真的发生
        backend.config.preferences.compaction_auto = True
        monkeypatch.setattr(backend, "_compaction_tail_budget", lambda: 10)
        published.clear()
        await backend.handle(_chat_send(session_id, "第二轮"))
        assert len(summaries) == 1
        finished = [event for event in published if event["event"] == "assistant.finished"][-1]
        assert finished["context"]["compacted"] is True
        assert (
            backend.sessions[session_id]
            .messages[0]["content"]
            .startswith('<conversation-summary trigger="auto" ')
        )

    asyncio.run(run())


# ---------------------------------------------------------------------------
# B1/B2/B3：models.dev 接进配置助手 + 规格可编辑 + 中转站逐项自定义
# （docs/b2b3-wiring-design.md §4.1；全部离线，不发真实网络请求）
#
# A/B 组在本文件；C 组（ProviderConfig.set_model_spec / 取值边界）已归位
# tests/test_config.py、D 组（config show/export/import/health）已归位 tests/test_cli.py，
# 见 docs/claude-backend-followup.md §1。
# ---------------------------------------------------------------------------

# 真实的 models.dev 片段（2026-09-26 只读抓取）：deepseek 的 1000000/393216 +
# effort low,high,max + toggle；anthropic 的 200000/8192 + budget_tokens ≥1024。
# 刻意选成"与内置预设不一致"（deepseek：预设 1048576/384000）与"一致"
# （anthropic：预设就是 200000/8192）各一条，供两种判定分支使用。
CATALOG_PAYLOAD: dict[str, Any] = {
    "deepseek": {
        "models": {
            "deepseek-flash": {
                "reasoning": True,
                "reasoning_options": [
                    {"type": "effort", "values": ["low", "high", "max"]},
                    {"type": "toggle"},
                ],
                "limit": {"context": 1_000_000, "output": 393_216},
            }
        }
    },
    "anthropic": {
        "models": {
            "claude-sonnet-4-20250514": {
                "reasoning": True,
                "reasoning_options": [{"type": "budget_tokens", "min": 1024}],
                "limit": {"context": 200_000, "output": 8_192},
            }
        }
    },
}


@pytest.fixture(autouse=True)
def _offline_model_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """本文件任何用例都不许真的去拉 models.dev。

    `config.options` 的协议分支会取数（§3.3.3），不打桩的话整份用例都会联网。
    打的是 HTTP 层而不是 `fetch`：失败路径因此与真实断网逐字一致
    （`_fetch_from_source` 自己吞异常并记住失败）。需要目录的用例再用
    `_stub_catalog` 覆盖这一层。
    """
    ModelCatalog.reset_cache()

    def failing_urlopen(request, timeout):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(
        "ai_pr_review.services.model_catalog.urllib_request.urlopen", failing_urlopen
    )
    yield
    ModelCatalog.reset_cache()


def _stub_catalog(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any] | None = CATALOG_PAYLOAD,
) -> dict[str, int]:
    """把 models.dev 的 HTTP 层换成 `payload`（`None` = 断网），返回取数计数。

    计数打在 `ModelCatalog.fetch` 上而不是 urlopen：目录自己也有进程级缓存，
    数 URL 分不清"backend 的 `_catalog_state` memo 生效"和"恰好命中目录缓存"。
    """
    calls = {"fetch": 0}
    original_fetch = ModelCatalog.fetch

    def counting_fetch(self, *, refresh: bool = False):
        calls["fetch"] += 1
        return original_fetch(self, refresh=refresh)

    class StubResponse:
        def __enter__(self) -> "StubResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        calls["urlopen"] = calls.get("urlopen", 0) + 1
        if payload is None:
            raise urllib.error.URLError("offline")
        return StubResponse()

    monkeypatch.setattr(ModelCatalog, "fetch", counting_fetch)
    monkeypatch.setattr("ai_pr_review.services.model_catalog.urllib_request.urlopen", fake_urlopen)
    ModelCatalog.reset_cache()
    return calls


def _deepseek_backend(tmp_path: Path, config_path: Path | None = None) -> JsonlBackend:
    """主（远端）槽 = deepseek / deepseek-flash，并同步活跃槽（`model.status` 读它）。

    走 `ModelProviderConfig.from_name` 的真实路径：base_url 就是官方端点，
    后续若干断言依赖 `endpoint_matches_preset` 为真。
    """
    from ai_pr_review.config import ModelProviderConfig, ProviderConfig

    backend = JsonlBackend(config_path or (tmp_path / "config.json"))
    backend.config.provider = ProviderConfig.from_model_provider(
        ModelProviderConfig.from_name("deepseek", model_name="deepseek-flash", api_key="test-key")
    )
    backend.config._sync_runtime_sections()
    return backend


def _catalog_options(backend: JsonlBackend, request_id: str = "1") -> dict[str, Any]:
    events = asyncio.run(
        backend.handle({"id": request_id, "method": "config.options", "params": {}})
    )
    assert events[0]["ok"] is True
    return events[0]["result"]


def test_config_options_fetches_the_catalog_once_per_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """打开助手 = 一次取数（方案 §B2）；同一个助手里的第二次不得翻转 source。"""
    calls = _stub_catalog(monkeypatch)
    backend = JsonlBackend(tmp_path / "config.json")

    first = _catalog_options(backend, "1")["model"]
    second = _catalog_options(backend, "2")["model"]

    assert calls["fetch"] == 1
    assert first["catalog_state"]["source"] == "models.dev"
    assert second["catalog_state"]["source"] == "models.dev"
    assert first["catalog_state"]["reason"] == ""
    assert first["catalog_state"]["fetched_at"] == second["catalog_state"]["fetched_at"]


def test_config_options_falls_back_to_builtin_when_the_catalog_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """断网/形状错误一律静默回退内置预设：`ok` 仍为 true，绝不抛错挡配置流程。"""
    calls = _stub_catalog(monkeypatch, payload=None)
    backend = _deepseek_backend(tmp_path)

    model = _catalog_options(backend)["model"]

    assert calls["fetch"] == 1
    assert model["catalog_state"]["source"] == "builtin"
    assert model["catalog_state"]["reason"] == "fetch_failed"
    assert model["slots"]["remote"]["source"] == "builtin"  # deepseek-flash 有内置预设
    assert model["catalog"] is None
    assert model["context_window"] == 1_048_576  # 预设值原样生效


def test_config_options_respects_model_catalog_fetch_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`preferences.model_catalog_fetch=false`：一次都不取，reason 如实写 disabled。"""
    calls = _stub_catalog(monkeypatch)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"preferences": {"model_catalog_fetch": False}}), encoding="utf-8"
    )
    backend = JsonlBackend(config_path)

    model = _catalog_options(backend)["model"]

    assert calls["fetch"] == 0
    assert model["catalog_state"]["enabled"] is False
    assert model["catalog_state"]["source"] == "builtin"
    assert model["catalog_state"]["reason"] == "disabled"


def test_model_spec_block_marks_a_user_override_without_overwriting_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """§2.8 硬规则 1：生效值永远是落盘值，目录值只摆在 `catalog` 里，绝不静默覆盖。"""
    _stub_catalog(monkeypatch)
    backend = _deepseek_backend(tmp_path)
    backend.config.provider.set_model_spec(
        "deepseek-flash", context_window=128_000, max_output=8_192
    )
    backend.config._sync_runtime_sections()

    _catalog_options(backend)
    model = backend._setup_options()["model"]

    assert model["context_window"] == 128_000
    assert model["max_output"] == 8_192
    assert model["catalog"]["context_window"] == 1_000_000
    assert model["catalog"]["max_output"] == 393_216
    assert model["source"] == "builtin"
    assert model["needs_verification"] is True
    # 读出口没有写盘：落盘值仍是用户填的那两个数。
    assert backend.config.provider.models["deepseek-flash"].context_window == 128_000


def test_model_spec_block_matches_the_catalog_when_values_agree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """生效值与目录一致 → source 是目录来源，reasoning 摘要串按 controls 顺序拼。"""
    _stub_catalog(monkeypatch)
    backend = JsonlBackend(tmp_path / "config.json")  # 默认 anthropic/claude-sonnet-4-20250514

    model = _catalog_options(backend)["model"]

    assert (model["context_window"], model["max_output"]) == (200_000, 8_192)
    assert model["source"] == "models.dev"
    assert model["needs_verification"] is False
    assert model["endpoint_matches_preset"] is True
    assert model["reasoning"] == "预算 ≥1024"


def test_custom_endpoint_specs_never_take_official_presets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """B3 的核心：中转站的自定义模型名不套用任何官方数字，规格由用户逐项填。"""
    _stub_catalog(monkeypatch)
    config_path = tmp_path / "config.json"
    backend = JsonlBackend(config_path)

    backend._apply_setup(
        {
            "runtime_profile": "cloud",
            "provider_name": "custom",
            "model_name": "relay-model",
            "base_url": "https://relay.example.com/v1",
            "api_format": "openai",
            "context_window": 200_000,
            "max_output": 16_384,
        }
    )

    entry = backend.config.provider.models["relay-model"]
    assert (entry.context_window, entry.max_output) == (200_000, 16_384)
    reloaded = AppConfig.load(config_path)
    assert (reloaded.provider.models["relay-model"].context_window) == 200_000
    assert (reloaded.provider.models["relay-model"].max_output) == 16_384

    model = backend._setup_options()["model"]["slots"]["remote"]
    assert model["provider"] == "custom"
    assert model["preset"] is None  # 预设表里只有字面量 custom-model
    assert model["source"] == "unknown"
    assert model["needs_verification"] is False  # 没有可比对的官方数据，不假称要核对
    custom = backend._setup_options()["custom_endpoint"]
    assert custom["default_model"] == "relay-model"
    assert custom["base_url"] == "https://relay.example.com/v1"
    assert (custom["context_window"], custom["max_output"]) == (200_000, 16_384)


def test_config_setup_persists_specs_and_all_exits_read_them_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """§2.5：提交的规格必须活过 `save`（save 会重建 provider），三个出口同键同形。"""
    _stub_catalog(monkeypatch)
    _offline_model_provider(monkeypatch)
    config_path = tmp_path / "config.json"
    backend = _deepseek_backend(tmp_path, config_path)

    async def run() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        # 先打开一次助手把目录取回来，再看提交之后三个出口是否一致。
        await backend.handle({"id": "0", "method": "config.options", "params": {}})
        snapshot = backend._apply_setup(
            {
                "runtime_profile": "cloud",
                "provider_name": "deepseek",
                "model_name": "deepseek-flash",
                "context_window": 1_000_000,
                "max_output": 393_216,
            }
        )
        options = (await backend.handle({"id": "1", "method": "config.options", "params": {}}))[0][
            "result"
        ]
        status = (await backend.handle({"id": "2", "method": "model.status", "params": {}}))[0][
            "result"
        ]
        return snapshot, options, status

    snapshot, options, status = asyncio.run(run())

    reloaded = AppConfig.load(config_path)
    assert reloaded.provider.models["deepseek-flash"].context_window == 1_000_000
    assert reloaded.provider.models["deepseek-flash"].max_output == 393_216

    for block in (options["model"], snapshot["model_spec"], status["model_spec"]):
        assert block["context_window"] == 1_000_000
        assert block["max_output"] == 393_216
        assert block["source"] == "models.dev"
        assert block["needs_verification"] is False
    # 同键同形：`slots` 只属于 config.options（快照/状态是"活跃槽那一份"）。
    assert set(snapshot["model_spec"]) == set(options["model"]) - {"slots"}
    assert set(status["model_spec"]) == set(snapshot["model_spec"])
    assert set(options["model"]["slots"]) == {"remote", "local"}


def test_config_setup_spec_params_are_partial_updates(tmp_path: Path) -> None:
    """缺失/`null` = 保持落盘值：只给一个字段时不碰另一个槽、也不重置另一个字段。"""
    config_path = tmp_path / "config.json"
    backend = _deepseek_backend(tmp_path, config_path)

    backend._apply_setup({"runtime_profile": "custom", "local_max_output": 2_048})

    local_entry = backend.config.local_provider.models["qwen3.5:4b"]
    assert (local_entry.context_window, local_entry.max_output) == (8_192, 2_048)
    remote_entry = backend.config.provider.models["deepseek-flash"]
    assert (remote_entry.context_window, remote_entry.max_output) == (1_048_576, 384_000)

    # 显式 null 与"字段缺失"同义：不动任何值。
    backend._apply_setup(
        {
            "runtime_profile": "custom",
            "local_context_window": None,
            "local_max_output": None,
        }
    )

    assert AppConfig.load(config_path).local_provider.models["qwen3.5:4b"].max_output == 2_048


@pytest.mark.parametrize(
    "params",
    [
        {"context_window": 1_023},  # 越界（下界 1024）
        {"context_window": 10_000_001},  # 越界（上界）
        {"max_output": 0},  # 越界（下界 1）
        {"context_window": True},  # bool 不是整数
        {"context_window": 1e6},  # float 拒绝（只接受 int 与数字串）
        {"max_output": "not a number"},
        {"context_window": 1_024, "max_output": 10_000_000},  # 输出 > 上下文
    ],
)
def test_config_setup_rejects_an_invalid_spec_and_writes_nothing(
    params: dict[str, Any], tmp_path: Path
) -> None:
    """非法规格整单失败：文案含「模型规格」（TUI 靠它路由回该屏），磁盘一字不动。"""
    from ai_pr_review.config import ConfigValidationError, ModelProviderConfig, ProviderConfig

    config_path = tmp_path / "config.json"
    backend = JsonlBackend(config_path)
    backend.config.provider = ProviderConfig.from_model_provider(
        ModelProviderConfig.from_name("deepseek", model_name="deepseek-flash", api_key="k")
    )
    backend.config._sync_runtime_sections()
    backend._apply_setup(
        {
            "runtime_profile": "cloud",
            "provider_name": "deepseek",
            "model_name": "deepseek-flash",
            "context_window": 1_000_000,
            "max_output": 393_216,
        }
    )
    before_bytes = config_path.read_bytes()
    before_entry = backend.config.provider.models["deepseek-flash"]

    with pytest.raises(ConfigValidationError) as excinfo:
        backend._apply_setup(dict(params))

    assert "模型规格" in str(excinfo.value)
    assert config_path.read_bytes() == before_bytes
    after = backend.config.provider.models["deepseek-flash"]
    assert (after.context_window, after.max_output) == (
        before_entry.context_window,
        before_entry.max_output,
    )


def test_config_setup_applies_specs_in_the_custom_routing_profile(tmp_path: Path) -> None:
    """`runtime_profile="custom"` 只写槽位路由，规格参数不能被分支静默吞掉。"""
    config_path = tmp_path / "config.json"
    backend = _deepseek_backend(tmp_path, config_path)

    backend._apply_setup(
        {
            "runtime_profile": "custom",
            "chat_slot": "local",
            "review_slot": "remote",
            "context_window": 1_000_000,
            "max_output": 393_216,
        }
    )

    entry = backend.config.provider.models["deepseek-flash"]
    assert (entry.context_window, entry.max_output) == (1_000_000, 393_216)
    assert backend.config.preferences.chat_slot == "local"
    reloaded = AppConfig.load(config_path)
    assert reloaded.provider.models["deepseek-flash"].context_window == 1_000_000
    assert reloaded.preferences.chat_slot == "local"


def test_model_status_spec_key_does_not_shadow_the_model_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """§2.3 硬约束：规格块叫 `model_spec`。`model` 必须还是字符串模型名。"""
    _stub_catalog(monkeypatch)
    _offline_model_provider(monkeypatch)
    backend = _deepseek_backend(tmp_path)

    status = asyncio.run(backend.handle({"id": "1", "method": "model.status", "params": {}}))[0][
        "result"
    ]

    assert status["model"] == "deepseek-flash"
    assert isinstance(status["model_spec"], dict)
    assert status["source"] == status["model_spec"]["source"]
    assert status["needs_verification"] == status["model_spec"]["needs_verification"]


def test_model_status_and_config_snapshot_never_fetch_the_catalog(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """方案 §B2 验收：状态/快照/三次 chat 调用都不触发任何拉取。"""
    calls = _stub_catalog(monkeypatch)
    backend = _deepseek_backend(tmp_path)
    captured: dict[str, Any] = {}
    _stub_provider(monkeypatch, captured)

    async def run() -> None:
        await backend.handle({"id": "1", "method": "model.status", "params": {}})
        await backend.handle({"id": "2", "method": "config.snapshot", "params": {}})
        session = (await backend.handle({"id": "3", "method": "session.create", "params": {}}))[0][
            "result"
        ]
        for index in range(3):
            await backend.handle(_chat_send(session["session_id"], f"你好 {index}"))

    asyncio.run(run())

    assert calls["fetch"] == 0


def test_reasoning_summary_text_follows_the_ui_language(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """§2.7：摘要串按 `preferences.ui_language` 双语生成；目录无该模型 → null。"""
    _stub_catalog(monkeypatch)
    backend = _deepseek_backend(tmp_path)
    _catalog_options(backend)

    backend.config.preferences.ui_language = "zh-CN"
    assert (
        backend._setup_options()["model"]["slots"]["remote"]["reasoning"]
        == "档位 low/high/max · 开关"
    )
    backend.config.preferences.ui_language = "en-US"
    assert (
        backend._setup_options()["model"]["slots"]["remote"]["reasoning"]
        == "effort low/high/max · toggle"
    )

    # 目录里没有的模型：reasoning 是 null——离线时我们并不知道，而不是"未声明"。
    from ai_pr_review.config import ProviderModelConfig

    backend.config.provider.models["unknown-model"] = ProviderModelConfig(name="unknown-model")
    backend.config.provider.default_model = "unknown-model"
    backend.config._sync_runtime_sections()
    block = backend._setup_options()["model"]["slots"]["remote"]
    assert block["reasoning"] is None
    assert block["reasoning_controls"] == []
    assert block["catalog"] is None


def test_catalog_fetch_does_not_block_the_event_loop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """取数在 `asyncio.to_thread` 里跑：同步 HTTP 10s 不能把 chat 流一起卡住。"""

    def slow_fetch(self, *, refresh: bool = False):
        time.sleep(0.3)
        return None

    monkeypatch.setattr(ModelCatalog, "fetch", slow_fetch)
    ModelCatalog.reset_cache()

    async def run() -> int:
        ticks = {"count": 0}

        async def ticker() -> None:
            while True:
                await asyncio.sleep(0.01)
                ticks["count"] += 1

        backend = JsonlBackend(tmp_path / "config.json")
        task = asyncio.create_task(ticker())
        try:
            await backend.handle({"id": "1", "method": "config.options", "params": {}})
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        return ticks["count"]

    # 0.3s / 10ms ≈ 30 次；断言 ≥3 只要求"事件循环没有被独占"，给 CI 留足余量。
    assert asyncio.run(run()) >= 3


def test_protocol_config_options_and_setup_carry_model_specs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """协议层 round trip：新键落地，既有键一个都没少（加法安全）。"""
    _stub_catalog(monkeypatch)
    _offline_model_provider(monkeypatch)
    backend = _deepseek_backend(tmp_path)

    async def run() -> tuple[dict[str, Any], dict[str, Any]]:
        options = (await backend.handle({"id": "1", "method": "config.options", "params": {}}))[0][
            "result"
        ]
        setup = (
            await backend.handle(
                {
                    "id": "2",
                    "method": "config.setup",
                    "params": {
                        "runtime_profile": "cloud",
                        "context_window": 1_000_000,
                        "max_output": 393_216,
                    },
                }
            )
        )[0]["result"]
        return options, setup

    options, setup = asyncio.run(run())

    assert options["model"]["model"] == "deepseek-flash"
    assert options["custom_endpoint"]["name"] == "custom"
    for key in (
        "providers",
        "runtime_profiles",
        "api_formats",
        "ui_languages",
        "output_formats",
        "chat_layouts",
        "workbench_modes",
        "local",
        "current",
        "routing",
        "repo_context",
        "symbol_locate",
        "review_reasoning_effort",
    ):
        assert key in options
    assert setup["model_spec"]["context_window"] == 1_000_000
    assert setup["model_spec"]["max_output"] == 393_216


def test_config_catalog_refresh_bypasses_the_process_memo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ "重新获取"按钮的后端：忽略进程内定档，重拉一次并立刻反映到读出口。"""
    calls = _stub_catalog(monkeypatch)
    backend = JsonlBackend(tmp_path / "config.json")
    _catalog_options(backend)
    assert calls["fetch"] == 1

    refreshed = asyncio.run(
        backend.handle({"id": "2", "method": "config.catalog.refresh", "params": {}})
    )[0]

    assert refreshed["ok"] is True
    assert refreshed["result"]["model"]["catalog_state"]["source"] == "models.dev"
    # refresh 走的是 `ModelCatalog.refresh`（无视缓存），所以这里数的是 HTTP 层。
    assert calls["urlopen"] == 2


# ---------------------------------------------------------------------------
# review 思考档位的出口（config.snapshot / config.options / config.setup）
# 背景：docs/review-reasoning-assessment.md §4.3 第二步
# ---------------------------------------------------------------------------


def test_review_reasoning_effort_defaults_to_off_in_the_snapshot(tmp_path: Path) -> None:
    """默认档 `off` = 现状，snapshot 与 chat 档位同样式暴露（前端只读值）。"""
    backend = JsonlBackend(tmp_path / "config.json")

    snapshot = backend._config_snapshot()

    assert snapshot["review_reasoning_effort"] == "off"
    # 与 chat 档位是两个独立的键，默认值不同（chat 默认 auto）。
    assert snapshot["chat_reasoning_effort"] == "auto"


def test_config_options_expose_the_review_reasoning_vocabulary(tmp_path: Path) -> None:
    """`config.options.review_reasoning_effort`：当前值 + 五个可选值（词表来自 config）。"""
    from ai_pr_review.config import REVIEW_REASONING_EFFORTS

    backend = JsonlBackend(tmp_path / "config.json")
    block = backend._setup_options()["review_reasoning_effort"]

    assert block["value"] == "off"
    assert [item["value"] for item in block["options"]] == list(REVIEW_REASONING_EFFORTS)
    assert [item["value"] for item in block["options"]] == [
        "off",
        "low",
        "high",
        "max",
        "auto",
    ]
    # 每个档位都要有可渲染的文案（TUI 不硬编码中文）。
    assert all(item["label"] for item in block["options"])
    # deepseek 是受支持的供应商（默认预设 anthropic 也是）——没有置灰说明。
    assert "state" not in block
    assert "reason" not in block


def test_config_setup_writes_review_reasoning_effort_end_to_end(tmp_path: Path) -> None:
    """`config.setup` 写入 → 落盘 → 重载 → snapshot 与审查请求配置都拿到新档位。"""
    config_path = tmp_path / "config.json"
    backend = JsonlBackend(config_path)

    snapshot = backend._apply_setup(
        {
            "runtime_profile": "cloud",
            "provider_name": "deepseek",
            "api_key": "test-key",
            "model_name": "deepseek-flash",
            "review_reasoning_effort": "high",
        }
    )

    assert snapshot["review_reasoning_effort"] == "high"
    persisted = json.loads(config_path.read_text(encoding="utf-8"))["preferences"]
    assert persisted["review_reasoning_effort"] == "high"
    reloaded = AppConfig.load(config_path)
    assert reloaded.preferences.review_reasoning_effort == "high"
    # 审查请求读的是 ai_client 上那一份（混合编排按文件重建客户端配置时靠它带过去）。
    assert reloaded.ai_client.review_reasoning_effort == "high"
    assert backend.config.ai_client.review_reasoning_effort == "high"

    # 不传该键 = 保持不变（部分更新），不影响别的偏好。
    backend._apply_setup({"runtime_profile": "cloud", "review_reasoning_effort": ""})
    assert backend.config.preferences.review_reasoning_effort == "high"


def test_config_setup_rejects_an_unknown_review_reasoning_effort(tmp_path: Path) -> None:
    """向导里刚做出的选择非法必须整单失败（同 repo_context），不能静默回退。"""
    from ai_pr_review.config import ConfigValidationError

    config_path = tmp_path / "config.json"
    backend = JsonlBackend(config_path)

    with pytest.raises(ConfigValidationError, match="review 思考档位"):
        backend._apply_setup(
            {
                "runtime_profile": "cloud",
                "provider_name": "deepseek",
                "api_key": "test-key",
                "model_name": "deepseek-flash",
                "review_reasoning_effort": "extreme",
            }
        )

    assert backend.config.preferences.review_reasoning_effort == "off"


def test_review_reasoning_options_explain_greyed_out_providers(tmp_path: Path) -> None:
    """不支持注入的供应商必须给出口说明（本地置灰 / 未收录），而不是假装可调。"""
    from ai_pr_review.config import AIClientConfig, ModelProviderConfig, ProviderConfig

    local_backend = JsonlBackend(tmp_path / "local.json")
    local_backend._apply_setup({"runtime_profile": "local"})
    local_block = local_backend._setup_options()["review_reasoning_effort"]

    assert local_block["state"] == "unsupported"
    assert "本地" in local_block["reason"]

    unknown_backend = JsonlBackend(tmp_path / "unknown.json")
    unknown_backend.config.ai_client = AIClientConfig(
        provider="mystery-llm",
        api_key="relay-key",
        model="mystery-1",
        base_url="https://mystery.example.com/v1",
        api_format="openai",
    )
    unknown_backend.config.provider = ProviderConfig.from_model_provider(
        unknown_backend.config.ai_client.model_provider
    )
    unknown_backend.config._sync_runtime_sections()
    unknown_block = unknown_backend._setup_options()["review_reasoning_effort"]

    assert unknown_block["state"] == "unsupported"
    assert unknown_block["reason"]

    # 第三种：中转/自定义端点配成 Anthropic 协议——规格表判它透明（只透传 effort），
    # 但 Anthropic 形态的 provider 不读 kwargs，参数一个都到不了线上。
    relay_backend = JsonlBackend(tmp_path / "relay.json")
    relay_backend.config.provider = ProviderConfig.from_model_provider(
        ModelProviderConfig(
            name="custom",
            display_name="Custom",
            api_key="relay-key",
            base_url="https://relay.example.com",
            model_name="relay-claude",
            api_format="anthropic",
        )
    )
    relay_backend.config._sync_runtime_sections()
    relay_block = relay_backend._setup_options()["review_reasoning_effort"]

    assert relay_block["state"] == "unsupported"
    assert "Anthropic" in relay_block["reason"]


def test_review_reasoning_options_agree_across_the_three_exits(tmp_path: Path) -> None:
    """`config.options` / `model.status` 同键同形（与 repo_context/symbol_locate 同一约定）。"""
    backend = JsonlBackend(tmp_path / "config.json", event_sink=lambda event: None)

    options_block = backend._setup_options()["review_reasoning_effort"]
    status = asyncio.run(backend._model_status())

    assert status["review_reasoning_effort"] == options_block
    # 写一次档位之后三个出口仍然一致（status 也要跟得上，前端才不用另开请求）。
    backend._apply_setup(
        {
            "runtime_profile": "cloud",
            "provider_name": "deepseek",
            "api_key": "test-key",
            "model_name": "deepseek-flash",
            "review_reasoning_effort": "low",
        }
    )

    assert backend._config_snapshot()["review_reasoning_effort"] == "low"
    assert backend._setup_options()["review_reasoning_effort"]["value"] == "low"
    refreshed = asyncio.run(backend._model_status())
    assert (
        refreshed["review_reasoning_effort"] == backend._setup_options()["review_reasoning_effort"]
    )
