# PR Fetcher 模块设计文档

> 📅 设计日期：2026-05-29
> 🤖 参与模型：DeepSeek V4 Pro + GPT 5.4
> 📋 设计方式：双模型并行商讨 + 方案整合

---

## 一、设计概述

### 1.1 模块职责
- 解析 GitHub PR URL
- 获取 PR 元数据（标题、描述、作者等）
- 获取 PR diff
- 获取变更文件列表和内容
- 实现 Rate Limit 控制

### 1.2 设计原则
- **接口稳定**：支持后续扩展到 GitLab/Bitbucket
- **错误统一**：调用方不需要感知底层异常
- **可测试性**：完整的单元测试覆盖
- **可扩展性**：支持缓存、增量获取等扩展

---

## 二、双模型方案对比

### 2.1 DeepSeek V4 Pro 方案

**特点：**
- ✅ 直接创建了完整的项目结构
- ✅ 实现了完整的代码
- ✅ 包含单元测试
- ⚠️ 测试存在导入错误（Repository.Repository）

**代码结构：**
```
src/ai_pr_review/
├── config.py
├── models/
│   └── pr_data.py
├── services/
│   ├── exceptions.py
│   ├── pr_fetcher.py
│   └── token_bucket.py
└── utils/
    └── github_url_parser.py
```

**优点：**
- 快速实现，立即可用
- 代码结构清晰
- 包含完整的错误处理

**缺点：**
- 测试存在导入错误
- 部分实现可能不够完善

---

### 2.2 GPT 5.4 方案

**特点：**
- ✅ 详细的设计文档
- ✅ 完整的代码示例
- ✅ 详细的单元测试设计
- ✅ 考虑了扩展性

**设计亮点：**
1. **接口设计**：`fetch()`, `fetch_metadata()`, `fetch_diff_only()`
2. **错误分层**：统一异常映射，调用方无需感知 `GithubException`
3. **Rate Limit 分层**：Token Bucket + GitHub 原生 rate limit
4. **扩展性考虑**：支持缓存层、超大 PR 处理

**优点：**
- 设计文档详细
- 考虑了扩展性
- 单元测试设计完善

**缺点：**
- 没有直接创建代码文件
- 需要手动实现

---

## 三、整合方案

### 3.1 整合策略

基于两个模型的方案，我建议采用以下整合策略：

1. **采用 DeepSeek 的项目结构**（已创建）
2. **采用 GPT 5.4 的接口设计**（更完善）
3. **修复 DeepSeek 的测试错误**
4. **补充 GPT 5.4 的扩展性设计**

### 3.2 最终接口设计

```python
class PRFetcher:
    """从 GitHub 获取 Pull Request 完整数据。"""

    def __init__(
        self,
        github_token: str | None = None,
        config: PRFetcherConfig | None = None,
    ) -> None:
        """初始化 PR Fetcher。"""
        pass

    def fetch(self, pr_url: str) -> PRData:
        """获取 PR 的完整数据。"""
        pass

    def fetch_metadata(self, pr_url: str) -> PRData:
        """仅获取 PR 元数据。"""
        pass

    def fetch_diff_only(self, pr_url: str) -> str:
        """仅获取 unified diff。"""
        pass

    def fetch_file_content(
        self,
        owner: str,
        repo: str,
        file_path: str,
        ref: str,
    ) -> str | None:
        """获取某个 ref 下文件内容。"""
        pass

    @property
    def rate_limiter(self) -> TokenBucket:
        """获取速率限制器。"""
        pass

    @property
    def remaining_rate_limit(self) -> int:
        """获取剩余 API 调用次数。"""
        pass
```

### 3.3 数据模型设计

