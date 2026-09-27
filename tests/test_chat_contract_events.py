"""契约 v1 独立端到端验收：真实 JSONL 事件序列 + 结构化断言。

对照 docs/codex-chat-backend-c1.md §2（契约 v1，字段名以此为准）。
本文件只新增验收测试，不改产品代码。所有 stub 离线运行，不发真实网络请求。

验证维度（prompt 要求）:
  a. 事件类型序列合法（started 最先、finished 最后、reasoning_delta/delta 只在中间）
  b. reasoning 文本不出现在任何 assistant.delta 的累积结果中；累积 delta == finished.text
  c. finished 的 duration_seconds>0、usage 三键、context 七键、warning 为 null
  d. stub 不返回 usage 时 context 走估算（used_tokens>0）且 usage 为 null
  e. provider 抛错时 assistant.failed 出现且无 finished
  + /think（set 与 unsupported）、/compact（成功与失败）、/history 三模式结构断言
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from ai_pr_review.backend.jsonl_server import JsonlBackend
from ai_pr_review.services.model_providers.base import ProviderResponse


# ---------------------------------------------------------------------------
# 最小 helper（复制 tests/test_jsonl_backend.py 的既有模式，不 import 私有 helper）
# ---------------------------------------------------------------------------


def _reply(events: list[dict[str, Any]]) -> dict[str, Any]:
    return next(event for event in events if "ok" in event)


async def _execute_async(
    backend: JsonlBackend,
    name: str,
    args: list[Any],
    session_id: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"name": name, "args": args}
    if session_id is not None:
        params["session_id"] = session_id
    events = await backend.handle({"id": "cmd", "method": "command.execute", "params": params})
    return _reply(events)


async def _new_session_async(backend: JsonlBackend) -> str:
    events = await backend.handle({"id": "s", "method": "session.create", "params": {}})
    return str(_reply(events)["result"]["session_id"])


def _chat_send(session_id: str, text: str = "你好") -> dict[str, Any]:
    return {
        "id": "turn",
        "method": "chat.send",
        "params": {"session_id": session_id, "text": text},
    }


def _chat_backend_with_sink(
    tmp_path: Path, published: list[dict[str, Any]]
) -> JsonlBackend:
    """通过 Key 校验、事件全部进 published 列表的后端。"""
    backend = JsonlBackend(tmp_path / "config.json", event_sink=published.append)
    backend.config.provider.api_key = "test-key"
    backend.config.ai_client.api_key = "test-key"
    return backend


def _chat_ready_backend(tmp_path: Path) -> JsonlBackend:
    """通过 Key 校验的后端（命令测试用，不关心事件流）。"""
    backend = JsonlBackend(tmp_path / "config.json", event_sink=lambda event: None)
    backend.config.provider.api_key = "test-key"
    backend.config.ai_client.api_key = "test-key"
    return backend


def _seed_run(backend: JsonlBackend, pr_number: int, summary: str) -> str:
    """存一条历史 run，返回 run_id。"""
    from ai_pr_review.services.prompt_assembler import ReviewResult
    from ai_pr_review.services.result_store import ResultStore

    store = ResultStore(backend.config.result_store)
    return store.save_result(
        f"https://github.com/o/r/pull/{pr_number}",
        ReviewResult(summary=summary, findings=[]),
    )


# ---------------------------------------------------------------------------
# Stub provider
# ---------------------------------------------------------------------------


class _StreamingStub:
    """模拟带 reasoning_content + usage 的流式 provider。"""

    def __init__(
        self,
        *,
        reasoning_chunks: list[str] | None = None,
        delta_chunks: list[str] | None = None,
        answer: str = "",
        usage: dict[str, int] | None = None,
        reasoning: str | None = None,
        fail: bool = False,
    ) -> None:
        self.reasoning_chunks = reasoning_chunks or []
        self.delta_chunks = delta_chunks or []
        self.answer = answer
        self.usage = usage
        self.reasoning = reasoning
        self.fail = fail

    async def stream_chat(self, messages: list, on_delta: Any, **kwargs: Any) -> ProviderResponse:
        if self.fail:
            raise RuntimeError("provider exploded")
        on_reasoning = kwargs.get("on_reasoning")
        for chunk in self.reasoning_chunks:
            if on_reasoning is not None:
                await on_reasoning(chunk)
        for chunk in self.delta_chunks:
            await on_delta(chunk)
        await asyncio.sleep(0.01)  # 保证 duration_seconds > 0
        return ProviderResponse(
            text=self.answer,
            usage=self.usage,
            reasoning=self.reasoning,
        )


# ---------------------------------------------------------------------------
# a+b+c：完整事件序列合法 + reasoning 隔离 + finished 元数据齐全
# ---------------------------------------------------------------------------


def test_contract_event_sequence_is_legal_and_reasoning_is_isolated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """契约 v1 a+b+c：事件序列合法、reasoning 与正文隔离、finished 元数据齐全。"""

    async def run() -> None:
        published: list[dict[str, Any]] = []
        backend = _chat_backend_with_sink(tmp_path, published)
        session_id = await _new_session_async(backend)

        stub = _StreamingStub(
            reasoning_chunks=["思考第一步。", "思考第二步。"],
            delta_chunks=["你好", "，世界"],
            answer="你好，世界",
            usage={"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            reasoning="思考第一步。思考第二步。",
        )
        monkeypatch.setattr(
            "ai_pr_review.backend.jsonl_server.create_model_provider",
            lambda config: stub,
        )

        response = await backend.handle(_chat_send(session_id, "请打招呼"))
        assert response[0]["ok"] is True

        # —— a. 事件类型序列合法 ——
        names = [item["event"] for item in published]
        assert names[0] == "assistant.started", f"序列应以 started 开头: {names}"
        assert names[-1] == "assistant.finished", f"序列应以 finished 结尾: {names}"
        middle = names[1:-1]
        assert all(n in ("assistant.reasoning_delta", "assistant.delta") for n in middle), names
        assert "assistant.reasoning_delta" in middle
        assert "assistant.delta" in middle

        # —— b. reasoning 隔离 + 累积 delta == finished.text ——
        delta_text = "".join(
            item["text"] for item in published if item["event"] == "assistant.delta"
        )
        reasoning_text = "".join(
            item["text"]
            for item in published
            if item["event"] == "assistant.reasoning_delta"
        )
        # reasoning 文本不得出现在任何 assistant.delta 的累积结果中
        for chunk in ("思考第一步。", "思考第二步。"):
            assert chunk not in delta_text, f"reasoning 泄漏进 delta: {delta_text!r}"
        assert "思考" not in delta_text
        assert reasoning_text == "思考第一步。思考第二步。"

        finished = next(i for i in published if i["event"] == "assistant.finished")
        assert delta_text == finished["text"] == "你好，世界"

        # —— c. finished 元数据 ——
        assert finished["duration_seconds"] > 0, finished["duration_seconds"]
        assert set(finished["usage"]) == {
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
        }
        assert finished["usage"] == {
            "prompt_tokens": 20,
            "completion_tokens": 10,
            "total_tokens": 30,
        }
        assert set(finished["context"]) == {
            "used_tokens",
            "budget_tokens",
            "used_percent",
            "trimmed_messages",
            "compacted",
            # 2026-09-26 契约扩展：预算来源（config|model_spec|fallback）。
            # 见 docs/codex-chat-backend-c1.md §2 与 docs/chat-contract-verification.md。
            "budget_source",
            # 2026-09-27 契约扩展（会话/压缩改造 C 组）：压力分级
            # （low|medium|high|critical|null）。见 docs/claude-sessions-compaction.md §3。
            "pressure",
        }
        assert finished["context"]["budget_source"] in {
            "config",
            "model_spec",
            "fallback",
        }
        assert finished["context"]["pressure"] in {
            "low",
            "medium",
            "high",
            "critical",
            None,
        }
        assert finished["warning"] is None
        assert finished["reasoning"] == "思考第一步。思考第二步。"
        assert finished["session_id"] == session_id
        assert finished["request_id"] == "turn"
        # 2026-09-26 扩展：本轮实际模型名（TUI 的"消息指标行"显示"谁答的"）。
        # 按轮下发而不是让前端读当前 runtime——用户中途 /model 切换后历史必须各归各。
        # fixture 用默认配置（anthropic 预设）——断言它随槽位走，而不是硬编码某个供应商。
        assert finished["model"] == "claude-sonnet-4-20250514"

        # —— 真实 dump（供报告摘录）——
        print("=== CONTRACT EVENT DUMP (test_contract_event_sequence) ===")
        for item in published:
            print(json.dumps(item, ensure_ascii=False))
        print("=== END DUMP ===")

    asyncio.run(run())


# ---------------------------------------------------------------------------
# d：无 usage → context 走估算
# ---------------------------------------------------------------------------


def test_contract_context_estimated_when_provider_omits_usage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """契约 v1 d：stub 不返回 usage 时 context 走估算（used_tokens>0），usage 为 null。"""

    async def run() -> None:
        published: list[dict[str, Any]] = []
        backend = _chat_backend_with_sink(tmp_path, published)
        session_id = await _new_session_async(backend)

        stub = _StreamingStub(
            delta_chunks=["回答内容"],
            answer="回答内容",
            usage=None,
        )
        monkeypatch.setattr(
            "ai_pr_review.backend.jsonl_server.create_model_provider",
            lambda config: stub,
        )

        await backend.handle(_chat_send(session_id, "一个普通问题"))
        finished = next(i for i in published if i["event"] == "assistant.finished")
        assert finished["usage"] is None
        context = finished["context"]
        assert context["used_tokens"] > 0, "估算来源应给出正 token 数"
        assert context["budget_tokens"] > 0
        # 估算来源合理：短消息的 token 数不会超预算
        assert context["used_tokens"] < context["budget_tokens"]
        assert context["used_percent"] > 0

    asyncio.run(run())


# ---------------------------------------------------------------------------
# e：provider 抛错 → assistant.failed，无 finished
# ---------------------------------------------------------------------------


def test_contract_provider_error_emits_failed_without_finished(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """契约 v1 e：provider 抛错 → assistant.failed 出现，且无 assistant.finished。"""

    async def run() -> None:
        published: list[dict[str, Any]] = []
        backend = _chat_backend_with_sink(tmp_path, published)
        session_id = await _new_session_async(backend)

        stub = _StreamingStub(fail=True)
        monkeypatch.setattr(
            "ai_pr_review.backend.jsonl_server.create_model_provider",
            lambda config: stub,
        )

        response = await backend.handle(_chat_send(session_id, "你好"))
        names = [item["event"] for item in published]
        assert "assistant.failed" in names, names
        assert "assistant.finished" not in names, names
        assert names[0] == "assistant.started"

        failed = next(i for i in published if i["event"] == "assistant.failed")
        assert "provider exploded" in failed["message"]
        assert failed["session_id"] == session_id
        assert failed["request_id"] == "turn"
        assert response[0]["ok"] is False

    asyncio.run(run())


# ---------------------------------------------------------------------------
# /think：set 与 unsupported 两态
# ---------------------------------------------------------------------------


def test_contract_think_set_state(tmp_path: Path) -> None:
    """/think 支持的 provider → {kind:"think", state:"set"}。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        reply = await _execute_async(backend, "think", ["low"])
        assert reply["ok"] is True
        result = reply["result"]
        assert result["kind"] == "think"
        assert result["state"] == "set"
        assert result["effort"] == "low"

    asyncio.run(run())


