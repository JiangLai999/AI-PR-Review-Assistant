# AI PR Review Assistant — 项目设计书

> 最后更新：2026-09-29 · 版本：v1.1 · 状态：对外文档

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
| **PR 获取** | 解析 GitHub PR URL，获取元数据、Diff 与文件内容 |
| **智能过滤** | 规则预过滤（跳过测试 / 文档 / 纯删除 / 超大文件），支持 `force_include` 白名单 |
| **上下文构建** | tree-sitter → 正则 → diff-only 三级降级；相关文件预取（test→import→init）与预算裁剪 |
| **审查计划** | 调用模型**之前**产出 `ReviewPlan`：风险等级与类别、优先文件、策略、规划依据 |
| **确定性分析** | 静态安全规则、Python AST、符号索引与跨文件接口影响（可复现、可进 CI） |
| **AI 审查** | 19 个 provider 预设（含本地 Ollama）（`PROVIDER_KEY_MAP` 共 22 键，含别名与内部项），本地/云端双槽路由，结构化 JSON 输出 |
| **证据校验** | 文件 / 行号 / 变更行 / 代码片段四项校验 → `valid` / `needs_review` / `invalid` / `unverified` |
| **成本与预算** | local / remote 共享账本、各自价目；单次运行与 24h 滑动窗口双重上限 |
| **后处理** | 置信度过滤、去重、按严重度排序、Finding 行号本地化 |
| **结果存储** | SQLite 持久化 Run、统计与人工反馈（`feedback`） |
| **报告渲染** | 终端彩色、Markdown、JSON、GitHub PR 评论 |
| **三入口交互** | CLI（`pr-review`）、OpenTUI Chat（`pr-review chat`）、Web 工作台（`pr-review serve`），共用同一内核 |
| **离线可演示** | `pr-review demo` / `showcase`：不调用 GitHub 与模型，可零密钥演示 |

### 1.3 技术栈

| 技术 | 用途 |
|------|------|
| Python 3.12 / 3.13 | 主语言（CI 双版本矩阵） |
| Click | CLI 框架（16 个顶层命令 + 默认审查入口） |
| Rich | 终端 UI 与表格 |
| Pydantic | 数据模型与校验 |
| PyGithub | GitHub API |
| Anthropic SDK + OpenAI 兼容 HTTP | 模型调用（19 个 provider 预设，`PROVIDER_KEY_MAP` 共 22 键） |
| tree-sitter（可选 extra） | AST 级上下文；未安装时自动降级 |
| SQLite | 审查历史、统计与 Chat 会话 |
| asyncio | 审查编排与并发控制 |
| 标准库 `ThreadingHTTPServer` | Web 工作台 HTTP 接口（运行不需要 Node） |
| OpenTUI + Bun（SolidJS） | 交互式 Chat 界面；缺少 Bun 时回退纯文本或预编译二进制 |
| 原生 HTML/CSS/JS + GSAP | 官网（文档中心与动画），GitHub Pages 托管 |

### 1.4 项目结构

