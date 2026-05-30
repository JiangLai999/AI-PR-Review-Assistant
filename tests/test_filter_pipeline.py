"""Filter Pipeline 模块单元测试。"""

import pytest

from ai_pr_review.config import DEFAULT_FILTER_EXCLUDE_PATTERNS, FilterPipelineConfig
from ai_pr_review.models.pr_data import FileDiff, FileStatus, PRData
from ai_pr_review.services.filter_pipeline import (
    FileFilter,
    FilterPipeline,
    FilterReason,
    FilterReasonCode,
)


def build_file(
    filename: str,
    *,
    additions: int = 1,
    deletions: int = 0,
    changes: int | None = None,
    status: FileStatus = FileStatus.MODIFIED,
) -> FileDiff:
    """构造测试用 FileDiff，减少样板代码。"""
    total_changes = changes if changes is not None else additions + deletions
    return FileDiff(
        filename=filename,
        status=status,
        additions=additions,
        deletions=deletions,
        changes=total_changes,
    )


class TestFileFilter:
    """单文件过滤器测试。"""

    def test_force_include_overrides_exclude_pattern(self):
        config = FilterPipelineConfig(
            force_include=["docs/ARCHITECTURE.md"],
            exclude_patterns=["**/*.md"],
        )
        file_filter = FileFilter(config=config)

        result = file_filter.evaluate(build_file("docs/ARCHITECTURE.md"))

        assert result.included is True
        assert result.primary_reason is not None
        assert result.primary_reason.code == FilterReasonCode.FORCE_INCLUDED
        assert result.primary_reason.details["pattern"] == "docs/ARCHITECTURE.md"

    def test_exclude_patterns_skip_matching_file(self):
        config = FilterPipelineConfig(exclude_patterns=["**/*.md"])
        file_filter = FileFilter(config=config)

        result = file_filter.evaluate(build_file("docs/README.md"))

        assert result.included is False
        assert result.primary_reason is not None
        assert result.primary_reason.code == FilterReasonCode.EXCLUDED_BY_PATTERN
        assert result.primary_reason.to_dict()["details"]["pattern"] == "**/*.md"

    def test_deletion_only_file_is_excluded(self):
        file_filter = FileFilter(FilterPipelineConfig(exclude_patterns=[]))

        result = file_filter.evaluate(build_file("src/legacy.py", additions=0, deletions=12))

        assert result.included is False
        assert result.primary_reason is not None
        assert result.primary_reason.code == FilterReasonCode.EXCLUDED_DELETION_ONLY

    def test_large_change_file_is_excluded(self):
        file_filter = FileFilter(FilterPipelineConfig(exclude_patterns=[], max_changes=100))

        result = file_filter.evaluate(build_file("src/generated.py", changes=101))

        assert result.included is False
        assert result.primary_reason is not None
        assert result.primary_reason.code == FilterReasonCode.EXCLUDED_TOO_LARGE
        assert result.primary_reason.details == {"changes": 101, "max_changes": 100}

    def test_custom_rule_can_exclude_file(self):
        def exclude_migrations(file_diff: FileDiff) -> FilterReason | None:
            if file_diff.filename.startswith("migrations/"):
                return FilterReason(
                    code=FilterReasonCode.CUSTOM_RULE,
                    action="exclude",
                    message="迁移脚本由自定义规则跳过。",
                    details={"rule": "exclude_migrations"},
                )
            return None

        file_filter = FileFilter(
            FilterPipelineConfig(exclude_patterns=[]),
            custom_rules=[exclude_migrations],
        )

        result = file_filter.evaluate(build_file("migrations/0001_initial.sql"))

        assert result.included is False
        assert result.primary_reason is not None
        assert result.primary_reason.code == FilterReasonCode.CUSTOM_RULE
        assert result.primary_reason.action == "exclude"
        assert result.primary_reason.details["rule"] == "exclude_migrations"

    def test_custom_rule_can_include_file(self):
        def include_security_policy(file_diff: FileDiff) -> FilterReason | None:
            if file_diff.filename == "security/policy.txt":
                return FilterReason(
                    code=FilterReasonCode.CUSTOM_RULE,
                    action="include",
                    message="安全策略文件强制进入人工审查。",
                    details={"rule": "include_security_policy"},
                )
            return None

        file_filter = FileFilter(
            FilterPipelineConfig(exclude_patterns=[]),
            custom_rules=[include_security_policy],
        )

        result = file_filter.evaluate(build_file("security/policy.txt"))

        assert result.included is True
        assert result.primary_reason is not None
        assert result.primary_reason.code == FilterReasonCode.CUSTOM_RULE
        assert result.primary_reason.action == "include"

    def test_non_matching_file_is_included_by_default(self):
        file_filter = FileFilter(FilterPipelineConfig(exclude_patterns=[]))

        result = file_filter.evaluate(build_file("src/core/service.py"))

        assert result.included is True
        assert result.primary_reason is not None
        assert result.primary_reason.code == FilterReasonCode.INCLUDED_BY_DEFAULT

    @pytest.mark.parametrize(
        ("filename", "expected_patterns"),
        [
            ("tests/test_filter_pipeline.py", {"tests/**", "test_*.py", "**/test_*.py"}),
            ("src/module/tests/test_service.py", {"tests/**", "**/tests/**"}),
            ("test_main.py", {"test_*.py", "**/test_*.py"}),
            ("src/test_utils.py", {"test_*.py", "**/test_*.py"}),
        ],
    )
    def test_default_exclude_patterns_skip_test_files(self, filename, expected_patterns):
        file_filter = FileFilter(FilterPipelineConfig())

        result = file_filter.evaluate(build_file(filename))

        assert expected_patterns <= set(DEFAULT_FILTER_EXCLUDE_PATTERNS)
        assert result.included is False
        assert result.primary_reason is not None
        assert result.primary_reason.code == FilterReasonCode.EXCLUDED_BY_PATTERN
        assert result.primary_reason.details["pattern"] in expected_patterns