def test_contract_think_unsupported_state(tmp_path: Path) -> None:
    """/think 本地 Ollama provider → {kind:"think", state:"unsupported"}。"""

    async def run() -> None:
        backend = JsonlBackend(tmp_path / "config.json")
        backend._apply_setup({"runtime_profile": "local", "local_model": "qwen3.5:4b"})
        reply = await _execute_async(backend, "think", ["max"])
        assert reply["ok"] is True
        result = reply["result"]
        assert result["kind"] == "think"
        assert result["state"] == "unsupported"

    asyncio.run(run())


# ---------------------------------------------------------------------------
# /compact：成功与失败
# ---------------------------------------------------------------------------


def test_contract_compact_success_shape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """契约 v1：/compact 成功 → {kind, kept_turns, replaced_messages, before/after_tokens,
    summary_chars}；2026-09-27 起保留口径改为 **token + 对话轮**（B 组），并新增
    trigger / omitted_messages / files 三个字段（见 docs/claude-sessions-compaction.md §2）。
    """

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        session_id = await _new_session_async(backend)
        # 长消息：新的保留口径按 token 算预算，22 条短消息装得下就**没有可压的东西**
        # （旧实现按条数硬砍 10 轮，这里的 token 量才是"真的超预算"）。
        backend.sessions[session_id].messages = [
            {"role": role, "content": f"old {index} " + "x" * 400, "timestamp": "2026-01-01"}
            for index in range(22)
            for role in ("user", "assistant")
        ][:22]

        class SummaryProvider:
            async def chat(self, messages: list, **kwargs: Any) -> ProviderResponse:
                return ProviderResponse(text="earlier facts")

        monkeypatch.setattr(
            "ai_pr_review.backend.jsonl_server.create_model_provider",
            lambda config: SummaryProvider(),
        )
        reply = await _execute_async(backend, "compact", ["保留 API 细节"], session_id)
        assert reply["ok"] is True
        result = reply["result"]
        assert result["kind"] == "compact"
        expected_keys = {
            "kept_turns",
            "replaced_messages",
            "before_tokens",
            "after_tokens",
            "summary_chars",
            "trigger",
            "omitted_messages",
            "files",
        }
        assert expected_keys <= set(result), f"缺少字段: {expected_keys - set(result)}"
        assert result["trigger"] == "manual"
        assert result["kept_turns"] >= 1
        assert result["replaced_messages"] > 0
        assert result["before_tokens"] > 0
        assert result["after_tokens"] > 0
        assert result["summary_chars"] > 0
        # 原文保留量确实变小了（压缩的意义），且摘要进了历史
        assert result["after_tokens"] < result["before_tokens"]
        assert backend.sessions[session_id].messages[0]["role"] == "system"
        assert "earlier facts" in backend.sessions[session_id].messages[0]["content"]

    asyncio.run(run())