```text
AI-PR-Review-Assistant/
├── src/ai_pr_review/
│   ├── cli.py                    # CLI 入口（16 个顶层命令 + 默认审查）
│   ├── config.py                 # 配置模型、加载优先级与 provider 预设
│   ├── config_wizard.py          # 交互式配置向导
│   ├── chat_commands.py          # 纯文本 Chat 的斜杠命令
│   ├── chat_runtime.py           # Chat 主循环（TUI / 纯文本共用）
│   ├── web_server.py             # Web 工作台 HTTP 服务（标准库）
│   ├── demo_runner.py / demo_fixtures.py     # 离线 Demo
│   ├── backend/jsonl_server.py   # TUI 后端（JSONL 协议 + command.execute 分发）
│   ├── models/                   # PRData / ReviewPlan / Evidence 等数据模型
│   ├── services/
│   │   ├── review_orchestrator.py / hybrid_orchestrator.py   # 编排与混合路由
│   │   ├── pr_fetcher.py / filter_pipeline.py / context_builder.py
│   │   ├── repo_context.py       # 相关文件预取（test→import→init）
│   │   ├── prompt_assembler.py / ai_client.py / post_processor.py
│   │   ├── finding_localizer.py / publish_service.py
│   │   ├── result_store.py / report_renderer.py / cost_controller.py
│   │   ├── analyzers/            # 静态规则、Python AST、符号索引、跨文件
│   │   ├── evidence/             # Finding 证据校验
│   │   └── model_providers/      # 多供应商适配
│   ├── web_static/               # Web 工作台静态资源（随包分发）
│   └── tui_static/               # 已提交的 TUI bundle（无 Bun 时可回退）
├── frontend/tui/                 # OpenTUI 源码与前端测试
├── web/                          # Web 工作台前端源码与构建
├── scripts/                      # 官网文档生成、提交包卫生守卫、协作调度
├── tests/                        # Python 测试（1545 项）
├── docs/                         # 文档（设计 / API / 合规 / 开发记录）
├── website/                      # 官网（文档中心 + 命令速查）
└── pyproject.toml / install.sh / install.ps1
```

---

## 二、系统架构

### 2.1 整体架构

采用**真单体架构**，所有模块运行在单一进程中，通过函数调用进行模块间通信。

```text
┌────────────────────────── 入口层 ──────────────────────────┐
│  CLI (Click)   │   Chat (OpenTUI / 纯文本)   │   Web 工作台  │
│  pr-review …   │   pr-review chat            │ pr-review serve│
└────────┬───────┴──────────────┬──────────────┴───────┬──────┘
         └──────────────────────┼──────────────────────┘
                                ▼
              ReviewOrchestrator / HybridOrchestrator (asyncio)
                                │
   PR Fetcher → Filter Pipeline → Context Builder (+ Repo Context) → ReviewPlan
                                │
        ┌───────────────────────┼────────────────────────┐
        ▼                       ▼                        ▼
  确定性分析层              模型层                    证据层
  · 静态安全规则            · ModelSelector           · FindingValidator
  · Python AST              · AI Client / 多供应商     · 文件 / 行号 /
  · 符号索引 + 跨文件        · 本地 / 云端双槽         · 变更行 / 片段
  · CostLedger 预算闸门      · 结构化 JSON 输出         · 四态结论
        └───────────────────────┼────────────────────────┘
                                ▼
        PostProcessor → ReportRenderer（终端 / Markdown / JSON / GitHub）
                                ▼
        ResultStore（SQLite：Run / 统计 / 反馈）→ history / explain / export-run
```

### 2.2 数据流

```text
GitHub PR URL
    │
    ▼
┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│ PR Fetcher  │──▶│   Filter    │──▶│  Context    │──▶│  Review     │
│ 元数据/Diff │   │ 规则/白名单 │   │ 三级降级    │   │  Planner    │
│ 文件内容    │   │ 纯删除/超大 │   │ 相关文件    │   │ 风险与策略  │
└─────────────┘   └─────────────┘   └─────────────┘   └──────┬──────┘
                                                             │
                            ┌────────────────────────────────┤
                            ▼                                ▼
                   ┌─────────────┐                  ┌─────────────┐
                   │ 确定性分析  │                  │ AI 审查     │
                   │ 规则/AST/   │                  │ 双槽路由 +  │
                   │ 跨文件影响  │                  │ 成本账本    │
                   └──────┬──────┘                  └──────┬──────┘
                          └────────────┬───────────────────┘
                                       ▼
                              ┌─────────────────┐
                              │ FindingValidator│  ← 文件/行号/变更行/片段
                              │ 四态证据结论    │
                              └────────┬────────┘
                                       ▼
                    ┌──────────────────┴──────────────────┐
                    ▼                                     ▼
            ┌─────────────┐                       ┌─────────────┐
            │ PostProcess │                       │ ResultStore │
            │ 去重/排序   │                       │ SQLite 历史 │
            └──────┬──────┘                       └──────┬──────┘
                   ▼                                     ▼
        终端 / Markdown / JSON / GitHub 评论     history / stats / feedback
```