```python
class FileStatus(str, Enum):
    """文件变更状态。"""
    ADDED = "added"
    MODIFIED = "modified"
    REMOVED = "removed"
    RENAMED = "renamed"
    COPIED = "copied"
    CHANGED = "changed"

class FileDiff(BaseModel):
    """单个变更文件的信息。"""
    filename: str
    previous_filename: str | None = None
    status: FileStatus
    additions: int = 0
    deletions: int = 0
    changes: int = 0
    patch: str | None = None
    raw_url: str | None = None
    blob_url: str | None = None

    @property
    def is_deletion_only(self) -> bool:
        """判断是否为纯删除。"""
        return self.additions == 0 and self.deletions > 0

    @property
    def extension(self) -> str:
        """获取文件扩展名。"""
        return self.filename.rsplit(".", 1)[-1].lower() if "." in self.filename else ""

    def is_too_large(self, max_lines: int = 500) -> bool:
        """判断变更是否过大。"""
        return self.changes > max_lines

class PRData(BaseModel):
    """完整 PR 数据。"""
    pr_number: int
    title: str
    description: str | None = None
    author: str
    state: str
    head_sha: str
    base_sha: str
    head_ref: str
    base_ref: str
    diff: str = ""
    files: list[FileDiff] = Field(default_factory=list)
    url: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    merged: bool = False
    owner: str
    repo: str

    @property
    def repo_full_name(self) -> str:
        """获取仓库全名。"""
        return f"{self.owner}/{self.repo}"

    @property
    def total_additions(self) -> int:
        """获取总新增行数。"""
        return sum(file.additions for file in self.files)

    @property
    def total_deletions(self) -> int:
        """获取总删除行数。"""
        return sum(file.deletions for file in self.files)

    @property
    def total_changes(self) -> int:
        """获取总变更行数。"""
        return sum(file.changes for file in self.files)

    @property
    def changed_files_count(self) -> int:
        """获取变更文件数量。"""
        return len(self.files)

class ParsedPRUrl(BaseModel):
    """PR URL 解析结果。"""
    owner: str
    repo: str
    pr_number: int
```

### 3.4 错误处理设计

```python
class PRFetcherError(Exception):
    """PR Fetcher 模块基础异常。"""
    def __init__(self, message: str, original_error: Exception | None = None):
        super().__init__(message)
        self.original_error = original_error

class InvalidPRURLError(PRFetcherError):
    """GitHub PR URL 格式无效。"""

class AuthenticationError(PRFetcherError):
    """GitHub Token 无效或未提供。"""

class PRNotFoundError(PRFetcherError):
    """PR 或仓库不存在，或无权限访问。"""

class RateLimitExceededError(PRFetcherError):
    """GitHub API 速率限制超出。"""
    def __init__(
        self,
        message: str,
        reset_timestamp: float | None = None,
        original_error: Exception | None = None,
    ):
        super().__init__(message, original_error)
        self.reset_timestamp = reset_timestamp

class NetworkError(PRFetcherError):
    """网络请求异常。"""

class GitHubAPIError(PRFetcherError):
    """GitHub API 非预期错误。"""
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        original_error: Exception | None = None,
    ):
        super().__init__(message, original_error)
        self.status_code = status_code
```

### 3.5 Token Bucket 实现

```python
@dataclass
class TokenBucket:
    """线程安全的 Token Bucket 限流器。"""
    rate: float
    burst: float = 10.0

    def __post_init__(self) -> None:
        if self.rate <= 0:
            raise ValueError("rate must be > 0")
        if self.burst <= 0:
            raise ValueError("burst must be > 0")

        self._tokens: float = self.burst
        self._last_refill: float = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        """补充 token。"""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
        self._last_refill = now

    def acquire(self) -> None:
        """阻塞直到拿到一个 token。"""
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait_time = (1.0 - self._tokens) / self.rate
            time.sleep(wait_time)

    def try_acquire(self) -> bool:
        """非阻塞尝试获取一个 token。"""
        with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    def wait_for_tokens(self, required: int = 1, timeout: float | None = None) -> bool:
        """等待多个 token。"""
        if required <= 0:
            return True

        deadline = None if timeout is None else time.monotonic() + timeout

        while True:
            with self._lock:
                self._refill()
                if self._tokens >= required:
                    self._tokens -= required
                    return True
                missing = required - self._tokens
                wait_time = missing / self.rate

            if deadline is not None and time.monotonic() + wait_time > deadline:
                return False

            time.sleep(wait_time)

    @property
    def available_tokens(self) -> float:
        """获取当前可用 token 数量。"""
        with self._lock:
            self._refill()
            return self._tokens
```

### 3.6 GitHub URL 解析

