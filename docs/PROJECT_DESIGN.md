# AI PR Review Assistant — 项目设计书

> 📅 版本：v1.0
> 📅 更新日期：2026-05-31
> 📝 状态：已完成

---

## 目录

- [一、项目概述](#一项目概述)
- [二、系统架构](#二系统架构)
- [三、核心模块设计](#三核心模块设计)
- [四、配置系统设计](#四配置系统设计)
- [五、CLI 设计](#五cli-设计)
- [六、数据模型设计](#六数据模型设计)
- [七、技术创新点](#七技术创新点)
- [八、测试策略](#八测试策略)
- [九、部署与发布](#九部署与发布)

---

## 一、项目概述

### 1.1 项目简介

AI PR Review Assistant 是一个基于 AI 的 GitHub Pull Request 代码审查工具，通过智能分析 PR 变更，自动发现潜在问题，帮助开发者提升代码审查效率与质量。

### 1.2 核心功能

| 功能 | 说明 |
|------|------|
| **PR 获取** | 解析 GitHub PR URL，获取元数据、Diff、文件内容 |
| **智能过滤** | 自动跳过测试文件、文档、配置文件等不相关文件 |
| **上下文构建** | 基于 tree-sitter 提取函数/类结构，三级 fallback |
| **Prompt 组装** | 双层结构（基础层 + 语言层），650 tokens 精简指令 |
| **AI 审查** | 支持 18+ 模型供应商，结构化 JSON 输出 |
| **后处理** | 置信度过滤、去重、按严重度排序 |
| **结果存储** | SQLite 持久化，支持历史查询和统计 |
| **报告渲染** | 终端彩色、Markdown、JSON、GitHub PR 评论 |

### 1.3 技术栈

| 技术 | 用途 |
|------|------|
| Python 3.12 | 主语言 |
| Click | CLI 框架 |
| Rich | 终端 UI |
| Pydantic | 数据验证 |
| PyGithub | GitHub API |
| Anthropic SDK | AI 模型调用 |
| tree-sitter | AST 解析 |
| SQLite | 本地存储 |

### 1.4 项目结构

```
AI-PR-Review-Assistant/
├── src/ai_pr_review/
│   ├── cli.py                    # CLI 入口
│   ├── config.py                 # 配置管理
│   ├── config_wizard.py          # 配置向导
│   ├── chat_commands.py          # 聊天命令
│   ├── chat_runtime.py           # 聊天引擎
│   ├── models/
│   │   └── pr_data.py            # 数据模型
│   ├── services/
│   │   ├── pr_fetcher.py         # PR 获取
│   │   ├── filter_pipeline.py    # 文件过滤
│   │   ├── context_builder.py    # 上下文构建
│   │   ├── prompt_assembler.py   # Prompt 组装
│   │   ├── ai_client.py          # AI 调用
│   │   ├── post_processor.py     # 后处理
│   │   ├── report_renderer.py    # 报告渲染
│   │   ├── result_store.py       # 结果存储
│   │   ├── review_orchestrator.py# 编排层
│   │   ├── cost_controller.py    # 成本控制
│   │   ├── token_bucket.py       # 限流器
│   │   └── model_providers/      # 多供应商适配
│   └── utils/
│       └── github_url_parser.py  # URL 解析
├── tests/                        # 测试套件
├── docs/                         # 文档
├── website/                      # 前端展示
├── pyproject.toml                # 包配置
└── README.md                     # 项目说明
```

---

## 二、系统架构

### 2.1 整体架构

采用**真单体架构**，所有模块运行在单一进程中，通过函数调用进行模块间通信。

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLI Entry (Click)                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐    │
│  │PR Fetcher│──▶│  Filter  │──▶│ Context  │──▶│ Prompt   │    │
│  │(PyGithub)│   │ Pipeline │   │ Builder  │   │Assembler │    │
│  └──────────┘   └──────────┘   └──────────┘   └──────────┘    │
│       │                             │               │           │
│       │         ┌──────────┐        │               │           │
│       │         │  Token   │        │               │           │
│       │         │  Bucket  │        │               │           │
│       │         └──────────┘        │               │           │
│       │                             │               ▼           │
│       │                             │         ┌──────────┐      │
│       │                             │         │AI Client │      │
│       │                             │         │(Multi-   │      │
│       │                             │         │ Provider)│      │
│       │                             │         └──────────┘      │
│       │                             │               │           │
│       │                             │               ▼           │
│       │                             │         ┌──────────┐      │
│       │                             │         │  Post    │      │
│       │                             │         │Processor │      │
│       │                             │         └──────────┘      │
│       │                             │               │           │
│       ▼                             ▼               ▼           │
│  ┌──────────┐                 ┌──────────┐   ┌──────────┐      │
│  │  Result  │                 │  Report  │   │  Cost    │      │
│  │  Store   │                 │ Renderer │   │Controller│      │
│  │(SQLite)  │                 │ (Rich)   │   │          │      │
│  └──────────┘                 └──────────┘   └──────────┘      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 数据流

```
GitHub PR URL
    │
    ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ PR Fetcher  │────▶│   Filter    │────▶│  Context    │
│             │     │  Pipeline   │     │  Builder    │
│ - 获取元数据 │     │ - 跳过测试  │     │ - AST 提取  │
│ - 获取 Diff  │     │ - 跳过文档  │     │ - 三级降级  │
│ - 获取文件   │     │ - 跳过大文件│     │ - 多语言    │
└─────────────┘     └─────────────┘     └─────────────┘
                                               │
                                               ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Post       │◀────│  AI Client  │◀────│  Prompt     │
│  Processor  │     │             │     │  Assembler  │
│ - 置信度过滤 │     │ - 多供应商  │     │ - 双层结构  │
│ - 去重      │     │ - 重试机制  │     │ - JSON Schema│
│ - 排序      │     │ - 成本控制  │     │ - 自定义规则 │
└─────────────┘     └─────────────┘     └─────────────┘
       │
       ▼
┌─────────────┐     ┌─────────────┐
│  Result     │     │  Report     │
│  Store      │     │  Renderer   │
│ - SQLite    │     │ - Terminal  │
│ - 历史查询  │     │ - Markdown  │
│ - 统计分析  │     │ - JSON      │
└─────────────┘     │ - GitHub    │
                    └─────────────┘
```

### 2.3 模块职责

| 模块 | 职责 | 输入 | 输出 |
|------|------|------|------|
| PR Fetcher | 获取 PR 数据 | GitHub URL | PRData |
| Filter Pipeline | 过滤文件 | FileDiff[] | FileDiff[] |
| Context Builder | 构建上下文 | FileDiff + Content | FileContext |
| Prompt Assembler | 组装 Prompt | FileContext | SystemPrompt + UserPrompt |
| AI Client | 调用 AI 模型 | Prompts | ReviewResult |
| Post Processor | 后处理 | ReviewResult | ReviewResult |
| Result Store | 持久化 | ReviewResult | RunID |
| Report Renderer | 渲染报告 | ReviewResult | FormattedReport |
| Cost Controller | 成本控制 | UsageRecord | BudgetStatus |

---

## 三、核心模块设计

### 3.1 PR Fetcher 模块

#### 设计目标

从 GitHub 获取 PR 的元数据、Diff 和文件内容，支持分页获取和限流。

#### 核心数据结构

```python
class FileStatus(Enum):
    ADDED = "added"
    MODIFIED = "modified"
    REMOVED = "removed"
    RENAMED = "renamed"
    COPIED = "copied"
    CHANGED = "changed"

class FileDiff(BaseModel):
    filename: str
    previous_filename: str | None
    status: FileStatus
    additions: int
    deletions: int
    changes: int
    patch: str | None
    raw_url: str | None
    blob_url: str | None

    @property
    def is_deletion_only(self) -> bool:
        return self.additions == 0 and self.deletions > 0

    @property
    def extension(self) -> str:
        return Path(self.filename).suffix.lower()

class PRData(BaseModel):
    pr_number: int
    title: str
    description: str
    author: str
    state: str
    head_sha: str
    base_sha: str
    head_ref: str
    base_ref: str
    diff: str
    files: list[FileDiff]
    url: str
```

#### 关键类

```python
class PRFetcher:
    def __init__(self, config: PRFetcherConfig, github_token: str): ...

    def fetch(self, pr_url: str) -> PRData:
        """获取 PR 完整数据"""
        parsed = parse_pr_url(pr_url)
        pr = self._get_pull_request(parsed)
        metadata = self._fetch_metadata(pr)
        files = self._fetch_files(pr)
        diff = self._fetch_diff(pr)
        return PRData(..., files=files, diff=diff)

    def _fetch_files(self, pr) -> list[FileDiff]:
        """分页获取文件列表"""
        # 使用 Token Bucket 限流
        # 支持 0-based 分页
        ...
```

#### 限流机制

```python
class TokenBucket:
    """线程安全的令牌桶限流器"""

    def __init__(self, rate: float, burst: int): ...

    def acquire(self) -> None:
        """获取一个令牌，必要时等待"""
        ...

    def try_acquire(self) -> bool:
        """尝试获取令牌，不等待"""
        ...
```

#### 错误处理

```python
class PRFetcherError(Exception): ...
class InvalidPRURLError(PRFetcherError): ...
class AuthenticationError(PRFetcherError): ...
class PRNotFoundError(PRFetcherError): ...
class RateLimitExceededError(PRFetcherError): ...
class NetworkError(PRFetcherError): ...
class GitHubAPIError(PRFetcherError): ...
```

---

### 3.2 Filter Pipeline 模块

#### 设计目标

智能过滤不相关文件，减少 AI 审查的范围和成本。

#### 过滤规则

```python
# 始终跳过的文件模式
SKIP_PATTERNS = [
    "tests/**", "**/tests/**",
    "test_*.py", "**/test_*.py",
    "**/test/**", "**/__test__/**",
    "**/*.test.*", "**/*.spec.*",
    "docs/**", "**/*.md", "**/*.rst",
    "**/.github/**",
    "**/CHANGELOG*", "**/LICENSE*",
    "**/*.json", "**/*.lock",
    "**/*.yml", "**/*.yaml",
]

# 过滤逻辑
def should_skip_file(file_path: str, diff_stats: dict) -> bool:
    # 1. 匹配跳过模式
    # 2. 跳过纯删除文件
    # 3. 跳过超大文件（>500 行变更）
    ...
```

#### 白名单支持

```python
# 配置中的 force_include 字段
force_include: list[str] = [
    "src/critical/**",  # 始终审查
    "**/*.sql",         # 始终审查 SQL 文件
]
```

#### 核心类

```python
class FilterPipeline:
    def __init__(self, config: FilterPipelineConfig): ...

    def filter(self, files: list[FileDiff]) -> tuple[list[FileDiff], list[FileDiff]]:
        """返回 (included, excluded) 两个列表"""
        included = []
        excluded = []
        for file in files:
            if self._should_include(file):
                included.append(file)
            else:
                excluded.append(file)
        return included, excluded
```

---

### 3.3 Context Builder 模块

#### 设计目标

为每个文件构建丰富的上下文，帮助 AI 理解代码变更的背景。

#### 三级 Fallback 策略

```
Level 1: tree-sitter 全量解析（最准确）
    ├── 提取函数声明、参数、返回类型
    ├── 提取类定义、方法、继承关系
    └── 提取 import 语句

Level 2: 正则表达式提取（次准确）
    ├── 匹配函数定义模式
    ├── 匹配类定义模式
    └── 匹配 import 模式

Level 3: 仅提供 diff context（保底）
    └── 前后 30 行上下文
```

#### 核心数据结构

```python
class FunctionInfo(BaseModel):
    name: str
    start_line: int
    end_line: int
    parameters: list[str]
    return_type: str | None
    is_async: bool

class ClassInfo(BaseModel):
    name: str
    start_line: int
    end_line: int
    methods: list[str]
    parent_classes: list[str]

class FileContext(BaseModel):
    file_path: str
    language: str
    diff: str
    diff_with_context: str
    imports: list[str]
    functions: list[FunctionInfo]
    classes: list[ClassInfo]
    parse_mode: str  # "tree-sitter" | "regex" | "plain"
```

#### 核心类

```python
class ContextBuilder:
    def __init__(self, config: ContextBuilderConfig): ...

    def build_context(
        self,
        file_path: str,
        diff: str,
        full_content: str | None
    ) -> FileContext:
        """构建文件上下文"""
        language = self._detect_language(file_path)
        ast_context = self._extract_ast(file_path, full_content, language)
        diff_with_context = self._add_context_lines(diff, full_content)
        return FileContext(...)
```

#### 多语言支持

| 语言 | tree-sitter grammar | 支持的提取 |
|------|---------------------|-----------|
| Python | tree-sitter-python | 函数、类、import、装饰器 |
| JavaScript | tree-sitter-javascript | 函数、类、import/export、箭头函数 |
| TypeScript | tree-sitter-typescript | 函数、类、接口、类型、import |

---

### 3.4 Prompt Assembler 模块

#### 设计目标

组装高质量的审查 Prompt，引导 AI 产出结构化的审查结果。

#### 双层 Prompt 结构

```
┌─────────────────────────────────────────┐
│           System Prompt (~400 tokens)   │
│  ┌─────────────────────────────────────┐│
│  │ - 角色定义（代码审查专家）            ││
│  │ - 输出格式（JSON Schema）            ││
│  │ - 通用审查规则（安全、性能、正确性）  ││
│  │ - 严重度定义（critical/high/medium） ││
│  └─────────────────────────────────────┘│
├─────────────────────────────────────────┤
│       Language Layer (~250 tokens)      │
│  ┌─────────────────────────────────────┐│
│  │ - 语言特定检查维度                   ││
│  │ - 常见陷阱和反模式                   ││
│  │ - 最佳实践提示                       ││
│  └─────────────────────────────────────┘│
├─────────────────────────────────────────┤
│           User Prompt (动态)            │
│  ┌─────────────────────────────────────┐│
│  │ - 文件路径和语言                     ││
│  │ - Diff 内容                         ││
│  │ - 上下文（函数/类/import）           ││
│  └─────────────────────────────────────┘│
└─────────────────────────────────────────┘

总计：~650 tokens（相比原始 2000 tokens 减少 65%）
```

#### 核心数据结构

```python
class Finding(BaseModel):
    severity: Literal["critical", "high", "medium", "low", "info"]
    category: Literal[
        "correctness", "security", "resource",
        "error_handling", "performance",
        "concurrency", "architecture"
    ]
    file: str
    line_start: int
    line_end: int
    title: str
    problem: str
    suggestion: str
    confidence: float  # 0.0 ~ 1.0
    code_snippet: str | None

class ReviewResult(BaseModel):
    summary: str
    findings: list[Finding]
```

#### JSON Schema 约束

```python
def get_json_schema(self) -> dict:
    """返回 JSON Schema，强制 AI 输出结构化结果"""
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {"enum": ["critical", "high", "medium", "low", "info"]},
                        "category": {"enum": ["correctness", "security", ...]},
                        "file": {"type": "string"},
                        "line_start": {"type": "integer"},
                        "title": {"type": "string"},
                        "problem": {"type": "string"},
                        "suggestion": {"type": "string"},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": ["severity", "category", "file", "title", "problem", "suggestion", "confidence"]
                }
            }
        },
        "required": ["summary", "findings"]
    }
```

---

### 3.5 AI Client 模块

#### 设计目标

统一的 AI 模型调用接口，支持多供应商、重试机制和成本控制。

#### 多供应商架构

```
┌─────────────────────────────────────────────┐
│              AI Client                       │
│  ┌───────────────────────────────────────┐  │
│  │         Model Provider Factory        │  │
│  └───────────────────────────────────────┘  │
│           │           │           │         │
│           ▼           ▼           ▼         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │ Anthropic│ │  OpenAI  │ │ DeepSeek │   │
│  │ Provider │ │ Provider │ │ Provider │   │
│  └──────────┘ └──────────┘ └──────────┘   │
│           │           │           │         │
│           ▼           ▼           ▼         │
│  ┌───────────────────────────────────────┐  │
│  │    Unified chat() Interface           │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

#### 支持的供应商

| 供应商 | API 格式 | 说明 |
|--------|----------|------|
| Anthropic | anthropic | Claude 系列模型 |
| OpenAI | openai | GPT 系列模型 |
| DeepSeek | openai | DeepSeek 系列模型 |
| Qwen | openai | 通义千问系列 |
| SiliconFlow | openai | 硅基流动 |
| Moonshot | openai | 月之暗面 |
| Zhipu | openai | 智谱 AI |
| OpenRouter | openai | 多模型代理 |
| API2D | openai | 第三方代理 |
| Custom | openai | 自定义端点 |

#### 核心类

```python
class BaseModelProvider(ABC):
    """模型供应商抽象基类"""

    @abstractmethod
    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """调用模型"""
        ...

    @abstractmethod
    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """估算成本"""
        ...

class AIClient:
    """AI 客户端，封装重试和成本控制"""

    def __init__(self, config: AIClientConfig): ...

    def review_code(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> ReviewResult:
        """审查代码，返回结构化结果"""
        # 1. 检查预算
        # 2. 调用模型（3 次重试）
        # 3. 解析 JSON 输出
        # 4. 记录用量
        ...
```

#### 重试机制

```python
# 指数退避重试
MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]  # 秒

for attempt in range(MAX_RETRIES):
    try:
        response = provider.chat(...)
        return parse_response(response)
    except (RateLimitError, NetworkError) as e:
        if attempt < MAX_RETRIES - 1:
            time.sleep(RETRY_DELAYS[attempt])
        else:
            raise
```

---

### 3.6 Post Processor 模块

#### 设计目标

对 AI 输出的审查结果进行后处理，提高结果质量。

#### 四阶段处理流程

```
原始 ReviewResult
    │
    ▼
┌─────────────────┐
│ JSON Schema 验证 │  ← 确保格式正确
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  置信度过滤      │  ← 移除 confidence < 0.6 的结果
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  去重处理        │  ← 同文件 + 同类别 + 同行块（line // 10）
└─────────────────┘
    │
    ▼
┌─────────────────┐
│  严重度排序      │  ← critical > high > medium > low > info
└─────────────────┘
    │
    ▼
处理后的 ReviewResult
```

#### 核心类

```python
class PostProcessor:
    def __init__(self, config: PostProcessorConfig): ...

    def process(self, result: ReviewResult) -> ReviewResult:
        """处理审查结果"""
        findings = result.findings
        findings = self.filter_by_confidence(findings, self.config.confidence_threshold)
        findings = self.deduplicate(findings)
        findings = self.sort_by_severity(findings)
        return ReviewResult(summary=result.summary, findings=findings)

    def filter_by_confidence(
        self,
        findings: list[Finding],
        threshold: float
    ) -> list[Finding]:
        """过滤低置信度结果"""
        return [f for f in findings if f.confidence >= threshold]

    def deduplicate(self, findings: list[Finding]) -> list[Finding]:
        """去重：同文件 + 同类别 + 同行块"""
        seen = set()
        unique = []
        for f in findings:
            key = (f.file, f.category, f.line_start // 10)
            if key not in seen:
                seen.add(key)
                unique.append(f)
        return unique
```

---

### 3.7 Result Store 模块

#### 设计目标

持久化审查结果，支持历史查询和统计分析。

#### 数据库设计

```sql
CREATE TABLE runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pr_url TEXT NOT NULL,
    pr_number INTEGER,
    repo_owner TEXT,
    repo_name TEXT,
    head_sha TEXT,
    total_files INTEGER,
    included_files INTEGER,
    excluded_files INTEGER,
    total_findings INTEGER,
    critical_findings INTEGER DEFAULT 0,
    high_findings INTEGER DEFAULT 0,
    medium_findings INTEGER DEFAULT 0,
    low_findings INTEGER DEFAULT 0,
    info_findings INTEGER DEFAULT 0,
    total_cost REAL DEFAULT 0,
    duration_seconds REAL,
    model TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    result_json TEXT
);

CREATE INDEX idx_runs_pr_url ON runs(pr_url);
CREATE INDEX idx_runs_created_at ON runs(created_at);
```

#### 核心类

```python
class ResultStore:
    def __init__(self, config: ResultStoreConfig): ...

    def save_result(self, pr_url: str, result: ReviewResult) -> int:
        """保存审查结果，返回 run_id"""
        ...

    def get_result(self, run_id: int) -> ReviewResult:
        """获取审查结果"""
        ...

    def list_runs(self, pr_url: str = None, limit: int = 10) -> list[dict]:
        """列出审查记录"""
        ...

    def get_statistics(self) -> dict:
        """获取统计信息"""
        return {
            "total_runs": ...,
            "unique_prs": ...,
            "total_findings": ...,
            "total_cost": ...,
            "latest_run_at": ...,
        }
```

---

### 3.8 Cost Controller 模块

#### 设计目标

控制 AI 调用成本，防止意外高消费。

#### 三级成本控制

```
┌─────────────────────────────────────────────────┐
│                Cost Controller                   │
│                                                  │
│  Level 1: 单次运行硬上限 ($5/run)                │
│  ├── 运行前估算成本                              │
│  ├── 超过上限则拒绝执行                          │
│  └── 运行中实时累加                              │
│                                                  │
│  Level 2: 24 小时滑动窗口 ($50/24h)              │
│  ├── 记录每次运行的用量                          │
│  ├── 计算 24 小时内的总成本                      │
│  └── 超过上限则拒绝执行                          │
│                                                  │
│  Level 3: 预警机制 (80% 阈值)                    │
│  ├── 接近上限时发出警告                          │
│  └── 可选择降级或终止                            │
│                                                  │
└─────────────────────────────────────────────────┘
```

#### 核心类

```python
class CostController:
    def __init__(self, config: CostControllerConfig): ...

    def check_budget(self, estimated_cost: float) -> bool:
        """检查预算是否充足"""
        if self.get_run_cost() + estimated_cost > self.config.run_limit:
            return False
        if self.get_daily_cost() + estimated_cost > self.config.daily_limit:
            return False
        return True

    def record_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        model: str,
    ) -> None:
        """记录用量"""
        cost = self.estimate_cost(input_tokens, output_tokens, model)
        self.usage_records.append(UsageRecord(...))

    def get_run_cost(self) -> float:
        """获取本次运行的成本"""
        ...

    def get_daily_cost(self) -> float:
        """获取 24 小时内的总成本"""
        ...
```

---

### 3.9 Report Renderer 模块

#### 设计目标

将审查结果渲染为多种格式，满足不同场景需求。

#### 输出格式

| 格式 | 场景 | 特点 |
|------|------|------|
| **Terminal** | 本地开发 | Rich 面板、彩色输出、代码高亮 |
| **Markdown** | 文档导出 | 标准 Markdown、表格、代码块 |
| **JSON** | CI/CD 集成 | 结构化数据、可编程处理 |
| **GitHub Comment** | PR 评论 | Markdown 表格、严重度图标 |

#### 核心类

```python
class ReportRenderer:
    def __init__(self, config: ReportRendererConfig): ...

    def render_terminal(self, result: ReviewResult, pr_data: PRData) -> str:
        """渲染终端输出"""
        # 使用 Rich Panel、Table、Syntax
        ...

    def render_markdown(self, result: ReviewResult, pr_data: PRData) -> str:
        """渲染 Markdown"""
        ...

    def render_json(self, result: ReviewResult, pr_data: PRData) -> str:
        """渲染 JSON"""
        ...

    def render_github_comment(self, result: ReviewResult, pr_data: PRData) -> str:
        """渲染 GitHub PR 评论"""
        ...
```

---

### 3.10 Chat Workspace 模块

#### 设计目标

提供交互式终端聊天工作区，支持斜杠命令和会话管理。

#### 功能特性

| 功能 | 说明 |
|------|------|
| **品牌横幅** | ASCII 风格的品牌展示 |
| **状态栏** | 显示 Provider、Model、消息数 |
| **欢迎消息** | 启动时显示使用提示 |
| **消息渲染** | 支持 Markdown 和代码高亮 |
| **斜杠命令** | /help, /status, /model, /review 等 |
| **会话管理** | 新会话、恢复历史、压缩 |
| **输入增强** | prompt-toolkit 历史记录和补全 |

#### 斜杠命令列表

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助信息 |
| `/status` | 显示会话状态 |
| `/usage` | 显示消息/字符统计 |
| `/compact` | 压缩会话历史 |
| `/restore` | 恢复之前的会话 |
| `/config` | 显示当前配置 |
| `/session` | 显示会话信息 |
| `/history [N]` | 显示最近 N 条审查历史 |
| `/stats` | 显示审查统计 |
| `/model <ID>` | 切换模型 |
| `/review <URL>` | 执行 PR 审查 |
| `/clear` | 清空会话 |
| `/exit` | 退出聊天 |

---

## 四、配置系统设计

### 4.1 配置文件结构

```json
{
  "provider": {
    "name": "custom",
    "display_name": "Custom Endpoint",
    "api_key": "sk-xxx",
    "base_url": "https://api.example.com/v1",
    "api_format": "openai",
    "models": {
      "model-name": {
        "name": "model-name",
        "context_window": 32768,
        "max_output": 4096
      }
    },
    "default_model": "model-name"
  },
  "github_token": "ghp_xxx",
  "preferences": {
    "output_format": "terminal",
    "language": "zh-CN",
    "ui_language": "zh-CN",
    "chat_layout": "compact",
    "auto_publish_comment": false
  },
  "pr_fetcher": {
    "token_bucket_rate": 1.39,
    "max_retries": 3,
    "retry_base_delay": 1.0,
    "request_timeout": 30
  },
  "filter_pipeline": {
    "force_include": [],
    "exclude_patterns": ["tests/**", "docs/**", ...],
    "skip_deletion_only": true,
    "max_changes": 500
  },
  "context_builder": {
    "context_lines": 10,
    "enable_tree_sitter": true,
    "max_ast_items": 200
  },
  "prompt_assembler": {
    "include_json_schema_in_system_prompt": true,
    "custom_rules": []
  },
  "ai_client": {
    "api_key": "sk-xxx",
    "model": "model-name",
    "provider": "custom",
    "base_url": "https://api.example.com/v1",
    "api_format": "openai",
    "max_tokens": 4096,
    "timeout_seconds": 120,
    "max_retries": 3,
    "input_cost_per_million": 3.0,
    "output_cost_per_million": 15.0,
    "max_cost_per_run": 5.0,
    "max_cost_per_24h": 50.0
  },
  "cost_controller": {
    "run_limit": 5.0,
    "daily_limit": 50.0,
    "warning_threshold": 0.8
  },
  "post_processor": {
    "confidence_threshold": 0.6
  },
  "result_store": {
    "db_path": "~/.ai_pr_review/results.db",
    "max_results": 1000
  },
  "report_renderer": {
    "title": "AI PR Review Report",
    "json_indent": 2
  }
}
```

### 4.2 配置优先级

```
1. CLI 参数 (--config <path>)
2. 环境变量 (AI_PR_REVIEW_*)
3. 用户级配置 (~/.ai_pr_review/config.json)
4. 项目级配置 (.ai_pr_review/config.json)
5. 项目本地配置 (.ai_pr_review/config.local.json)
6. 默认值
```

### 4.3 配置命令

```bash
# 交互式配置向导
pr-review config

# 快速配置
pr-review config --quick

# 查看配置
pr-review config show

# 测试配置
pr-review config test

# 健康检查
pr-review config health

# 发现模型
pr-review config models

# 切换模型
pr-review config model --name <model>
```

---

## 五、CLI 设计

### 5.1 命令结构

```
pr-review
├── <PR_URL>              # 审查 PR
│   ├── --model           # 覆盖模型
│   ├── --format          # 输出格式
│   ├── --output          # 输出文件
│   ├── --publish-comment # 发布评论
│   ├── --verbose         # 详细输出
│   ├── --dry-run         # 干运行
│   ├── --only-fetch      # 仅获取
│   ├── --only-filter     # 仅过滤
│   └── --config          # 配置文件
├── config                # 配置命令
│   ├── (wizard)          # 配置向导
│   ├── show              # 查看配置
│   ├── test              # 测试配置
│   ├── health            # 健康检查
│   ├── models            # 发现模型
│   └── model             # 切换模型
├── chat                  # 聊天命令
│   ├── --message         # 发送消息
│   ├── --model           # 指定模型
│   └── --layout          # 布局模式
├── history               # 查看历史
├── stats                 # 查看统计
└── preferences           # 偏好设置
```

### 5.2 审查流程

```bash
# 基本用法
pr-review https://github.com/owner/repo/pull/123

# 指定模型
pr-review https://github.com/owner/repo/pull/123 --model gpt-4

# 输出为 Markdown
pr-review https://github.com/owner/repo/pull/123 --format markdown --output report.md

# 发布为 GitHub 评论
pr-review https://github.com/owner/repo/pull/123 --publish-comment

# 干运行（不调用 AI）
pr-review https://github.com/owner/repo/pull/123 --dry-run
```

---

## 六、数据模型设计

### 6.1 核心模型

```python
# PR 数据
class PRData(BaseModel):
    pr_number: int
    title: str
    description: str
    author: str
    state: str
    head_sha: str
    base_sha: str
    diff: str
    files: list[FileDiff]
    url: str

# 文件差异
class FileDiff(BaseModel):
    filename: str
    status: FileStatus
    additions: int
    deletions: int
    changes: int
    patch: str | None

# 文件上下文
class FileContext(BaseModel):
    file_path: str
    language: str
    diff: str
    diff_with_context: str
    imports: list[str]
    functions: list[FunctionInfo]
    classes: list[ClassInfo]
    parse_mode: str

# 审查结果
class ReviewResult(BaseModel):
    summary: str
    findings: list[Finding]

# 发现
class Finding(BaseModel):
    severity: str
    category: str
    file: str
    line_start: int
    line_end: int
    title: str
    problem: str
    suggestion: str
    confidence: float
    code_snippet: str | None
```

### 6.2 配置模型

```python
class AppConfig(BaseModel):
    provider: ProviderConfig
    github_token: str
    preferences: PreferencesConfig
    pr_fetcher: PRFetcherConfig
    filter_pipeline: FilterPipelineConfig
    context_builder: ContextBuilderConfig
    prompt_assembler: PromptAssemblerConfig
    ai_client: AIClientConfig
    cost_controller: CostControllerConfig
    post_processor: PostProcessorConfig
    result_store: ResultStoreConfig
    report_renderer: ReportRendererConfig
```

---

## 七、技术创新点

### 7.1 三方会谈决策模式

采用 Claude Code + DeepSeek V4 Pro + 用户的三方会谈模式，通过多轮质疑-回应-修订循环，达成技术共识。

**关键成果**：
- 撤回 Haiku 分类（避免漏判风险）
- 精简 Prompt（从 2000 tokens 降到 650 tokens）
- 完善 tree-sitter 三级 fallback

### 7.2 双层 Prompt 结构

将 Prompt 分为基础层（~400 tokens）和语言层（~250 tokens），总计 650 tokens，相比原始 2000 tokens 减少 65%。

### 7.3 tree-sitter 三级 Fallback

```
Level 1: tree-sitter 全量解析（最准确）
Level 2: 正则表达式提取（次准确）
Level 3: 仅提供 diff context（保底）
```

### 7.4 多供应商适配层

统一的 `BaseModelProvider` 抽象接口，支持 OpenAI 兼容格式和 Anthropic 原生格式，覆盖 18+ 供应商。

### 7.5 三级成本控制

- 单次运行硬上限：$5/run
- 24 小时滑动窗口：$50/24h
- 预警机制：80% 阈值

---

## 八、测试策略

### 8.1 测试覆盖

| 模块 | 测试数 | 覆盖率 |
|------|--------|--------|
| CLI | 54 | 85% |
| PR Fetcher | 48 | 87% |
| Filter Pipeline | 14 | 96% |
| Context Builder | 5 | 94% |
| Prompt Assembler | 6 | 95% |
| AI Client | 12 | 77% |
| Post Processor | 5 | 100% |
| Cost Controller | 6 | 93% |
| Result Store | 6 | 91% |
| Report Renderer | 6 | 97% |
| Model Providers | 8 | 82% |
| Review Orchestrator | 1 | 97% |
| **总计** | **175** | **88%** |

### 8.2 测试类型

- **单元测试**：每个模块独立测试
- **集成测试**：模块间交互测试
- **端到端测试**：完整流程测试

---

## 九、部署与发布

### 9.1 安装方式

```bash
# PyPI 安装（推荐）
pipx install ai-pr-review

# GitHub 安装
pipx install "git+https://github.com/JiangLai999/AI-PR-Review-Assistant.git"

# 一行命令安装（Linux/macOS）
curl -fsSL https://raw.githubusercontent.com/JiangLai999/AI-PR-Review-Assistant/main/install.sh | sh

# 一行命令安装（Windows PowerShell）
irm https://raw.githubusercontent.com/JiangLai999/AI-PR-Review-Assistant/main/install.ps1 | iex
```

### 9.2 CI/CD

- GitHub Actions 自动测试（Python 3.12/3.13）
- black + isort + mypy 代码质量检查
- 自动发布到 PyPI

---

*本文档整合了项目所有设计文档，作为项目的完整技术设计参考。*
