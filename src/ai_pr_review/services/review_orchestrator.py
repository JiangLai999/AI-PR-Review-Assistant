"""Review orchestration service."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ai_pr_review.config import AIClientConfig, AppConfig
from ai_pr_review.models.pr_data import FileDiff, FileStatus, PRData
from ai_pr_review.models.review_plan import CrossFileImpact, ReviewPlan
from ai_pr_review.services.agent.planner import ReviewPlanner
from ai_pr_review.services.ai_client import AIClient
from ai_pr_review.services.analyzers.cross_file_interface import (
    CrossFileInterfaceAnalyzer,
    InterfaceImpact,
)
from ai_pr_review.services.analyzers.finding_merge import combine_findings
from ai_pr_review.services.analyzers.python_ast_analyzer import PythonAstAnalyzer
from ai_pr_review.services.analyzers.static_analyzer import StaticAnalyzer
from ai_pr_review.services.analyzers.symbol_index import SymbolDefinition, SymbolIndex
from ai_pr_review.services.context_builder import ContextBuilder, FileContext
from ai_pr_review.services.evidence.finding_validator import FindingValidator
from ai_pr_review.services.filter_pipeline import FilterPipeline, FilterPipelineResult
from ai_pr_review.services.finding_localizer import localize_deterministic_finding
from ai_pr_review.services.model_capabilities import (
    calculate_review_output_budget,
    get_model_capabilities,
)
from ai_pr_review.services.post_processor import PostProcessor
from ai_pr_review.services.pr_fetcher import PRFetcher
from ai_pr_review.services.prompt_assembler import PromptAssembler, ReviewResult
from ai_pr_review.services.result_store import ResultStore


class ReviewCancelled(Exception):
    """审查被调用方取消。停止发生在文件之间，无法中断在飞的模型调用。"""


FILTER_REASON_SUMMARY_LABELS = {
    "excluded_by_pattern": "命中黑名单规则",
    "excluded_deletion_only": "仅删除改动",
    "excluded_too_large": "变更量过大",
    "custom_rule": "自定义规则过滤",
}


def elapsed_ms(started_at: float) -> int:
    """Milliseconds since `time.perf_counter()` reading `started_at`."""
    return max(0, round((time.perf_counter() - started_at) * 1000))


def file_result_payload(
    filename: str,
    status: str,
    *,
    findings_count: int | None = None,
    duration_ms: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Build one `file_result_callback` payload (contract §10.2).

    Every field is always present so callers can rely on the shape; unknown
    values stay `None` instead of being estimated.
    """
    return {
        "filename": filename,
        "status": status,
        "findings_count": findings_count,
        "duration_ms": duration_ms,
        "error": error,
    }


def emit_file_result(
    callback: Callable[[dict[str, Any]], None] | None,
    filename: str,
    status: str,
    **fields: Any,
) -> None:
    if callback is not None:
        callback(file_result_payload(filename, status, **fields))


def emit_skipped_file_results(
    callback: Callable[[dict[str, Any]], None] | None,
    filter_result: FilterPipelineResult,
) -> None:
    """Report every file the filter pipeline removed as `skipped`.

    `file_done_callback` is deliberately not called for these files: it only
    ever fired for files that entered review, and callers pair it with
    `progress_callback`. A filtered file spends no review time, so
    `duration_ms` is a real 0 rather than an estimate.
    """
    if callback is None:
        return
    for entry in getattr(filter_result, "results", None) or []:
        if getattr(entry, "included", True):
            continue
        emit_file_result(
            callback,
            entry.file.filename,
            "skipped",
            findings_count=None,
            duration_ms=0,
            error=None,
        )