```python
_GITHUB_PR_URL_PATTERN = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)/?.*$"
)

def parse_pr_url(pr_url: str) -> ParsedPRUrl:
    """解析 GitHub PR URL。"""
    match = _GITHUB_PR_URL_PATTERN.match(pr_url.strip())
    if not match:
        raise InvalidPRURLError(
            f"无效的 GitHub PR URL: {pr_url!r}。"
            "期望格式: https://github.com/<owner>/<repo>/pull/<number>"
        )

    return ParsedPRUrl(
        owner=match.group("owner"),
        repo=match.group("repo"),
        pr_number=int(match.group("number")),
    )
```

---

## 四、单元测试设计

### 4.1 测试分组

1. **TokenBucket 算法测试**
   - 初始 token 数量
   - try_acquire 成功/失败
   - acquire 阻塞等待
   - burst 上限
   - wait_for_tokens 超时

2. **URL 解析测试**
   - 标准 URL 解析
   - 带空格的 URL
   - 无效 URL 抛异常

3. **PRFetcher 初始化测试**
   - 显式 token
   - 无 token 抛异常

4. **错误映射测试**
   - 401 → AuthenticationError
   - 404 → PRNotFoundError
   - 403 rate limit → RateLimitExceededError
   - 500 → GitHubAPIError
   - ConnectionError → NetworkError

5. **重试逻辑测试**
   - 5xx 重试成功
   - 网络错误重试成功
   - 404 不重试
   - 指数退避延迟

6. **数据模型测试**
   - PRData 计算属性
   - FileDiff 辅助方法

### 4.2 测试示例

```python
class TestPRFetcherFetch:
    """PRFetcher.fetch() 测试。"""

    @pytest.fixture
    def fetcher(self):
        return PRFetcher(github_token="ghp_test")

    @pytest.fixture
    def mock_pr(self):
        pr = MagicMock(spec=PullRequest.PullRequest)
        pr.number = 42
        pr.title = "Test PR"
        pr.body = "PR description"
        type(pr.user).login = PropertyMock(return_value="test-user")
        pr.state = "open"
        type(pr.head).sha = PropertyMock(return_value="abc123")
        type(pr.base).sha = PropertyMock(return_value="def456")
        type(pr.head).ref = PropertyMock(return_value="feature")
        type(pr.base).ref = PropertyMock(return_value="main")
        pr.html_url = "https://github.com/owner/repo/pull/42"
        pr.created_at = None
        pr.updated_at = None
        pr.merged = False
        pr.diff_url = "https://api.github.com/repos/owner/repo/pulls/42"
        return pr

    def test_fetch_returns_complete_pr_data(self, fetcher, mock_pr):
        """测试 fetch() 返回完整的 PR 数据。"""
        with patch.object(fetcher, "_github") as mock_gh:
            mock_gh.get_repo.return_value.get_pull.return_value = mock_pr

            with patch.object(fetcher, "_fetch_diff", return_value="mock diff"):
                with patch.object(
                    fetcher,
                    "_fetch_files",
                    return_value=[
                        FileDiff(
                            filename="a.py",
                            status=FileStatus.MODIFIED,
                            additions=5,
                            deletions=2,
                            changes=7,
                        )
                    ],
                ):
                    result = fetcher.fetch("https://github.com/owner/repo/pull/42")

        assert result.pr_number == 42
        assert result.title == "Test PR"
        assert result.author == "test-user"
        assert result.head_sha == "abc123"
        assert result.base_sha == "def456"
        assert result.diff == "mock diff"
        assert len(result.files) == 1
        assert result.files[0].filename == "a.py"
        assert result.repo_full_name == "owner/repo"
        assert result.total_changes == 7
```

---

## 五、扩展性设计

### 5.1 缓存层扩展

```python
class PRCacheRepository:
    """PR 数据缓存仓储。"""

    def __init__(self, fetcher: PRFetcher, cache_backend: CacheBackend):
        self._fetcher = fetcher
        self._cache = cache_backend

    def fetch(self, pr_url: str) -> PRData:
        """获取 PR 数据（带缓存）。"""
        cache_key = self._make_cache_key(pr_url)

        # 尝试从缓存获取
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        # 从 GitHub 获取
        pr_data = self._fetcher.fetch(pr_url)

        # 存入缓存
        self._cache.set(cache_key, pr_data, ttl=3600)  # 1 小时

        return pr_data

    def _make_cache_key(self, pr_url: str) -> str:
        """生成缓存键。"""
        parsed = parse_pr_url(pr_url)
        return f"pr:{parsed.owner}:{parsed.repo}:{parsed.pr_number}"
```

