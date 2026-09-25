"""混合审查编排器 - 使用双模型协作策略执行审查。"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from ai_pr_review.config import AIClientConfig, AppConfig
from ai_pr_review.models.pr_data import FileDiff
from ai_pr_review.services import review_orchestrator as standard_review
from ai_pr_review.services.analyzers.python_ast_analyzer import PythonAstAnalyzer
from ai_pr_review.services.analyzers.static_analyzer import StaticAnalyzer
from ai_pr_review.services.context_builder import FileContext
from ai_pr_review.services.filter_pipeline import FilterPipeline
from ai_pr_review.services.finding_localizer import localize_deterministic_finding
from ai_pr_review.services.model_selector import ModelSelector, TaskComplexity
from ai_pr_review.services.prompt_assembler import Finding, PromptAssembler, ReviewResult
from ai_pr_review.services.result_store import ResultStore
from ai_pr_review.services.review_orchestrator import ReviewArtifacts, ReviewCancelled


class HybridReviewOrchestrator:
    """混合审查编排器 - 智能选择本地或远程模型"""

    def __init__(self, config: AppConfig):
        self.config = config
        self.model_selector = ModelSelector(config)
        self.pr_fetcher = standard_review.PRFetcher(config=config.pr_fetcher)
        self.filter_pipeline = standard_review.FilterPipeline()
        self.context_builder = standard_review.ContextBuilder()
        self.static_analyzer = StaticAnalyzer()
        self.ast_analyzer = PythonAstAnalyzer()
        self.prompt_assembler = standard_review.PromptAssembler()
        self.result_store = ResultStore(config.result_store)

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
        """执行混合模型审查

        使用双模型协作策略：
        - 低风险文件：本地模型 + 确定性规则
        - 中风险文件：根据策略决定
        - 高风险文件：远程模型深度分析

        `file_result_callback(payload)` 与标准编排器同构（契约 §10.2）：被过滤的
        文件报 `skipped`，逐文件模型调用抛异常时报 `failed`（本编排器按原语义
        吞掉异常继续跑），其余报 `reviewed`。`findings_count` 只统计该文件模型
        调用返回的 finding，确定性规则结论在运行级合并。
        """
        start_time = time.perf_counter()

        def stage(name: str, detail: str = "") -> None:
            if cancel_check is not None and cancel_check():
                raise ReviewCancelled()
            if stage_callback is not None:
                stage_callback(name, detail)

        # 阶段 1: 获取 PR 数据
        stage("fetching", "正在读取 PR 元数据与变更内容")
        pr_data = await asyncio.to_thread(self.pr_fetcher.fetch, pr_url)

        # 阶段 2: 过滤文件
        stage("filtering", f"共 {pr_data.changed_files_count} 个变更文件，正在过滤")
        filtered_pr_data, filter_result = self.filter_pipeline.filter_pr_data(pr_data)
        # 被过滤掉的文件永远不会进入审查循环，只能在这里如实上报。
        standard_review.emit_skipped_file_results(file_result_callback, filter_result)

        # 阶段 3: 构建上下文
        stage("context", f"为 {len(filtered_pr_data.files)} 个文件构建代码上下文")
        file_contexts = []
        for file_diff in filtered_pr_data.files:
            full_content = await asyncio.to_thread(
                self.pr_fetcher.fetch_file_content,
                pr_data.owner,
                pr_data.repo,
                file_diff.filename,
                pr_data.head_sha,
            )
            context = self.context_builder.build_context(
                file_diff.filename,
                file_diff.patch or "",
                full_content or "",
            )
            file_contexts.append((file_diff, context))

        # 阶段 4: 运行确定性规则（所有文件）
        stage("static_rules", "运行静态安全规则和 AST 分析")
        all_findings = []

        for file_diff, context in file_contexts:
            # 静态规则
            static_findings = self.static_analyzer.analyze(file_diff, context)
            for finding in static_findings:
                localized = localize_deterministic_finding(
                    finding, getattr(self.config.preferences, "language", "zh-CN")
                )
                all_findings.append(localized)

            # AST 分析
            if file_diff.filename.endswith(".py"):
                ast_findings = self.ast_analyzer.analyze(file_diff, context)
                for finding in ast_findings:
                    localized = localize_deterministic_finding(
                        finding, getattr(self.config.preferences, "language", "zh-CN")
                    )
                    all_findings.append(localized)

        # 阶段 5: 智能分级审查
        stage("reviewing", f"开始智能分级审查，共 {len(file_contexts)} 个文件")

        reviewed_count = 0
        total_cost = 0.0
        for file_diff, context in file_contexts:
            # 评估文件复杂度
            complexity = self.model_selector.evaluate_file_complexity(
                file_path=file_diff.filename,
                additions=file_diff.additions,
                deletions=file_diff.deletions,
                static_findings=all_findings,
            )

            # 选择模型
            provider, model_name, is_local = self.model_selector.select_model_for_task(
                task_type="file_review",
                complexity=complexity,
                context={
                    "file_path": file_diff.filename,
                    "additions": file_diff.additions,
                    "deletions": file_diff.deletions,
                    "static_findings": all_findings,
                },
            )

            # 进度回调
            if progress_callback:
                model_label = f"{'本地' if is_local else '远程'}/{model_name}"
                progress_callback(file_diff.filename, model_label)

            # 使用所选模型执行审查；低复杂度任务也走本地模型，避免静默丢失
            # 模型发现，并保证本地/远程策略都能产生统一 ReviewResult。
            system_prompt = self.prompt_assembler.build_system_prompt(context.language)
            user_prompt = self.prompt_assembler.build_user_prompt(context)

            call_started_at = time.perf_counter()
            try:
                selected_config = self.config.ai_client.model_provider
                if is_local:
                    from ai_pr_review.config import ModelProviderConfig

                    selected_config = ModelProviderConfig.from_name("ollama", model_name=model_name)
                selected_ai_config = AIClientConfig(
                    **{
                        **self.config.ai_client.__dict__,
                        "provider": selected_config.name,
                        "api_key": selected_config.api_key,
                        "model": model_name,
                        "base_url": selected_config.base_url,
                        "api_format": selected_config.api_format,
                        "headers": dict(selected_config.headers),
                        "extra_params": dict(selected_config.extra_params),
                    }
                )
                selected_client = standard_review.AIClient(selected_ai_config)
                response = await selected_client.review_code(system_prompt, user_prompt)
                result = response
                call_cost = getattr(selected_client, "total_run_cost", 0.0)
                total_cost += call_cost
                self.model_selector.record_cost(call_cost)
            except Exception as e:
                # 该文件的模型调用失败：如实上报 failed（findings_count 未知，
                # 不是 0），再按本编排器原有语义吞掉异常继续处理下一个文件。
                standard_review.emit_file_result(
                    file_result_callback,
                    file_diff.filename,
                    "failed",
                    findings_count=None,
                    duration_ms=standard_review.elapsed_ms(call_started_at),
                    error=str(e) or e.__class__.__name__,
                )
                result = ReviewResult(
                    summary=f"审查失败: {e}",
                    findings=[],
                )
            else:
                findings = getattr(result, "findings", None)
                standard_review.emit_file_result(
                    file_result_callback,
                    file_diff.filename,
                    "reviewed",
                    findings_count=len(findings) if isinstance(findings, list) else None,
                    duration_ms=standard_review.elapsed_ms(call_started_at),
                    error=None,
                )

            all_findings.extend(result.findings)
            reviewed_count += 1

            # 文件完成回调
            if file_done_callback:
                file_done_callback(file_diff.filename)

        # 阶段 6: 保存结果
        stage("persisting", "保存审查记录到本地数据库")
        duration = time.perf_counter() - start_time

        # 获取统计信息
        stats = self.model_selector.get_statistics()

        # 构建最终结果；空审查范围必须保留过滤原因，便于 CLI / Web 解释。
        if filter_result.included_count == 0:
            reason_labels = {
                "excluded_by_pattern": "命中黑名单规则",
                "excluded_deletion_only": "仅删除改动",
                "excluded_too_large": "变更量过大",
                "custom_rule": "自定义规则过滤",
            }
            reason_counts = filter_result.excluded_reason_counts()
            if reason_counts:
                reasons = "; ".join(
                    f"{reason_labels.get(code, code)} {count} 个"
                    for code, count in sorted(reason_counts.items())
                )
                summary = (
                    "No reviewable files remained after filtering. "
                    f"Excluded {filter_result.excluded_count} files: {reasons}."
                )
            else:
                summary = "No reviewable files remained after filtering."
        else:
            summary = f"审查完成，发现 {len(all_findings)} 个问题"
        review_result = ReviewResult(summary=summary, findings=all_findings)

        artifacts = ReviewArtifacts(
            pr_data=filtered_pr_data,
            review_result=review_result,
            filter_result=filter_result,
            review_plan=None,
            total_cost=total_cost,
            duration_seconds=duration,
            run_id="",  # 将由 ResultStore 生成
        )

        # Re-check right before persisting: cancelling after the last stage
        # callback used to still write a run into history and report completion.
        if cancel_check is not None and cancel_check():
            raise ReviewCancelled()

        # 保存到数据库
        run_id = self.result_store.save_result(
            pr_url=pr_url,
            result=review_result,
            head_sha=filtered_pr_data.head_sha,
            total_files=pr_data.changed_files_count,
            included_files=filter_result.included_count,
            excluded_files=filter_result.excluded_count,
            total_cost=total_cost,
            duration_seconds=duration,
            model=self.config.ai_client.model,
            metadata={
                "strategy": stats["strategy"],
                "hybrid": True,
                "local_calls": stats["local_calls"],
                "remote_calls": stats["remote_calls"],
                "routing_model": self.model_selector.local_model,
            },
        )

        artifacts.run_id = run_id

        return artifacts
