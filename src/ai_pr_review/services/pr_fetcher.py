"""PR Fetcher 模块 — 从 GitHub API 获取 PR 完整数据。

核心职责：
    1. 解析 GitHub PR URL
    2. 获取 PR 元数据（标题、描述、作者、状态等）
    3. 获取 PR 的 unified diff
    4. 获取变更文件列表与详情
    5. Token Bucket 速率控制
    6. 结构化错误处理与重试
"""

import logging
import time
from urllib.error import URLError

from github import Auth, Github, GithubException, PullRequest
from github.GithubException import RateLimitExceededException
from github.PaginatedList import PaginatedList
from github.Repository import Repository

from ai_pr_review.config import PRFetcherConfig
from ai_pr_review.models.pr_data import FileDiff, FileStatus, PRData
from ai_pr_review.services.exceptions import (
    AuthenticationError,
    GitHubAPIError,
    InvalidPRURLError,
    NetworkError,
    PRFetcherError,
    PRNotFoundError,
    RateLimitExceededError,
)
from ai_pr_review.services.token_bucket import TokenBucket
from ai_pr_review.utils.github_url_parser import parse_pr_url

logger = logging.getLogger(__name__)


class PRFetcher:
    """从 GitHub 获取 Pull Request 完整数据的核心组件。

    使用 PyGithub 调用 REST API，内置 Token Bucket 速率控制、
    指数退避重试和结构化错误处理。

    用法:
        fetcher = PRFetcher(github_token="ghp_xxx")
        pr_data = fetcher.fetch("https://github.com/owner/repo/pull/123")
    """

    def __init__(
        self,
        github_token: str | None = None,
        config: PRFetcherConfig | None = None,
    ) -> None:
        """
        Args:
            github_token: GitHub Personal Access Token。
                          为 None 时从环境变量 GITHUB_TOKEN 读取。
            config: PRFetcher 专用配置。为 None 时使用默认配置。
        """
        self._config = config or PRFetcherConfig()
        self._token = github_token or self._config.github_token

        if not self._token:
            raise AuthenticationError(
                "GitHub Token 未提供。请设置 GITHUB_TOKEN 环境变量或直接传入 token 参数。"
            )

        self._github = self._create_github_client()
        self._rate_limiter = TokenBucket(rate=self._config.token_bucket_rate)

    def _create_github_client(self) -> Github:
        try:
            auth = Auth.Token(self._token)
            client = Github(auth=auth, timeout=self._config.request_timeout)
        except TypeError:
            client = Github(self._token, timeout=self._config.request_timeout)
        return client

    def fetch(self, pr_url: str) -> PRData:
        """获取 PR 的完整数据。

        这是主入口方法，串联 URL 解析 → 元数据 → diff → 文件列表。

        Args:
            pr_url: GitHub PR URL

        Returns:
            PRData: 包含 PR 全部信息的结构化数据

        Raises:
            InvalidPRURLError: URL 格式无效
            PRNotFoundError: PR 不存在
            AuthenticationError: Token 无效
            RateLimitExceededError: API 速率限制已超出
            NetworkError: 网络异常
            GitHubAPIError: API 返回异常状态码
        """
        parsed = parse_pr_url(pr_url)
        logger.info("Fetching PR %s/%s#%d", parsed.owner, parsed.repo, parsed.pr_number)

        pr = self._get_pull_request(parsed.owner, parsed.repo, parsed.pr_number)

        diff = self._fetch_diff(pr)
        files = self._fetch_files(pr)

        return PRData(
            pr_number=pr.number,
            title=pr.title,
            description=pr.body,
            author=pr.user.login,
            state=pr.state,
            head_sha=pr.head.sha,
            base_sha=pr.base.sha,
            head_ref=pr.head.ref,
            base_ref=pr.base.ref,
            diff=diff,
            files=files,
            url=pr.html_url,
            created_at=pr.created_at,
            updated_at=pr.updated_at,
            merged=pr.merged,
            owner=parsed.owner,
            repo=parsed.repo,
        )

    def fetch_metadata(self, pr_url: str) -> PRData:
        """仅获取 PR 元数据，不拉取 diff 和文件列表。

        适合快速检查 PR 状态而不消耗过多 API 配额。
        """
        parsed = parse_pr_url(pr_url)
        pr = self._get_pull_request(parsed.owner, parsed.repo, parsed.pr_number)

        return PRData(
            pr_number=pr.number,
            title=pr.title,
            description=pr.body,
            author=pr.user.login,
            state=pr.state,
            head_sha=pr.head.sha,
            base_sha=pr.base.sha,
            head_ref=pr.head.ref,
            base_ref=pr.base.ref,
            diff="",
            files=[],
            url=pr.html_url,
            created_at=pr.created_at,
            updated_at=pr.updated_at,
            merged=pr.merged,
            owner=parsed.owner,
            repo=parsed.repo,
        )

    def fetch_diff_only(self, pr_url: str) -> str:
        """仅获取 PR 的 unified diff 文本。"""
        parsed = parse_pr_url(pr_url)
        pr = self._get_pull_request(parsed.owner, parsed.repo, parsed.pr_number)
        return self._fetch_diff(pr)

    # ── 内部方法 ────────────────────────────────────────────────

    def _get_pull_request(self, owner: str, repo: str, pr_number: int) -> PullRequest.PullRequest:
        repo_obj = self._get_repo(owner, repo)
        return self._execute_with_retry(
            lambda: repo_obj.get_pull(pr_number),
            error_context=f"获取 PR {owner}/{repo}#{pr_number}",
        )

    def _get_repo(self, owner: str, repo: str) -> Repository:
        return self._execute_with_retry(
            lambda: self._github.get_repo(f"{owner}/{repo}"),
            error_context=f"获取仓库 {owner}/{repo}",
        )

    def _fetch_diff(self, pr: PullRequest.PullRequest) -> str:
        self._rate_limiter.acquire()

        def _get_diff():
            headers = {"Accept": "application/vnd.github.v3.diff"}
            requester = pr._requester
            _, data = requester.requestJsonAndCheck("GET", pr.diff_url, headers=headers)
            if data is None:
                return ""
            if isinstance(data, bytes):
                return data.decode("utf-8", errors="replace")
            return str(data)

        try:
            response = self._execute_with_retry(
                _get_diff,
                max_retries=self._config.max_retries,
                error_context=f"获取 PR #{pr.number} diff",
            )
            return response
        except RateLimitExceededError:
            raise

    def _fetch_files(self, pr: PullRequest.PullRequest) -> list[FileDiff]:
        self._rate_limiter.acquire()
        return self._paginate_files(pr)

    def _paginate_files(self, pr: PullRequest.PullRequest) -> list[FileDiff]:
        """分页获取所有变更文件。"""
        all_files: list[FileDiff] = []
        page = 1
        per_page = 100

        while True:
            self._rate_limiter.acquire()
            page_files = self._execute_with_retry(
                lambda: pr.get_files().get_page(page),
                error_context=f"获取 PR #{pr.number} 文件列表 (第 {page} 页)",
            )
            if not page_files:
                break
            all_files.extend(
                FileDiff(
                    filename=f.filename,
                    previous_filename=f.previous_filename,
                    status=FileStatus(f.status),
                    additions=f.additions,
                    deletions=f.deletions,
                    changes=f.changes,
                    patch=f.patch,
                    raw_url=f.raw_url,
                    blob_url=f.blob_url,
                )
                for f in page_files
            )
            if len(page_files) < per_page:
                break
            page += 1

        return all_files

    def fetch_file_content(self, owner: str, repo: str, file_path: str, ref: str) -> str | None:
        """获取仓库中指定文件的内容。

        Args:
            owner: 仓库所有者
            repo: 仓库名称
            file_path: 文件路径
            ref: Git 引用（分支名/commit SHA）

        Returns:
            文件内容字符串，或 None 如果文件不存在
        """
        self._rate_limiter.acquire()
        repo_obj = self._get_repo(owner, repo)

        try:
            content_file = self._execute_with_retry(
                lambda: repo_obj.get_contents(file_path, ref=ref),
                error_context=f"获取文件 {owner}/{repo}/{file_path} @ {ref}",
            )
            if isinstance(content_file, list):
                return None
            content = content_file.content
            import base64

            return base64.b64decode(content).decode("utf-8", errors="replace")
        except PRNotFoundError:
            logger.warning("文件不存在: %s/%s/%s @ %s", owner, repo, file_path, ref)
            return None

    # ── 重试与错误处理 ───────────────────────────────────────────

    def _execute_with_retry(
        self,
        func,
        error_context: str = "",
        max_retries: int | None = None,
    ):
        """带指数退避重试和统一错误处理的执行器。"""
        max_retries = max_retries if max_retries is not None else self._config.max_retries
        last_exception: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                return func()
            except RateLimitExceededException as e:
                self._handle_github_rate_limit(e)
                continue
            except GithubException as e:
                last_exception = e
                if e.status == 401:
                    raise AuthenticationError(
                        f"GitHub Token 无效或已过期。请检查 GITHUB_TOKEN。" f"（{error_context}）",
                        original_error=e,
                    ) from e
                if e.status == 404:
                    raise PRNotFoundError(
                        f"请求的资源不存在（{error_context}）。"
                        f"请检查 owner/repo 名称和 PR 编号是否正确。",
                        original_error=e,
                    ) from e
                if e.status == 403:
                    raise RateLimitExceededError(
                        f"API 访问被禁止（{error_context}）。可能是速率限制或权限不足。",
                        original_error=e,
                    ) from e
                if e.status and e.status >= 500:
                    if attempt < max_retries:
                        delay = self._backoff_delay(attempt)
                        logger.warning(
                            "GitHub 5xx 错误（%s），第 %d/%d 次重试，等待 %.1fs",
                            error_context,
                            attempt + 1,
                            max_retries,
                            delay,
                        )
                        time.sleep(delay)
                        continue
                raise GitHubAPIError(
                    f"GitHub API 错误 {e.status}: {e.data.get('message', str(e)) if hasattr(e, 'data') else str(e)}"
                    f"（{error_context}）",
                    status_code=e.status,
                    original_error=e,
                ) from e
            except (URLError, ConnectionError, TimeoutError) as e:
                last_exception = e
                if attempt < max_retries:
                    delay = self._backoff_delay(attempt)
                    logger.warning(
                        "网络错误（%s），第 %d/%d 次重试，等待 %.1fs",
                        error_context,
                        attempt + 1,
                        max_retries,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                raise NetworkError(
                    f"网络请求失败（{error_context}）: {e}",
                    original_error=e,
                ) from e

        raise PRFetcherError(
            f"操作失败，已达最大重试次数（{error_context}）",
            original_error=last_exception,
        )

    def _handle_github_rate_limit(self, exception: RateLimitExceededException) -> None:
        """处理 GitHub API 速率限制：等待直到限制重置。"""
        reset_timestamp = None
        try:
            rate_limit = self._github.get_rate_limit().core
            reset_timestamp = rate_limit.reset.timestamp()
        except Exception:
            pass

        now = time.time()
        wait_seconds = 60
        if reset_timestamp and reset_timestamp > now:
            wait_seconds = reset_timestamp - now + 1

        logger.warning("GitHub API Rate Limit 已超出，等待 %.0f 秒后重试...", wait_seconds)
        time.sleep(wait_seconds)

    def _backoff_delay(self, attempt: int) -> float:
        delay = self._config.retry_base_delay * (2**attempt)
        return min(delay, self._config.retry_max_delay)

    # ── 属性 ────────────────────────────────────────────────────

    @property
    def rate_limiter(self) -> TokenBucket:
        """暴露速率限制器供外部监控。"""
        return self._rate_limiter

    @property
    def remaining_rate_limit(self) -> int:
        """获取当前剩余的 GitHub API 配额。

        Returns:
            本小时剩余请求数，获取失败返回 -1
        """
        try:
            return self._github.get_rate_limit().core.remaining
        except Exception:
            return -1
