"""ReviewOrchestrator tests."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import pytest

from ai_pr_review.config import (
    AIClientConfig,
    AppConfig,
    PostProcessorConfig,
    PRFetcherConfig,
    ResultStoreConfig,
)
from ai_pr_review.models.pr_data import FileDiff, FileStatus, PRData
from ai_pr_review.services.context_builder import FileContext
from ai_pr_review.services.filter_pipeline import (
    FilterPipelineResult,
    FilterReason,
    FilterReasonCode,
)
from ai_pr_review.services.hybrid_orchestrator import HybridReviewOrchestrator
from ai_pr_review.services.post_processor import PostProcessor
from ai_pr_review.services.prompt_assembler import (
    RELATED_FILE_RULES_EN,
    RELATED_FILE_RULES_ZH,
    Finding,
)
from ai_pr_review.services.prompt_assembler import PromptAssembler as RealPromptAssembler
from ai_pr_review.services.prompt_assembler import ReviewResult, related_file_system_rules
from ai_pr_review.services.repo_context import FileSystemRepoCache, RelatedFile
from ai_pr_review.services.review_orchestrator import (
    ReviewCancelled,
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

    def process_with_stats(self, result: ReviewResult) -> tuple[ReviewResult, dict[str, Any]]:
        """透传桩：不改变 finding，也不谎报计数（空字典 = 没统计）。"""
        return result, {}


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
    post_processor: type = StubPostProcessor,
) -> None:
    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.PRFetcher", StubPRFetcher)
    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.FilterPipeline", filter_pipeline)
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.ContextBuilder", StubContextBuilder
    )
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.PromptAssembler", StubPromptAssembler
    )
    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.AIClient", ai_client)
    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.PostProcessor", post_processor)
    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.ResultStore", StubResultStore)


def _patch_hybrid_orchestrator(
    monkeypatch,
    *,
    filter_pipeline: type = StubFilterPipeline,
    ai_client: type = StubAIClient,
    post_processor: type = StubPostProcessor,
) -> None:
    _patch_standard_orchestrator(
        monkeypatch,
        filter_pipeline=filter_pipeline,
        ai_client=ai_client,
        post_processor=post_processor,
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
    monkeypatch.setattr("ai_pr_review.services.hybrid_orchestrator.ResultStore", StubResultStore)
    # PostProcessor 同理：hybrid 直接 import，得替换它自己模块里的名字。
    # 默认透传，让「证据校验」「回调」等用例不受后处理影响；后处理用例显式传
    # `post_processor=PostProcessor`（真实实现）。
    monkeypatch.setattr("ai_pr_review.services.hybrid_orchestrator.PostProcessor", post_processor)


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


def test_hybrid_reports_every_file_failure_as_a_failure(monkeypatch, tmp_path):
    """每一份文件都失败时必须报「审查失败」，不能读成干净的 0 findings。

    真实事故场景：远程 API Key 缺失/失效时，``AIAuthenticationError`` 会被
    逐文件吞掉（本编排器的原语义），整轮照常写库。若只看 findings 数量，
    输出会是「审查完成，发现 0 个问题」——用户会误以为代码没有问题。
    """
    all_files = {f"src/file_{index}.py" for index in range(4)}

    class AlwaysFailingAIClient(SelectiveFailingAIClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, fail_files=all_files, **kwargs)

    _patch_hybrid_orchestrator(monkeypatch, ai_client=AlwaysFailingAIClient)
    monkeypatch.setattr(
        "ai_pr_review.services.hybrid_orchestrator.ResultStore", RecordingResultStore
    )

    artifacts = asyncio.run(HybridReviewOrchestrator(_standard_config(tmp_path)).review(PR_URL))

    assert artifacts.review_result.findings == []
    assert artifacts.review_result.summary.startswith("审查失败：")
    assert "均未能完成模型审查" in artifacts.review_result.summary
    saved = RecordingResultStore.last.saved_metadata
    assert saved["failed_file_count"] == 4
    assert sorted(item["filename"] for item in saved["failed_files"]) == sorted(all_files)
    assert all(item["error"] for item in saved["failed_files"])


def test_hybrid_partial_file_failure_is_visible_in_the_summary(monkeypatch, tmp_path):
    """部分文件失败时，标题必须写明未审查的文件数，而不是只报 findings。"""

    class OneFailingAIClient(SelectiveFailingAIClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, fail_files={"src/file_1.py"}, **kwargs)

    _patch_hybrid_orchestrator(monkeypatch, ai_client=OneFailingAIClient)
    monkeypatch.setattr(
        "ai_pr_review.services.hybrid_orchestrator.ResultStore", RecordingResultStore
    )

    artifacts = asyncio.run(HybridReviewOrchestrator(_standard_config(tmp_path)).review(PR_URL))

    assert artifacts.review_result.summary.startswith("审查完成（部分失败）")
    assert "1 个文件未能审查" in artifacts.review_result.summary
    assert artifacts.review_result.summary.endswith(
        f"发现 {len(artifacts.review_result.findings)} 个问题"
    )
    saved = RecordingResultStore.last.saved_metadata
    assert saved["failed_file_count"] == 1
    assert saved["failed_files"][0]["filename"] == "src/file_1.py"


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


# ---------------------------------------------------------------------------
# fork 元数据（docs/P6_PLAN_2026-09-25.md §4.3）
# ---------------------------------------------------------------------------


class ForkStubPRFetcher(StubPRFetcher):
    """head 仓库与 base 仓库不同的 PR：GitHub 上就是一次来自 fork 的 PR。"""

    head_repo_full_name = "contributor/repo"

    def fetch(self, pr_url: str) -> PRData:
        return (
            super()
            .fetch(pr_url)
            .model_copy(update={"head_repo_full_name": self.head_repo_full_name})
        )


class RecordingResultStore(StubResultStore):
    """StubResultStore 加一个类级指针，方便断言写进库里的 metadata。"""

    last: RecordingResultStore | None = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        RecordingResultStore.last = self

    @property
    def saved_metadata(self) -> dict[str, Any]:
        assert self.saved is not None, "save_result 没有被调用"
        return self.saved[2].get("metadata") or {}


def test_review_orchestrator_records_fork_metadata(monkeypatch, tmp_path):
    """fork PR 的 run 必须留下 is_fork/head_repo，供 `/publish` 重建链接。"""
    _patch_standard_orchestrator(monkeypatch)
    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.PRFetcher", ForkStubPRFetcher)
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.ResultStore", RecordingResultStore
    )
    orchestrator = ReviewOrchestrator(_standard_config(tmp_path))

    asyncio.run(orchestrator.review("https://github.com/owner/repo/pull/42"))

    assert RecordingResultStore.last.saved_metadata["fork"] == {
        "is_fork": True,
        "head_repo": "contributor/repo",
    }


def test_review_orchestrator_records_a_same_repository_run_as_not_a_fork(monkeypatch, tmp_path):
    _patch_standard_orchestrator(monkeypatch)
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.ResultStore", RecordingResultStore
    )
    orchestrator = ReviewOrchestrator(_standard_config(tmp_path))

    asyncio.run(orchestrator.review("https://github.com/owner/repo/pull/42"))

    assert RecordingResultStore.last.saved_metadata["fork"] == {
        "is_fork": False,
        "head_repo": None,
    }


def test_hybrid_orchestrator_records_fork_metadata(monkeypatch, tmp_path):
    _patch_hybrid_orchestrator(monkeypatch)
    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.PRFetcher", ForkStubPRFetcher)
    monkeypatch.setattr(
        "ai_pr_review.services.hybrid_orchestrator.ResultStore", RecordingResultStore
    )
    orchestrator = HybridReviewOrchestrator(_standard_config(tmp_path))

    asyncio.run(orchestrator.review("https://github.com/owner/repo/pull/42"))

    assert RecordingResultStore.last.saved_metadata["fork"] == {
        "is_fork": True,
        "head_repo": "contributor/repo",
    }


# ---------------------------------------------------------------------------
# hybrid 证据校验 + pr_author 元数据（docs/P6_PLAN_2026-09-25.md §1）
# ---------------------------------------------------------------------------

#: 校验器要判定「位置 + 片段」，所以桩上下文必须给出非空的 full_content：
#: 第 1 行是 diff 的变更行，第 2 行不是，第 9 行不存在。
CONTEXT_FILE_CONTENT = "new\nkeep\n"


class ContentStubContextBuilder(StubContextBuilder):
    """带 `full_content` 的上下文桩，让真实 FindingValidator 有事实可判。"""

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
            full_content=CONTEXT_FILE_CONTENT,
        )


class StaticFindingAnalyzer(StubStaticAnalyzer):
    """每个文件产出一条真实的 `static_rule` finding：证明规则产出也走校验。"""

    def analyze(self, file_diff: FileDiff, file_context: FileContext) -> list[Finding]:
        return [
            evidence_finding(
                file_diff.filename,
                title=f"Static rule issue in {file_diff.filename}",
                sources=["static_rule"],
            )
        ]


def evidence_finding(
    file: str,
    *,
    title: str = "Model issue",
    line: int = 1,
    snippet: str = "new",
    sources: list[str] | None = None,
    severity: str = "medium",
    confidence: float = 0.9,
) -> Finding:
    return Finding(
        severity=severity,
        category="correctness",
        file=file,
        line_start=line,
        line_end=line,
        title=title,
        problem="problem",
        suggestion="suggestion",
        confidence=confidence,
        code_snippet=snippet,
        sources=list(sources) if sources is not None else ["ai_analysis"],
    )


def scenario_ai_client_factory(findings_by_file: dict[str, list[Finding]]) -> type:
    """构造按文件名返回预置 finding 的 AIClient 替身类型。"""

    class ScenarioAIClient(StubAIClient):
        async def review_code(self, system_prompt: str, user_prompt: str) -> ReviewResult:
            return ReviewResult(
                summary=f"reviewed {user_prompt}",
                findings=list(findings_by_file.get(user_prompt, [])),
            )

    return ScenarioAIClient


def test_hybrid_run_validates_model_and_static_findings(monkeypatch, tmp_path):
    """混合编排器（cli 默认路径）的每条 finding 都要有证据状态与计数。

    Codex 定位的缺陷：hybrid 从不调用 FindingValidator，真实评论因此恒为
    「校验通过 0 / 未校验 N」。本用例用真实校验器覆盖三种结论。
    """
    model_findings = {
        # 行号落在变更行、片段在文件里 → valid
        "src/file_0.py": [evidence_finding("src/file_0.py", title="Model issue in src/file_0.py")],
        # 片段在文件里，但第 2 行不是 diff 的变更行 → needs_review
        "src/file_1.py": [
            evidence_finding(
                "src/file_1.py", title="Model issue in src/file_1.py", line=2, snippet="keep"
            )
        ],
        # 第 9 行超出该文件内容（只有 2 行）→ invalid，且只有拿到这个文件自己的
        # 上下文才可能得出这个结论。
        "src/file_2.py": [
            evidence_finding(
                "src/file_2.py", title="Model issue in src/file_2.py", line=9, snippet="keep"
            )
        ],
    }

    _patch_hybrid_orchestrator(monkeypatch, ai_client=scenario_ai_client_factory(model_findings))
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.ContextBuilder", ContentStubContextBuilder
    )
    monkeypatch.setattr(
        "ai_pr_review.services.hybrid_orchestrator.StaticAnalyzer", StaticFindingAnalyzer
    )
    monkeypatch.setattr(
        "ai_pr_review.services.hybrid_orchestrator.ResultStore", RecordingResultStore
    )
    orchestrator = HybridReviewOrchestrator(_standard_config(tmp_path))

    artifacts = asyncio.run(orchestrator.review("https://github.com/owner/repo/pull/42"))

    findings = {finding.title: finding for finding in artifacts.review_result.findings}
    expected_counts = {"valid": 5, "needs_review": 1, "invalid": 1}
    # 4 个文件的静态规则产出 + file_0 的模型产出 = valid；模型另两条各占一档。
    assert artifacts.validation_summary == expected_counts
    assert RecordingResultStore.last.saved_metadata["validation_summary"] == expected_counts
    assert findings["Static rule issue in src/file_0.py"].evidence_status == "valid"
    assert findings["Static rule issue in src/file_0.py"].evidence[0].source == "static_rule"
    assert findings["Model issue in src/file_0.py"].evidence_status == "valid"
    assert findings["Model issue in src/file_1.py"].evidence_status == "needs_review"
    assert findings["Model issue in src/file_2.py"].evidence_status == "invalid"
    # 校验只标注、不丢弃：7 条 finding 全在，且都带 id 与证据。
    assert len(artifacts.review_result.findings) == 7
    assert all(
        finding.evidence_status != "unverified" for finding in artifacts.review_result.findings
    )
    assert all(
        finding.finding_id and finding.evidence for finding in artifacts.review_result.findings
    )
    assert (
        "Finding line range is outside the available file content."
        in findings["Model issue in src/file_2.py"].evidence_issues
    )


def test_hybrid_validates_a_finding_against_the_file_it_points_at(monkeypatch, tmp_path):
    """模型审查 A 却点名 B：用 B 自己的上下文校验；B 不在本次范围则如实记 invalid。"""
    model_findings = {
        "src/file_0.py": [
            evidence_finding("src/file_2.py", title="Model issue in src/file_2.py"),
            evidence_finding("src/missing.py", title="Model issue in src/missing.py"),
        ]
    }

    _patch_hybrid_orchestrator(monkeypatch, ai_client=scenario_ai_client_factory(model_findings))
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.ContextBuilder", ContentStubContextBuilder
    )
    orchestrator = HybridReviewOrchestrator(_standard_config(tmp_path))

    artifacts = asyncio.run(orchestrator.review("https://github.com/owner/repo/pull/42"))

    findings = {finding.title: finding for finding in artifacts.review_result.findings}
    in_scope = findings["Model issue in src/file_2.py"]
    out_of_scope = findings["Model issue in src/missing.py"]
    assert in_scope.evidence_status == "valid"
    assert [evidence.file for evidence in in_scope.evidence] == ["src/file_2.py"]
    assert out_of_scope.evidence_status == "invalid"
    assert out_of_scope.evidence_issues == [
        "Finding file is not present in the cross-file review context."
    ]
    assert artifacts.validation_summary == {"valid": 1, "needs_review": 0, "invalid": 1}


def test_standard_orchestrator_records_the_pr_author(monkeypatch, tmp_path):
    """发布路径只能从 run metadata 重建 PRData，作者必须落库。"""
    _patch_standard_orchestrator(monkeypatch)
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.ResultStore", RecordingResultStore
    )
    orchestrator = ReviewOrchestrator(_standard_config(tmp_path))

    asyncio.run(orchestrator.review("https://github.com/owner/repo/pull/42"))

    assert RecordingResultStore.last.saved_metadata["pr_author"] == "alice"


def test_hybrid_orchestrator_records_the_pr_author(monkeypatch, tmp_path):
    """cli.run_review 默认走 hybrid：这条路径同样要留下 pr_author。"""
    _patch_hybrid_orchestrator(monkeypatch)
    monkeypatch.setattr(
        "ai_pr_review.services.hybrid_orchestrator.ResultStore", RecordingResultStore
    )
    orchestrator = HybridReviewOrchestrator(_standard_config(tmp_path))

    asyncio.run(orchestrator.review("https://github.com/owner/repo/pull/42"))

    assert RecordingResultStore.last.saved_metadata["pr_author"] == "alice"


def test_orchestrators_record_a_missing_author_as_an_empty_string(monkeypatch, tmp_path):
    """抓不到作者时写空串，不编造：发布路径据此回退到占位符。"""

    class AnonymousPRFetcher(StubPRFetcher):
        def fetch(self, pr_url: str) -> PRData:
            return super().fetch(pr_url).model_copy(update={"author": ""})

    _patch_standard_orchestrator(monkeypatch)
    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.PRFetcher", AnonymousPRFetcher)
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.ResultStore", RecordingResultStore
    )
    asyncio.run(
        ReviewOrchestrator(_standard_config(tmp_path)).review(
            "https://github.com/owner/repo/pull/42"
        )
    )
    assert RecordingResultStore.last.saved_metadata["pr_author"] == ""

    _patch_hybrid_orchestrator(monkeypatch)
    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.PRFetcher", AnonymousPRFetcher)
    monkeypatch.setattr(
        "ai_pr_review.services.hybrid_orchestrator.ResultStore", RecordingResultStore
    )
    asyncio.run(
        HybridReviewOrchestrator(_standard_config(tmp_path)).review(
            "https://github.com/owner/repo/pull/42"
        )
    )
    assert RecordingResultStore.last.saved_metadata["pr_author"] == ""


# ---------------------------------------------------------------------------
# hybrid 后处理：置信度门槛 / 去重 / 严重度排序
# （docs/claude-p6-hybrid-postprocess.md）
# ---------------------------------------------------------------------------

PR_URL = "https://github.com/owner/repo/pull/42"


def _config_with_threshold(tmp_path, threshold: float = 0.6) -> AppConfig:
    """用户显式配置的门槛：hybrid 路径此前完全忽略它。"""
    config = _standard_config(tmp_path)
    config.post_processor = PostProcessorConfig(confidence_threshold=threshold)
    return config


def test_hybrid_local_calls_are_not_billed_at_cloud_rates(monkeypatch, tmp_path):
    """local_only 的本地调用必须按 0 成本计费，不能套用云端价格表。

    Codex 实测缺陷：一次 local_only 运行（local=2 / remote=0）报告
    ≈$0.0311，与远程运行一模一样 —— 因为它复用了远程的
    input/output_cost_per_million。
    """
    from ai_pr_review.config import ModelProviderConfig

    _patch_hybrid_orchestrator(monkeypatch)
    orchestrator = HybridReviewOrchestrator(_config_with_threshold(tmp_path))
    remote_prices = orchestrator.config.ai_client
    assert remote_prices.input_cost_per_million > 0  # 云端槽位确实带价格

    ollama = ModelProviderConfig.from_name("ollama", model_name="qwen3.5:4b")
    local_config = orchestrator._client_config_for(ollama, "qwen3.5:4b", is_local=True)
    remote_config = orchestrator._client_config_for(ollama, "qwen3.5:4b", is_local=False)

    assert local_config.input_cost_per_million == 0.0
    assert local_config.output_cost_per_million == 0.0
    assert local_config.model == "qwen3.5:4b"
    assert local_config.base_url == ollama.base_url
    # 远程路径保持用户配置的价格表，不受本地路径影响。
    assert remote_config.input_cost_per_million == remote_prices.input_cost_per_million
    assert remote_config.output_cost_per_million == remote_prices.output_cost_per_million


def test_hybrid_orchestrator_drops_findings_below_the_configured_threshold(monkeypatch, tmp_path):
    """cli.run_review 默认走 hybrid：用户配置的门槛 0.6 必须在这里生效。

    Codex 实测缺陷：hybrid 从不调用 PostProcessor，配置的置信度门槛与去重被
    整个绕开，0.50/0.55 的低置信度 finding 直接进入报告与 GitHub 评论。
    """
    model_findings = {
        "src/file_0.py": [
            evidence_finding("src/file_0.py", title="Kept issue", confidence=0.85),
            evidence_finding("src/file_0.py", title="Noise below threshold", confidence=0.50),
        ]
    }

    _patch_hybrid_orchestrator(
        monkeypatch,
        ai_client=scenario_ai_client_factory(model_findings),
        post_processor=PostProcessor,  # 真实后处理，不是透传桩
    )
    monkeypatch.setattr(
        "ai_pr_review.services.hybrid_orchestrator.ResultStore", RecordingResultStore
    )

    artifacts = asyncio.run(
        HybridReviewOrchestrator(_config_with_threshold(tmp_path)).review(PR_URL)
    )

    assert [finding.title for finding in artifacts.review_result.findings] == ["Kept issue"]
    expected_stats = {
        "before": 2,
        "after": 1,
        "below_threshold": 1,
        "duplicates": 0,
        "threshold": 0.6,
        "severity_sorted": True,
    }
    assert artifacts.filtered_findings == expected_stats
    assert RecordingResultStore.last.saved_metadata["filtered_findings"] == expected_stats
    # 标题只报后处理之后的真实条数，不把被丢掉的噪音算进去。
    assert artifacts.review_result.summary == "审查完成，发现 1 个问题"


def test_hybrid_reports_nothing_when_the_only_finding_is_below_the_threshold(monkeypatch, tmp_path):
    """门槛 0.6 + 0.55 的 finding → 结果为空，且 below_threshold=1。"""
    model_findings = {
        "src/file_0.py": [
            evidence_finding("src/file_0.py", title="Half-confident guess", confidence=0.55)
        ]
    }

    _patch_hybrid_orchestrator(
        monkeypatch,
        ai_client=scenario_ai_client_factory(model_findings),
        post_processor=PostProcessor,
    )
    monkeypatch.setattr(
        "ai_pr_review.services.hybrid_orchestrator.ResultStore", RecordingResultStore
    )

    artifacts = asyncio.run(
        HybridReviewOrchestrator(_config_with_threshold(tmp_path)).review(PR_URL)
    )

    assert artifacts.review_result.findings == []
    assert artifacts.filtered_findings == {
        "before": 1,
        "after": 0,
        "below_threshold": 1,
        "duplicates": 0,
        "threshold": 0.6,
        "severity_sorted": True,
    }
    assert artifacts.review_result.summary == "审查完成，发现 0 个问题"
    assert RecordingResultStore.last.saved_metadata["filtered_findings"]["below_threshold"] == 1


def test_hybrid_and_standard_paths_post_process_identically(monkeypatch, tmp_path):
    """同一输入下两条路径的 finding 顺序与去重结果逐条一致（共用同一入口）。"""

    def scenario() -> dict[str, list[Finding]]:
        return {
            "src/file_0.py": [
                # info 但置信度低于门槛 → 丢
                evidence_finding(
                    "src/file_0.py",
                    title="low confidence info",
                    line=1,
                    severity="info",
                    confidence=0.55,
                ),
                # 与下一条同一 (file, category, line//10) → 去重只留更优的那条
                evidence_finding(
                    "src/file_0.py", title="medium duplicate (worse)", line=11, confidence=0.70
                ),
                evidence_finding(
                    "src/file_0.py", title="medium duplicate (better)", line=12, confidence=0.92
                ),
                evidence_finding(
                    "src/file_0.py",
                    title="critical issue",
                    line=30,
                    severity="critical",
                    confidence=0.99,
                ),
                evidence_finding(
                    "src/file_0.py", title="high issue", line=40, severity="high", confidence=0.80
                ),
            ]
        }

    expected_order = [
        ("critical issue", "critical", 30),
        ("high issue", "high", 40),
        ("medium duplicate (better)", "medium", 12),
    ]
    expected_stats = {
        "before": 5,
        "after": 3,
        "below_threshold": 1,
        "duplicates": 1,
        "threshold": 0.6,
        "severity_sorted": True,
    }

    _patch_hybrid_orchestrator(
        monkeypatch,
        ai_client=scenario_ai_client_factory(scenario()),
        post_processor=PostProcessor,
    )
    monkeypatch.setattr(
        "ai_pr_review.services.hybrid_orchestrator.ResultStore", RecordingResultStore
    )
    hybrid_artifacts = asyncio.run(
        HybridReviewOrchestrator(_config_with_threshold(tmp_path)).review(PR_URL)
    )
    hybrid_metadata = RecordingResultStore.last.saved_metadata

    _patch_standard_orchestrator(
        monkeypatch,
        ai_client=scenario_ai_client_factory(scenario()),
        post_processor=PostProcessor,
    )
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.ResultStore", RecordingResultStore
    )
    standard_artifacts = asyncio.run(
        ReviewOrchestrator(_config_with_threshold(tmp_path)).review(PR_URL)
    )
    standard_metadata = RecordingResultStore.last.saved_metadata

    def order_of(artifacts) -> list[tuple[str, str, int]]:
        return [
            (finding.title, finding.severity, finding.line_start)
            for finding in artifacts.review_result.findings
        ]

    assert order_of(hybrid_artifacts) == expected_order
    assert order_of(standard_artifacts) == expected_order
    assert hybrid_artifacts.filtered_findings == expected_stats
    assert standard_artifacts.filtered_findings == expected_stats
    # run metadata 同键同值：库里能解释「模型给了 5 条、为什么只留下 3 条」。
    assert hybrid_metadata["filtered_findings"] == expected_stats
    assert standard_metadata["filtered_findings"] == expected_stats


def test_post_processor_process_still_applies_threshold_dedup_and_severity_sort():
    """`process()` 现在只是 `process_with_stats()` 的薄壳，行为必须逐字不变。"""
    processor = PostProcessor(PostProcessorConfig(confidence_threshold=0.6))
    result = ReviewResult(
        summary="原始 summary",
        findings=[
            evidence_finding("src/a.py", title="noise", line=1, severity="low", confidence=0.40),
            evidence_finding("src/a.py", title="duplicate (worse)", line=11, confidence=0.65),
            evidence_finding("src/a.py", title="duplicate (better)", line=12, confidence=0.90),
            evidence_finding(
                "src/a.py", title="critical", line=40, severity="critical", confidence=0.95
            ),
        ],
    )

    processed = processor.process(result)
    processed_with_stats, stats = processor.process_with_stats(result)

    assert processed == processed_with_stats
    assert processed.summary == "原始 summary"
    assert [(finding.title, finding.severity) for finding in processed.findings] == [
        ("critical", "critical"),
        ("duplicate (better)", "medium"),
    ]
    assert stats == {
        "before": 4,
        "after": 2,
        "below_threshold": 1,
        "duplicates": 1,
        # 记录本次真正使用的门槛，历史 Run 复现时据此披露（而不是读今天的配置）
        "threshold": 0.6,
        "severity_sorted": True,
    }
    # 入参不被就地修改：调用方仍能看到后处理前的完整 finding 列表。
    assert len(result.findings) == 4


# ---------------------------------------------------------------------------
# 取消：逐文件审查阶段可中断（任务 claude-p6-cancel-interrupt）
# ---------------------------------------------------------------------------


def _sleeping_ai_client(
    started: list[str],
    cancelled: list[str],
    *,
    sleep_seconds: float = 30.0,
) -> type:
    """模型调用会一直睡的桩：只有取消能让这轮审查结束。

    取消时在 `except asyncio.CancelledError` 里记账：真实客户端在这里断开
    HTTP 连接，桩用记账证明"在飞的调用真的被中止了"，而不是被丢在后台。
    """

    class SleepingAIClient:
        def __init__(self, *args, **kwargs):
            self.total_run_cost = 0.0

        async def review_code(self, system_prompt: str, user_prompt: str) -> ReviewResult:
            started.append(user_prompt)
            try:
                await asyncio.sleep(sleep_seconds)
            except asyncio.CancelledError:
                cancelled.append(user_prompt)
                raise
            return ReviewResult(summary=f"reviewed {user_prompt}", findings=[])

    return SleepingAIClient


def _recording_result_store(saved: list[Any]) -> type:
    """记录 save_result 调用的桩：用来断言"取消后没有落库"。"""

    class RecordingResultStore:
        def __init__(self, *args, **kwargs):
            pass

        def save_result(self, *args, **kwargs) -> str:
            saved.append((args, kwargs))
            return "run-should-not-exist"

    return RecordingResultStore


def test_cancel_interrupts_a_file_review_in_flight(monkeypatch, tmp_path):
    """取消要打断在飞的模型调用：1 秒内抛 ReviewCancelled、不落库、不伪造回调。"""
    started: list[str] = []
    cancelled: list[str] = []
    saved: list[Any] = []
    results: list[dict[str, Any]] = []
    done: list[str] = []

    _patch_standard_orchestrator(monkeypatch, ai_client=_sleeping_ai_client(started, cancelled))
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.ResultStore",
        _recording_result_store(saved),
    )

    config = _standard_config(tmp_path)
    config.ai_client = AIClientConfig(api_key="api-key", review_concurrency=3)
    orchestrator = ReviewOrchestrator(config)
    cancel_requested = threading.Event()

    async def scenario() -> float:
        async def request_cancel_later() -> None:
            await asyncio.sleep(0.3)
            cancel_requested.set()

        cancel_task = asyncio.create_task(request_cancel_later())
        started_at = time.perf_counter()
        with pytest.raises(ReviewCancelled):
            await orchestrator.review(
                "https://github.com/owner/repo/pull/42",
                cancel_check=cancel_requested.is_set,
                file_result_callback=results.append,
                file_done_callback=done.append,
            )
        elapsed = time.perf_counter() - started_at
        await cancel_task
        return elapsed

    elapsed = asyncio.run(scenario())

    # 模型调用睡 30s，能这么快返回只能是被取消打断的
    assert elapsed < 1.0, f"取消用了 {elapsed:.2f}s，说明还在等模型调用返回"
    assert started, "取消前的文件应当已经发起过模型调用"
    # 每个已发起的调用都真的收到了取消，没有一个被遗弃在后台
    assert sorted(cancelled) == sorted(started)
    # 取消发生在写库之前：不能留下 run 记录
    assert saved == []
    # 没有结论的文件不报 reviewed/failed/skipped，也不触发 file_done
    assert results == []
    assert done == []


def test_cancel_between_files_does_not_start_further_reviews(monkeypatch, tmp_path):
    """文件之间取消：后续文件连模型调用都不该发起，已完成的结果照常上报。"""
    calls: list[str] = []
    saved: list[Any] = []
    results: list[dict[str, Any]] = []
    done: list[str] = []
    cancel_requested = threading.Event()

    class CancelAfterEachCallAIClient:
        def __init__(self, *args, **kwargs):
            self.total_run_cost = 0.0

        async def review_code(self, system_prompt: str, user_prompt: str) -> ReviewResult:
            calls.append(user_prompt)
            # 第一个文件跑完之后才请求取消：下一个文件必须根本没被调用
            cancel_requested.set()
            return ReviewResult(summary=f"reviewed {user_prompt}", findings=[])

    _patch_standard_orchestrator(monkeypatch, ai_client=CancelAfterEachCallAIClient)
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.ResultStore",
        _recording_result_store(saved),
    )

    config = _standard_config(tmp_path)
    # 并发 1：串行逐文件，取消一定落在两个文件之间
    config.ai_client = AIClientConfig(api_key="api-key", review_concurrency=1)
    orchestrator = ReviewOrchestrator(config)

    with pytest.raises(ReviewCancelled):
        asyncio.run(
            orchestrator.review(
                "https://github.com/owner/repo/pull/42",
                cancel_check=cancel_requested.is_set,
                file_result_callback=results.append,
                file_done_callback=done.append,
            )
        )

    assert calls == ["src/file_0.py"]
    assert saved == []
    # 取消不能把已经跑完的文件结论也吞掉
    assert [payload["status"] for payload in results] == ["reviewed"]
    assert done == ["src/file_0.py"]


def test_hybrid_cancel_interrupts_a_file_review_in_flight(monkeypatch, tmp_path):
    """混合编排器的在飞调用同样可被取消，且不把取消报成 failed。"""
    started: list[str] = []
    cancelled: list[str] = []
    saved: list[Any] = []
    results: list[dict[str, Any]] = []
    done: list[str] = []

    _patch_hybrid_orchestrator(monkeypatch, ai_client=_sleeping_ai_client(started, cancelled))
    monkeypatch.setattr(
        "ai_pr_review.services.hybrid_orchestrator.ResultStore",
        _recording_result_store(saved),
    )

    orchestrator = HybridReviewOrchestrator(_standard_config(tmp_path))
    cancel_requested = threading.Event()

    async def scenario() -> float:
        async def request_cancel_later() -> None:
            await asyncio.sleep(0.3)
            cancel_requested.set()

        cancel_task = asyncio.create_task(request_cancel_later())
        started_at = time.perf_counter()
        with pytest.raises(ReviewCancelled):
            await orchestrator.review(
                "https://github.com/owner/repo/pull/42",
                cancel_check=cancel_requested.is_set,
                file_result_callback=results.append,
                file_done_callback=done.append,
            )
        elapsed = time.perf_counter() - started_at
        await cancel_task
        return elapsed

    elapsed = asyncio.run(scenario())

    assert elapsed < 1.0, f"取消用了 {elapsed:.2f}s，说明还在等模型调用返回"
    assert started == ["src/file_0.py"]
    assert cancelled == started
    assert saved == []
    # 取消不是 failed：这个文件没有结论，不报任何状态
    assert results == []
    assert done == []


def test_cancelled_review_releases_its_cost_reservation(monkeypatch) -> None:
    """取消（含收尾期间被再取消一次）不能把额度预留漏在客户端上。"""
    from ai_pr_review.services.ai_client import AIClient

    class HangingProvider:
        async def chat(self, messages, **kwargs):
            await asyncio.sleep(30)

        def estimate_cost(self, input_tokens, output_tokens, input_price, output_price) -> float:
            return 0.01

    monkeypatch.setattr(
        "ai_pr_review.services.ai_client.create_model_provider",
        lambda config, client_factory=None: HangingProvider(),
    )
    client = AIClient(AIClientConfig(api_key="api-key", model="stub-model"))

    async def scenario() -> None:
        task = asyncio.create_task(client.review_code("system", "user"))
        await asyncio.sleep(0.05)
        assert client.reserved_cost > 0
        # 别的请求正持有额度锁：释放若去等锁，就会被下面的第二次取消打断
        async with client._budget_lock:
            task.cancel()
            await asyncio.sleep(0.05)
            task.cancel()
            await asyncio.sleep(0.05)
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert client.reserved_cost == 0


# ---------------------------------------------------------------------------
# 仓库感知 L1-b：FileContext.related_files + PromptAssembler 注入段 + hybrid 预取
# ---------------------------------------------------------------------------


def _related(
    path: str,
    reason: str = "test",
    content: str = "def t():\n    pass\n",
    *,
    truncated: bool = False,
    from_cache: bool = False,
) -> dict[str, Any]:
    return {
        "path": path,
        "reason": reason,
        "content": content,
        "truncated": truncated,
        "from_cache": from_cache,
    }


class TestFileContextRelatedFilesDefault:
    def test_related_files_defaults_to_empty_list(self):
        context = FileContext(
            file_path="src/a.py",
            language="python",
            diff="d",
            diff_with_context="c",
            parse_mode="regex",
        )
        assert context.related_files == []

    def test_default_empty_leaves_prompt_unchanged(self):
        context = FileContext(
            file_path="src/a.py",
            language="python",
            diff="d",
            diff_with_context="c",
            parse_mode="regex",
        )
        assembler = RealPromptAssembler()
        prompt = assembler.build_user_prompt(context)
        assert "相关仓库文件" not in prompt
        assert "Related repository files" not in prompt
        system = assembler.build_system_prompt("python")
        assert "RELATED FILE RULES" not in system


class TestRelatedFilesPromptFreeze:
    """§4.5 段格式冻结：逐字断言，改动即失败。"""

    def test_user_prompt_section_format_zh(self):
        assembler = RealPromptAssembler(response_language="zh-CN")
        context = FileContext(
            file_path="src/service.py",
            language="python",
            diff="@@ -1 +1 @@\n-a\n+b",
            diff_with_context="ctx",
            parse_mode="regex",
            related_files=[
                _related(
                    "tests/test_auth_service.py",
                    "test",
                    "def test_ok():\n    assert True\n",
                    truncated=True,
                ),
                _related("path/to/config.py", "import", "X = 1\n", from_cache=True),
            ],
        )

        prompt = assembler.build_user_prompt(context)

        expected = (
            "\n## 相关仓库文件（未被本次修改）\n"
            "\n"
            "### tests/test_auth_service.py（原因：test，已截断）\n"
            "```python\n"
            "def test_ok():\n"
            "    assert True\n"
            "```\n"
            "\n"
            "### path/to/config.py（原因：import）\n"
            "```python\n"
            "X = 1\n"
            "```"
        )
        assert prompt.endswith(expected)

    def test_user_prompt_section_format_en(self):
        assembler = RealPromptAssembler(response_language="en-US")
        context = FileContext(
            file_path="src/service.py",
            language="python",
            diff="@@ -1 +1 @@\n-a\n+b",
            diff_with_context="ctx",
            parse_mode="regex",
            related_files=[
                _related(
                    "tests/test_auth_service.py",
                    "test",
                    "def test_ok():\n    assert True\n",
                    truncated=True,
                ),
            ],
        )

        prompt = assembler.build_user_prompt(context)

        expected = (
            "\n## Related repository files (not modified in this PR)\n"
            "\n"
            "### tests/test_auth_service.py (reason: test, truncated)\n"
            "```python\n"
            "def test_ok():\n"
            "    assert True\n"
            "```"
        )
        assert prompt.endswith(expected)

    def test_system_prompt_honesty_rules_zh_and_en(self):
        zh = RealPromptAssembler(response_language="zh-CN").build_system_prompt(
            "python", include_related_file_rules=True
        )
        en = RealPromptAssembler(response_language="en-US").build_system_prompt(
            "python", include_related_file_rules=True
        )
        assert RELATED_FILE_RULES_ZH in zh
        assert "引用它们时必须给出 `文件:行`" in zh
        assert "未在上下文中出现的文件内容不得臆测" in zh
        assert RELATED_FILE_RULES_EN in en
        assert "always give `file:line`" in en
        assert "Never invent file content that does not appear in the context" in en
        assert related_file_system_rules("zh-CN") == RELATED_FILE_RULES_ZH
        assert related_file_system_rules("en-US") == RELATED_FILE_RULES_EN


class CountingRepoProvider:
    """stub 预取器：记录构造与 collect_for_file 调用。"""

    constructions = 0
    collect_calls: list[str] = []
    items: list[RelatedFile] = []
    error: Exception | None = None

    @classmethod
    def reset(cls, items: list[RelatedFile] | None = None, error: Exception | None = None):
        cls.constructions = 0
        cls.collect_calls = []
        cls.items = items or []
        cls.error = error

    def __init__(self, *args, **kwargs):
        CountingRepoProvider.constructions += 1
        self.kwargs = kwargs

    def collect_for_file(self, file_path: str):
        CountingRepoProvider.collect_calls.append(file_path)
        if CountingRepoProvider.error is not None:
            raise CountingRepoProvider.error
        return list(CountingRepoProvider.items)


class TestHybridRepoContextInjection:
    def _run(self, monkeypatch, tmp_path, *, mode: str, items=None, error=None):
        CountingRepoProvider.reset(items=items, error=error)
        _patch_hybrid_orchestrator(monkeypatch)
        monkeypatch.setattr(
            "ai_pr_review.services.hybrid_orchestrator.RepoContextProvider",
            CountingRepoProvider,
        )
        monkeypatch.setattr(
            "ai_pr_review.services.hybrid_orchestrator.ResultStore",
            RecordingResultStore,
        )
        config = _standard_config(tmp_path)
        config.preferences.repo_context = mode
        orchestrator = HybridReviewOrchestrator(config)
        artifacts = asyncio.run(orchestrator.review("https://github.com/owner/repo/pull/42"))
        return artifacts

    def test_off_does_not_call_provider(self, monkeypatch, tmp_path):
        self._run(monkeypatch, tmp_path, mode="off")

        assert CountingRepoProvider.constructions == 0
        assert CountingRepoProvider.collect_calls == []
        meta = RecordingResultStore.last.saved_metadata["repo_context"]
        assert meta["files"] == []
        assert meta["skipped_reason"] == "off"

    def test_non_off_calls_provider_and_records_metadata(self, monkeypatch, tmp_path):
        items = [
            RelatedFile(
                path="tests/test_src.py",
                reason="test",
                content="def t():\n    pass\n",
                truncated=False,
                from_cache=True,
            ),
            RelatedFile(
                path="pkg/dep.py",
                reason="import",
                content="X = 1\n",
                truncated=True,
                from_cache=False,
            ),
        ]
        self._run(monkeypatch, tmp_path, mode="tests+imports", items=items)

        # StubPRFetcher 造了 4 个文件，每个都会 collect 一次
        assert CountingRepoProvider.constructions == 1
        assert len(CountingRepoProvider.collect_calls) == 4
        meta = RecordingResultStore.last.saved_metadata["repo_context"]
        assert meta["files"] == [
            "tests/test_src.py",
            "pkg/dep.py",
            "tests/test_src.py",
            "pkg/dep.py",
            "tests/test_src.py",
            "pkg/dep.py",
            "tests/test_src.py",
            "pkg/dep.py",
        ]
        assert meta["from_cache"] == 4
        assert meta["truncated"] == ["pkg/dep.py"] * 4
        assert meta["skipped_reason"] is None

    def test_provider_exception_degrades_and_sets_skipped_reason(self, monkeypatch, tmp_path):
        artifacts = self._run(
            monkeypatch,
            tmp_path,
            mode="tests+imports",
            error=RuntimeError("prefetch exploded"),
        )

        # 审查必须正常完成，不能被预取失败打断
        assert artifacts.review_result is not None
        meta = RecordingResultStore.last.saved_metadata["repo_context"]
        assert meta["files"] == []
        assert meta["skipped_reason"] == "prefetch exploded"

    def test_tests_mode_passes_test_only_reasons(self, monkeypatch, tmp_path):
        captured: dict[str, Any] = {}

        class CaptureProvider(CountingRepoProvider):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                captured.update(kwargs)

        CountingRepoProvider.reset()
        _patch_hybrid_orchestrator(monkeypatch)
        monkeypatch.setattr(
            "ai_pr_review.services.hybrid_orchestrator.RepoContextProvider",
            CaptureProvider,
        )
        monkeypatch.setattr(
            "ai_pr_review.services.hybrid_orchestrator.ResultStore",
            RecordingResultStore,
        )
        config = _standard_config(tmp_path)
        config.preferences.repo_context = "tests"
        asyncio.run(
            HybridReviewOrchestrator(config).review("https://github.com/owner/repo/pull/42")
        )

        assert captured.get("reasons") == frozenset({"test"})
        assert captured.get("max_files") == 3
        assert captured.get("budget_tokens") == 4000


class TestFileSystemRepoCache:
    def test_put_then_get_roundtrip(self, tmp_path):
        cache = FileSystemRepoCache("owner", "repo", "sha123", root=tmp_path)
        cache.put("pkg/mod.py", "hello\n")

        assert cache.get("pkg/mod.py") == "hello\n"
        # 落盘路径符合 <root>/<owner>__<repo>/<sha>/<safe-path>.txt
        stored = list(cache.directory.glob("*.txt"))
        assert len(stored) == 1
        assert stored[0].name == "pkg__mod.py.txt"

    def test_miss_returns_none_and_put_is_atomic(self, tmp_path):
        cache = FileSystemRepoCache("o", "r", "s", root=tmp_path)
        assert cache.get("missing.py") is None

        cache.put("a/b.py", "content")
        leftovers = [p for p in cache.directory.iterdir() if p.name.startswith(".tmp-")]
        assert leftovers == []
        assert cache.get("a/b.py") == "content"

    def test_path_traversal_is_sanitized(self, tmp_path):
        cache = FileSystemRepoCache("o", "r", "s", root=tmp_path)
        cache.put("../../evil.py", "x")

        assert cache.get("../../evil.py") == "x"
        # 真正要保证的是：落盘点必须在缓存目录内，不能写出 root 之外。
        target = next(cache.directory.glob("*.txt"))
        assert target.resolve().is_relative_to(cache.directory.resolve())
        assert target.resolve().is_relative_to(tmp_path.resolve())
        # 干净的路径键不得依赖真实目录结构
        assert not (tmp_path.parent / "evil.py").exists()
        assert not (tmp_path / "evil.py").exists()


def test_post_processor_merges_same_location_findings_across_categories() -> None:
    """实测（PR #31 真实 run）：`website/js/main.js:86` 被写成两条
    （high 94% 与 high 80%），只因分类不同（security vs ai_analysis）就没有合并，
    报告里看着像两个独立缺陷。同一文件、同一 10 行桶内只应保留更强的那条。
    """
    processor = PostProcessor(PostProcessorConfig(confidence_threshold=0.6))

    def make(category: str, confidence: float, title: str) -> Finding:
        return Finding(
            severity="high",
            category=category,
            file="website/js/main.js",
            line_start=86,
            line_end=86,
            title=title,
            problem="innerHTML 直接写入",
            suggestion="改用 textContent 或白名单清洗",
            confidence=confidence,
            code_snippet="docsPanelBody.innerHTML = tab.html;",
        )

    processed, stats = processor.process_with_stats(
        ReviewResult(
            summary="s",
            findings=[
                make("security", 0.94, "潜在 HTML 注入"),
                make("performance", 0.80, "未转义写入"),
            ],
        )
    )

    assert [finding.title for finding in processed.findings] == ["潜在 HTML 注入"]
    assert stats["duplicates"] == 1
    assert stats["before"] == 2
    assert stats["after"] == 1


# ---------------------------------------------------------------------------
# 双模型路由 / 成本三处缺陷的回归（2026-09-28）
#
# 这三条都由外部审计发现、主控复核后修复，共同点是"功能看起来在跑，配置/预算却
# 静默失效"。测试都写成**判别性**的：改回旧实现就会红。
# ---------------------------------------------------------------------------


class RecordingModelSelector(StubModelSelector):
    """记录每次路由评估时收到的 static_findings 数量，用来验证"只看本文件"。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seen_by_file: dict[str, int] = {}

    def evaluate_file_complexity(self, **kwargs):
        self.seen_by_file[str(kwargs.get("file_path"))] = len(kwargs.get("static_findings") or [])
        return "low"


