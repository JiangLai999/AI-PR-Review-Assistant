from __future__ import annotations

import asyncio
import contextlib
import json
import threading
from pathlib import Path

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

    assert [event["event"] for event in published] == ["review.started"]


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
