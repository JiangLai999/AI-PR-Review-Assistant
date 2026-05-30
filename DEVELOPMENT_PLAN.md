# AI PR Review 助手 — 开发方案与实行大纲 (v2.0)

> 📅 创建日期：2026-05-29
> 📅 最后更新：2026-05-29（第四轮整合）
> 🤖 协作模型：Claude Code + DeepSeek V4 Pro

---

## 一、项目概述

### 1.1 项目目标
开发一个 AI 代码评审工具，帮助开发者提升 Pull Request 的 Review 效率与质量。

### 1.2 核心功能
- ✅ PR 变更总结
- ✅ 风险代码识别
- ✅ Review 建议生成
- ✅ 支持 GitHub PR 自动分析

### 1.3 设计原则
- **准确性优先**：控制误报与漏报
- **上下文感知**：理解代码语义，不只是语法
- **渐进交付**：流式推送结果，优化用户体验
- **成本可控**：多模型策略，按需调用

---

## 二、技术架构设计（第四轮确认）

### 2.1 最终架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                         用户入口                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐   │
│  │  CLI (MVP)   │  │  Web UI      │  │  GitHub Check Runs       │   │
│  │  pr-review    │  │  React+TS    │  │  (Phase 3+)              │   │
│  │  <pr-url>     │  │  Monaco      │  │                          │   │
│  └──────┬───────┘  └──────┬───────┘  └───────────┬──────────────┘   │
└─────────┼─────────────────┼──────────────────────┼──────────────────┘
          └─────────────────┼──────────────────────┘
                            │
              ┌─────────────▼──────────────┐
              │     FastAPI (Sync+Async)    │
              │  • POST /review → Background│
              │    Tasks → run_review()     │
              │  • GET /review/{id} →       │
              │    status + SSE progress    │
              └─────────────┬──────────────┘
                            │
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                  ▼
┌─────────────────┐ ┌──────────────┐ ┌─────────────────┐
│  PR Fetcher     │ │ Review Engine│ │  SQLite (WAL)   │
│  • PyGithub     │ │              │ │  • review_jobs  │
│  • gidgethub    │ │ ┌──────────┐ │ │  • findings     │
│  • RateLimit    │ │ │ Context  │ │ │  • feedback     │
│    Manager      │ │ │ Builder  │ │ └─────────────────┘
└────────┬────────┘ │ └────┬─────┘ │
         │          │      │       │
         │          │ ┌────▼─────┐ │
         └──────────┼▶│ Prompt   │ │
                    │ │ Orch.    │ │
                    │ │ • 基础层 │ │
                    │ │   400t   │ │
                    │ │ • 语言层 │ │
                    │ │   250t   │ │
                    │ └────┬─────┘ │
                    │      │       │
                    │ ┌────▼─────┐ │
                    │ │ LLM Call │ │
                    │ │ • MVP:   │ │
                    │ │   规则过 │ │
                    │ │   滤+    │ │
                    │ │   Sonnet │ │
                    │ │ • Phase3:│ │
                    │ │   Haiku→ │ │
                    │ │   Sonnet │ │
                    │ └────┬─────┘ │
                    │      │       │
                    │ ┌────▼──────┐│
                    │ │Post-      ││
                    │ │Processor  ││
                    │ │•去重/过滤 ││
                    │ │•置信度评分││
                    │ └───────────┘│
                    └──────────────┘
