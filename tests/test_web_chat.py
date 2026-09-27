"""审查结果问答服务层测试（`ai_pr_review.web_chat`）。

模型调用**全部打桩**：`monkeypatch.setattr(web_chat, "create_model_provider", ...)`
替换掉工厂，`answer_with_context` 内部拿到的是假 provider —— 测试不发起任何真实
网络请求，也不读写任何真实凭据（Key 一律用 `FAKE_KEY` 这类可识别假串）。
"""

from __future__ import annotations

import pytest

from ai_pr_review import web_chat
from ai_pr_review.config import AppConfig, ResultStoreConfig
from ai_pr_review.services.model_providers.base import ProviderResponse
from ai_pr_review.services.prompt_assembler import Finding, ReviewResult
from ai_pr_review.services.result_store import ResultStore
from ai_pr_review.services.review_context import estimate_tokens
from ai_pr_review.web_chat import ChatError, answer_with_context

FAKE_KEY = "sk-test-fake-key-not-a-real-credential"
PR_URL = "https://github.com/owner/repo/pull/7"


class _FakeProvider:
    """记录调用参数的假 provider；`error` 非空时按上游故障抛出。"""

    def __init__(
        self, *, reply: str = "回答", usage: dict | None = None, error: Exception | None = None
    ):
        self._reply = reply
        self._usage = usage
        self._error = error
        self.messages: list[dict] = []
        self.kwargs: dict = {}

    async def chat(self, messages: list[dict], **kwargs):
        self.messages = messages
        self.kwargs = kwargs
        if self._error is not None:
            raise self._error
        return ProviderResponse(text=self._reply, usage=self._usage)

    @property
    def system_prompt(self) -> str:
        return str(self.kwargs.get("system_prompt", ""))


def _config(tmp_path, *, api_key: str | None = FAKE_KEY) -> AppConfig:
    config = AppConfig.from_env()
    config.result_store = ResultStoreConfig(db_path=str(tmp_path / "results.db"))
    if api_key:
        config.provider.api_key = api_key
        config.ai_client.api_key = api_key
    return config


def _save_run(config: AppConfig) -> str:
    store = ResultStore(config=config.result_store)
    finding = Finding(
        severity="high",
        category="security",
        file="src/app.py",
        line_start=3,
        line_end=3,
        title="SQL injection risk",
        problem="User input is concatenated into SQL.",
        suggestion="Use parameterized queries.",
        confidence=0.95,
        code_snippet="query = f'SELECT ...'",
        finding_id="finding-abc",
    )
    return store.save_result(
        PR_URL,
        ReviewResult(summary="one issue", findings=[finding]),
        metadata={"validation_summary": {"valid": 1, "needs_review": 0, "invalid": 0}},
    )


def _stub(monkeypatch, provider: _FakeProvider) -> None:
    monkeypatch.setattr(web_chat, "create_model_provider", lambda config: provider)


# ---------------------------------------------------------------------------
# 错误路径
# ---------------------------------------------------------------------------


async def test_requires_text(tmp_path):
    config = _config(tmp_path)

    with pytest.raises(ChatError) as excinfo:
        await answer_with_context(config, text="   ")

    assert excinfo.value.code == "invalid_request"
    assert excinfo.value.message == "text is required"


async def test_unknown_run_is_not_found(tmp_path):
    config = _config(tmp_path)

    with pytest.raises(ChatError) as excinfo:
        await answer_with_context(config, run_id="does-not-exist", text="这条为什么判中风险？")

    assert excinfo.value.code == "not_found"
    assert "does-not-exist" in excinfo.value.message


async def test_missing_api_key_raises(tmp_path, monkeypatch):
    config = _config(tmp_path, api_key="")

    def _unexpected(*args, **kwargs):
        pytest.fail("provider must not be built before the api-key check")

    monkeypatch.setattr(web_chat, "create_model_provider", _unexpected)

    with pytest.raises(ChatError) as excinfo:
        await answer_with_context(config, text="你好")

    assert excinfo.value.code == "missing_api_key"
    assert "API Key" in excinfo.value.message


