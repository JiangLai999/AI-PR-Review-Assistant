"""GitHub PR URL 解析工具。

支持多种 GitHub URL 格式的解析。
"""

import re

from ai_pr_review.models.pr_data import ParsedPRUrl
from ai_pr_review.services.exceptions import InvalidPRURLError

_GITHUB_PR_URL_PATTERN = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)/?.*$"
)
_GITHUB_SSH_PATTERN = re.compile(
    r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+)\.git$"
)


def parse_pr_url(pr_url: str) -> ParsedPRUrl:
    """从 GitHub PR URL 解析 owner、repo 和 PR 编号。

    支持的格式：
        - https://github.com/owner/repo/pull/123
        - https://github.com/owner/repo/pull/123/files
        - http://github.com/owner/repo/pull/123

    Args:
        pr_url: GitHub PR URL 字符串

    Returns:
        ParsedPRUrl: 包含 owner、repo、pr_number

    Raises:
        InvalidPRURLError: URL 格式不匹配
    """
    match = _GITHUB_PR_URL_PATTERN.match(pr_url.strip())
    if not match:
        raise InvalidPRURLError(
            f"无效的 GitHub PR URL: {pr_url!r}。"
            f"期望格式: https://github.com/<owner>/<repo>/pull/<number>"
        )

    return ParsedPRUrl(
        owner=match.group("owner"),
        repo=match.group("repo"),
        pr_number=int(match.group("number")),
    )