### 5.2 超大 PR 处理

```python
class PRData(BaseModel):
    """完整 PR 数据。"""
    # ... 原有字段 ...

    # 超大 PR 扩展字段
    is_truncated: bool = False
    truncated_reason: str | None = None
    raw_diff_size: int = 0

    def should_chunk(self, max_tokens: int = 15000) -> bool:
        """判断是否需要分块处理。"""
        estimated_tokens = len(self.diff) // 4  # 粗略估算
        return estimated_tokens > max_tokens
```

### 5.3 多平台扩展

```python
class PRFetcherBase(ABC):
    """PR Fetcher 基类。"""

    @abstractmethod
    def fetch(self, pr_url: str) -> PRData:
        """获取 PR 数据。"""
        pass

    @abstractmethod
    def fetch_metadata(self, pr_url: str) -> PRData:
        """获取 PR 元数据。"""
        pass

class GitHubPRFetcher(PRFetcherBase):
    """GitHub PR Fetcher。"""
    pass

class GitLabPRFetcher(PRFetcherBase):
    """GitLab MR Fetcher（未来扩展）。"""
    pass

class BitbucketPRFetcher(PRFetcherBase):
    """Bitbucket PR Fetcher（未来扩展）。"""
    pass
```

---

## 六、修复 DeepSeek 的测试错误

### 6.1 问题分析

DeepSeek 的测试存在导入错误：
```
AttributeError: type object 'Repository' has no attribute 'Repository'
```

### 6.2 修复方案

在 `src/ai_pr_review/services/pr_fetcher.py` 中，修改导入：

```python
# 修复前
from github import Repository

# 修复后
from github.Repository import Repository
```

或者直接使用：
```python
from github import Repository
```

并在类型注解中使用：
```python
def _get_repo(self, owner: str, repo: str) -> Repository.Repository:
    """获取仓库对象。"""
    pass
```

---

## 七、下一步行动

### 7.1 立即执行

1. ✅ 修复 DeepSeek 的测试导入错误
2. ✅ 运行单元测试验证
3. ✅ 整合 GPT 5.4 的扩展性设计

### 7.2 后续模块

继续商讨以下模块：

| 序号 | 模块 | 预估时间 |
|------|------|----------|
| 2 | Filter Pipeline | 20 分钟 |
| 3 | Context Builder | 40 分钟 |
| 4 | Prompt Assembler | 30 分钟 |
| 5 | AI Client | 30 分钟 |
| 6 | Post-Processor | 20 分钟 |
| 7 | Cost Controller | 20 分钟 |
| 8 | Result Store | 20 分钟 |
| 9 | Report Renderer | 20 分钟 |
| 10 | CLI Entry | 20 分钟 |

---

## 八、总结

### 8.1 双模型协作价值

通过 DeepSeek V4 Pro 和 GPT 5.4 的并行商讨，我们获得了：

1. **多视角设计**：两个模型从不同角度思考问题
2. **快速实现**：DeepSeek 直接创建了完整代码
3. **详细文档**：GPT 5.4 提供了详细的设计文档
4. **扩展性考虑**：GPT 5.4 考虑了缓存、多平台等扩展

### 8.2 最终方案优势

整合后的方案具有以下优势：

- ✅ **接口稳定**：支持后续扩展
- ✅ **错误统一**：调用方无需感知底层异常
- ✅ **可测试性**：完整的单元测试覆盖
- ✅ **可扩展性**：支持缓存、增量获取等扩展
- ✅ **多平台支持**：可扩展到 GitLab/Bitbucket

### 8.3 创新点

这种**双模型并行商讨 + 方案整合**的模式，展示了：

1. **AI 协作的潜力**：不同模型可以互补
2. **效率提升**：并行讨论节省时间
3. **质量保证**：多视角设计更完善
4. **透明决策**：所有设计决策都有据可查

---

**下一步**：修复测试错误，然后继续商讨 Filter Pipeline 模块。
