from __future__ import annotations

import asyncio
import contextlib
import json
import threading
from pathlib import Path
from typing import Any

import pytest

from ai_pr_review.backend.jsonl_server import JsonlBackend, ReviewCancelled


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
        *[
            name
            for stage in stages
            for name in ("review.stage", "review.stage_done")
        ],
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
    from ai_pr_review.backend.jsonl_server import (
        REVIEW_STAGE_LABELS,
        REVIEW_STAGE_PROGRESS,
    )

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