### 2.3 模块职责

| 模块 | 职责 | 输入 | 输出 |
|------|------|------|------|
| PR Fetcher | 获取 PR 数据 | GitHub URL | PRData |
| Filter Pipeline | 过滤文件 | FileDiff[] | FileDiff[] |
| Context Builder | 构建上下文（tree-sitter → 正则 → diff 三级降级） | FileDiff + Content | FileContext |
| Review Planner | 生成确定性审查计划 | PRData + FilterResult | ReviewPlan |
| Static Analyzer | 逐行安全规则 | FileDiff + FileContext | Finding[] |
| Python AST Analyzer | 语法级规则（可变默认参数、裸异常、资源泄漏等） | FileDiff + FileContext | Finding[] |
| Symbol Index | 提取签名、定位跨文件引用 | FileContext[] | SymbolDefinition[] / CrossFileReference[] |
| Cross-file Interface Analyzer | 签名对比与外部调用方影响 | FileContext[] + base 签名 | InterfaceImpact[] |
| Finding Validator | 校验 finding 是否对应真实变更 | Finding + FileDiff + FileContext | Evidence |
| Prompt Assembler | 组装 Prompt | FileContext | SystemPrompt + UserPrompt |
| AI Client | 调用 AI 模型 | Prompts | ReviewResult |
| Post Processor | 后处理 | ReviewResult | ReviewResult |
| Result Store | 持久化 | ReviewResult | RunID |
| Report Renderer | 渲染报告 | ReviewResult | FormattedReport |
| Cost Controller | 成本控制 | UsageRecord | BudgetStatus |
| Benchmark | 量化分析策略效果 | BenchmarkCase[] | BenchmarkReport |
| Web Server | 本地工作台 HTTP 接口 | HTTP 请求 | JSON |
| Repo Context Provider | 预取相关文件（test→import→init，带缓存与截断） | FileDiff + 仓库根 | RelatedFile[] |
| Hybrid Orchestrator / Model Selector | 按复杂度与配置路由模型，组织本地/云端协作 | ReviewPlan + 配置 | 槽位选择 + ReviewResult |
| Publish Service | 预览并发布 GitHub PR 评论 | Run + Finding[] | 评论 URL |
| Demo Runner | 离线 Demo（不联网、不调用模型） | case_key | Demo 结果 |
| Chat Runtime / JSONL Backend | Chat 会话、斜杠命令与审查上下文绑定 | 用户输入 | 会话消息 / 绑定状态 |
| Web Config | Web 工作台独立配置（`*.web.json`）读写 | 设置页输入 | 配置视图 |

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

```text
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

```text
┌─────────────────────────────────────────┐
│   System Prompt · 基础层（727 字符）     │
│  ┌─────────────────────────────────────┐│
│  │ - 角色定义（代码审查专家）            ││
│  │ - 输出格式（JSON Schema）            ││
│  │ - 通用审查规则（安全、性能、正确性）  ││
│  │ - 严重度定义（critical/high/medium） ││
│  └─────────────────────────────────────┘│
├─────────────────────────────────────────┤
│   Language Layer · 语言层（≈280 字符）   │
│  ┌─────────────────────────────────────┐│
│  │ - 语言特定检查维度                   ││
│  │ - 常见陷阱和反模式                   ││
│  └─────────────────────────────────────┘│
├─────────────────────────────────────────┤
│   Related-file rules（相关文件诚实约束） │
│  ┌─────────────────────────────────────┐│
│  │ - 只引用真实提供的相关文件（73 字符）││
│  └─────────────────────────────────────┘│
├─────────────────────────────────────────┤
│           User Prompt（动态）           │
│  ┌─────────────────────────────────────┐│
│  │ - 文件路径和语言                     ││
│  │ - Diff 内容                         ││
│  │ - 上下文（函数/类/import）           ││
│  └─────────────────────────────────────┘│
└─────────────────────────────────────────┘

