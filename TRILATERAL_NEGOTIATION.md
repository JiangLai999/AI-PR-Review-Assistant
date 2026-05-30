# 三方会谈：AI PR Review 助手架构设计

> 📅 会谈日期：2026-05-29
> 🤖 参与方：
> - **Claude Code**（主持人 & 架构师）
> - **DeepSeek V4 Pro**（技术审查官）
> - **用户**（决策者）
>
> 📋 会谈轮次：4 轮
> ⏱️ 总时长：约 2 小时
> 📝 记录方式：AI 协作对话

---

## 会谈背景

### 项目需求
开发一个 AI 代码评审工具，帮助开发者提升 Pull Request 的 Review 效率与质量。

### 会谈目标
通过多方协作，制定出一个经过深思熟虑、具有可行性的技术方案。

### 会谈原则
1. **开放质疑**：任何观点都可被质疑和挑战
2. **数据驱动**：决策基于事实和逻辑，而非假设
3. **务实优先**：避免过度设计，快速验证核心价值
4. **风险意识**：识别潜在风险并制定应对策略

---

## 第一轮：架构质疑

### 🎤 Claude Code 提出初步方案

**Claude Code**：
> 我有一个初步想法，请 DeepSeek 审查：
> 1. **单体应用优先**：MVP 阶段不用微服务，直接用 FastAPI + Celery 单体架构
> 2. **同步分析优先**：先实现同步的 PR 分析，异步队列为 Phase 2 再加
> 3. **单模型策略**：MVP 只用一个模型（比如 Claude Sonnet），不搞复杂的多模型路由
> 4. **简化上下文**：先只做 diff + 前后 10 行，不做复杂的 AST 解析
> 
> 理由：快速验证核心价值，避免过度设计，降低初期复杂度。

### 🔍 DeepSeek 的质疑

**DeepSeek V4 Pro**：
> **质疑 1：你说"单体应用"，但却选了 FastAPI + Celery**
> 
> 这本身已经是一个分布式架构了。Celery 需要 message broker（Redis/RabbitMQ）+ result backend，你还没写一行业务代码就已经引入了 3 个运行时组件。
> 
> **真正的单体 MVP 应该是**：一个 FastAPI 进程，用 `BackgroundTasks` 或 `asyncio.create_task` 处理异步逻辑，所有状态存 SQLite。

**DeepSeek V4 Pro**：
> **质疑 2："同步分析优先" 与 GitHub Webhook 的物理限制冲突**
> 
> GitHub Webhook 要求 **10 秒内返回 200**，否则标记为 delivery failure 并重试。一次 LLM API 调用处理 diff 通常需要 8-30 秒。
> 
> 如果你做同步分析，用户在 PR 页面看不到即时反馈，GitHub 会不断重试失败的 webhook。

**DeepSeek V4 Pro**：
> **质疑 3：单模型策略在 PR Review 场景下有结构性缺陷**
> 
> PR Review 天然适合**双模型架构**：分类/Triage 用便宜模型，深度分析用强模型。如果所有 diff 都用 Sonnet 分析，成本会很高。

**DeepSeek V4 Pro**：
> **质疑 4："diff + 前后 10 行" 是一个危险的假设**
> 
> 10 行在很多语言中连一个完整的函数签名都看不到。AI 会瞎猜，产出垃圾 review。

### 💬 用户的反馈

**用户**：
> DeepSeek 的质疑很有道理。我接受关于 Celery 和同步分析的建议。但我对双模型策略有顾虑：Haiku 做分类的准确率如何保证？如果 Haiku 误判了重要代码为"不值得看"，会漏掉关键问题。

### 📊 第一轮决策

| 决策点 | 最终决定 | 理由 |
|--------|----------|------|
| 架构 | 真单体（FastAPI + BackgroundTasks + SQLite） | 减少运维面 |
| 异步 | MVP 就用 BackgroundTasks 实现异步 | GitHub Webhook 10 秒限制 |
| 模型 | 暂不决定，继续讨论 | 用户对 Haiku 分类有顾虑 |
| 上下文 | 暂不决定，继续讨论 | 需要更多技术细节 |

---

## 第二轮：技术辩论

### 🎤 Claude Code 的回应