class HighFindingForFirstFileAnalyzer(StubStaticAnalyzer):
    """只对 src/file_0.py 报一条高危 finding，其余文件干干净净。"""

    def analyze(self, file_diff: FileDiff, file_context: FileContext) -> list[Finding]:
        if file_diff.filename != "src/file_0.py":
            return []
        return [
            Finding(
                severity="high",
                category="security",
                file=file_diff.filename,
                line_start=1,
                line_end=1,
                title="hardcoded credential",
                problem="problem",
                suggestion="suggestion",
                confidence=0.9,
                code_snippet="pass",
            )
        ]


class CountingAIClient(StubAIClient):
    """统计 AIClient 被实例化了几次。"""

    instances = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        CountingAIClient.instances += 1


class CumulativeCostAIClient(StubAIClient):
    """像真实 ``AIClient`` 那样把 ``total_run_cost`` 做成**实时累计值**。

    与真实实现对齐的契约：

    * ``total_run_cost`` 是**读时求值**的 property，不是 ``__init__`` 时的快照；
    * 拿到共享账本时，任一槽位读到的都是**全局累计**，不会各记一份。
    """

    COST_PER_CALL = 0.25

    def __init__(self, *args, cost_ledger=None, **kwargs):
        # 父类 __init__ 会写 ``self.total_run_cost``（快照式桩值），
        # 因此先让属性承载就位，再清零，避免 1.25 被当成真实花费。
        self._own_total = 0.0
        self._ledger = cost_ledger
        super().__init__(*args, **kwargs)
        self._own_total = 0.0

    @property
    def total_run_cost(self) -> float:
        if self._ledger is not None:
            return self._ledger.run_total
        return self._own_total

    @total_run_cost.setter
    def total_run_cost(self, value: float) -> None:
        self._own_total = float(value)

    async def review_code(self, system_prompt: str, user_prompt: str) -> ReviewResult:
        result = await super().review_code(system_prompt, user_prompt)
        if self._ledger is not None:
            self._ledger.run_total += self.COST_PER_CALL
        else:
            self._own_total += self.COST_PER_CALL
        return result