```

### 2.2 上下文构建细节

```
┌─────────────────────────────────────┐
│ tree-sitter AST → 函数/类边界       │
│                 → 依赖导入           │
├─────────────────────────────────────┤
│ Layer 1: diff ±20行（直接变更）     │
│ Layer 2: 函数/类完整上下文          │
│ Layer 3: 文件级 import/signature    │
│ Fallback: Layer 1→2→3 逐级降级，    │
│           token 不足时裁切 Layer 3   │
└─────────────────────────────────────┘
```

### 2.3 成本控制策略

```
硬上限    : 单 PR ≤ $X（可配置）
滑动窗口  : 最近 N 次消费均值超阈报警
文件级路由 : 小文件全量 Sonnet，大文件按 chunk 拆分
降级策略  : 超预算时 Layer 3→2→1 逐级降级上下文
```

### 2.4 增量 Review 策略

```
Push compare: 比较 HEAD vs base 的完整 diff
Diff-of-diff: 本次 diff vs 上次已 Review 的 diff
自动选择   : 变更比例 >50% → 全量 Review，否则增量 Review
```

### 2.5 架构决策记录（ADR）

| 决策 | 选型 | 替代方案（已否决） | 理由 |
|------|------|--------------------|------|
| 架构 | 真单体 | 微服务 / Celery 解耦 | MVP 复杂度可控，BackgroundTasks 满足异步需求 |
| 异步 | FastAPI BackgroundTasks | Celery + Redis | 无需额外中间件，部署简单 |
| 数据库 | SQLite (WAL) | PostgreSQL | 单进程读写，WAL 模式并发读足够 |
| 模型策略 | 规则过滤 + 全量 Sonnet（MVP）→ Haiku+Sonnet 级联（Phase 3） | 多模型并行 | MVP 先做对再做省，Phase 3 降本 |
| 上下文提取 | tree-sitter AST | 正则 / 简单截断 | 精确识别函数/类边界，按语义单元切分 |
| Prompt 结构 | 双层（基础 400t + 语言 250t） | 单层长 Prompt | 模块化复用，按语言精准适配 |
| 增量 Review | Diff-of-diff + 自动选择 | 仅全量 / 仅增量 | 平衡效率与准确性 |
| Token 估算 | tiktoken（Python）/ 语言对应 tokenizer | 字符/行估算 | 精确控制预算，避免超支 |

---

## 三、核心功能模块

### 3.1 PR 数据获取模块 (`pr_fetcher`)

| 子模块 | 职责 |
|--------|------|
| GitHub Client | REST API（PR 元数据、diff、文件列表）+ GraphQL API（批量查文件内容） |
| RateLimit 管理 | Token Bucket 算法，自适应调整请求速率 |
| Clone Manager | 按需 `shallow clone` 仓库，获取完整代码上下文 |
| Webhook 监听器 | 监听 PR open/synchronize 事件，自动触发 Review |

### 3.2 上下文构建模块 (`context_builder`)

**三层上下文窗口设计**：

```
Layer 1: 直接变更（diff hunks + 前后 20 行）
Layer 2: 函数/类完整上下文（tree-sitter 提取的完整函数体/类定义）
Layer 3: 文件级上下文（imports, type defs, class signatures）
```

Fallback 机制：token 预算不足时从 Layer 3 开始逐级裁切。

**处理流程**：
1. Diff Parser → 解析 diff 为结构化数据
2. tree-sitter Extractor → 提取函数/类边界、imports、类型定义
3. Chunk Splitter → 按函数/类边界切分（优先保留完整语义单元）
4. Prompt Assembler → 拼接双层 Prompt（基础层 + 语言层）

### 3.3 AI 分析引擎 (`review_engine`)

**MVP 阶段 — 规则过滤 + 全量 Sonnet**：

```
规则过滤 (tree-sitter AST)
       │
       ▼
┌─────────────────────┐
│ 高风险代码段识别     │  ← tree-sitter 匹配 pattern
│ (SQL注入/空指针等)   │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ 全量 Sonnet 分析     │  ← 全部变更发给 Sonnet 深度分析
│ (双层 Prompt)        │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Post-Processor       │  ← 去重、置信度过滤、分级
└─────────────────────┘
```

**Phase 3 增强 — 多 Pass 流水线**：

```
Pass 1: 变更摘要  ──→  Haiku 快速生成每文件摘要
Pass 2: 风险初筛  ──→  Haiku 安全漏洞、空指针、资源泄漏 pattern
Pass 3: 深度分析  ──→  Sonnet 仅对 Pass 2 标记的高风险代码
Pass 4: 建议生成  ──→  Sonnet 针对确认风险生成修改建议
Pass 5: 去重聚合  ──→  跨文件合并相同风险，去除低置信度项
```

**结构化输出格式**：
```json
{
  "file": "src/auth/login.ts",
  "findings": [
    {
      "id": "risk-001",
      "severity": "high|medium|low|info",
      "category": "security|performance|logic|style|coverage",
      "line_range": [45, 52],
      "title": "Potential SQL injection in raw query",
      "description": "User input is directly concatenated...",
      "suggestion": "Use parameterized query instead...",
      "confidence": 0.92,
      "pass_source": "pass_3"
    }
  ]
}
```

### 3.4 结果展示模块 (`dashboard`)

- **Diff 视图**：Monaco Editor 渲染 diff，侧栏标注 Review 发现
- **摘要面板**：PR 概览（变更文件数、风险统计、整体评分）
- **历史管理**：团队维度的 Review 历史、趋势、高频问题统计
- **集成输出**：支持 GitHub PR Comment、Check Runs API、Slack 通知

### 3.5 反馈闭环模块 (`feedback_loop`)

```
User accepts/rejects finding → 存储反馈 → 评估 Prompt 质量
                                              │
                                              ▼
                                    自动生成 few-shot 示例
                                    纳入后续 Review 上下文