实测（2026-09-29，`services/prompt_assembler.py`）：Python 的 system prompt ≈ 1,084 字符
（基础层 727 + 语言层 284 + 相关文件约束 73），量级约 300–350 tokens；
user prompt 随 diff、上下文与相关文件动态变化，不写死总量。
```

#### 核心数据结构

```python
class Finding(BaseModel):
    severity: str          # critical | high | medium | low | info
    category: str          # correctness | security | resource | error_handling |
                           # performance | concurrency | architecture
    file: str
    line_start: int
    line_end: int
    title: str
    problem: str
    suggestion: str
    confidence: float  # 0.0 ~ 1.0
    code_snippet: str
    finding_id: str = ""
    sources: list[str] = ["ai_analysis"]   # rule / ast / cross_file / ai_analysis
    evidence: list[Evidence] = []
    evidence_status: str = "unverified"     # valid | needs_review | invalid | unverified
    evidence_issues: list[str] = []
    rule_id: str = ""
    suggested_patch: str = ""

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

```text
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
| Ollama（本地） | openai | 本机模型，隐私优先；也是"仅本地"槽位的实现 |
| Anthropic | anthropic | Claude 系列模型（原生协议） |
| OpenAI | openai | GPT 系列模型 |
| DeepSeek | openai | DeepSeek 系列模型 |
| Qwen | openai | 通义千问系列 |
| SiliconFlow | openai | 硅基流动 |
| Moonshot | openai | 月之暗面 |
| Zhipu | openai | 智谱 AI |
| Baichuan | openai | 百川智能 |
| Minimax | openai | MiniMax |
| Stepfun | openai | 阶跃星辰 |
| Doubao | openai | 豆包（火山方舟） |
| Hunyuan | openai | 腾讯混元 |
| Yi | openai | 零一万物 |
| OpenRouter | openai | 多模型代理 |
| API2D / CloseAI / OhMyGPT | openai | 第三方代理 |
| Custom | openai | 自定义端点（base URL + key + 模型名 + 上下文长度均可单独配置） |

> 预设共 **19 个**（含本地 Ollama）（`PROVIDER_KEY_MAP` 共 22 键，含别名与内部项）；第三方中转站按 Custom 处理，不共享官方价目表，
> 成本估算以配置的价目为准（见 `services/cost_controller.py`）。

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

```text
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

```text
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
| **两种形态** | OpenTUI 交互界面（默认）与纯文本 CLI（缺少 Bun / OpenTUI 时自动回退） |
| **审查上下文** | `/review` 完成后绑定该 Run，可继续追问 Finding 与证据；`/context` 查看或解绑 |
| **思考档位** | `/think off\|low\|high\|max\|auto`；本地端点会置灰并说明原因 |
| **会话管理** | `/sessions` 切换 / 重命名 / 删除，`/new`、`/rename`、`/compact` 压缩 |
| **Findings 交互** | `Ctrl+O` 打开详情、`Ctrl+F` 筛选、`Alt+P` 发布预览（需再确认） |
| **状态栏** | Provider / 模型 / 思考档位 / 会话名 / 消息数 |
| **输入增强** | TUI 命令菜单与补全；纯文本 CLI 使用 prompt-toolkit 历史与补全 |

#### 斜杠命令（按界面区分）

完整清单、参数与注意事项见 `docs/chat-features.md`：

| 界面 | 命令 |
|------|------|
| TUI · CLI 通用 | `/help` `/status` `/model` `/review` `/history` `/compact` `/new` |
| 仅 TUI | `/setup` `/think` `/context` `/cancel` `/retry` `/report` `/export` `/explain` `/feedback` `/publish` `/demo` `/showcase` `/workbench` `/sessions` `/rename` |
| 仅 CLI | `/usage` `/stats` `/config` `/session` `/restore` `/clear` `/exit` |

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
  "local_provider": {
    "name": "ollama",
    "base_url": "http://127.0.0.1:11434/v1",
    "api_format": "openai",
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

```text
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

