# AI PR Review 助手 — 最终开发方案

> 📅 最终确认日期：2026-05-29
> 🤖 协作模型：Claude Code + DeepSeek V4 Pro（四轮深入讨论）
> 📋 讨论轮次：4 轮（架构质疑 → 技术辩论 → 争议解决 → 方案确认）

---

## 一、讨论过程总结

### 第一轮：架构质疑
- DeepSeek 质疑了"单体 + Celery"的矛盾
- 指出 GitHub Webhook 的 10 秒限制
- 建议双模型策略替代单模型
- 批评"diff + 前后 10 行"的上下文不足

### 第二轮：技术辩论
- 讨论了 SQLite WAL 模式的并发能力
- 设计了 Haiku 分类的 Prompt 示例
- 详解了 tree-sitter 的语言支持和 fallback 策略
- 制定了结构化输出的保证机制

### 第三轮：争议解决
- **撤回 Haiku 分类**：MVP 阶段改用规则过滤 + 全量 Sonnet
- **精简 Prompt**：从 2000 tokens 降到 650 tokens（双层结构）
- **完善 tree-sitter**：JS/TS 一流支持，Vue SFC 三段拆分，三级 fallback
- **增加增量 Review**：Diff-of-diff 设计，但建议 MVP 不做

### 第四轮：方案确认
- 确认最终技术栈
- 识别 10 个关键风险点
- 制定开发优先级
- 确定 MVP 不做增量 Review

---

## 二、最终技术决策

| 决策点 | 最终方案 | 讨论过程 |
|--------|----------|----------|
| **架构** | 真单体（FastAPI + BackgroundTasks + SQLite） | 第一轮质疑 Celery 的必要性 |
| **异步** | MVP CLI 同步执行，Phase 2 Web 用 BackgroundTasks | 区分 CLI 和 Web 场景 |
| **模型策略** | MVP 规则过滤 + 全量 Sonnet | 第三轮撤回 Haiku 分类 |
| **上下文** | tree-sitter 提取函数/类，三级 fallback | 第二轮详解 JS/TS/Vue 支持 |
| **Prompt** | 双层结构（基础层 400 tokens + 语言层 250 tokens） | 第三轮精简 65% |
| **成本控制** | 硬上限 $5/run + 滑动窗口 $50/24h | 第二轮设计动态预算 |
| **增量 Review** | MVP 不做，Phase 3 再上 | 第四轮确认复杂度过高 |
| **MVP 范围** | CLI 命令，支持 Python/JS/TS，2-3 周 | 第四轮确认 |

---

## 三、最终技术栈

### 后端
- **Python 3.12**：异步原生支持
- **FastAPI**：API 框架（Phase 2 使用）
- **SQLite WAL**：MVP 阶段数据库
- **Anthropic SDK**：Claude API 调用
- **PyGithub**：GitHub REST API
- **tree-sitter**：AST 代码解析

### 前端（Phase 2）
- **React 18 + TypeScript**
- **Monaco Editor**：Diff 渲染
- **shadcn/ui**：组件库

### 开发工具
- **click**：CLI 框架
- **Rich**：终端美化输出
- **Pydantic**：数据校验

---

## 四、最终架构图（MVP 版本）