def test_hybrid_routes_on_current_files_findings_only(monkeypatch, tmp_path):
    """复杂度评估/模型选择只应看到**本文件**的静态发现。

    回归点：原先把全局累计 ``all_findings`` 当单文件 ``static_findings`` 传入，
    于是第一个文件的高危发现会把后续所有文件都推向远程模型（判定随处理顺序放大）。
    """
    selector = RecordingModelSelector()
    # 顺序要紧：`_patch_hybrid_orchestrator` 自己会把 ModelSelector / StaticAnalyzer
    # 换成默认桩，所以自定义桩必须在它**之后**打上去。
    _patch_hybrid_orchestrator(monkeypatch)
    monkeypatch.setattr(
        "ai_pr_review.services.hybrid_orchestrator.ModelSelector", lambda *a, **k: selector
    )
    monkeypatch.setattr(
        "ai_pr_review.services.hybrid_orchestrator.StaticAnalyzer",
        HighFindingForFirstFileAnalyzer,
    )

    asyncio.run(HybridReviewOrchestrator(_standard_config(tmp_path)).review(PR_URL))

    assert selector.seen_by_file["src/file_0.py"] == 1, selector.seen_by_file
    assert selector.seen_by_file["src/file_1.py"] == 0, selector.seen_by_file
    assert selector.seen_by_file["src/file_2.py"] == 0, selector.seen_by_file
    assert selector.seen_by_file["src/file_3.py"] == 0, selector.seen_by_file


