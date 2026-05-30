"""Review orchestration service."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass

from ai_pr_review.config import AIClientConfig, AppConfig
from ai_pr_review.models.pr_data import FileDiff, PRData
from ai_pr_review.services.ai_client import AIClient
from ai_pr_review.services.context_builder import ContextBuilder, FileContext
from ai_pr_review.services.filter_pipeline import FilterPipeline, FilterPipelineResult
from ai_pr_review.services.post_processor import PostProcessor
from ai_pr_review.services.pr_fetcher import PRFetcher
from ai_pr_review.services.prompt_assembler import PromptAssembler, ReviewResult
from ai_pr_review.services.result_store import ResultStore


@dataclass(slots=True)
class ReviewArtifacts:
    pr_data: PRData
    filter_result: FilterPipelineResult
    review_result: ReviewResult | None = None
    total_cost: float = 0.0
    duration_seconds: float = 0.0
    run_id: str | None = None


class ReviewOrchestrator:
    """Coordinates fetch, filter, review, and persistence."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self._config = config or AppConfig.load()
        self._pr_fetcher = PRFetcher(config=self._config.pr_fetcher)
        self._filter_pipeline = FilterPipeline(config=self._config.filter_pipeline)
        self._context_builder = ContextBuilder(config=self._config.context_builder)
        self._prompt_assembler = PromptAssembler(config=self._config.prompt_assembler)
        self._post_processor = PostProcessor(config=self._config.post_processor)

    async def fetch_only(self, pr_url: str) -> ReviewArtifacts:
        start_time = time.perf_counter()
        pr_data = await asyncio.to_thread(self._pr_fetcher.fetch, pr_url)
        return ReviewArtifacts(
            pr_data=pr_data,
            filter_result=FilterPipelineResult(),
            duration_seconds=time.perf_counter() - start_time,
        )

    async def filter_only(self, pr_url: str) -> ReviewArtifacts:
        start_time = time.perf_counter()
        pr_data = await asyncio.to_thread(self._pr_fetcher.fetch, pr_url)
        _, filter_result = self._filter_pipeline.filter_pr_data(pr_data)
        return ReviewArtifacts(
            pr_data=pr_data,
            filter_result=filter_result,
            duration_seconds=time.perf_counter() - start_time,
        )

    async def review(
        self,
        pr_url: str,
        *,
        model: str | None = None,
        progress_callback: Callable[[str, str], None] | None = None,
    ) -> ReviewArtifacts:
        start_time = time.perf_counter()
        app_config = self._config
        if model:
            app_config.ai_client = AIClientConfig(
                **{**app_config.ai_client.__dict__, "model": model}
            )

        pr_data = await asyncio.to_thread(self._pr_fetcher.fetch, pr_url)
        filtered_pr_data, filter_result = self._filter_pipeline.filter_pr_data(pr_data)
        ai_client = AIClient(config=app_config.ai_client)

        file_contexts = await self._build_file_contexts(pr_data, filtered_pr_data.files)
        file_results = await self._review_file_contexts(
            file_contexts,
            ai_client,
            app_config.ai_client.review_concurrency,
            progress_callback,
        )

        summaries: list[str] = []
        findings = []
        for file_diff, file_result in zip(filtered_pr_data.files, file_results, strict=False):
            if file_result.summary.strip():
                summaries.append(f"{file_diff.filename}: {file_result.summary.strip()}")
            findings.extend(file_result.findings)

        raw_result = ReviewResult(
            summary="\n".join(summaries) if summaries else self._build_empty_summary(filter_result),
            findings=findings,
        )
        review_result = self._post_processor.process(raw_result)
        if not review_result.summary.strip():
            review_result = review_result.model_copy(
                update={"summary": self._build_empty_summary(filter_result)}
            )

        duration_seconds = time.perf_counter() - start_time
        total_cost = getattr(ai_client, "total_run_cost", 0.0)
        run_id = ResultStore(config=app_config.result_store).save_result(
            pr_url,
            review_result,
            head_sha=pr_data.head_sha,
            total_files=pr_data.changed_files_count,
            included_files=filter_result.included_count,
            excluded_files=filter_result.excluded_count,
            total_cost=total_cost,
            duration_seconds=duration_seconds,
            model=app_config.ai_client.model,
        )

        return ReviewArtifacts(
            pr_data=pr_data,
            filter_result=filter_result,
            review_result=review_result,
            total_cost=total_cost,
            duration_seconds=duration_seconds,
            run_id=run_id,
        )

    async def _build_file_contexts(
        self,
        pr_data: PRData,
        files: list[FileDiff],
    ) -> list[tuple[FileDiff, FileContext]]:
        semaphore = asyncio.Semaphore(max(1, self._config.pr_fetcher.fetch_concurrency))

        async def build_file_context(file_diff: FileDiff) -> tuple[FileDiff, FileContext]:
            async with semaphore:
                full_content = await asyncio.to_thread(
                    self._pr_fetcher.fetch_file_content,
                    pr_data.owner,
                    pr_data.repo,
                    file_diff.filename,
                    pr_data.head_sha,
                )
            file_context = self._context_builder.build_context(
                file_diff.filename,
                file_diff.patch or "",
                full_content or "",
            )
            return file_diff, file_context

        return await asyncio.gather(*(build_file_context(file_diff) for file_diff in files))

    async def _review_file_contexts(
        self,
        file_contexts: list[tuple[FileDiff, FileContext]],
        ai_client: AIClient,
        concurrency: int,
        progress_callback: Callable[[str, str], None] | None,
    ) -> list[ReviewResult]:
        semaphore = asyncio.Semaphore(max(1, concurrency))

        async def review_file(file_diff: FileDiff, file_context: FileContext) -> ReviewResult:
            system_prompt = self._prompt_assembler.build_system_prompt(file_context.language)
            user_prompt = self._prompt_assembler.build_user_prompt(file_context)
            if progress_callback is not None:
                progress_callback(file_diff.filename, self._config.ai_client.model)
            async with semaphore:
                return await ai_client.review_code(system_prompt, user_prompt)

        return await asyncio.gather(
            *(review_file(file_diff, file_context) for file_diff, file_context in file_contexts)
        )

    def _build_empty_summary(self, filter_result: FilterPipelineResult) -> str:
        if filter_result.included_count == 0:
            return "No reviewable files remained after filtering."
        return "No valid findings were identified."


__all__ = ["ReviewArtifacts", "ReviewOrchestrator"]