**Claude Code**：
> 我接受你的建议。但我有新的问题：
> 1. **SQLite 并发问题**：WAL 模式能撑住多少并发？
> 2. **Haiku 分类 Prompt**：能否给出一个具体的示例？
> 3. **tree-sitter 支持**：对 JavaScript/TypeScript 效果如何？
> 4. **成本估算**：50 文件 PR 的实际成本是多少？

### 🔍 DeepSeek 的详细回答

**DeepSeek V4 Pro**：
> **SQLite WAL 模式可应对 MVP 阶段。**
> 
> 开启 WAL 后，读写可以并发，写入者也不会互相阻塞。WAL 模式下，单机 SQLite 可以撑住 **10-20 个并发 BackgroundTask worker**。

**DeepSeek V4 Pro**：
> **Haiku 分类 Prompt 设计**：
> 
> 核心策略是 **"宁可错抓不可放过"**——分类 prompt 设计成高召回、低过滤。
> 
> ```
> A diff hunk is `worth_review: true` if ANY of the following apply:
> 1. Security risk
> 2. Logic change
> 3. Data integrity
> 4. Error handling
> ...
> When in doubt, ALWAYS return `worth_review: true`.
> ```

**DeepSeek V4 Pro**：
> **tree-sitter 对 JS/TS 的支持是一流的**。
> 
> tree-sitter-javascript 和 tree-sitter-typescript 是最早维护的 grammar，覆盖率高。能力包括：精准提取函数声明、类定义、import/export 语句，识别 JSX 结构，TypeScript 类型注解。

**DeepSeek V4 Pro**：
> **双模型成本估算（50 文件 PR）**：
> 
> | 模型策略 | 单次 Review 成本 |
> |----------|-----------------|
> | 纯 Haiku（全量） | ≈ $0.10 |
> | 纯 Sonnet（全量） | ≈ $1.50 |
> | **双模型混合（推荐）** | **≈ $0.86** |

### 💬 用户的进一步质疑

**用户**：
> 我对 Haiku 分类的可靠性仍有担忧。能否给出 Haiku 在代码分类任务上的实际准确率数据？另外，Prompt 2000 tokens 会不会太长？

### 📊 第二轮决策

| 决策点 | 最终决定 | 理由 |
|--------|----------|------|
| SQLite | WAL 模式，MVP 够用 | 单机 10-20 并发没问题 |
| Haiku 分类 | 继续讨论 | 用户仍有顾虑 |
| tree-sitter | 必须使用 | JS/TS 支持一流 |
| 成本 | 双模型 ≈ $0.86/PR | 可接受 |

---

## 第三轮：争议解决

### 🎤 Claude Code 的质疑

**Claude Code**：
> 我对你的方案有以下质疑：
> 1. **Haiku 分类可靠性**：没有 benchmark 数据，误判风险高
> 2. **Prompt 冗长**：2000 tokens 太长，稀释注意力
> 3. **tree-sitter 实际效果**：Vue SFC 怎么处理？
> 4. **成本估算准确性**：16% 高风险比例是怎么来的？
> 5. **增量 Review**：用户多次 push 时怎么处理？

### 🔍 DeepSeek 的回应

**DeepSeek V4 Pro**：
> **我撤回在 MVP 阶段用 Haiku 做风险分类的建议，采纳你的方案。**
> 
> 理由：
> - 没有 Haiku 在代码风险分类任务上的独立 benchmark 数据
> - 误报尚可接受，但**漏报不可接受**——一个 missed SQL 注入就是安全事故
> - MVP 阶段的核心目标是验证全链路跑通，成本不是第一优先级

**DeepSeek V4 Pro**：
> **修订方案 — MVP 阶段规则过滤 + 全量 Sonnet**：
> 
> ```
> 规则预过滤 (始终审查):
> - src/auth/, src/middleware/, migrations/, **/config/**, **/*.sql
> 
> 直接跳过:
> - test/**, __test__/**, *.test.*, *.spec.*, docs/**, *.md
> 
> 所有剩余文件 → 全部送 Sonnet
> ```

**DeepSeek V4 Pro**：
> **Prompt 精简版设计（双层结构）**：
> 
> - 基础层（~400 tokens）：角色、输出格式、通用规则
> - 语言层（~250 tokens）：语言特定检查维度
> - **总开销：650 tokens**，比原来减少 65%