def test_hybrid_reuses_one_client_per_model(monkeypatch, tmp_path):
    """同一 provider/model 全程只应建一个 AIClient（run 级预算的载体）。

    回归点：原先在逐文件循环里 ``AIClient(selected_ai_config)``，
    每个客户端各持一份 CostController ⇒ ``max_cost_per_run`` / 24h 预算被按文件数稀释。
    """
    CountingAIClient.instances = 0
    _patch_hybrid_orchestrator(monkeypatch, ai_client=CountingAIClient)

    artifacts = asyncio.run(HybridReviewOrchestrator(_standard_config(tmp_path)).review(PR_URL))

    assert artifacts.run_id == "run-123"
    assert (
        CountingAIClient.instances == 1
    ), f"应为 4 个文件复用 1 个客户端，实际建了 {CountingAIClient.instances} 个"


def test_hybrid_bills_cost_incrementally_with_a_reused_client(monkeypatch, tmp_path):
    """复用客户端后成本必须按**增量**结算，不能把累计值反复相加。

    回归点：``total_run_cost`` 在真实实现里是累计值；若复用客户端却仍
    ``total_cost += client.total_run_cost``，4 个文件会算成 0.25+0.5+0.75+1.0=2.5。
    """
    _patch_hybrid_orchestrator(monkeypatch, ai_client=CumulativeCostAIClient)

    artifacts = asyncio.run(HybridReviewOrchestrator(_standard_config(tmp_path)).review(PR_URL))

    assert artifacts.total_cost == pytest.approx(4 * CumulativeCostAIClient.COST_PER_CALL)


