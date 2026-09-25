"""ReviewOrchestrator tests."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from ai_pr_review.config import AIClientConfig, AppConfig, PRFetcherConfig, ResultStoreConfig
from ai_pr_review.models.pr_data import FileDiff, FileStatus, PRData
from ai_pr_review.services.context_builder import FileContext
from ai_pr_review.services.filter_pipeline import (
    FilterPipelineResult,
    FilterReason,
    FilterReasonCode,
)
from ai_pr_review.services.hybrid_orchestrator import HybridReviewOrchestrator
from ai_pr_review.services.prompt_assembler import Finding, ReviewResult
from ai_pr_review.services.review_orchestrator import (
    ReviewOrchestrator,
    file_result_payload,
)


class StubPRFetcher:
    def __init__(self, *args, **kwargs):
        self.active_fetches = 0
        self.max_active_fetches = 0

    def fetch(self, pr_url: str) -> PRData:
        files = [
            FileDiff(
                filename=f"src/file_{index}.py",
                status=FileStatus.MODIFIED,
                additions=1,
                deletions=0,
                changes=1,
                patch="@@ -1 +1 @@\n-old\n+new",
            )
            for index in range(4)
        ]
        return PRData(
            pr_number=42,
            title="Concurrent review",
            description="desc",
            author="alice",
            state="open",
            head_sha="head123",
            base_sha="base123",
            head_ref="feature",
            base_ref="main",
            diff="diff",
            files=files,
            url=pr_url,
            merged=False,
            owner="owner",
            repo="repo",
        )

    def fetch_file_content(self, owner: str, repo: str, file_path: str, ref: str) -> str | None:
        async def wait() -> None:
            self.active_fetches += 1
            self.max_active_fetches = max(self.max_active_fetches, self.active_fetches)
            await asyncio.sleep(0.01)
            self.active_fetches -= 1

        asyncio.run(wait())
        return "def run():\n    return True\n"


class StubFilterPipeline:
    def __init__(self, *args, **kwargs):
        pass

    def filter_pr_data(self, pr_data: PRData):
        result = FilterPipelineResult()
        result.results = []
        for file_diff in pr_data.files:
            result.results.append(type("FilterResult", (), {"file": file_diff, "included": True})())
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

    def build_user_prompt(self, file_context: FileContext) -> str:
        return file_context.file_path


class StubAIClient:
    def __init__(self, *args, **kwargs):
        self.total_run_cost = 1.25
        self.active_reviews = 0
        self.max_active_reviews = 0

    async def review_code(self, system_prompt: str, user_prompt: str) -> ReviewResult:
        self.active_reviews += 1
        self.max_active_reviews = max(self.max_active_reviews, self.active_reviews)
        await asyncio.sleep(0.01)
        self.active_reviews -= 1
        return ReviewResult(
            summary=f"reviewed {user_prompt}",
            findings=[
                Finding(
                    severity="low",
                    category="architecture",
                    file=user_prompt,
                    line_start=1,
                    line_end=1,
                    title="Issue",
                    problem="problem",
                    suggestion="suggestion",
                    confidence=0.9,
                    code_snippet="pass",
                )
            ],
        )


class SelectiveFailingAIClient(StubAIClient):
    """只对指定文件抛异常，其他文件照常返回结果。"""

    def __init__(self, *args, fail_files: set[str] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_files = fail_files or set()

    async def review_code(self, system_prompt: str, user_prompt: str) -> ReviewResult:
        if user_prompt in self.fail_files:
            raise RuntimeError(f"model call failed for {user_prompt}")
        return await super().review_code(system_prompt, user_prompt)


class PartiallyExcludingFilterPipeline:
    """保留第一个文件，其余全部过滤：同时覆盖 reviewed 与 skipped。"""

    def __init__(self, *args, **kwargs):
        pass

    def filter_pr_data(self, pr_data: PRData):
        result = FilterPipelineResult()
        included = pr_data.files[:1]
        result.results = [
            type("FilterResult", (), {"file": file_diff, "included": True})()
            for file_diff in included
        ] + [
            type("FilterResult", (), {"file": file_diff, "included": False})()
            for file_diff in pr_data.files[1:]
        ]
        return pr_data.model_copy(update={"files": included}), result


class StubModelSelector:
    """混合编排器的模型选择桩：始终选本地模型，避免真实网络调用。"""

    def __init__(self, *args, **kwargs):
        self.local_model = "qwen3.5:4b"
        self.total_cost = 0.0

    def evaluate_file_complexity(self, **kwargs) -> str:
        return "low"

    def select_model_for_task(self, **kwargs):
        return "ollama", "qwen3.5:4b", True

    def record_cost(self, cost: float) -> None:
        self.total_cost += cost

    def get_statistics(self) -> dict[str, Any]:
        return {"strategy": "balanced", "local_calls": 4, "remote_calls": 0}


class StubStaticAnalyzer:
    def __init__(self, *args, **kwargs):
        pass

    def analyze(self, file_diff: FileDiff, file_context: FileContext) -> list[Finding]:
        return []


class StubPythonAstAnalyzer(StubStaticAnalyzer):
    pass


class StubPostProcessor:
    def __init__(self, *args, **kwargs):
        pass

    def process(self, result: ReviewResult) -> ReviewResult:
        return result


class StubResultStore:
    def __init__(self, *args, **kwargs):
        self.saved = None

    def save_result(self, pr_url: str, result: ReviewResult, **kwargs) -> str:
        self.saved = (pr_url, result, kwargs)
        return "run-123"


def test_review_orchestrator_limits_fetch_and_review_concurrency(monkeypatch, tmp_path):
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
    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.AIClient", StubAIClient)
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.PostProcessor", StubPostProcessor
    )
    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.ResultStore", StubResultStore)

    config = AppConfig.from_env()
    config.pr_fetcher = PRFetcherConfig(github_token="token", fetch_concurrency=2)
    config.ai_client = AIClientConfig(api_key="api-key", review_concurrency=3)
    config.result_store = ResultStoreConfig(db_path=str(tmp_path / "results.db"))
    orchestrator = ReviewOrchestrator(config)

    artifacts = asyncio.run(orchestrator.review("https://github.com/owner/repo/pull/42"))

    assert artifacts.run_id == "run-123"
    assert artifacts.total_cost == 1.25
    assert len(artifacts.review_result.findings) == 4
    assert orchestrator._pr_fetcher.max_active_fetches <= 2
    assert artifacts.review_result.summary.count("reviewed") == 4


def test_review_orchestrator_explains_empty_filtered_summary(monkeypatch, tmp_path):
    class ExcludingFilterPipeline:
        def __init__(self, *args, **kwargs):
            pass

        def filter_pr_data(self, pr_data: PRData):
            result = FilterPipelineResult()
            result.results = [
                type(
                    "FilterResult",
                    (),
                    {
                        "file": file_diff,
                        "included": False,
                        "primary_reason": FilterReason(
                            code=FilterReasonCode.EXCLUDED_BY_PATTERN,
                            action="exclude",
                            message="命中黑名单",
                        ),
                    },
                )()
                for file_diff in pr_data.files
            ]
            filtered_pr_data = pr_data.model_copy(update={"files": []})
            return filtered_pr_data, result

    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.PRFetcher", StubPRFetcher)
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.FilterPipeline", ExcludingFilterPipeline
    )
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.ContextBuilder", StubContextBuilder
    )
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.PromptAssembler", StubPromptAssembler
    )
    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.AIClient", StubAIClient)
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.PostProcessor", StubPostProcessor
    )
    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.ResultStore", StubResultStore)

    config = AppConfig.from_env()
    config.pr_fetcher = PRFetcherConfig(github_token="token", fetch_concurrency=2)
    config.ai_client = AIClientConfig(api_key="api-key", review_concurrency=3)
    config.result_store = ResultStoreConfig(db_path=str(tmp_path / "results.db"))
    orchestrator = ReviewOrchestrator(config)

    artifacts = asyncio.run(orchestrator.review("https://github.com/owner/repo/pull/42"))

    assert "No reviewable files remained after filtering" in artifacts.review_result.summary
    assert "命中黑名单规则 4 个" in artifacts.review_result.summary


# ---------------------------------------------------------------------------
# file_result_callback（docs/review-workspace-contract.md §10.2）
# ---------------------------------------------------------------------------


def _standard_config(tmp_path) -> AppConfig:
    config = AppConfig.from_env()
    config.pr_fetcher = PRFetcherConfig(github_token="token", fetch_concurrency=2)
    config.ai_client = AIClientConfig(api_key="api-key", review_concurrency=3)
    config.result_store = ResultStoreConfig(db_path=str(tmp_path / "results.db"))
    return config


def _patch_standard_orchestrator(
    monkeypatch,
    *,
    filter_pipeline: type = StubFilterPipeline,
    ai_client: type = StubAIClient,
) -> None:
    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.PRFetcher", StubPRFetcher)
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.FilterPipeline", filter_pipeline
    )
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.ContextBuilder", StubContextBuilder
    )
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.PromptAssembler", StubPromptAssembler
    )
    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.AIClient", ai_client)
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.PostProcessor", StubPostProcessor
    )
    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.ResultStore", StubResultStore)


def _patch_hybrid_orchestrator(
    monkeypatch,
    *,
    filter_pipeline: type = StubFilterPipeline,
    ai_client: type = StubAIClient,
) -> None:
    _patch_standard_orchestrator(
        monkeypatch, filter_pipeline=filter_pipeline, ai_client=ai_client
    )
    monkeypatch.setattr(
        "ai_pr_review.services.hybrid_orchestrator.ModelSelector", StubModelSelector
    )
    monkeypatch.setattr(
        "ai_pr_review.services.hybrid_orchestrator.StaticAnalyzer", StubStaticAnalyzer
    )
    monkeypatch.setattr(
        "ai_pr_review.services.hybrid_orchestrator.PythonAstAnalyzer", StubPythonAstAnalyzer
    )
    # 混合编排器直接用自己模块里的 ResultStore 名字构造，必须单独替换。
    monkeypatch.setattr(
        "ai_pr_review.services.hybrid_orchestrator.ResultStore", StubResultStore
    )


def test_file_result_payload_keeps_unknown_values_null() -> None:
    """契约 §10.2：取不到的值必须是 null，不能编造 0。"""
    assert file_result_payload("src/a.py", "failed", error="boom") == {
        "filename": "src/a.py",
        "status": "failed",
        "findings_count": None,
        "duration_ms": None,
        "error": "boom",
    }


def test_file_result_callback_reports_reviewed_files_with_real_values(monkeypatch, tmp_path):
    """reviewed 文件带真实 findings_count/duration_ms/error=None；旧回调语义不变。"""
    results: list[dict[str, Any]] = []
    done: list[str] = []
    order: list[tuple[str, str]] = []

    def on_result(payload: dict[str, Any]) -> None:
        results.append(payload)
        order.append(("result", payload["filename"]))

    def on_done(filename: str) -> None:
        done.append(filename)
        order.append(("done", filename))

    _patch_standard_orchestrator(monkeypatch)
    orchestrator = ReviewOrchestrator(_standard_config(tmp_path))

    artifacts = asyncio.run(
        orchestrator.review(
            "https://github.com/owner/repo/pull/42",
            file_result_callback=on_result,
            file_done_callback=on_done,
        )
    )

    filenames = [f"src/file_{index}.py" for index in range(4)]
    assert artifacts.run_id == "run-123"
    assert [payload["filename"] for payload in results] == filenames
    assert all(payload["status"] == "reviewed" for payload in results)
    assert all(payload["findings_count"] == 1 for payload in results)
    assert all(payload["error"] is None for payload in results)
    assert all(
        isinstance(payload["duration_ms"], int) and payload["duration_ms"] >= 0
        for payload in results
    )
    # 旧回调仍然每个文件各触发一次
    assert sorted(done) == filenames
    # 后端依赖的顺序：结果先到，file_done 后到（每个文件各自成立）
    for filename in filenames:
        assert order.index(("result", filename)) < order.index(("done", filename))


def test_file_result_callback_reports_failed_files_before_reraising(monkeypatch, tmp_path):
    """模型调用抛异常 → 报 failed（findings_count 未知为 null），异常照旧向上抛。"""
    results: list[dict[str, Any]] = []
    done: list[str] = []

    class FailingAIClient(SelectiveFailingAIClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, fail_files={"src/file_2.py"}, **kwargs)

    _patch_standard_orchestrator(monkeypatch, ai_client=FailingAIClient)
    orchestrator = ReviewOrchestrator(_standard_config(tmp_path))

    with pytest.raises(RuntimeError, match="src/file_2.py"):
        asyncio.run(
            orchestrator.review(
                "https://github.com/owner/repo/pull/42",
                file_result_callback=results.append,
                file_done_callback=done.append,
            )
        )

    failed = [payload for payload in results if payload["status"] == "failed"]
    assert [payload["filename"] for payload in failed] == ["src/file_2.py"]
    assert failed[0]["findings_count"] is None
    assert failed[0]["duration_ms"] >= 0
    assert "src/file_2.py" in failed[0]["error"]
    # 失败路径上旧回调照样触发（原 finally 语义）
    assert "src/file_2.py" in done


def test_file_result_callback_reports_filtered_files_as_skipped(monkeypatch, tmp_path):
    """被过滤掉的文件报 skipped；旧 file_done_callback 不为它们触发。"""
    results: list[dict[str, Any]] = []
    done: list[str] = []

    _patch_standard_orchestrator(monkeypatch, filter_pipeline=PartiallyExcludingFilterPipeline)
    orchestrator = ReviewOrchestrator(_standard_config(tmp_path))

    asyncio.run(
        orchestrator.review(
            "https://github.com/owner/repo/pull/42",
            file_result_callback=results.append,
            file_done_callback=done.append,
        )
    )

    reviewed = [payload for payload in results if payload["status"] == "reviewed"]
    skipped = [payload for payload in results if payload["status"] == "skipped"]
    assert [payload["filename"] for payload in reviewed] == ["src/file_0.py"]
    assert [payload["filename"] for payload in skipped] == [
        "src/file_1.py",
        "src/file_2.py",
        "src/file_3.py",
    ]
    assert all(payload["findings_count"] is None for payload in skipped)
    assert all(payload["error"] is None for payload in skipped)
    assert all(payload["duration_ms"] == 0 for payload in skipped)
    assert done == ["src/file_0.py"]


def test_hybrid_file_result_callback_reports_reviewed_and_failed(monkeypatch, tmp_path):
    """混合编排器同样上报真实结果，且失败文件不终止整轮审查（原语义）。"""
    results: list[dict[str, Any]] = []
    done: list[str] = []

    class FailingAIClient(SelectiveFailingAIClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, fail_files={"src/file_1.py"}, **kwargs)

    _patch_hybrid_orchestrator(monkeypatch, ai_client=FailingAIClient)
    orchestrator = HybridReviewOrchestrator(_standard_config(tmp_path))

    artifacts = asyncio.run(
        orchestrator.review(
            "https://github.com/owner/repo/pull/42",
            file_result_callback=results.append,
            file_done_callback=done.append,
        )
    )

    assert artifacts.run_id == "run-123"
    by_file = {payload["filename"]: payload for payload in results}
    assert by_file["src/file_0.py"]["status"] == "reviewed"
    assert by_file["src/file_0.py"]["findings_count"] == 1
    assert by_file["src/file_0.py"]["error"] is None
    assert by_file["src/file_1.py"]["status"] == "failed"
    assert by_file["src/file_1.py"]["findings_count"] is None
    assert "src/file_1.py" in by_file["src/file_1.py"]["error"]
    assert sorted(done) == [f"src/file_{index}.py" for index in range(4)]


def test_cli_run_review_forwards_file_result_callback(monkeypatch, tmp_path):
    """cli.run_review 原样转发 file_result_callback，旧关键字参数一个不少。"""
    from ai_pr_review import cli
    from ai_pr_review.services.review_orchestrator import ReviewArtifacts

    captured: dict[str, Any] = {}

    class FakeOrchestrator:
        def __init__(self, config):
            pass

        async def review(self, pr_url, **kwargs):
            captured.update(kwargs)
            return ReviewArtifacts(
                pr_data=PRData(
                    pr_number=42,
                    title="forwarding",
                    author="alice",
                    state="open",
                    head_sha="head123",
                    base_sha="base123",
                    head_ref="feature",
                    base_ref="main",
                    url=pr_url,
                    owner="owner",
                    repo="repo",
                    files=[],
                ),
                filter_result=FilterPipelineResult(),
                run_id="run-cli",
            )

    monkeypatch.setattr(cli, "HybridReviewOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(cli, "ReviewOrchestrator", FakeOrchestrator)

    payloads: list[dict[str, Any]] = []

    def on_result(payload: dict[str, Any]) -> None:
        payloads.append(payload)

    artifacts = asyncio.run(
        cli.run_review(
            "https://github.com/owner/repo/pull/42",
            config=_standard_config(tmp_path),
            progress_console=None,
            file_result_callback=on_result,
        )
    )

    assert artifacts.run_id == "run-cli"
    assert captured["file_result_callback"] is on_result
    # 旧调用签名保持兼容：这些关键字参数仍然逐个传下去
    assert set(captured) == {
        "model",
        "progress_callback",
        "file_done_callback",
        "stage_callback",
        "cancel_check",
        "file_result_callback",
    }


def test_hybrid_file_result_callback_reports_filtered_files_as_skipped(monkeypatch, tmp_path):
    """混合编排器也要为被过滤的文件报 skipped。"""
    results: list[dict[str, Any]] = []

    _patch_hybrid_orchestrator(monkeypatch, filter_pipeline=PartiallyExcludingFilterPipeline)
    orchestrator = HybridReviewOrchestrator(_standard_config(tmp_path))

    asyncio.run(
        orchestrator.review(
            "https://github.com/owner/repo/pull/42",
            file_result_callback=results.append,
        )
    )

    skipped = [payload for payload in results if payload["status"] == "skipped"]
    assert [payload["filename"] for payload in skipped] == [
        "src/file_1.py",
        "src/file_2.py",
        "src/file_3.py",
    ]
    assert all(payload["findings_count"] is None for payload in skipped)
