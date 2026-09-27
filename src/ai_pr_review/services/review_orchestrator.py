"""Review orchestration service."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ai_pr_review.config import AIClientConfig, AppConfig
from ai_pr_review.models.pr_data import FileDiff, FileStatus, PRData
from ai_pr_review.models.review_plan import CrossFileImpact, CrossFileReference, ReviewPlan
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
from ai_pr_review.services.patch_generator import PatchGenerator, is_patch_eligible
from ai_pr_review.services.post_processor import PostProcessor
from ai_pr_review.services.pr_fetcher import PRFetcher
from ai_pr_review.services.prompt_assembler import Finding, PromptAssembler, ReviewResult
from ai_pr_review.services.repo_context import FileSystemRepoCache
from ai_pr_review.services.result_store import ResultStore
from ai_pr_review.services.symbol_locator import (
    RepoSymbolLocator,
    SymbolLocation,
    changed_symbols_from_impacts,
)

logger = logging.getLogger(__name__)


class ReviewCancelled(Exception):
    """审查被调用方取消。

    既在文件之间生效，也能中断已经在飞的模型调用（见
    `call_with_cancellation`）：抛出时，本次审查发起的模型调用都已收到取消。
    """


# 轮询取消标志的间隔：`asyncio.wait(timeout=...)` 到点就醒，所以取消请求最多
# 迟这么久生效，而不是等到整个模型调用返回。
CANCEL_POLL_INTERVAL_SECONDS = 0.25

# 发出取消后等待在飞任务真正收尾的上限。底层客户端若无视取消（例如把请求丢给
# 不响应取消的线程），也不能让用户一直等：到点就按已取消返回。
CANCEL_SETTLE_TIMEOUT_SECONDS = 1.0


FILTER_REASON_SUMMARY_LABELS = {
    "excluded_by_pattern": "命中黑名单规则",
    "excluded_deletion_only": "仅删除改动",
    "excluded_too_large": "变更量过大",
    "custom_rule": "自定义规则过滤",
}


def elapsed_ms(started_at: float) -> int:
    """Milliseconds since `time.perf_counter()` reading `started_at`."""
    return max(0, round((time.perf_counter() - started_at) * 1000))


def _stat_value(usage: object, key: str) -> int:
    """从 ``usage_stats()`` 的结果里取一个非负整数；缺失/坏值记 0（不编造）。"""
    if not isinstance(usage, dict):
        return 0
    try:
        return max(0, int(usage.get(key, 0) or 0))
    except (TypeError, ValueError):
        return 0


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


async def call_with_cancellation(
    call: Callable[[], Awaitable[Any]],
    cancel_check: Callable[[], bool] | None,
    *,
    poll_interval: float = CANCEL_POLL_INTERVAL_SECONDS,
    settle_timeout: float = CANCEL_SETTLE_TIMEOUT_SECONDS,
) -> Any:
    """Run one model call in its own task so a cancel request can stop it mid-flight.

    只检查文件边界是不够的：一个 30 秒的模型调用会让按了 Esc 的用户继续等满
    30 秒。这里把调用包成 `asyncio.Task`，每 `poll_interval` 秒（`asyncio.wait`
    的 timeout 到点即醒）查一次 `cancel_check()`；一旦已请求取消就
    `task.cancel()`，**等它收尾**（HTTP 请求/桩都看到取消）再抛
    `ReviewCancelled`。

    取消语义不吞：用户取消转成 `ReviewCancelled`；调用方自己被取消（超时、退出）
    时先停掉在飞的调用，再把 `CancelledError` 原样抛出去。
    """
    task = asyncio.ensure_future(call())
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=poll_interval)
            if done:
                return task.result()
            if cancel_check is not None and cancel_check():
                task.cancel()
                # 等任务真的结束再抛：这样 `ReviewCancelled` 的含义是"没有调用
                # 还在跑"，而不是"我先走了，它自己慢慢跑"。
                await asyncio.wait({task}, timeout=settle_timeout)
                raise ReviewCancelled()
    except asyncio.CancelledError:
        # 调用方在取消我们：把在飞的模型调用一起停掉，别留下没人接的 HTTP 请求。
        task.cancel()
        try:
            await asyncio.wait({task}, timeout=settle_timeout)
        except asyncio.CancelledError:
            # 收尾期间又被取消一次：任务已收到取消请求，让原始取消继续传播。
            task.cancel()
        raise


async def _cancel_in_flight(tasks: list[asyncio.Task[Any]]) -> None:
    """Stop every task still in flight and wait for it to actually end.

    `asyncio.gather` 只把第一个异常抛出来，同批任务会继续跑：取消时若不显式
    收尾，其余文件（以及它们的模型调用）会在 `ReviewCancelled` 之后继续存在。
    """
    pending = [task for task in tasks if not task.done()]
    if not pending:
        return
    for task in pending:
        task.cancel()
    try:
        done, _ = await asyncio.wait(pending, timeout=CANCEL_SETTLE_TIMEOUT_SECONDS)
    except asyncio.CancelledError:
        # 外层正在取消（超时/退出）：任务已收到取消请求，让原异常继续向上抛。
        for task in pending:
            task.cancel()
        return
    for task in done:
        if not task.cancelled():
            # 取出异常（即使不处理），否则事件循环会在回收时报
            # "Task exception was never retrieved"。
            task.exception()


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

    def _plan_language(self) -> str:
        """计划文案跟随**界面语言**。

        与 `services/i18n_text` 的既有分工一致：`ui_language` 管"生成时冻结的展示文案"
        （摘要 `review_summary`、过滤原因 `filter_included_by_default` 都用的它），
        `language` 管"模型用什么语言回答"（`PromptAssembler.response_language`）。
        计划随 run 落库、之后由界面原样回放，所以属于前者。
        """
        return str(getattr(self._config.preferences, "ui_language", "") or "zh-CN")

    async def plan_only(self, pr_url: str) -> ReviewArtifacts:
        """Fetch, filter, and produce a transparent review plan without AI calls."""
        start_time = time.perf_counter()
        pr_data = await asyncio.to_thread(self._pr_fetcher.fetch, pr_url)
        _, filter_result = self._filter_pipeline.filter_pr_data(pr_data)
        return ReviewArtifacts(
            pr_data=pr_data,
            filter_result=filter_result,
            review_plan=self._planner.build_plan(pr_data, filter_result, language=self._plan_language()),
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

        `cancel_check()` 在每个文件边界被调用，并在模型调用进行中被轮询（见
        `call_with_cancellation`）；返回 True 时抛出 `ReviewCancelled`，在飞的
        调用已随取消中止，尚未开始的文件不会再调度。取消发生在任何写库之前，
        因此被取消的审查不会留下 run 记录，也不会为没有结论的文件发
        `reviewed`/`failed`/`skipped` 回调；`file_done_callback` 同理不触发
        （reviewed / failed 两条正常路径的触发时机与顺序逐字未变）。
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
        review_plan = self._planner.build_plan(
            pr_data, filter_result, language=self._plan_language()
        )
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
            cancel_check=cancel_check,
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
        # L2：仅在签名真实变化时定位外部引用；无变化零请求，异常降级为空。
        symbols_located = self._locate_changed_symbols(
            pr_data,
            interface_impacts,
            exclude_paths={file_diff.filename for file_diff, _ in file_contexts},
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
                cancel_check=cancel_check,
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

        # L3 修复建议（docs/repo-aware-review-plan.md §6）：写库前给达标 finding 生成
        # unified diff 片段。开关默认关闭；关闭时不构造生成器、零模型调用。
        # 刻意不新增 stage id：CLI/TUI 的 stage 标签表不在本任务写集内，未知 id 会
        # 显示成裸 id 且进度条回退（见 docs/claude-l3-patch.md）。
        review_result, suggested_patch_stats = await self._attach_suggested_patches(
            review_result, file_contexts, ai_client, cancel_check
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
                # L2 符号定位：仅签名变化符号；定位为空时该符号如实缺席。
                "symbols_located": symbols_located,
                # L3 修复建议（§6）：开关状态 + 达标条数 + 生成/跳过/非法输出计数 +
                # 真实 token 用量。开关关闭时这几个数字必须是 0，便于审计"没花钱"。
                "suggested_patches": suggested_patch_stats,
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

    def _suggested_patch_enabled(self) -> bool:
        """``preferences.suggested_patch``：默认关闭。

        开启 = 每条达标 finding 多一次模型调用（真实成本），所以只有用户显式
        打开才跑。读法与邻居 ``_symbol_locate_enabled`` 一致：构造时
        ``PreferencesConfig.__post_init__`` 已归一化，这里只做布尔化。
        """
        return bool(getattr(self._config.preferences, "suggested_patch", False))

    async def _attach_suggested_patches(
        self,
        review_result: ReviewResult,
        file_contexts: list[tuple[FileDiff, FileContext]],
        ai_client: AIClient,
        cancel_check: Callable[[], bool] | None,
    ) -> tuple[ReviewResult, dict[str, Any]]:
        """为达标 finding 生成修复建议 patch，返回 (结果, 统计)。

        达标 = ``critical``/``high`` 且 ``evidence_status == "valid"``（方案 §6）。
        补丁只写回 ``Finding.suggested_patch``：不落盘到用户仓库、不提交。

        - 开关关闭时**不构造** ``PatchGenerator``、不发起任何调用（零成本）；
        - 生成失败/输出不合法/找不到该文件的上下文一律如实计入 ``patches_skipped``，
          绝不中断审查；
        - 取消语义与逐文件审查一致：每个 finding 的调用都经
          ``call_with_cancellation``，用户取消时抛 ``ReviewCancelled``，不写库。
        """
        findings = list(review_result.findings)
        candidates = [finding for finding in findings if is_patch_eligible(finding)]
        stats: dict[str, Any] = {
            "enabled": self._suggested_patch_enabled(),
            "candidates": len(candidates),
            "patches_generated": 0,
            "patches_skipped": 0,
            "calls": 0,
            "patches_invalid": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }
        if not stats["enabled"] or not candidates:
            return self._clear_suggested_patches(review_result), stats

        try:
            generator = PatchGenerator(client=ai_client)
        except Exception as exc:
            # 构造失败也属于"补丁生成不可用"：判过档的 finding 全部如实记为跳过。
            logger.warning("patch generator unavailable: %s", exc)
            stats["patches_skipped"] = len(candidates)
            return self._clear_suggested_patches(review_result), stats

        # finding.file -> 该文件的上下文：模型审查 A 却点名 B（跨文件 finding）时，
        # 也必须用 B 自己的内容来写 B 的补丁；找不到上下文就如实跳过。
        contexts = {file_diff.filename: context for file_diff, context in file_contexts}

        updated: list[Finding] = []
        for finding in findings:
            patch = ""
            if is_patch_eligible(finding):
                context = contexts.get(finding.file)
                if context is not None:
                    try:
                        patch = await call_with_cancellation(
                            lambda: generator.generate(finding, context), cancel_check
                        )
                    except ReviewCancelled:
                        raise
                    except Exception as exc:
                        # 兜底：生成器已自行降级，这里防的是自定义/替身实现抛出的异常。
                        logger.warning(
                            "suggested patch generation failed for %s: %s",
                            finding.file,
                            exc,
                        )
                if patch:
                    stats["patches_generated"] += 1
                else:
                    stats["patches_skipped"] += 1
            # 一律以本方法的结论重建该字段：schema 里没有它，模型自述的值不算数
            # （与 sources/evidence_status 等服务端字段同一条原则）。
            updated.append(finding.model_copy(update={"suggested_patch": patch}))

        try:
            usage = generator.usage_stats()
        except Exception as exc:
            # 统计读不出来不影响结果：数字保持 0（不编造），补丁照常写回。
            logger.warning("patch usage stats unavailable: %s", exc)
            usage = {}
        stats.update(
            {
                "calls": _stat_value(usage, "calls"),
                "patches_invalid": _stat_value(usage, "invalid_outputs"),
                "input_tokens": _stat_value(usage, "input_tokens"),
                "output_tokens": _stat_value(usage, "output_tokens"),
            }
        )
        return review_result.model_copy(update={"findings": updated}), stats

    @staticmethod
    def _clear_suggested_patches(review_result: ReviewResult) -> ReviewResult:
        """清空模型自述的 ``suggested_patch``；没有值时原样返回（零拷贝）。

        该字段只由 ``PatchGenerator`` 生成并经语法校验写入：模型既看不到它
        （不在交给模型的 schema 里），自述的内容也不得进入报告。
        """
        if not any(finding.suggested_patch for finding in review_result.findings):
            return review_result
        return review_result.model_copy(
            update={
                "findings": [
                    finding.model_copy(update={"suggested_patch": ""})
                    for finding in review_result.findings
                ]
            }
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

    def _symbol_locate_enabled(self) -> bool:
        return bool(getattr(self._config.preferences, "symbol_locate", True))

    def _list_repo_tree_paths(self, owner: str, repo: str, ref: str) -> list[str]:
        """列出 ref 下全部 blob 路径；任何失败返回空列表（定位自然降级为空）。

        ``PRFetcher`` 未暴露 trees API（且不在本次 write_scope），这里经其内部
        ``_get_repo`` 走 PyGithub ``get_git_tree(recursive=True)``。测试用 stub
        覆写本方法即可，无需真实网络。
        """
        try:
            get_repo = getattr(self._pr_fetcher, "_get_repo", None)
            if get_repo is None:
                return []
            repo_obj = get_repo(owner, repo)
            tree = repo_obj.get_git_tree(ref, recursive=True)
            paths: list[str] = []
            for entry in getattr(tree, "tree", None) or []:
                if getattr(entry, "type", "") != "blob":
                    continue
                path = getattr(entry, "path", "")
                if path:
                    paths.append(path)
            return paths
        except Exception:
            return []

    def _locate_changed_symbols(
        self,
        pr_data: PRData,
        interface_impacts: list[InterfaceImpact],
        *,
        exclude_paths: set[str],
    ) -> dict[str, list[str]]:
        """对签名变化符号做仓库级定位，返回 ``{symbol: ["path:line", ...]}``。

        - 无签名变化（``interface_impacts`` 为空）或开关关闭时不触发任何请求。
        - 只保留**未被 PR 修改**的文件里的引用点（``exclude_paths`` 传变更文件）。
        - 某符号定位为空时如实省略，不写占位。
        - 任何异常降级为空字典，绝不中断审查。
        """
        if not self._symbol_locate_enabled():
            return {}
        symbols = changed_symbols_from_impacts(interface_impacts)
        if not symbols:
            return {}
        try:
            locator = RepoSymbolLocator(
                read_tree=lambda: self._list_repo_tree_paths(
                    pr_data.owner, pr_data.repo, pr_data.head_sha
                ),
                read_file=lambda path: self._pr_fetcher.fetch_file_content(
                    pr_data.owner, pr_data.repo, path, pr_data.head_sha
                ),
                cache=FileSystemRepoCache(pr_data.owner, pr_data.repo, pr_data.head_sha),
            )
        except Exception:
            return {}

        changed_files = {item.filename for item in pr_data.files}
        changed_files.update(exclude_paths or set())
        located: dict[str, list[str]] = {}
        for symbol in symbols:
            try:
                hits = locator.locate(symbol, exclude_paths=changed_files)
            except Exception:
                hits = []
            if not hits:
                continue
            located[symbol] = [f"{hit.path}:{hit.line}" for hit in hits]
            self._merge_located_references(interface_impacts, symbol, hits)
        return located

    @staticmethod
    def _merge_located_references(
        interface_impacts: list[InterfaceImpact],
        symbol: str,
        hits: list[SymbolLocation],
    ) -> None:
        """把定位到的外部引用并入对应 ``InterfaceImpact``（CrossFileReference 模型）。"""
        for impact in interface_impacts:
            change = getattr(impact, "change", None)
            if change is None or getattr(change, "symbol", "") != symbol:
                continue
            owner = getattr(change, "file", "")
            for hit in hits:
                impact.references.append(
                    CrossFileReference(
                        symbol=symbol,
                        file=owner,
                        line=hit.line,
                        referencing_file=hit.path,
                    )
                )
                if hit.path not in impact.affected_files:
                    impact.affected_files.append(hit.path)

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
        cancel_check: Callable[[], bool] | None = None,
    ) -> list[ReviewResult]:
        semaphore = asyncio.Semaphore(max(1, concurrency))

        def cancel_requested() -> bool:
            return cancel_check is not None and cancel_check()

        async def review_file(file_diff: FileDiff, file_context: FileContext) -> ReviewResult:
            system_prompt = self._prompt_assembler.build_system_prompt(file_context.language)
            user_prompt = self._build_file_prompt(file_context, review_plan)
            async with semaphore:
                # 取消检查放在拿到并发额度之后：排队时被取消的文件不会再发起调用。
                if cancel_requested():
                    raise ReviewCancelled()
                # 回调放在拿到并发额度之后：否则并发时会瞬间把全部文件报成
                # "已开始"，之后长时间无动静，进度条反而更不可信。
                if progress_callback is not None:
                    progress_callback(file_diff.filename, self._config.ai_client.model)
                started_at = time.perf_counter()
                cancelled = False
                try:
                    result = await call_with_cancellation(
                        lambda: ai_client.review_code(system_prompt, user_prompt),
                        cancel_check,
                    )
                except (ReviewCancelled, asyncio.CancelledError):
                    # 取消不是这个文件的结论：不报 reviewed/failed/skipped，也不触发
                    # file_done——那会让人以为它跑完并产生了结论。
                    cancelled = True
                    raise
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
                    if file_done_callback is not None and not cancelled:
                        file_done_callback(file_diff.filename)

        tasks: list[asyncio.Task[ReviewResult]] = []
        try:
            for file_diff, file_context in file_contexts:
                # 每个文件开始前检查：已请求取消时立即抛出，剩余文件不再调度。
                if cancel_requested():
                    raise ReviewCancelled()
                tasks.append(asyncio.create_task(review_file(file_diff, file_context)))
            return list(await asyncio.gather(*tasks))
        except (ReviewCancelled, asyncio.CancelledError):
            # gather 不会取消同批任务：取消必须把在飞的模型调用一起收掉。
            await _cancel_in_flight(tasks)
            raise

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
        cancel_check: Callable[[], bool] | None = None,
    ) -> ReviewResult:
        system_prompt = self._prompt_assembler.build_cross_file_system_prompt()
        user_prompt = self._prompt_assembler.build_cross_file_user_prompt(
            contexts,
            impacts,
            review_plan,
            interface_impacts=interface_impacts,
        )
        # 跨文件审查也是整轮模型调用：同样要能被取消，而不是等它跑完。
        return await call_with_cancellation(
            lambda: ai_client.review_code(system_prompt, user_prompt), cancel_check
        )

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
    "ReviewCancelled",
    "ReviewOrchestrator",
    "call_with_cancellation",
    "elapsed_ms",
    "emit_file_result",
    "emit_skipped_file_results",
    "file_result_payload",
]