def test_model_selector_reads_budget_from_preferences(tmp_path):
    """路由用的成本上限必须来自 ``preferences.max_cost_per_review``。

    回归点：``ModelSelector`` 原先读 ``self.ai_config``（``AIClientConfig`` 上根本没有
    这个字段），``getattr(..., 0.5)`` 永远返回默认值 —— 用户配的成本上限完全不生效。
    这里用"预算耗尽后本会走远程的 auth 路径"来判别：预算生效 → 本地，预算失效 → 远程。
    """
    from ai_pr_review.services.model_selector import ModelSelector

    config = AppConfig.from_env()
    config.ai_client = AIClientConfig(api_key="api-key")
    config.preferences.max_cost_per_review = 0.01
    selector = ModelSelector(config)

    # 已花 0.02 > 上限 0.01 → 一律本地（即使文件路径命中高危模式）
    selector.total_cost = 0.02
    assert selector._should_use_remote({"file_path": "src/auth_service.py"}) is False

    # 没花钱 → 同一 context 会走远程，证明上面的 False 确实来自预算而非路径判定
    selector.total_cost = 0.0
    assert selector._should_use_remote({"file_path": "src/auth_service.py"}) is True


def test_model_selector_treats_zero_budget_as_no_remote_spend(tmp_path):
    """``max_cost_per_review = 0`` 是合法配置：不该被 ``or 0.5`` 之类的写法吞成 0.5。"""
    from ai_pr_review.services.model_selector import ModelSelector

    config = AppConfig.from_env()
    config.ai_client = AIClientConfig(api_key="api-key")
    config.preferences.max_cost_per_review = 0
    selector = ModelSelector(config)

    assert selector._should_use_remote({"file_path": "src/auth_service.py"}) is False