def test_contract_compact_failure_is_protocol_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """契约 v1：/compact 失败 → ok:False（协议级 error），原历史一字不动。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        session_id = await _new_session_async(backend)
        # 长消息：必须真的走到模型调用（见上一条用例——短消息在新的 token 口径下会被
        # 判成"装得下"，根本压不起来，失败路径也就无从验证）。
        original = [
            {"role": role, "content": f"old {index} " + "x" * 400, "timestamp": "2026-01-01"}
            for index in range(22)
            for role in ("user", "assistant")
        ][:22]
        backend.sessions[session_id].messages = original

        class FailingProvider:
            async def chat(self, messages: list, **kwargs: Any) -> ProviderResponse:
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
# /history 三模式
# ---------------------------------------------------------------------------


def test_contract_history_chat_messages_mode(tmp_path: Path) -> None:
    """/history --chat（有 session）→ {kind:"history", items}，列对话消息。

    2026-09-27 用户反馈后：对话消息改由显式 `--chat` 打开（默认 `/history` 已是审查列表）。
    """

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        session_id = await _new_session_async(backend)
        backend.sessions[session_id].messages = [
            {
                "role": "user",
                "content": "x" * 80,
                "timestamp": "2026-01-01T00:00:00+00:00",
            },
            {
                "role": "assistant",
                "content": "answer",
                "timestamp": "2026-01-01T00:00:01+00:00",
            },
        ]
        reply = await _execute_async(backend, "history", ["--chat"], session_id)
        assert reply["ok"] is True
        result = reply["result"]
        assert result["kind"] == "history"
        assert "items" in result
        assert "text" in result
        assert len(result["items"]) == 2
        first = result["items"][0]
        assert {"index", "role", "excerpt", "timestamp", "in_window"} <= set(first)
        assert first["role"] == "user"
        assert first["in_window"] is True

    asyncio.run(run())


def test_contract_history_runs_mode(tmp_path: Path) -> None:
    """/history --runs → 审查历史列表（无 kind 键）。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        _seed_run(backend, 31, "审查摘要")
        reply = await _execute_async(backend, "history", ["--runs"])
        assert reply["ok"] is True
        result = reply["result"]
        assert "runs" in result
        assert "kind" not in result, "--runs 模式不应返回 kind"
        assert "statistics" in result

    asyncio.run(run())


def test_contract_history_run_detail_mode(tmp_path: Path) -> None:
    """/history <run_id> → 详情 + bound 绑定标记。"""

    async def run() -> None:
        backend = _chat_ready_backend(tmp_path)
        session_id = await _new_session_async(backend)
        run_id = _seed_run(backend, 31, "审查摘要")
        reply = await _execute_async(backend, "history", [run_id], session_id)
        assert reply["ok"] is True
        result = reply["result"]
        assert result["run"] is not None
        assert result["run"]["id"] == run_id
        assert "report" in result
        assert "bound" in result
        assert result["bound"] is True
        assert backend.sessions[session_id].current_run_id == run_id

    asyncio.run(run())
