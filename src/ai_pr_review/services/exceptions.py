"""自定义异常层次结构。

为所有 PR Fetcher 相关的错误提供结构化异常类型。
"""


class PRFetcherError(Exception):
    """PR Fetcher 模块基础异常。"""

    def __init__(self, message: str, original_error: Exception | None = None):
        super().__init__(message)
        self.original_error = original_error


class InvalidPRURLError(PRFetcherError):
    """GitHub PR URL 格式无效。"""


class AuthenticationError(PRFetcherError):
    """GitHub Token 无效或未提供 (HTTP 401)。"""


class PRNotFoundError(PRFetcherError):
    """PR 不存在或无权访问 (HTTP 404)。"""


class RateLimitExceededError(PRFetcherError):
    """GitHub API Rate Limit 已耗尽 (HTTP 403 + rate limit)。"""

    def __init__(
        self,
        message: str,
        reset_timestamp: float | None = None,
        original_error: Exception | None = None,
    ):
        super().__init__(message, original_error)
        self.reset_timestamp = reset_timestamp


class NetworkError(PRFetcherError):
    """网络请求失败 (连接超时、DNS 解析失败等)。"""


class GitHubAPIError(PRFetcherError):
    """GitHub API 返回非预期状态码 (500, 422 等)。"""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        original_error: Exception | None = None,
    ):
        super().__init__(message, original_error)
        self.status_code = status_code


class AIClientError(Exception):
    """AI Client 模块基础异常。"""

    def __init__(self, message: str, original_error: Exception | None = None):
        super().__init__(message)
        self.original_error = original_error


class AIAuthenticationError(AIClientError):
    """Anthropic API Key 无效或未提供。"""


class AIRequestTimeoutError(AIClientError):
    """AI 请求超时。"""


class AIResponseFormatError(AIClientError):
    """AI 返回的结构化输出无法解析或校验。"""


class AICostLimitError(AIClientError):
    """AI 调用成本超出限制。"""


class AIServiceError(AIClientError):
    """AI 服务调用失败。"""