```
┌─────────────────────────────────────────────────────────────────────┐
│                        MVP Phase 1: CLI 单体                         │
│                                                                     │
│  $ pr-review https://github.com/owner/repo/pull/123                 │
│       │                                                             │
│       ▼                                                             │
│  ┌──────────────────────────────────────────────┐                   │
│  │              CLI Entry (click)                │                   │
│  │   - 解析 GitHub PR URL                        │                   │
│  │   - 配置参数 (model, skip-pattern, max-cost)  │                   │
│  └──────────────────────┬───────────────────────┘                   │
│                         │                                           │
│                         ▼                                           │
│  ┌──────────────────────────────────────────────┐                   │
│  │             PR Fetcher (PyGithub)             │                   │
│  │  - REST: PR metadata, diff, file list        │                   │
│  │  - Token Bucket rate limit (5000/hr)         │                   │
│  │  - Shallow clone 获取完整文件内容              │                   │
│  └──────────────────────┬───────────────────────┘                   │
│                         │                                           │
│                         ▼                                           │
│  ┌──────────────────────────────────────────────┐                   │
│  │          Filter Pipeline (规则过滤)           │                   │
│  │  - Skip: test_*.py, *.test.ts, *.spec.ts     │                   │
│  │  - Skip: docs/, *.md, *.json, *.lock         │                   │
│  │  - Skip: 删除文件, 纯格式化变更               │                   │
│  │  - Skip: 变更行数 > 500 的文件 (标记跳过)     │                   │
│  └──────────────────────┬───────────────────────┘                   │
│                         │                                           │
│                         ▼                                           │
│  ┌──────────────────────────────────────────────┐                   │
│  │        Context Builder (双层上下文)           │                   │
│  │  Layer 1: diff hunks + 前后10行              │                   │
│  │  Layer 2: tree-sitter 提取 imports/types     │                   │
│  │  Chunk: 按文件/函数边界切分, ≤15K tokens/chunk │                  │
│  └──────────────────────┬───────────────────────┘                   │
│                         │                                           │
│                         ▼                                           │
│  ┌──────────────────────────────────────────────┐                   │
│  │         Prompt Assembler (双层结构)           │                   │
│  │  Base (400t): 角色、输出格式、通用规则        │                   │
│  │  Lang (250t): 语言特定检查维度                │                   │
│  │  Output JSON Schema 强制约束                  │                   │
│  └──────────────────────┬───────────────────────┘                   │
│                         │                                           │
│                         ▼                                           │
│  ┌──────────────────────────────────────────────┐                   │
│  │           AI Client (Anthropic SDK)           │                   │
│  │  - Model: claude-sonnet-4-20250514           │                   │
│  │  - max_tokens: 4096                          │                   │
│  │  - 重试: 3次指数退避 (1s/2s/4s)              │                   │
│  │  - 超时: 120s                                │                   │
│  └──────────────────────┬───────────────────────┘                   │
│                         │                                           │
│                         ▼                                           │
│  ┌──────────────────────────────────────────────┐                   │
│  │          Post-Processor (后处理)              │                   │
│  │  - JSON Schema 校验                           │                   │
│  │  - 置信度 < 0.6 自动丢弃                     │                   │
│  │  - 同文件同模式去重                           │                   │
│  └──────────────────────┬───────────────────────┘                   │
│                         │                                           │
│                         ▼                                           │
│  ┌──────────────────────────────────────────────┐                   │
│  │            Result Store (SQLite WAL)          │                   │
│  │  - 存储 ReviewResult (JSON)                   │                   │
│  │  - run_history 表                             │                   │
│  └──────────────────────┬───────────────────────┘                   │
│                         │                                           │
│                         ▼                                           │
│  ┌──────────────────────────────────────────────┐                   │
│  │          Report Renderer (终端输出)            │                   │
│  │  - Rich 库美化终端输出                        │                   │
│  │  - Markdown 报告导出                         │                   │
│  │  - 可选: 一键发布为 GitHub PR Comment         │                   │
│  └──────────────────────────────────────────────┘                   │
│                                                                     │
│  ┌──────────────────────────────────────────────┐                   │
│  │            Cost Controller (成本控制)          │                   │
│  │  - 全局硬上限: $5/run                         │                   │
│  │  - 滑动窗口: 24h 累计 ≤ $50                   │                   │
│  │  - 实时 token 计数器, 接近上限提前终止         │                   │
│  └──────────────────────────────────────────────┘                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 五、核心模块设计

### 5.1 PR Fetcher 模块

```python
# services/pr_fetcher.py