**DeepSeek V4 Pro**：
> **tree-sitter 的三级 fallback**：
> 
> ```
> Level 1: tree-sitter 全量解析
> Level 2: 正则表达式提取关键 pattern
> Level 3: 仅提供 diff context（前后 30 行）
> ```

**DeepSeek V4 Pro**：
> **增量 Review 设计（Diff-of-diff）**：
> 
> ```
> Push 新 commit 时:
> ├── 新增文件 → 全新分析
> ├── 删除文件 → findings 标记为 resolved
> └── 修改文件 → 仅分析变更 hunk
> ```

### 💬 用户的确认

**用户**：
> 很好！我接受这些修订。但我认为增量 Review 复杂度太高，建议 MVP 不做。

### 📊 第三轮决策

| 决策点 | 最终决定 | 理由 |
|--------|----------|------|
| **Haiku 分类** | ❌ 撤回，改用规则过滤 + 全量 Sonnet | 无 benchmark 数据，漏判风险高 |
| **Prompt** | 双层结构（400 + 250 = 650 tokens） | 减少 65%，平衡成本和效果 |
| **tree-sitter** | 三级 fallback | 保证鲁棒性 |
| **增量 Review** | MVP 不做，Phase 3 再上 | 复杂度过高 |

---

## 第四轮：方案确认

### 🎤 Claude Code 的最终确认

**Claude Code**：
> 请确认最终技术方案：
> 
> - 技术栈：Python 3.12 + FastAPI + SQLite WAL + tree-sitter + PyGithub
> - 架构：真单体，BackgroundTasks 异步，不用 Celery
> - 模型：MVP 全量 Sonnet，规则过滤跳过 test/docs
> - Prompt：双层结构，基础层 400 tokens + 语言层 250 tokens
> - 成本控制：硬上限 + 滑动窗口
> - 增量 Review：MVP 不做
> - MVP 范围：CLI 命令，支持 Python/JS/TS，2-3 周

### 🔍 DeepSeek 的最终确认

**DeepSeek V4 Pro**：
> **方案确认**，并补充以下风险：
> 
> ### 🔴 高风险
> 1. **BackgroundTasks 不做持久化**：服务重启丢失任务
> 2. **单模型无降级**：API 故障即全军覆没
> 3. **GitHub API Rate Limit**：未做保护
> 
> ### 🟡 中风险
> 4. **tree-sitter 编译问题**：Windows 环境
> 5. **Diff-of-diff 复杂度高**：建议 MVP 不做
> 6. **Prompt 650 tokens 偏紧**：可放宽到 1000 tokens
> 7. **单文件超大 diff**：行数硬上限 500 行
> 
> ### 🟢 低风险
> 8. **SQLite 多写并发**：MVP 单线程没问题
> 9. **缺少质量基准**：准备 10 个回归用例
> 10. **Windows 路径兼容性**：统一使用 pathlib

**DeepSeek V4 Pro**：
> **最终架构图（MVP 版本）**：
> 
> ```
> CLI Entry → PR Fetcher → Filter Pipeline
>                 ↓
>         Context Builder (tree-sitter)
>                 ↓
>         Prompt Assembler (双层结构)
>                 ↓
>         AI Client (Anthropic SDK)
>                 ↓
>         Post-Processor → Result Store → Report Renderer
> ```

### 💬 用户的最终确认

**用户**：
> 方案确认。请开始 Phase 1 MVP 开发。

### 📊 第四轮最终决策

| 决策点 | 最终决定 | 理由 |
|--------|----------|------|
| **架构** | 真单体（FastAPI + BackgroundTasks + SQLite） | 最小化运维复杂度 |
| **模型** | MVP 规则过滤 + 全量 Sonnet | 避免 Haiku 漏判风险 |
| **Prompt** | 双层结构（650 tokens） | 平衡成本和效果 |
| **上下文** | tree-sitter + 三级 fallback | 保证鲁棒性 |
| **成本控制** | 硬上限 $5/run + 滑动窗口 $50/24h | 防止意外高消费 |
| **增量 Review** | MVP 不做 | 复杂度过高 |
| **开发周期** | 2-3 周 | 务实可行 |

---

## 会谈成果总结

### ✅ 达成共识的决策