```

---

## 四、技术栈选择

### 4.1 最终技术栈

| 层级 | 技术选型 | 理由 |
|------|----------|------|
| **后端框架** | Python 3.12 + FastAPI | 异步原生支持、AI 生态完善、类型安全 |
| **异步机制** | FastAPI BackgroundTasks | MVP 无需额外中间件，部署简单 |
| **数据库** | SQLite (WAL 模式) | 单进程读写足够，零运维，WAL 支持高并发读 |
| **LLM 编排** | 自定义轻量 Prompt Manager | 避免 LangChain 黑盒，保持可控 |
| **代码解析** | tree-sitter (Python binding) | 多语言 AST 提取函数/类边界 |
| **Token 计算** | tiktoken (Python) / 语言对应 tokenizer | 精确控制 Prompt 预算 |
| **GitHub API** | PyGithub + gidgethub (async) | REST + GraphQL 双通道 |
| **前端** | React 18 + TypeScript + shadcn/ui | 组件可控、AI 友好 |
| **Diff 渲染** | Monaco Editor (只读模式) | VS Code 同款编辑器 |
| **CI 集成** | GitHub App + Check Runs API | 原生嵌入 PR 流程 |

### 4.2 模型选择策略

| 阶段 | 使用场景 | 模型 | 选择理由 |
|------|----------|------|----------|
| MVP | 全部 Review | Claude Sonnet | 代码理解最强，200K 上下文窗口 |
| Phase 3 | 初筛 (Pass1/2) | Claude Haiku | ~$0.25/1M tokens, 极快 |
| Phase 3 | 深度分析 (Pass3/4) | Claude Sonnet | 代码理解最强 |
| 可选 | 隐私部署 | DeepSeek-Coder-V2 / Qwen2.5-Coder | 开源可私有化 |

---

## 五、开发阶段划分

### Phase 1: MVP — CLI 原型（3-4 周）

**目标**：跑通 "URL 输入 → Review 输出" 全链路

```
交付物：
├── CLI 命令: pr-review <github-pr-url>
├── PR Fetcher (GitHub API 基础集成)
├── tree-sitter 集成（Python/JS/TS）
├── Context Builder（双层 Prompt + 三级 Fallback）
├── Sonnet API 调用 + 双层 Prompt
├── 输出：文本报告 + JSON 结构化数据
└── 单元测试 + 集成测试
```

**优先级**：🔴 最高

### Phase 2: Web 应用 + 异步化（3-4 周）

**目标**：可用的 Web 工具，支持团队使用

```
交付物：
├── FastAPI 后端 (Auth, BackgroundTasks, Result API)
├── React 前端 (提交页面 + 结果展示)
├── SSE 实时进度推送
├── 文件级分块分析
├── SQLite 结果持久化
├── 结构化输出 (JSON Schema 约束)
└── GitHub OAuth 登录
```

**优先级**：🔴 高

### Phase 3: 智能增强（3-4 周）

**目标**：提升分析质量，控制成本与误报

```
交付物：
├── Multi-pass Analysis Pipeline (Haiku→Sonnet)
├── 多模型路由
├── tree-sitter AST 上下文增强（Layer 2/3）
├── 置信度评分 + 自动过滤低置信度
├── 反馈收集机制
├── Custom Rules 配置 (用户自定义检查规则)
├── 成本控制（硬上限 + 滑动窗口 + 文件级路由）
├── 增量 Review (Diff-of-diff)
└── GitHub Check Runs 集成
```

**优先级**：🟡 中

### Phase 4: 生态集成（2-3 周）

**目标**：融入开发流程，扩大覆盖

```
交付物：
├── GitHub App (Webhook 自动触发)
├── CI/CD 插件 (GitHub Actions Action)
├── Slack/Discord Bot 通知
├── 团队统计面板 (Review 趋势、高频问题)
├── VS Code 扩展 (本地 Review 能力)
└── 多仓库/组织级管理
```

**优先级**：🟢 低

---

## 六、关键技术难点与解决方案

### 6.1 超大 PR 的上下文窗口管理

**问题**：一个 PR 可能包含 50+ 文件、5000+ 行变更，远超模型上下文限制。

**解决方案 — tree-sitter 按函数边界分块**：

```
                    PR Diff (100 files)
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
    ┌──────────┐    ┌──────────┐    ┌──────────┐
    │ Batch 1  │    │ Batch 2  │    │ Batch N  │  ← tree-sitter 识别
    │ ≤5 files │    │ ≤5 files │    │ ≤5 files │     函数/类边界切分
    │ ≤15K t   │    │ ≤15K t   │    │ ≤15K t   │
    └────┬─────┘    └────┬─────┘    └────┬─────┘
         │               │               │
         ▼               ▼               ▼
    [分析每批]       [分析每批]       [分析每批]     ← Map 阶段 (BackgroundTasks 并发)
         │               │               │
         └───────────────┼───────────────┘
                         │
                         ▼
                  ┌──────────────┐
                  │ Batch 摘要合并 │
                  │ 去重 + 聚合    │               ← Reduce 阶段
                  └──────────────┘