async def test_upstream_failure_becomes_chat_failed(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _stub(monkeypatch, _FakeProvider(error=RuntimeError("connection reset")))

    with pytest.raises(ChatError) as excinfo:
        await answer_with_context(config, text="你好")

    assert excinfo.value.code == "chat_failed"
    assert "模型调用失败" in excinfo.value.message
    assert "connection reset" in excinfo.value.message


# ---------------------------------------------------------------------------
# 成功路径
# ---------------------------------------------------------------------------


async def test_plain_chat_without_run_has_empty_context_meta(tmp_path, monkeypatch):
    config = _config(tmp_path)
    provider = _FakeProvider(
        reply="你好，有什么可以帮你？",
        usage={"prompt_tokens": 6, "completion_tokens": 4, "total_tokens": 10},
    )
    _stub(monkeypatch, provider)

    payload = await answer_with_context(config, text="你好")

    assert payload["reply"] == "你好，有什么可以帮你？"
    assert payload["model"] == config.provider.default_model
    assert payload["usage"] == {
        "prompt_tokens": 6,
        "completion_tokens": 4,
        "total_tokens": 10,
    }
    assert payload["context_meta"] == {
        "bound_run": None,
        "token_estimate": None,
        "sections": [],
        "truncated": False,
        "note": "",
    }
    assert "system_prompt" not in provider.kwargs
    assert provider.messages == [{"role": "user", "content": "你好"}]


async def test_bound_run_injects_findings_and_reports_sections(tmp_path, monkeypatch):
    config = _config(tmp_path)
    run_id = _save_run(config)
    provider = _FakeProvider(reply="第 1 条判高风险是因为…")
    _stub(monkeypatch, provider)

    payload = await answer_with_context(config, run_id=run_id, text="第 1 条为什么判高风险？")

    meta = payload["context_meta"]
    assert meta["bound_run"] == run_id
    assert meta["truncated"] is False
    assert meta["note"] == ""
    # 段名如实反映注入内容：L1 摘要 + L2 清单 + L3 全文（本 run 无 L4 记录）
    assert meta["sections"] == ["run_summary", "findings", "finding_details"]
    assert provider.system_prompt.startswith("你正在协助分析一次 PR 审查结果。")
    # run 摘要、findings 的文件/行号/严重度/证据状态、PR 链接都在上下文里
    assert f'<review_context run_id="{run_id}">' in provider.system_prompt
    assert PR_URL in provider.system_prompt
    assert "SQL injection risk" in provider.system_prompt
    assert "src/app.py:3" in provider.system_prompt
    assert "[high]" in provider.system_prompt
    assert "证据: unverified" in provider.system_prompt
    assert provider.messages == [{"role": "user", "content": "第 1 条为什么判高风险？"}]


async def test_context_meta_token_estimate_is_int(tmp_path, monkeypatch):
    config = _config(tmp_path)
    run_id = _save_run(config)
    provider = _FakeProvider()
    _stub(monkeypatch, provider)

    payload = await answer_with_context(config, run_id=run_id, text="总结一下")

    meta = payload["context_meta"]
    assert isinstance(meta["token_estimate"], int)
    assert meta["token_estimate"] > 0
    # 与 `review_context.estimate_tokens` 同口径：量的是注入的上下文本体
    start = f'<review_context run_id="{run_id}">\n'
    body = provider.system_prompt.split(start, 1)[1].rsplit("\n</review_context>", 1)[0]
    assert meta["token_estimate"] == estimate_tokens(body)


async def test_over_budget_truncates_and_notes(tmp_path, monkeypatch):
    config = _config(tmp_path)
    run_id = _save_run(config)
    # 极小预算：内层阶梯到底仍超，触发外层「findings → 运行摘要 → 只留问题」
    config.preferences.chat_context_budget = 1
    provider = _FakeProvider(reply="只按问题回答")
    _stub(monkeypatch, provider)

    payload = await answer_with_context(config, run_id=run_id, text="为什么？")

    meta = payload["context_meta"]
    assert meta["bound_run"] == run_id
    assert meta["truncated"] is True
    assert "预算" in meta["note"]
    assert "findings" in meta["note"]
    assert "run_summary" in meta["note"]
    assert meta["sections"] == []
    assert meta["token_estimate"] == 0
    assert "system_prompt" not in provider.kwargs
    assert payload["reply"] == "只按问题回答"


# ---------------------------------------------------------------------------
# usage 与本地槽
# ---------------------------------------------------------------------------


async def test_usage_is_null_when_provider_reports_none(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _stub(monkeypatch, _FakeProvider(reply="只有正文，没有用量"))

    payload = await answer_with_context(config, text="你好")

    assert payload["usage"] is None


async def test_local_slot_without_key_is_allowed(tmp_path, monkeypatch):
    config = _config(tmp_path, api_key="")
    config.preferences.chat_slot = "local"
    provider = _FakeProvider(reply="本地模型回答")
    _stub(monkeypatch, provider)

    payload = await answer_with_context(config, text="你好")

    assert payload["reply"] == "本地模型回答"
    assert payload["model"]
    assert payload["usage"] is None
    # 本地思考模型压进内容通道（与 CLI chat 同口径），且不因缺 Key 被拒
    assert provider.kwargs["reasoning_effort"] == "none"
