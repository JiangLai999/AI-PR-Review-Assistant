"""轻量路径获取单测：`fetch_changed_file_paths` / `fetch_repo_tree_paths`。

背景（`docs/claude-repo-structure-context.md` §B/§C）：聊天侧"本次 PR 变更文件"
与"仓库目录树"两段注入只需要**路径清单**；大 PR 上 `fetch()` 会把整个 diff 一并
拉下来（几十万字符的浪费），这两个方法刻意走轻量路径。

覆盖来源：claude 实现时 `tests/test_pr_fetcher.py` 不在其写集，两个新方法只由
证据脚本以替身 PyGithub 覆盖——本文件补齐单测（主控，2026-09-27）。
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from ai_pr_review.models.pr_data import FileDiff, FileStatus
from ai_pr_review.services.pr_fetcher import PRFetcher


@pytest.fixture
def fetcher() -> PRFetcher:
    return PRFetcher(github_token="ghp_test")


def test_fetch_changed_file_paths_returns_paths_and_never_fetches_diff(
    fetcher: PRFetcher,
) -> None:
    """返回路径清单，且**绝不调用** `_fetch_diff`（轻量路径的核心约束）。"""
    files = [
        FileDiff(
            filename="website/index.html",
            status=FileStatus.ADDED,
            additions=346,
            deletions=0,
            changes=346,
        ),
        FileDiff(
            filename="scripts/build_website_docs.py",
            status=FileStatus.ADDED,
            additions=80,
            deletions=0,
            changes=80,
        ),
    ]
    with patch.object(fetcher, "_get_pull_request", return_value=Mock(number=42)):
        with patch.object(fetcher, "_fetch_files", return_value=files):
            with patch.object(fetcher, "_fetch_diff") as fetch_diff:
                paths = fetcher.fetch_changed_file_paths(
                    "https://github.com/owner/repo/pull/42"
                )

    assert paths == ["website/index.html", "scripts/build_website_docs.py"]
    fetch_diff.assert_not_called()


def test_fetch_repo_tree_paths_keeps_blobs_only_and_skips_empty(fetcher: PRFetcher) -> None:
    """git tree：只返回 blob（文件），目录项与空路径都不返回。"""
    tree = Mock(
        tree=[
            Mock(type="blob", path="website/index.html"),
            Mock(type="tree", path="website/js"),  # 目录项：跳过
            Mock(type="blob", path="scripts/build_website_docs.py"),
            Mock(type="blob", path=""),  # 空路径：跳过
        ]
    )
    repo = Mock()
    repo.get_git_tree.return_value = tree
    with patch.object(fetcher, "_get_repo", return_value=repo):
        with patch.object(fetcher, "_rate_limiter") as limiter:
            # 让重试层"执行"传入的 lambda（而不是短路返回），这样能验证
            # `get_git_tree(recursive=True)` 真的以正确参数被调用。
            with patch.object(
                fetcher, "_execute_with_retry", side_effect=lambda fn, **_kw: fn()
            ):
                paths = fetcher.fetch_repo_tree_paths("owner", "repo", "abc123")

    assert paths == ["website/index.html", "scripts/build_website_docs.py"]
    limiter.acquire.assert_called_once()
    # recursive 必须为真：否则只拿到根目录一层，注入给模型的"结构"没有意义。
    assert repo.get_git_tree.call_args.kwargs.get("recursive") is True


def test_fetch_repo_tree_paths_tolerates_missing_tree_attribute(fetcher: PRFetcher) -> None:
    """`tree` 属性缺失（异常替身 / 老版本 SDK）时返回空列表而不是崩。"""
    with patch.object(fetcher, "_get_repo", return_value=Mock()):
        with patch.object(fetcher, "_rate_limiter"):
            with patch.object(fetcher, "_execute_with_retry", return_value=Mock(spec=[])):
                paths = fetcher.fetch_repo_tree_paths("owner", "repo", "abc123")

    assert paths == []