class PRFetcher:
    def __init__(self, github_token: str):
        self.github = Github(github_token)
        self.rate_limiter = TokenBucket(rate=5000/3600)  # 5000/hr
    
    async def fetch_pr(self, pr_url: str) -> PRData:
        """获取 PR 的完整数据"""
        owner, repo, pr_number = self.parse_url(pr_url)
        
        # 获取 PR 元数据
        pr = self.github.get_repo(f"{owner}/{repo}").get_pull(pr_number)
        
        # 获取 diff
        diff = await self.fetch_diff(pr)
        
        # 获取文件列表和内容
        files = await self.fetch_files(pr)
        
        return PRData(
            pr=pr,
            diff=diff,
            files=files,
            head_sha=pr.head.sha,
            base_sha=pr.base.sha
        )
```

### 5.2 Filter Pipeline 模块

```python
# services/filter.py

SKIP_PATTERNS = [
    r"**/test/**", r"**/__test__/**", r"**/*.test.*", r"**/*.spec.*",
    r"docs/**", r"**/*.md", r"**/*.rst",
    r"**/.github/**",
    r"**/CHANGELOG*", r"**/LICENSE*",
    r"**/*.json", r"**/*.lock", r"**/*.yml", r"**/*.yaml",
]

def should_skip_file(file_path: str, diff_stats: dict) -> bool:
    """判断是否跳过该文件"""
    # 1. 匹配跳过模式
    if any(fnmatch(file_path, pattern) for pattern in SKIP_PATTERNS):
        return True
    
    # 2. 纯删除文件
    if diff_stats.get("deletions", 0) > 0 and diff_stats.get("additions", 0) == 0:
        return True
    
    # 3. 变更行数过多（可能是生成文件）
    if diff_stats.get("changes", 0) > 500:
        return True
    
    return False
```

### 5.3 Context Builder 模块

```python
# services/context_builder.py

class ContextBuilder:
    def __init__(self):
        self.parsers = {
            "python": tree_sitter_python,
            "javascript": tree_sitter_javascript,
            "typescript": tree_sitter_typescript,
        }
    
    async def build_context(self, file_path: str, diff: str) -> FileContext:
        """构建文件上下文"""
        language = self.detect_language(file_path)
        
        # Layer 1: diff + 前后 10 行
        diff_context = self.extract_diff_context(diff, context_lines=10)
        
        # Layer 2: tree-sitter AST 提取
        ast_context = await self.extract_ast_context(file_path, language)
        
        return FileContext(
            file_path=file_path,
            language=language,
            diff=diff_context,
            imports=ast_context.get("imports", []),
            functions=ast_context.get("functions", []),
            classes=ast_context.get("classes", [])
        )
    
    async def extract_ast_context(self, file_path: str, language: str) -> dict:
        """tree-sitter 提取 AST 上下文（三级 fallback）"""
        try:
            # Level 1: tree-sitter
            return await self.tree_sitter_extract(file_path, language)
        except Exception:
            try:
                # Level 2: regex fallback
                return await self.regex_extract(file_path, language)
            except Exception:
                # Level 3: 仅返回 diff context
                return {"parse_failed": True}
```

### 5.4 Prompt Assembler 模块

```python
# prompts/assembler.py

BASE_SYSTEM_PROMPT = """You are a code reviewer. Output findings in the specified JSON format ONLY.
No preamble, no markdown fences, no commentary outside the JSON.

PRINCIPLES:
1. Flag bugs, security issues, and logic errors. IGNORE style, formatting, 
   and naming unless they cause functional defects.
2. Each finding must reference a specific line from the diff.
3. If a finding can be detected by ESLint/Pylint/Rubocop/etc, downgrade 
   confidence to ≤0.5 or omit it.
4. Confidence reflects certainty: 0.9+ = certain bug, 0.7–0.9 = likely 
   issue, 0.5–0.7 = worth mentioning, <0.5 = do not report.

OUTPUT FORMAT:
{"findings":[{"severity":"high|medium|low","category":"security|logic|
  performance|error_handling|data_integrity","line_range":[start,end],
  "title":"...","description":"...","suggestion":"...","confidence":0.0}]}"""