```text
pr-review
├── <PR_URL>              # 默认审查入口（等价 `pr-review review <PR_URL>`）
│   ├── --model / --mode / --max-cost            # 模型、路由模式、单次预算
│   ├── --format terminal|markdown|json / --output
│   ├── --publish-comment / --verbose / --dry-run
│   └── --only-fetch / --only-filter / --show-filter-reasons
├── plan <PR_URL>         # 只输出审查计划（不调用模型）
├── trace <PR_URL>        # 规划流水线各阶段耗时
├── explain <RUN_ID>      # 解释历史 Run 的 Finding 与证据
├── export-run <RUN_ID>   # 导出历史 Run（--format markdown|json）
├── feedback <RUN_ID> <FINDING_ID> --status accepted|rejected|fixed|needs_review [--note]
├── history               # 历史 Run（--pr-url / --limit / --json / --table）
├── stats                 # 聚合统计（JSON）
├── doctor                # 环境体检（--json-output）
├── demo                  # 离线 Demo（--case / --list-cases / --json-output）
├── benchmark             # 规则回归（--strategy static|ast|combined|all）
├── showcase              # 参赛演示路径（--json-output / --interactive）
├── serve                 # Web 工作台（--host / --port，默认 127.0.0.1:8787）
├── chat                  # Chat 工作区（--message / --model / --layout / --tui / --plain）
├── preferences           # 个人偏好（语言、布局、输出格式、思考档位…）
├── local-model check     # 本地 Ollama 可用性诊断
└── config                # 配置命令
    ├── (wizard) / --quick / --advanced / --save-key
    ├── show / init / test / health / model / models
    └── export / import / preferences
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

# 只看审查计划与过滤原因（不消耗模型成本）
pr-review plan https://github.com/owner/repo/pull/123
pr-review https://github.com/owner/repo/pull/123 --only-filter --show-filter-reasons

# 零密钥离线演示 + 体检
pr-review doctor
pr-review demo --case sql-injection

# 启动工作台 / Chat
pr-review serve
pr-review chat
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

### 7.1 证据优先：Finding 四态校验

每条 Finding 都要对齐 PR 的真实变更（文件、行号、变更行、代码片段），结论落到四态：
`valid` / `needs_review` / `invalid` / `unverified`，并携带置信度与来源（规则 / AST / AI）。

实现见 `src/ai_pr_review/services/evidence/finding_validator.py`。

### 7.2 可解释的审查计划（ReviewPlan）

调用模型之前先产出结构化计划：风险等级与类别、优先文件、策略、是否需要跨文件分析、规划依据。
`pr-review plan` 与 `--dry-run` 都停在这一步，成本与范围因此是**先确定、后消耗**。

### 7.3 双层 Prompt 结构

基础层（727 字符）定义角色、JSON 输出格式与通用规则；语言层（约 280 字符）补充该语言的检查维度；
另有相关文件"诚实约束"段（73 字符），要求模型只引用真实提供的文件。
实测 Python 的 system prompt ≈ 1,084 字符（约 300–350 tokens），user prompt 随上下文动态变化。

### 7.4 tree-sitter 三级 Fallback

```text
Level 1: tree-sitter 全量解析（最准确）
Level 2: 正则表达式提取（次准确）
Level 3: 仅提供 diff context（保底；`parse_mode` 随结果返回）
```

### 7.5 多供应商适配层

统一的 provider 抽象接口，支持 OpenAI 兼容格式与 Anthropic 原生格式，内置 **19 个预设**（含本地 Ollama）（`PROVIDER_KEY_MAP` 共 22 键，含别名与内部项）；
第三方中转站走 Custom 预设，base URL / key / 模型名 / 上下文长度均可单独配置。

### 7.6 双槽成本账本

- 槽位：`local` / `remote` / `hybrid`，Chat 与审查可分别指定模型；
- 账本：两槽共享同一本预算账，但各自按自己的价目计算（避免本地模型被按云端价计费）；
- 闸门：单次运行硬上限 `$5/run`、24 小时滑动窗口 `$50/24h`（可配置），另有 80% 预警；
- 路由：按任务复杂度与用户配置选择模型（`services/model_selector.py`、`services/hybrid_orchestrator.py`）。

### 7.7 三入口同内核 + 审查上下文闭环

CLI / OpenTUI Chat / Web 工作台共用同一套审查编排；Chat 中 `/review` 完成后会把该 Run
绑定为对话上下文（`/context` 查看或解绑），因此"审查结论"可以被继续追问，而不是一次性输出。

---

## 八、测试策略

### 8.1 测试覆盖

| 层次 | 内容 | 现状（2026-09-29） |
|------|------|--------|
| Python 测试 | `tests/` 全量：CLI、服务、编排、JSONL 后端、Web API、文档守卫 | **1545 项通过** |
| 前端 / TUI 测试 | OpenTUI 组件、命令菜单、格式化与协议（bun test） | CI `frontend` 与 `tui` 两个 job |
| 构建与类型 | `bun run typecheck`、Web 前端构建、Windows wheel 构建 | CI `build` job |
| 文档防漂移 | API 文档覆盖全部可见命令、官网产物与生成器逐字一致、README 命令表 = 实现集合 | `tests/test_cli_docs.py`、`tests/test_website_docs.py` |
| 提交包卫生 | 凭据扫描、必检路径、`.gitignore` 覆盖检查 | `scripts/check_submission_hygiene.py` |

> 覆盖率由 pytest-cov 在 CI 输出，本文不写死百分比，避免文档与代码漂移。

### 8.2 测试类型

- **单元测试**：模块级行为与边界，含负样例（例如"危险协议不得进入 href"）；
- **集成测试**：编排层、JSONL 后端协议、Web API、Chat 会话与压缩；
- **守卫测试**：文档 / 命令 / 官网产物 / 提交包的一致性，防止"代码改了、文档没改"；
- **端到端测试**：真实 PR 链路按需手工复跑（不在 CI 里消耗真实模型额度）。

---

## 九、部署与发布

### 9.1 安装方式

> ⚠️ PyPI 上的 `ai-pr-review` 是**同名的其他项目**，请从下面任一 GitHub 方式安装本仓库。

```bash
# GitHub 安装（推荐）
pipx install "git+https://github.com/JiangLai999/AI-PR-Review-Assistant.git"

# 一行命令安装（Linux/macOS）
curl -fsSL https://raw.githubusercontent.com/JiangLai999/AI-PR-Review-Assistant/main/install.sh | sh

# 一行命令安装（Windows PowerShell）
irm https://raw.githubusercontent.com/JiangLai999/AI-PR-Review-Assistant/main/install.ps1 | iex

# 源码安装（开发，含可选 AST 依赖）
git clone https://github.com/JiangLai999/AI-PR-Review-Assistant.git
cd AI-PR-Review-Assistant && pip install -e ".[ast]"
```

### 9.2 CI/CD

- GitHub Actions **五个 job**：`build`（Windows wheel）、`frontend`、`tui`、`test-and-quality`（Python 3.12 / 3.13）；
- 质量检查：black（pin 24.10.0）+ isort + mypy；
- 产物：wheel 由 `build` job 产出；PyPI 发布需先确认包名归属（见 `docs/RELEASE.md`），当前以 GitHub 安装为准；
- 官网：站点仓（AI-PR-Review-Assistant-web）push 到 `main` 后由 GitHub Pages 自动构建部署。

---

*本文档整合了项目所有设计文档，作为项目的完整技术设计参考。*