```

**实施细节**：
- 用 tree-sitter 识别函数/类边界，以函数为单位切分
- 每批分配双层 Prompt 结构：基础层 400t + 语言层 250t + 代码
- 超长单文件按函数粒度递归处理
- 三级 Fallback: Layer 1→2→3 逐级降级

### 6.2 误报控制

**问题**：LLM 倾向于 "宁可错杀" 式输出，导致大量无意义告警。

**解决方案 — 三级过滤体系**：

```
原始 LLM 输出
      │
      ▼
┌─────────────────┐
│ Layer 1: Schema │  结构化输出格式 + JSON Schema 校验
│ Validation      │  不合格 → 重试 (max 2 次)
└────────┬────────┘
         ▼
┌─────────────────┐
│ Layer 2: Self-  │  模型自检："请重新审查以下发现，标记
│ Critique Pass   │  哪些是误报/低价值告警"
│                 │  使用独立模型实例避免确认偏误
└────────┬────────┘
         ▼
┌─────────────────┐
│ Layer 3: Rule-  │  基于规则的后处理：
│ based Filter    │  - 置信度 < 0.7 且 severity=low → 丢弃
│                 │  - 相同文件+相同模式 → 去重
│                 │  - Linter 能检测的问题 → 降权
│                 │  - 仅风格差异(无功能影响) → 标记为 info
└────────┬────────┘
         ▼
    最终 Review 结果
