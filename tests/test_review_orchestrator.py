"""ReviewOrchestrator tests."""

from __future__ import annotations

import asyncio

from ai_pr_review.config import AIClientConfig, AppConfig, PRFetcherConfig, ResultStoreConfig
from ai_pr_review.models.pr_data import FileDiff, FileStatus, PRData
from ai_pr_review.services.context_builder import FileContext
from ai_pr_review.services.filter_pipeline import FilterPipelineResult
from ai_pr_review.services.prompt_assembler import Finding, ReviewResult
from ai_pr_review.services.review_orchestrator import ReviewOrchestrator


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
