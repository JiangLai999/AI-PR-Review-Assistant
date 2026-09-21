"""混合审查编排器 - 使用双模型协作策略执行审查。"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from ai_pr_review.config import AppConfig
from ai_pr_review.models.pr_data import FileDiff
from ai_pr_review.services.ai_client import AIClient
from ai_pr_review.services.analyzers.python_ast_analyzer import PythonAstAnalyzer
from ai_pr_review.services.analyzers.static_analyzer import StaticAnalyzer
from ai_pr_review.services.context_builder import ContextBuilder, FileContext
from ai_pr_review.services.filter_pipeline import FilterPipeline
from ai_pr_review.services.finding_localizer import localize_deterministic_finding
from ai_pr_review.services.model_selector import ModelSelector, TaskComplexity
from ai_pr_review.services.pr_fetcher import PRFetcher
from ai_pr_review.services.prompt_assembler import Finding, PromptAssembler, ReviewResult
from ai_pr_review.services.result_store import ResultStore
from ai_pr_review.services.review_orchestrator import ReviewArtifacts, ReviewCancelled


class HybridReviewOrchestrator:
    """混合审查编排器 - 智能选择本地或远程模型"""

    def __init__(self, config: AppConfig):
        self.config = config
        self.model_selector = ModelSelector(config)
        self.pr_fetcher = PRFetcher(config)
        self.filter_pipeline = FilterPipeline()
        self.context_builder = ContextBuilder()
        self.static_analyzer = StaticAnalyzer()
        self.ast_analyzer = PythonAstAnalyzer()
        self.prompt_assembler = PromptAssembler()
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
    ) -> ReviewArtifacts:
        """执行混合模型审查

        使用双模型协作策略：
        - 低风险文件：本地模型 + 确定性规则
        - 中风险文件：根据策略决定
        - 高风险文件：远程模型深度分析
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

        # 阶段 3: 构建上下文
        stage("context", f"为 {len(filtered_pr_data.files)} 个文件构建代码上下文")
        file_contexts = []
        for file_diff in filtered_pr_data.files:
            context = self.context_builder.build_context(file_diff, filtered_pr_data)
            file_contexts.append((file_diff, context))

        # 阶段 4: 运行确定性规则（所有文件）
        stage("static_rules", "运行静态安全规则和 AST 分析")
        all_findings = []

        for file_diff, context in file_contexts:
            # 静态规则
            static_findings = self.static_analyzer.analyze(file_diff, context)
            for finding in static_findings:
                localized = localize_deterministic_finding(
                    finding, self.config.preferences.response_language
                )
                all_findings.append(localized)

            # AST 分析
            if file_diff.filename.endswith(".py"):
                ast_findings = self.ast_analyzer.analyze(file_diff, context)
                for finding in ast_findings:
                    localized = localize_deterministic_finding(
                        finding, self.config.preferences.response_language
                    )
                    all_findings.append(localized)

        # 阶段 5: 智能分级审查
        stage("reviewing", f"开始智能分级审查，共 {len(file_contexts)} 个文件")

        reviewed_count = 0
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

            # 执行审查
            if is_local and complexity in {TaskComplexity.TRIVIAL, TaskComplexity.SIMPLE}:
                # 本地模型简化审查（跳过 AI 调用，只用确定性规则）
                result = ReviewResult(
                    summary=f"已通过确定性规则检查（{complexity.value}）",
                    findings=[],
                )
            else:
                # 使用 AI 模型审查
                ai_client = AIClient(self.config)
                messages = self.prompt_assembler.assemble_file_review_prompt(
                    file_diff, context, None
                )

                try:
                    response = await ai_client.review_file(messages)
                    result = ReviewResult(
                        summary=response.get("summary", ""),
                        findings=[Finding(**f) for f in response.get("findings", [])],
                    )

                    # 记录成本
                    cost = response.get("cost", 0.0)
                    self.model_selector.record_cost(cost)
                except Exception as e:
                    result = ReviewResult(
                        summary=f"审查失败: {e}",
                        findings=[],
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

        # 构建最终结果
        review_result = ReviewResult(
            summary=f"审查完成，发现 {len(all_findings)} 个问题",
            findings=all_findings,
        )

        artifacts = ReviewArtifacts(
            pr_data=filtered_pr_data,
            review_result=review_result,
            filter_result=filter_result,
            review_plan=None,
            total_cost=stats["total_cost"],
            duration_seconds=duration,
            run_id="",  # 将由 ResultStore 生成
        )

        # 保存到数据库
        run_id = self.result_store.save_result(
            pr_url=pr_url,
            pr_data=filtered_pr_data,
            review_result=review_result,
            cost=stats["total_cost"],
            duration_seconds=duration,
            model=f"hybrid:{stats['local_calls']}L+{stats['remote_calls']}R",
        )

        artifacts.run_id = run_id

        return artifacts
