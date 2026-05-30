"""PR 文件过滤管道。

这个模块负责把 PR 中的文件变更做一层统一过滤，避免把明显无审查价
值的文件继续送给后续 AI 分析逻辑。实现目标：

1. 使用显式配置管理默认过滤规则。
2. 支持白名单（force_include）覆盖黑名单。
3. 支持运行时注入自定义规则，便于业务扩展。
4. 为每个文件提供结构化过滤原因，方便调试、日志和测试。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Callable, Literal

from ai_pr_review.config import FilterPipelineConfig
from ai_pr_review.models.pr_data import FileDiff, PRData

FilterAction = Literal["include", "exclude"]
CustomFilterRule = Callable[[FileDiff], "FilterReason | None"]


class FilterReasonCode(str, Enum):
    """结构化原因代码。

    代码用于程序消费，message 用于日志和调试阅读。
    """

    FORCE_INCLUDED = "force_included"
    EXCLUDED_BY_PATTERN = "excluded_by_pattern"
    EXCLUDED_DELETION_ONLY = "excluded_deletion_only"
    EXCLUDED_TOO_LARGE = "excluded_too_large"
    CUSTOM_RULE = "custom_rule"
    INCLUDED_BY_DEFAULT = "included_by_default"


@dataclass(slots=True)
class FilterReason:
    """单条结构化过滤原因。"""

    code: FilterReasonCode
    action: FilterAction
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """导出为普通字典，方便日志或后续 JSON 序列化。"""
        return {
            "code": self.code.value,
            "action": self.action,
            "message": self.message,
            "details": self.details,
        }


@dataclass(slots=True)
class FilterResult:
    """单个文件的过滤结果。"""

    file: FileDiff
    included: bool
    reasons: list[FilterReason] = field(default_factory=list)

    @property
    def filename(self) -> str:
        return self.file.filename

    @property
    def primary_reason(self) -> FilterReason | None:
        return self.reasons[0] if self.reasons else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.file.filename,
            "included": self.included,
            "reasons": [reason.to_dict() for reason in self.reasons],
        }


@dataclass(slots=True)
class FilterPipelineResult:
    """整批文件经过过滤管道后的结果。"""

    results: list[FilterResult] = field(default_factory=list)

    @property
    def included_files(self) -> list[FileDiff]:
        return [result.file for result in self.results if result.included]

    @property
    def excluded_files(self) -> list[FileDiff]:
        return [result.file for result in self.results if not result.included]

    @property
    def included_results(self) -> list[FilterResult]:
        return [result for result in self.results if result.included]

    @property
    def excluded_results(self) -> list[FilterResult]:
        return [result for result in self.results if not result.included]

    @property
    def total_files(self) -> int:
        return len(self.results)

    @property
    def included_count(self) -> int:
        return len(self.included_results)

    @property
    def excluded_count(self) -> int:
        return len(self.excluded_results)

    def excluded_reason_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for result in self.excluded_results:
            reason = result.primary_reason
            if reason is None:
                continue
            code = reason.code.value
            counts[code] = counts.get(code, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_files": self.total_files,
            "included_count": self.included_count,
            "excluded_count": self.excluded_count,
            "excluded_reason_counts": self.excluded_reason_counts(),
            "results": [result.to_dict() for result in self.results],
        }


class FileFilter:
    """核心文件过滤器。

    该类只负责评估单个文件，保证规则顺序稳定：

    1. 白名单优先，命中后立即保留。
    2. 默认黑名单规则。
    3. 内建启发式规则（纯删除、大文件）。
    4. 自定义规则。
    5. 都未命中时默认保留。
    """

    def __init__(
        self,
        config: FilterPipelineConfig | None = None,
        custom_rules: list[CustomFilterRule] | None = None,
    ) -> None:
        self._config = config or FilterPipelineConfig()
        self._custom_rules = custom_rules or []

    def evaluate(self, file_diff: FileDiff) -> FilterResult:
        """评估单个文件是否应被纳入后续分析。"""
        matched_force_include = self._match_first_pattern(
            file_diff.filename,
            self._config.force_include,
        )
        if matched_force_include is not None:
            return FilterResult(
                file=file_diff,
                included=True,
                reasons=[
                    FilterReason(
                        code=FilterReasonCode.FORCE_INCLUDED,
                        action="include",
                        message="文件命中 force_include 白名单，强制保留。",
                        details={"pattern": matched_force_include},
                    )
                ],
            )

        matched_exclude_pattern = self._match_first_pattern(
            file_diff.filename,
            self._config.exclude_patterns,
        )
        if matched_exclude_pattern is not None:
            return FilterResult(
                file=file_diff,
                included=False,
                reasons=[
                    FilterReason(
                        code=FilterReasonCode.EXCLUDED_BY_PATTERN,
                        action="exclude",
                        message="文件命中 exclude_patterns 黑名单。",
                        details={"pattern": matched_exclude_pattern},
                    )
                ],
            )

        if self._config.skip_deletion_only and file_diff.is_deletion_only:
            return FilterResult(
                file=file_diff,
                included=False,
                reasons=[
                    FilterReason(
                        code=FilterReasonCode.EXCLUDED_DELETION_ONLY,
                        action="exclude",
                        message="文件仅包含删除，没有新增内容。",
                        details={
                            "additions": file_diff.additions,
                            "deletions": file_diff.deletions,
                        },
                    )
                ],
            )

        if self._config.max_changes is not None and file_diff.changes > self._config.max_changes:
            return FilterResult(
                file=file_diff,
                included=False,
                reasons=[
                    FilterReason(
                        code=FilterReasonCode.EXCLUDED_TOO_LARGE,
                        action="exclude",
                        message="文件变更量超过阈值，疑似生成文件或超大改动。",
                        details={
                            "changes": file_diff.changes,
                            "max_changes": self._config.max_changes,
                        },
                    )
                ],
            )

        custom_reason = self._run_custom_rules(file_diff)
        if custom_reason is not None:
            return FilterResult(
                file=file_diff,
                included=custom_reason.action == "include",
                reasons=[custom_reason],
            )

        return FilterResult(
            file=file_diff,
            included=True,
            reasons=[
                FilterReason(
                    code=FilterReasonCode.INCLUDED_BY_DEFAULT,
                    action="include",
                    message="文件未命中过滤规则，默认纳入审查。",
                )
            ],
        )

    def _run_custom_rules(self, file_diff: FileDiff) -> FilterReason | None:
        """按顺序执行自定义规则，首个命中规则即生效。"""
        for rule in self._custom_rules:
            reason = rule(file_diff)
            if reason is None:
                continue

            if reason.action not in {"include", "exclude"}:
                raise ValueError(
                    f"Unsupported custom rule action: {reason.action!r}. "
                    "Expected 'include' or 'exclude'."
                )

            if reason.code != FilterReasonCode.CUSTOM_RULE:
                # 自定义规则统一落到 CUSTOM_RULE，便于下游统计。
                reason = FilterReason(
                    code=FilterReasonCode.CUSTOM_RULE,
                    action=reason.action,
                    message=reason.message,
                    details=reason.details,
                )

            return reason

        return None

    def _match_first_pattern(self, file_path: str, patterns: list[str]) -> str | None:
        normalized_path = self._normalize_path(file_path)
        for pattern in patterns:
            if PurePosixPath(normalized_path).match(pattern):
                return pattern
        return None

    @staticmethod
    def _normalize_path(file_path: str) -> str:
        # 统一转成 POSIX 路径，避免 Windows 下分隔符导致 glob 模式失效。
        return file_path.replace("\\", "/").lstrip("/")


class FilterPipeline:
    """面向 PR 文件列表的批量过滤管道。"""

    def __init__(
        self,
        config: FilterPipelineConfig | None = None,
        custom_rules: list[CustomFilterRule] | None = None,
    ) -> None:
        self._filter = FileFilter(config=config, custom_rules=custom_rules)

    def run(self, files: list[FileDiff]) -> FilterPipelineResult:
        """过滤一组文件，返回包含明细和汇总的结果对象。"""
        return FilterPipelineResult(results=[self._filter.evaluate(file) for file in files])

    def filter_pr_data(self, pr_data: PRData) -> tuple[PRData, FilterPipelineResult]:
        """对完整 PRData 做过滤，并返回过滤后的副本和结果明细。

        这里不原地修改输入对象，便于调用方保留原始 PR 数据用于日志或调试。
        """
        result = self.run(pr_data.files)
        filtered_pr_data = pr_data.model_copy(update={"files": result.included_files})
        return filtered_pr_data, result