```

### 6.3 跨文件逻辑理解

**问题**：代码变更可能影响其他文件（函数签名变更导致调用方报错等）。

**解决方案**：
1. **静态分析 pass**：tree-sitter 解析 AST → 提取依赖图 → 查找引用文件
2. **演进方向**：仓库级向量索引，自动 retrieve 语义相关的 top-k 代码段

### 6.4 响应速度优化

**问题**：完整 Review 链路可能耗时 30s~3min。

**解决方案 — 渐进式交付**：

```
T+0s   用户提交 PR URL
T+1s   → 立即返回 job_id + SSE 连接
T+3s   → 推送进度: "正在获取 PR 数据..."
T+5s   → 推送进度: "发现 12 个变更文件"
T+8s   → 推送进度: "正在分析 src/auth/login.ts (1/12)"
T+10s  → 推送: login.ts 的基础分析 (流式)
T+12s  → 推送: login.ts 的发现 (流式)
...
T+45s  → 全部分析完成，推送最终聚合报告
```

### 6.5 不同语言的 Review 策略适配

**问题**：Python、TypeScript、Go、Rust 等语言的 Review 侧重点完全不同。

**解决方案 — 双层 Prompt 结构**：

- **基础层 (400 tokens)**：通用 Review 规则，所有语言共享
- **语言层 (250 tokens)**：按语言定制，Python 侧重类型安全/异常处理/async 正确性，JS/TS 侧重空值检查/类型利用/副作用管理等

```json
{
  "language": "python",
  "base_prompt": "通用 Review 规则 (400 tokens)",
  "lang_prompt": "Python 特定规则: type_safety, exception_handling, async_correctness, resource_management (250 tokens)",
  "tree_sitter_queries": { ... }
}
```

---

## 七、目录结构设计

```
ai-pr-review/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── routes/
│   │   │   │   ├── review.py        # Review 相关路由
│   │   │   │   ├── auth.py          # 认证路由
│   │   │   │   └── webhook.py       # GitHub Webhook
│   │   │   └── deps.py              # 依赖注入
│   │   ├── core/
│   │   │   ├── config.py            # 配置管理
│   │   │   ├── security.py          # JWT、加密
│   │   │   └── exceptions.py        # 自定义异常
│   │   ├── services/
│   │   │   ├── pr_fetcher.py        # PR 数据获取
│   │   │   ├── context_builder.py   # 上下文构建 + tree-sitter
│   │   │   ├── review_engine.py     # Review 引擎
│   │   │   ├── llm_client.py        # LLM API 调用
│   │   │   └── github_client.py     # GitHub API 客户端
│   │   ├── models/
│   │   │   ├── review.py            # Review 数据模型
│   │   │   └── feedback.py          # 反馈模型
│   │   ├── prompts/
│   │   │   ├── base.py              # 基础层 Prompt (400t)
│   │   │   ├── languages/           # 各语言 Prompt (250t)
│   │   │   │   ├── python.py
│   │   │   │   ├── javascript.py
│   │   │   │   └── typescript.py
│   │   │   └── orchestrator.py      # Prompt 编排
│   │   └── tasks/
│   │       └── review_task.py       # BackgroundTasks 入口
│   ├── tests/
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── ReviewSubmit.tsx     # 提交表单
│   │   │   ├── ReviewResult.tsx     # 结果展示
│   │   │   ├── DiffViewer.tsx       # Diff 查看器
│   │   │   └── FindingsList.tsx     # 发现列表
│   │   ├── hooks/
│   │   ├── services/
│   │   ├── stores/
│   │   └── App.tsx
│   ├── package.json
│   └── Dockerfile
├── docs/
│   ├── ARCHITECTURE.md
│   ├── API.md
│   └── CONTRIBUTING.md
└── README.md
```

---

## 八、风险矩阵

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| **GitHub API Rate Limit** | 高 | 中 | Token Bucket 自适应限流；`shallow clone` 减少 API 调用；使用 GraphQL 批量查询 |
| **LLM Provider Rate Limit** | 高 | 中 | 请求队列 + 指数退避重试；监控 quotas 预判；备用模型降级（Sonnet → Haiku） |
| **LLM 输出不稳定** | 高 | 高 | JSON Schema 校验 + 2 次重试；Self-Critique Pass 自检；规则后处理兜底 |
| **tree-sitter 语言支持不完善** | 中 | 低 | 优先覆盖 Python/JS/TS（tree-sitter 社区最成熟）；其他语言降级为行级切分 |
| **Diff 解析边缘情况** | 中 | 中 | 文件重命名/二进制/子模块需单独处理；超大文件直接截断并标记 |
| **SQLite 写入并发瓶颈** | 低 | 低 | WAL 模式读取无阻塞；写入场景少（仅创建 job + 存储结果）；Phase 3+ 评估迁移 PostgreSQL |
| **Token 预算超支** | 中 | 中 | tiktoken 精确计算；文件级路由 + 三级 Fallback 逐级裁切；硬上限熔断 |
| **单文件超长无法分析** | 中 | 低 | tree-sitter 按函数粒度递归切分；超长函数降级为行级分块 + 关键词提取 |

---

## 九、未来扩展方向

| 方向 | 描述 | 优先级 |
|------|------|--------|
| **Fine-tune 专用模型** | 用历史 Review 数据微调开源模型，降低 API 成本 | 中 |
| **Repository 全量索引** | 对整个仓库做向量 embedding，实现跨文件语义搜索 | 高 |
| **自动化修复** | Review 发现问题后自动生成 PR 修复建议 | 低 |
| **多平台支持** | 扩展 GitLab、Bitbucket、Gitee | 中 |
| **安全专用引擎** | 集成 Semgrep/CodeQL，结合 LLM 做更精准的安全审查 | 中 |
| **Review 质量度量** | 统计 Review 发现 → Bug 修复的转化率，量化 ROI | 低 |
| **知识库积累** | 团队自定义编码规范 → 自动纳入 Prompt 模板 | 中 |

---

## 十、总结

### 架构亮点

1. **真单体 + BackgroundTasks**：MVP 零外部依赖，降低部署复杂度
2. **双层 Prompt 结构**：基础层 400t + 语言层 250t，模块化、可复用、成本可控
3. **三级 Fallback**：Layer 1→2→3 逐级降级上下文，token 预算自动适配
4. **tree-sitter 精确分块**：按函数/类边界切分，避免截断语义
5. **增量 Review (Diff-of-diff)**：变更比例 >50% 走全量，其余走增量
6. **三层成本控制**：硬上限 + 滑动窗口 + 文件级路由
7. **MVP 规则过滤 + 全量 Sonnet**：先做对，Phase 3 再用 Haiku 降本

### 核心设计理念

> **"用工程手段弥补 LLM 的不确定性"** — 每一步都有确定性的校验和兜底策略，而不是盲目信任模型输出。

---

*本方案由 Claude Code 与 DeepSeek V4 Pro 协作完成*