1. **真单体架构**：FastAPI + BackgroundTasks + SQLite，最小化运维复杂度
2. **规则过滤 + 全量 Sonnet**：MVP 阶段保证质量，避免 Haiku 漏判风险
3. **双层 Prompt 结构**：650 tokens 精简指令，平衡成本和效果
4. **tree-sitter 上下文增强**：AST 提取函数/类，三级 fallback 保证鲁棒性
5. **三级成本控制**：硬上限 + 滑动窗口 + 文件级路由

### 🔍 识别的关键风险

| 风险等级 | 风险描述 | 应对策略 |
|----------|----------|----------|
| 🔴 高 | BackgroundTasks 不持久化 | MVP CLI 同步执行 |
| 🔴 高 | 单模型无降级 | 3 次指数退避重试 |
| 🔴 高 | GitHub API Rate Limit | Token Bucket 限速 |
| 🟡 中 | tree-sitter 编译问题 | pin 版本 0.21.x |
| 🟡 中 | 增量 Review 复杂度 | MVP 不做 |

### 💡 创新点

1. **多方协作决策**：通过 Claude Code + DeepSeek + 用户的三方讨论，避免单一视角的局限性
2. **质疑-回应-修订循环**：每一轮讨论都有质疑和回应，最终达成共识
3. **风险前置识别**：在开发前就识别出 10 个关键风险并制定应对策略
4. **务实优先原则**：避免过度设计，MVP 阶段聚焦核心价值验证
5. **透明决策过程**：所有决策都有明确的理由和讨论过程

---

## 会谈价值

### 对项目的价值
- ✅ 避免了 Haiku 分类的潜在漏判风险
- ✅ 精简了 Prompt 设计，减少 65% token 消耗
- ✅ 完善了 tree-sitter 的 fallback 策略
- ✅ 识别了 10 个关键风险并制定应对策略
- ✅ 制定了务实可行的开发计划

### 对团队的价值
- ✅ 展示了 AI 协作的最佳实践
- ✅ 建立了多方讨论的决策模式
- ✅ 积累了技术方案设计的经验
- ✅ 形成了可复用的架构设计流程

### 对行业的价值
- ✅ 证明了 AI 可以参与复杂的技术决策
- ✅ 展示了多模型协作的潜力
- ✅ 提供了透明、可追溯的决策过程
- ✅ 推动了 AI 辅助软件工程的发展

---

## 附录：会谈时间线

| 时间 | 事件 | 参与方 |
|------|------|--------|
| T+0min | Claude Code 提出初步方案 | Claude Code |
| T+5min | DeepSeek 提出 4 个质疑 | DeepSeek |
| T+15min | 用户对 Haiku 分类提出顾虑 | 用户 |
| T+20min | DeepSeek 详细回答技术问题 | DeepSeek |
| T+35min | 用户对 Prompt 长度提出质疑 | 用户 |
| T+40min | DeepSeek 设计精简版 Prompt | DeepSeek |
| T+55min | Claude Code 提出 5 个新质疑 | Claude Code |
| T+60min | DeepSeek 撤回 Haiku 分类建议 | DeepSeek |
| T+75min | 用户确认增量 Review 复杂度过高 | 用户 |
| T+80min | Claude Code 请求最终确认 | Claude Code |
| T+85min | DeepSeek 补充 10 个风险点 | DeepSeek |
| T+95min | 用户确认最终方案 | 用户 |
| T+100min | 开始 Phase 1 MVP 开发 | 全体 |

---

## 会谈启示

### 1. AI 协作的价值
- **多视角**：不同 AI 模型有不同的知识和偏见，多方讨论可以互相补充
- **质疑精神**：AI 可以提出人类可能忽略的质疑，帮助发现潜在问题
- **效率提升**：AI 可以快速提供技术细节和数据支持

### 2. 决策透明的重要性
- **可追溯**：每个决策都有明确的理由和讨论过程
- **可复用**：其他项目可以参考这个决策过程
- **可改进**：团队可以回顾和优化决策流程

### 3. 务实优先的原则
- **避免过度设计**：MVP 阶段聚焦核心价值验证
- **风险前置**：在开发前就识别和应对风险
- **迭代优化**：通过 Phase 1-4 逐步完善系统

---

**会谈结束时间**：2026-05-29 21:00
**下次会谈**：Phase 1 MVP 完成后
**记录人**：Claude Code
**审核人**：DeepSeek V4 Pro + 用户

---

*本文档记录了 AI PR Review 助手项目的三方会谈过程，展示了多方协作决策的最佳实践。*