LANGUAGE_INJECTIONS = {
    "python": """PYTHON SPECIFIC CHECKS:
- bare except without raise → error_handling
- mutable default arg (def f(x=[])) → logic
- async without await → logic
- f-string with user input in SQL → security
- file handle not in context manager → error_handling
- eval/exec on user input → security""",
    
    "typescript": """TS/JS SPECIFIC CHECKS:
- null/undefined access without guard → error_handling
- any type bypassing type safety → logic
- missing await on Promise → logic
- prototype pollution (Object.assign on user input) → security
- XSS via innerHTML/dangerouslySetInnerHTML → security""",
}

def build_system_prompt(language: str) -> str:
    base = BASE_SYSTEM_PROMPT
    injection = LANGUAGE_INJECTIONS.get(language, "")
    if injection:
        return base + "\n\n" + injection
    return base
```

### 5.5 AI Client 模块

```python
# services/ai_client.py

class AIClient:
    def __init__(self, api_key: str):
        self.client = Anthropic(api_key=api_key)
        self.model = "claude-sonnet-4-20250514"
        self.max_tokens = 4096
    
    async def review_code(self, system_prompt: str, user_prompt: str) -> ReviewResult:
        """调用 Claude API 进行代码审查"""
        for attempt in range(3):  # 3 次重试
            try:
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                    timeout=120
                )
                
                # 解析 JSON 响应
                result = self.parse_response(response.content[0].text)
                
                # Pydantic 校验
                return ReviewResult.model_validate(result)
                
            except Exception as e:
                if attempt == 2:  # 最后一次尝试
                    raise
                await asyncio.sleep(2 ** attempt)  # 指数退避
```

### 5.6 Post-Processor 模块

```python
# services/post_processor.py