def test_hybrid_shares_one_ledger_across_slots(monkeypatch, tmp_path):
    """hybrid 的 local / remote 两个客户端必须共享同一个账本。

    判别方式：一轮里两个客户端都会 `record_usage`，共享账本时**每个**客户端读到的
    `total_run_cost` 都等于全局总量（= `artifacts.total_cost`）；若各持一份，
    两个客户端会各自停在 0.5，而 artifacts.total_cost 是 1.0 —— 断言随之失败。
    """

    class AlternatingModelSelector(StubModelSelector):
        """奇偶文件交替走 local / remote，确保 hybrid 真的建出两个客户端。"""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.seen = 0

        def select_model_for_task(self, **kwargs):
            self.seen += 1
            if self.seen % 2 == 0:
                return "deepseek", "deepseek-chat", False
            return "ollama", "qwen3.5:4b", True

    CountingAIClient.instances = 0
    seen_clients: list[Any] = []

    class RecordingAIClient(CumulativeCostAIClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            seen_clients.append(self)

    _patch_hybrid_orchestrator(monkeypatch, ai_client=RecordingAIClient)
    monkeypatch.setattr(
        "ai_pr_review.services.hybrid_orchestrator.ModelSelector",
        lambda *a, **k: AlternatingModelSelector(),
    )

    artifacts = asyncio.run(HybridReviewOrchestrator(_standard_config(tmp_path)).review(PR_URL))

    assert len(seen_clients) == 2, "local / remote 应各建一个客户端"
    assert artifacts.total_cost == pytest.approx(4 * CumulativeCostAIClient.COST_PER_CALL)
    for client in seen_clients:
        assert client.total_run_cost == pytest.approx(
            artifacts.total_cost
        ), "两个槽位必须共享同一账本"