@dataclass(slots=True)
class ReviewArtifacts:
    pr_data: PRData
    filter_result: FilterPipelineResult
    review_result: ReviewResult | None = None
    total_cost: float = 0.0
    duration_seconds: float = 0.0
    run_id: str | None = None
    review_plan: ReviewPlan | None = None
    validation_summary: dict[str, int] = field(default_factory=dict)
    # PostProcessor 的过滤计数（before/after/below_threshold/duplicates/
    # severity_sorted），与 run metadata 的 `filtered_findings` 同源同值。
    filtered_findings: dict[str, Any] = field(default_factory=dict)
    cross_file_impacts: list[CrossFileImpact] = field(default_factory=list)
    interface_impacts: list[InterfaceImpact] = field(default_factory=list)


class ReviewOrchestrator:
    """Coordinates fetch, filter, review, and persistence."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self._config = config or AppConfig.load()
        self._pr_fetcher = PRFetcher(config=self._config.pr_fetcher)
        self._filter_pipeline = FilterPipeline(config=self._config.filter_pipeline)
        self._context_builder = ContextBuilder(config=self._config.context_builder)
        self._prompt_assembler = PromptAssembler(
            config=self._config.prompt_assembler,
            response_language=getattr(self._config.preferences, "language", "zh-CN"),
        )
        self._post_processor = PostProcessor(config=self._config.post_processor)
        self._planner = ReviewPlanner()
        self._static_analyzer = StaticAnalyzer()
        self._python_ast_analyzer = PythonAstAnalyzer()
        self._cross_file_interface = CrossFileInterfaceAnalyzer()
        self._finding_validator = FindingValidator()

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

    async def plan_only(self, pr_url: str) -> ReviewArtifacts:
        """Fetch, filter, and produce a transparent review plan without AI calls."""
        start_time = time.perf_counter()
        pr_data = await asyncio.to_thread(self._pr_fetcher.fetch, pr_url)
        _, filter_result = self._filter_pipeline.filter_pr_data(pr_data)
        return ReviewArtifacts(
            pr_data=pr_data,
            filter_result=filter_result,
            review_plan=self._planner.build_plan(pr_data, filter_result),
            duration_seconds=time.perf_counter() - start_time,
        )

    async def review(
        self,
        pr_url: str,
        *,
        model: str | None = None,
        progress_callback: Callable[[str, str], None] | None = None,
        file_done_callback: Callable[[str], None] | None = None,
        stage_callback: Callable[[str, str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        file_result_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> ReviewArtifacts:
        """执行完整审查。

        `progress_callback(filename, model)` 在**真正开始处理**某个文件时触发
        （即拿到并发额度之后），`file_done_callback(filename)` 在该文件完成后触发。
        两者配对才能驱动一个诚实的进度条：只报"开始"而不报"完成"会让人以为卡死。

        `stage_callback(stage, detail)` 报告非文件级的阶段变化（抓取、规划、落库等）。

        `file_result_callback(payload)` 是可选的真实结果回调（契约 §10.2）：
        `payload` 含 filename/status(`reviewed`|`skipped`|`failed`)/findings_count/
        duration_ms/error。被过滤掉的文件报 `skipped`（不触发 `file_done_callback`），
        模型调用抛异常时先报 `failed` 再照旧抛出；`findings_count` 无法取得时为 None，
        且只统计该文件模型调用返回的 finding（确定性规则结论在运行级合并，不按文件归属）。

        `cancel_check()` 在每个文件边界被调用；返回 True 时抛出 `ReviewCancelled`。
        注意：无法中断已经在飞的模型调用，停止发生在文件之间。
        """
        start_time = time.perf_counter()
        app_config = self._config
        if model:
            app_config.ai_client = AIClientConfig(
                **{**app_config.ai_client.__dict__, "model": model}
            )

        def stage(name: str, detail: str = "") -> None:
            if cancel_check is not None and cancel_check():
                raise ReviewCancelled()
            if stage_callback is not None:
                stage_callback(name, detail)

        stage("fetching", "正在读取 PR 元数据与变更内容")
        pr_data = await asyncio.to_thread(self._pr_fetcher.fetch, pr_url)
        stage("filtering", f"共 {pr_data.changed_files_count} 个变更文件，正在过滤")
        filtered_pr_data, filter_result = self._filter_pipeline.filter_pr_data(pr_data)
        review_plan = self._planner.build_plan(pr_data, filter_result)
        # 被过滤掉的文件永远不会进入审查循环，只能在这里如实上报。
        emit_skipped_file_results(file_result_callback, filter_result)
        ai_client = AIClient(config=app_config.ai_client)

        stage("context", f"正在为 {filter_result.included_count} 个文件构建上下文")
        file_contexts = await self._build_file_contexts(pr_data, filtered_pr_data.files)
        stage("reviewing", f"开始逐文件审查（并发 {app_config.ai_client.review_concurrency}）")
        file_results = await self._review_file_contexts(
            file_contexts,
            ai_client,
            app_config.ai_client.review_concurrency,
            progress_callback,
            review_plan,
            file_done_callback=file_done_callback,
            file_result_callback=file_result_callback,
        )
        stage("cross_file", "正在分析跨文件接口影响")
        cross_file_contexts = file_contexts[: max(1, app_config.ai_client.cross_file_max_files)]
        cross_file_impacts, cross_file_references = (
            self._cross_file_interface.build_relationship_map(cross_file_contexts)
        )
        base_signatures = await self._load_base_signatures(pr_data, cross_file_contexts)
        interface_impacts = self._cross_file_interface.analyze(
            cross_file_contexts, base_signatures=base_signatures
        )

        summaries: list[str] = []
        findings = []
        validation_counts = {"valid": 0, "needs_review": 0, "invalid": 0}
        for (file_diff, file_context), file_result in zip(
            file_contexts, file_results, strict=False
        ):
            if file_result.summary.strip():
                summaries.append(f"{file_diff.filename}: {file_result.summary.strip()}")
            candidate_findings = list(file_result.findings)
            if app_config.ai_client.enable_static_analysis:
                candidate_findings.extend(
                    combine_findings(
                        self._static_analyzer.analyze(file_diff, file_context),
                        self._python_ast_analyzer.analyze(file_diff, file_context),
                    )
                )
            for finding in candidate_findings:
                finding = localize_deterministic_finding(
                    finding, getattr(app_config.preferences, "language", "zh-CN")
                )
                evidence = self._finding_validator.validate(finding, file_diff, file_context)
                findings.append(self._finding_validator.annotate(finding, evidence))
                validation_counts[evidence.validation_status] += 1

        if (
            app_config.ai_client.enable_cross_file_review
            and review_plan.requires_cross_file_analysis
            and len(cross_file_contexts) > 1
        ):
            cross_file_result = await self._review_cross_file_contexts(
                cross_file_contexts,
                cross_file_impacts,
                ai_client,
                review_plan,
                interface_impacts=interface_impacts,
            )
            for finding in cross_file_result.findings:
                evidence = self._finding_validator.validate_against_contexts(
                    finding, cross_file_contexts
                )
                findings.append(self._finding_validator.annotate(finding, evidence))
                validation_counts[evidence.validation_status] += 1
            if cross_file_result.summary.strip():
                summaries.append(f"Cross-file impact: {cross_file_result.summary.strip()}")

        raw_result = ReviewResult(
            summary="\n".join(summaries) if summaries else self._build_empty_summary(filter_result),
            findings=findings,
        )
        review_result, filtered_findings = self._post_processor.process_with_stats(raw_result)
        if not review_result.summary.strip():
            review_result = review_result.model_copy(
                update={"summary": self._build_empty_summary(filter_result)}
            )

        stage("persisting", "正在写入本地 SQLite 历史与反馈数据")
        duration_seconds = time.perf_counter() - start_time
        total_cost = getattr(ai_client, "total_run_cost", 0.0)
        # Re-check right before persisting: cancelling after the last stage
        # callback used to still write a run into history and report completion.
        if cancel_check is not None and cancel_check():
            raise ReviewCancelled()
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
            metadata={
                # Kept so `/publish` can render the real PR title later; runs
                # saved before this field existed have no title at all and are
                # published with an explicit placeholder instead (§12.2).
                "pr_title": pr_data.title,
                # 同理：发布时只能从库里重建 PRData，作者也只能来自这里。
                # 抓不到作者时写空串，由发布路径决定用什么占位符。
                "pr_author": pr_data.author or "",
                # Fork 信息（P6 ③）：`/publish` 之后只能从库里重建 PRData，而 fork
                # 的 head commit 不在 base 仓库里，blob 链接必然 404。存下这个判断，
                # 历史 Run 没有该键即保持原有的 blob 行为。
                "fork": {
                    "is_fork": pr_data.is_fork,
                    "head_repo": pr_data.head_repo_full_name,
                },
                "review_plan": review_plan.model_dump(mode="json"),
                "language": {
                    "ui_language": getattr(app_config.preferences, "ui_language", "zh-CN"),
                    "response_language": getattr(app_config.preferences, "language", "zh-CN"),
                },
                "review_policy": {
                    "provider": app_config.ai_client.provider,
                    "model": app_config.ai_client.model,
                    "output_budget": calculate_review_output_budget(
                        app_config.ai_client.provider,
                        app_config.ai_client.model,
                        input_chars=sum(
                            len(context.diff_with_context) for _, context in file_contexts
                        ),
                        cross_file=review_plan.requires_cross_file_analysis,
                    ),
                    "capabilities": {
                        "supports_json_object": get_model_capabilities(
                            app_config.ai_client.provider, app_config.ai_client.model
                        ).supports_json_object,
                        "supports_thinking_disable": get_model_capabilities(
                            app_config.ai_client.provider, app_config.ai_client.model
                        ).supports_thinking_disable,
                    },
                },
                "validation_summary": validation_counts,
                # 后处理丢掉了多少（门槛/去重）：报告与历史 Run 都能解释
                # 「模型给了 N 条、库里为什么只有 M 条」。
                "filtered_findings": filtered_findings,
                "cross_file_impacts": [
                    impact.model_dump(mode="json") for impact in cross_file_impacts
                ],
                "interface_impacts": [impact.to_dict() for impact in interface_impacts],
            },
        )

        return ReviewArtifacts(
            pr_data=pr_data,
            filter_result=filter_result,
            review_result=review_result,
            total_cost=total_cost,
            duration_seconds=duration_seconds,
            run_id=run_id,
            review_plan=review_plan,
            validation_summary=validation_counts,
            filtered_findings=filtered_findings,
            cross_file_impacts=cross_file_impacts,
            interface_impacts=interface_impacts,
        )

    async def _load_base_signatures(
        self,
        pr_data: PRData,
        contexts: list[tuple[FileDiff, FileContext]],
    ) -> dict[str, SymbolDefinition]:
        """从 PR base 版本读取同名文件，提取变更前的符号签名。

        只有能取到 base 版本时才做签名对比；失败时返回空字典，
        接口影响分析会自然退化为“无签名变更”。
        """
        if not pr_data.base_sha or len(contexts) < 2:
            return {}

        semaphore = asyncio.Semaphore(max(1, self._config.pr_fetcher.fetch_concurrency))

        async def load_one(file_diff: FileDiff) -> tuple[str, str] | None:
            if file_diff.status.value == "added":
                return None
            async with semaphore:
                content = await asyncio.to_thread(
                    self._pr_fetcher.fetch_file_content,
                    pr_data.owner,
                    pr_data.repo,
                    file_diff.filename,
                    pr_data.base_sha,
                )
            if not content:
                return None
            return file_diff.filename, content

        results = await asyncio.gather(
            *(load_one(file_diff) for file_diff, _ in contexts), return_exceptions=True
        )

        base_contexts: list[tuple[FileDiff, FileContext]] = []
        for item in results:
            if isinstance(item, BaseException) or item is None:
                continue
            filename, content = item
            file_diff = FileDiff(
                filename=filename,
                status=FileStatus.MODIFIED,
                additions=0,
                deletions=0,
                changes=0,
                patch="",
            )
            base_contexts.append(
                (file_diff, self._context_builder.build_context(filename, "", content))
            )

        if not base_contexts:
            return {}
        return SymbolIndex(base_contexts).signature_map()

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
        review_plan: ReviewPlan | None = None,
        file_done_callback: Callable[[str], None] | None = None,
        file_result_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> list[ReviewResult]:
        semaphore = asyncio.Semaphore(max(1, concurrency))

        async def review_file(file_diff: FileDiff, file_context: FileContext) -> ReviewResult:
            system_prompt = self._prompt_assembler.build_system_prompt(file_context.language)
            user_prompt = self._build_file_prompt(file_context, review_plan)
            async with semaphore:
                # 回调放在拿到并发额度之后：否则并发时会瞬间把全部文件报成
                # "已开始"，之后长时间无动静，进度条反而更不可信。
                if progress_callback is not None:
                    progress_callback(file_diff.filename, self._config.ai_client.model)
                started_at = time.perf_counter()
                try:
                    result = await ai_client.review_code(system_prompt, user_prompt)
                except Exception as exc:
                    # 先如实上报失败，再保持原有的"异常向上抛、整轮审查终止"语义。
                    emit_file_result(
                        file_result_callback,
                        file_diff.filename,
                        "failed",
                        findings_count=None,
                        duration_ms=elapsed_ms(started_at),
                        error=str(exc) or exc.__class__.__name__,
                    )
                    raise
                else:
                    findings = getattr(result, "findings", None)
                    emit_file_result(
                        file_result_callback,
                        file_diff.filename,
                        "reviewed",
                        findings_count=len(findings) if isinstance(findings, list) else None,
                        duration_ms=elapsed_ms(started_at),
                        error=None,
                    )
                    return result
                finally:
                    if file_done_callback is not None:
                        file_done_callback(file_diff.filename)

        return await asyncio.gather(
            *(review_file(file_diff, file_context) for file_diff, file_context in file_contexts)
        )

    def _build_file_prompt(self, file_context: FileContext, review_plan: ReviewPlan | None) -> str:
        """Keep custom PromptAssembler implementations source-compatible."""
        try:
            return self._prompt_assembler.build_user_prompt(file_context, review_plan)
        except TypeError as exc:
            if "positional" not in str(exc) and "argument" not in str(exc):
                raise
            return self._prompt_assembler.build_user_prompt(file_context)

    async def _review_cross_file_contexts(
        self,
        contexts: list[tuple[FileDiff, FileContext]],
        impacts: list[CrossFileImpact],
        ai_client: AIClient,
        review_plan: ReviewPlan,
        interface_impacts: list[InterfaceImpact] | None = None,
    ) -> ReviewResult:
        system_prompt = self._prompt_assembler.build_cross_file_system_prompt()
        user_prompt = self._prompt_assembler.build_cross_file_user_prompt(
            contexts,
            impacts,
            review_plan,
            interface_impacts=interface_impacts,
        )
        return await ai_client.review_code(system_prompt, user_prompt)

    def _build_empty_summary(self, filter_result: FilterPipelineResult) -> str:
        if filter_result.included_count == 0:
            reason_counts = filter_result.excluded_reason_counts()
            if not reason_counts:
                return "No reviewable files remained after filtering."
            parts = [
                f"{FILTER_REASON_SUMMARY_LABELS.get(code, code)} {count} 个"
                for code, count in sorted(reason_counts.items())
            ]
            return (
                "No reviewable files remained after filtering. "
                f"Excluded {filter_result.excluded_count} files: {'; '.join(parts)}."
            )
        return "No valid findings were identified."


__all__ = [
    "ReviewArtifacts",
    "ReviewOrchestrator",
    "elapsed_ms",
    "emit_file_result",
    "emit_skipped_file_results",
    "file_result_payload",
]