class PostProcessor:
    def process(self, findings: list[Finding]) -> list[Finding]:
        """后处理 findings"""
        # 1. 置信度过滤
        findings = [f for f in findings if f.confidence >= 0.6]
        
        # 2. 同文件同模式去重
        findings = self.deduplicate(findings)
        
        # 3. 按严重程度排序
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        findings.sort(key=lambda f: severity_order.get(f.severity, 5))
        
        return findings
    
    def deduplicate(self, findings: list[Finding]) -> list[Finding]:
        """去重：同文件 + 同类别 + 相近行号"""
        seen = set()
        unique = []
        
        for finding in findings:
            key = (finding.file, finding.category, finding.line_range[0] // 10)
            if key not in seen:
                seen.add(key)
                unique.append(finding)
        
        return unique
```

---

## 六、关键风险与应对策略

### 🔴 高风险

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| **BackgroundTasks 不持久化** | 服务重启丢失任务 | MVP CLI 同步执行，Phase 2 用 Redis + RQ |
| **单模型无降级** | API 故障全军覆没 | 3 次指数退避重试 + 超时优雅报错 |
| **GitHub API Rate Limit** | 频繁抓文件触发限流 | Token Bucket 限速 (5000/hr) |

### 🟡 中风险

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| **tree-sitter 编译问题** | Windows 环境编译失败 | pin 版本 0.21.x，CI 验证跨平台 |
| **Diff-of-diff 复杂度高** | 实现困难 | MVP 不做，Phase 3 再上 |
| **Prompt 650 tokens 偏紧** | 输出质量差 | 预留扩展到 1000 tokens |
| **单文件超大 diff** | 函数 2000 行无法处理 | 行数硬上限 500 行二次切分 |

### 🟢 低风险

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| **SQLite 多写并发** | "database is locked" | MVP CLI 单线程，Phase 2 换 PostgreSQL |
| **缺少质量基准** | 无法度量效果 | 准备 10 个已知问题 PR 作为回归用例 |
| **Windows 路径兼容性** | Git 命令执行失败 | 统一使用 pathlib，测试 Windows 环境 |

---

## 七、开发计划（修订版）

### Phase 1 MVP（2-3 周）

**目标**：跑通 "URL 输入 → Review 输出" 全链路

| 优先级 | 任务 | 预估 | 产出 |
|--------|------|------|------|
| **P0** | 项目骨架搭建 | 0.5d | 可运行的空壳 |
| **P0** | GitHub PR Fetcher | 1d | 核心数据入口 |
| **P0** | Anthropic Client 封装 | 0.5d | API 通信层 |
| **P0** | Prompt 模板 + JSON Schema | 0.5d | Prompt 工程 |
| **P0** | 规则过滤器 | 0.5d | 成本控制第一关 |
| **P1** | tree-sitter Context Builder | 1d | 上下文增强 |
| **P1** | Chunk Splitter | 1d | 大 PR 分块 |
| **P1** | Post-Processor | 0.5d | 输出质量控制 |
| **P1** | CLI 入口 + Rich 终端输出 | 0.5d | 用户界面 |
| **P1** | SQLite 存储层 | 0.5d | 持久化 |
| **P2** | Cost Controller | 0.5d | 成本兜底 |
| **P2** | Markdown 报告导出 | 0.5d | 离线查看 |
| **P2** | GitHub PR Comment 发布 | 0.5d | 集成输出 |
| **P2** | 手动回归测试集 | 1d | 质量度量 |

**关键路径**：
```
骨架 → Fetcher → AI Client → Prompt → Filter
                                    ↓
                        Context Builder → Chunk Splitter
                                               ↓
                              Post-Processor → CLI 入口 → 可用！
```

**第一周目标**：
- Day 1-2: 骨架 + Fetcher（能拉到 diff 并打印）
- Day 3-4: AI Client + Prompt（能发请求拿到结构化 JSON）
- Day 5: Filter + 端到端跑通一个简单 PR

### Phase 2 Web 应用（3-4 周）

**目标**：可用的 Web 工具，支持团队使用

```
交付物：
├── FastAPI 后端 (Auth, Job Queue, Result API)
├── React 前端 (提交页面 + 结果展示)
├── WebSocket/SSE 实时进度推送
├── 文件级分块并行分析
├── PostgreSQL 结果持久化
├── 结构化输出 (JSON Schema 约束)
└── GitHub OAuth 登录
```

### Phase 3 智能增强（3-4 周）

**目标**：提升分析质量，控制误报

```
交付物：
├── Multi-pass Analysis Pipeline
├── 多模型路由 (Haiku 初筛 → Sonnet 深析)
├── tree-sitter 完整 AST 上下文
├── 置信度评分 + 自动过滤低置信度
├── 反馈收集机制
├── Custom Rules 配置
├── GitHub Check Runs 集成
└── 增量 Review (Diff-of-diff)
```

### Phase 4 生态集成（2-3 周）

**目标**：融入开发流程，扩大覆盖

```
交付物：
├── GitHub App (Webhook 自动触发)
├── CI/CD 插件 (GitHub Actions Action)
├── Slack/Discord Bot 通知
├── 团队统计面板
├── VS Code 扩展
└── 多仓库/组织级管理
```

---

## 八、目录结构设计

```
ai-pr-review/
├── pyproject.toml                 # 项目配置
├── README.md
├── DEVELOPMENT_PLAN.md
│
├── src/
│   └── ai_pr_review/
│       ├── __init__.py
│       ├── cli.py                 # CLI 入口 (click)
│       ├── config.py              # 配置管理
│       │
│       ├── services/
│       │   ├── __init__.py
│       │   ├── pr_fetcher.py      # PR 数据获取
│       │   ├── context_builder.py # 上下文构建
│       │   ├── filter.py          # 规则过滤
│       │   ├── prompt_assembler.py # Prompt 组装
│       │   ├── ai_client.py       # AI API 调用
│       │   ├── post_processor.py  # 后处理
│       │   ├── cost_controller.py # 成本控制
│       │   └── report_renderer.py # 报告渲染
│       │
│       ├── models/
│       │   ├── __init__.py
│       │   ├── pr_data.py         # PR 数据模型
│       │   ├── review_result.py   # Review 结果模型
│       │   └── finding.py         # Finding 模型
│       │
│       ├── prompts/
│       │   ├── __init__.py
│       │   ├── base.py            # 基础 Prompt
│       │   └── languages/
│       │       ├── python.py      # Python 特定检查
│       │       ├── typescript.py  # TypeScript 特定检查
│       │       └── javascript.py  # JavaScript 特定检查
│       │
│       └── utils/
│           ├── __init__.py
│           ├── github_url_parser.py # GitHub URL 解析
│           ├── token_counter.py     # Token 计数
│           └── tree_sitter_utils.py # tree-sitter 工具
│
├── tests/
│   ├── __init__.py
│   ├── test_pr_fetcher.py
│   ├── test_context_builder.py
│   ├── test_filter.py
│   └── fixtures/                  # 测试数据
│       └── sample_prs/
│
├── data/
│   └── regression/                # 回归测试用例
│       └── known_issues/
│
└── docs/
    ├── ARCHITECTURE.md
    ├── API.md
    └── CONTRIBUTING.md
```

---

## 九、质量评估指标

### 核心指标

| 指标 | MVP 目标 | 成熟期目标 | 计算方式 |
|------|---------|-----------|----------|
| **Precision（精确率）** | ≥ 50% | ≥ 80% | TP / (TP + FP) |
| **Recall（召回率）** | ≥ 60% | ≥ 90% | TP / (TP + FN) |
| **Critical 漏报率** | ≤ 5% | ≤ 1% | FN_critical / Total_critical |
| **反馈接受率** | ≥ 40% | ≥ 70% | accepted / total_findings |
| **单 PR 平均成本** | < $1.50 | < $0.50 | 总成本 / PR 数量 |
| **平均 Review 耗时** | < 90s | < 30s | 从提交到结果返回 |

### 评估方法

1. **反馈转化率**（Phase 3）
   - 用户 accept/reject 每个 finding
   - 直接产出 TP/FP 数据

2. **黄金集评估**
   - 选 20 个历史 PR（已知 43 个确认 Bug）
   - 跑系统对比 Precision/Recall

3. **A/B 对比**
   - A 组：纯人工 Review
   - B 组：AI 辅助 Review
   - 对比增量价值和效率提升

---

## 十、未来扩展方向

| 方向 | 描述 | 优先级 | 阶段 |
|------|------|--------|------|
| **Fine-tune 专用模型** | 用历史 Review 数据微调开源模型 | 中 | Phase 4+ |
| **Repository 全量索引** | pgvector 向量检索，跨文件语义搜索 | 高 | Phase 3 |
| **自动化修复** | 发现问题后自动生成 PR 修复建议 | 低 | Phase 4+ |
| **多平台支持** | 扩展 GitLab、Bitbucket、Gitee | 中 | Phase 4 |
| **安全专用引擎** | 集成 Semgrep/CodeQL | 中 | Phase 3 |
| **Review 质量度量** | 统计 Bug 修复转化率，量化 ROI | 低 | Phase 4 |
| **知识库积累** | 团队编码规范自动纳入 Prompt | 中 | Phase 3 |

---

## 十一、总结

### 核心设计理念

> **"用工程手段弥补 LLM 的不确定性"** — 每一步都有确定性的校验和兜底策略，而不是盲目信任模型输出。

### 架构亮点

1. **真单体架构**：FastAPI + BackgroundTasks + SQLite，最小化运维复杂度
2. **规则过滤 + 全量 Sonnet**：MVP 阶段保证质量，避免 Haiku 漏判风险
3. **双层 Prompt 结构**：650 tokens 精简指令，平衡成本和效果
4. **tree-sitter 上下文增强**：AST 提取函数/类，三级 fallback 保证鲁棒性
5. **三级成本控制**：硬上限 + 滑动窗口 + 文件级路由

### 讨论价值

通过四轮深入讨论，我们：
- ✅ 撤回了 Haiku 分类（避免漏判风险）
- ✅ 精简了 Prompt（从 2000 tokens 降到 650 tokens）
- ✅ 完善了 tree-sitter 设计（JS/TS 一流支持，三级 fallback）
- ✅ 增加了增量 Review 设计（但 MVP 不做）
- ✅ 识别了 10 个关键风险点并制定应对策略

---

**下一步行动**：搭建项目骨架，开始 Phase 1 MVP 开发。

---

*本方案由 Claude Code 与 DeepSeek V4 Pro 经过四轮深入讨论协作完成*