class TestFilterPipeline:
    """批量过滤管道测试。"""

    def test_run_returns_included_and_excluded_groups(self):
        pipeline = FilterPipeline(
            FilterPipelineConfig(exclude_patterns=["**/*.md"], max_changes=50)
        )
        files = [
            build_file("src/main.py", changes=10),
            build_file("docs/README.md", changes=5),
            build_file("src/generated.py", changes=60),
        ]

        result = pipeline.run(files)

        assert result.total_files == 3
        assert result.included_count == 1
        assert result.excluded_count == 2
        assert [file.filename for file in result.included_files] == ["src/main.py"]
        assert {file.filename for file in result.excluded_files} == {
            "docs/README.md",
            "src/generated.py",
        }

    def test_filter_pr_data_returns_filtered_copy_and_result(self, mock_pr_data_dict):
        pr_payload = {
            **mock_pr_data_dict,
            "files": [
                build_file("src/app.py", changes=12),
                build_file("docs/guide.md", changes=4),
            ],
        }
        pr_data = PRData(**pr_payload)
        pipeline = FilterPipeline(FilterPipelineConfig(exclude_patterns=["**/*.md"]))

        filtered_pr_data, result = pipeline.filter_pr_data(pr_data)

        assert pr_data.files[0].filename == "src/app.py"
        assert len(pr_data.files) == 2
        assert [file.filename for file in filtered_pr_data.files] == ["src/app.py"]
        assert result.excluded_count == 1

    def test_pipeline_result_to_dict_contains_structured_reasons(self):
        pipeline = FilterPipeline(FilterPipelineConfig(exclude_patterns=["**/*.md"]))

        result = pipeline.run([build_file("docs/README.md")]).to_dict()

        assert result["total_files"] == 1
        assert result["excluded_reason_counts"] == {"excluded_by_pattern": 1}
        assert result["results"][0]["filename"] == "docs/README.md"
        assert result["results"][0]["reasons"][0]["code"] == "excluded_by_pattern"
        assert result["results"][0]["reasons"][0]["action"] == "exclude"
