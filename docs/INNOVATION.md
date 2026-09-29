# AI PR Review Assistant — 项目创新点

> 最后更新：2026-09-29 · 状态：对外文档
> 🏆 差异化：证据优先的审查闭环 + 可解释计划 + 双槽路由账本；CLI / Chat / Web 三入口共用同一内核

---

## 一、定位：不是"一次模型调用"，而是一条可验证的审查流水线

真实 PR 的完整链路：

```text
GitHub PR URL
  → 获取变更 → 文件过滤 → 构建上下文 → 生成审查计划
  → 静态规则 / AST / 跨文件分析  ┐
  → AI 模型审查（本地 / 云端、成本预算）┘ → 汇总 Findings
  → 文件 / 行号 / 代码片段证据校验 → 后处理
  → 终端、Markdown、JSON 或 GitHub 评论；SQLite 历史与人工反馈
```

- 三个入口共用同一套 Python 审查内核：CLI（`pr-review`）、OpenTUI Chat（`pr-review chat`）、Web 工作台（`pr-review serve`）；
- 离线 Demo（`pr-review demo`）只走内置样例 + 规则 + 证据校验：不调用 GitHub、不调用模型、不写正式审查历史；
- 与"贴一段 diff 让模型点评"的差别在于：**每一步都有输入、输出与可回溯的状态**。

---

## 二、证据优先：Finding 四态校验

每条 Finding 在进入报告前都要对齐 PR 的真实变更（`src/ai_pr_review/services/evidence/finding_validator.py`）：
文件是否在本次变更中、行号是否合法、是否命中变更行、代码片段是否与文件内容一致。

校验结果映射为四态，在终端、Markdown、GitHub 评论与 Web 界面统一展示
（`src/ai_pr_review/services/report_renderer.py`）：

| 状态 | 含义 |
|---|---|
| `valid` | 位置与片段自洽 |
| `needs_review` | 待人工确认 |
| `invalid` | 证据不成立 |
| `unverified` | 未校验（未知 / 缺失状态的兜底） |

Finding 同时携带**置信度**与**来源**（规则 / AST / AI）。价值：把"模型说了什么"变成"能核对到 diff 的结论"，
误报可以被显式标注，而不是被当真。

---

## 三、可解释的审查计划：先规划，再决定要不要花钱

规划阶段**不调用模型**（`pr-review plan`、`pr-review <PR_URL> --dry-run`），先产出结构化 `ReviewPlan`
（`src/ai_pr_review/models/review_plan.py`）：

| 字段 | 含义 |
|---|---|
| `intent` | 本次审查意图 |
| `risk_level` / `risk_categories` | 风险等级与风险类别 |
| `priority_files` / `skipped_files` | 优先审查与跳过的文件 |
| `strategies` | 采用的审查策略 |
| `requires_cross_file_analysis` | 是否需要跨文件分析 |
| `estimated_file_reviews` | 预计审查文件数 |
| `rationale` | 规划依据（逐条可读） |

价值：审查范围与成本在调用模型**之前**就是确定的，用户可以据此决定继续、调整，或只跑计划。

---

## 四、双槽路由 + 成本账本：让取舍显式可审计

- **槽位**：`local`（Ollama 等本地端点）/ `remote`（云端）/ `hybrid`（本地→远端回退）；
  Chat 与审查可以分别指定模型，第三方中转站可单独配置 base URL / key / 模型名与上下文长度；
- **账本**：`CostLedger`（`src/ai_pr_review/services/cost_controller.py`）让 local / remote 两槽共享同一本预算账，
  但各自按自己的价目计算——刻意不共用 controller，避免本地模型被误按云端价计费；
- **闸门**：单次运行与 24 小时滑动窗口双重上限（默认 `$5 / run`、`$50 / 24h`，可配置），超预算显式拦截；
- **路由**：按任务复杂度（`TaskComplexity`，`src/ai_pr_review/services/model_selector.py`）与用户配置选择模型，
  混合编排见 `src/ai_pr_review/services/hybrid_orchestrator.py`。

价值：隐私、成本、质量之间的取舍是**显式且可审计**的，而不是藏在代码注释里。

---

## 五、三级上下文降级：不因环境缺失而崩溃

```text
Level 1  tree-sitter 语法树：函数 / 类 / import 结构（最准确）
Level 2  正则结构提取：语法包不可用时的降级路径
Level 3  diff-only 兜底：仍给出可审查的最小上下文
```

解析模式（`parse_mode`）随结果一起返回，报告里能看出这一轮用的是哪一级
（`src/ai_pr_review/services/context_builder.py`）。相关文件预取
（`src/ai_pr_review/services/repo_context.py`）按 test → import → init 顺序工作，
带行数截断、缓存与预算裁剪，任一步失败即降级。

价值：少装一个语法包不会让审查崩溃，也不会静默给出更差的上下文而不自知。

---

## 六、确定性分析与 AI 协同：两层的分工是明确的

- **确定性层**：静态安全规则、Python AST 分析、跨文件接口影响分析——可复现、可进 CI；
- **模型层**：结构化 JSON 输出，双层 prompt 结构（`src/ai_pr_review/services/prompt_assembler.py`：
  基础 system prompt 定义角色与输出格式，语言特定段补充各语言的检查维度），
  另有一段"相关文件诚实约束"，要求模型只引用真实提供的文件；
- **合并**：确定性结果与模型结果统一进入 Finding 列表，去重后由
  `src/ai_pr_review/services/finding_localizer.py` 对齐文件与行号；
  文件级过滤与跳过规则见 `src/ai_pr_review/services/filter_pipeline.py`。

价值：CI 级的确定性和模型的语义理解是互补关系，而不是互相替代。

---

## 七、三入口 + 审查上下文闭环

| 入口 | 启动方式 | 特点 |
|---|---|---|
| CLI | `pr-review <PR_URL>` | 16 个顶层命令 + 默认审查入口；终端 / Markdown / JSON / GitHub 评论四种输出 |
| Chat | `pr-review chat` | OpenTUI 交互界面；缺少 Bun / OpenTUI 时自动回退纯文本 CLI |
| Web 工作台 | `pr-review serve` | 标准库 `ThreadingHTTPServer` + 已提交的静态前端，运行不需要 Node |

Chat 不是孤立聊天：`/review` 触发审查后会**把该 Run 绑定为对话上下文**，之后可以继续追问 Finding、
证据与修复建议；`/context` 查看或解绑，`/think` 调整思考档位，`/sessions` 切换 / 重命名会话，
`/compact` 压缩上下文，`Ctrl+O` 打开 Findings 详情。完整命令与界面差异见 `docs/chat-features.md`。

**复盘闭环**：每次 Run 写入 SQLite，`history` / `stats` / `explain` / `export-run` / `feedback`
支持回看、统计、导出与人工结论记录；`benchmark` 用内置样例集做规则回归
（**精选样例成绩，不代表真实世界的泛化准确率**）。

---

## 八、把"诚实"做成机制：工程可信度

- **防漂移守卫**：`docs/API.md` 必须覆盖全部可见命令；官网文档产物必须与生成器逐字一致
  （`scripts/build_website_docs.py` + `tests/test_website_docs.py`）；README 的斜杠命令表必须等于
  两套界面的实现集合；首页命令卡数量必须等于标题数字；提交包走密钥卫生守卫；
- **CI**：build / frontend / tui / test-and-quality（Python 3.12 与 3.13）五个 job，
  当前全量 **1544 passed + 4 skipped**（2026-09-29 CI；本机含可选 AST 依赖时 1545）；
- **合规**：MIT 授权边界、第三方许可与商标总表、AI 生成素材逐条登记、
  "不使用来源不明组件"的口径，见 `docs/COMPLIANCE_AND_ORIGINALITY.md`；
- **能力边界**：README 与报告都明确区分"已实现 / 需额外配置 / 规划中"，benchmark 成绩不当作泛化准确率宣传。

---

## 九、方法论：多 agent 协作 + 透明开发记录

项目开发采用**一个主控 + 多个子代理**的协作方式：主控负责拆解任务、定义写入范围（write_scope）、
集成与验收；子代理（Claude Code、MiMo Code、OpenCode、WorkBuddy 等，配合 DeepSeek / GLM / MiMo 等模型）
按任务单执行并以报告回报。协作总线、任务单与各 agent 的临时目录都只留在本地，不入库。

- 每个子任务都有明确的**写入范围**与验证要求，产物必须通过 CI 与守卫才能合并；
- 完整时间线、决策、踩坑与质量数据汇总在 `docs/DEV_RECORD.md`；
- 早期设计阶段的讨论结论（Celery → 真单体、AI 分类 → 规则过滤、Prompt 精简、上下文从"diff + 10 行"
  升级为三级降级等）作为**历史决策**保留在 `docs/DEV_RECORD.md`；
  **产品现状以本文、README 与 `docs/API.md` 为准**。

---

## 十、行业价值

- **可复核**：把 AI 审查从"黑箱结论"推进到"带证据状态与置信度的结论"；
- **可落地**：本地可跑、成本可控、离线可演示——面向真实工程，而不是演示稿；
- **可复用**：双槽成本账本、三级上下文降级、证据四态校验、防漂移文档守卫，都与具体模型无关；
- **可追溯**：透明开发记录让"这些功能是怎么做出来的"有据可查。

---

## 十一、相关文档

| 文档 | 说明 |
|---|---|
| [`docs/PROJECT_DESIGN.md`](PROJECT_DESIGN.md) | 项目设计书：架构、模块划分与关键取舍 |
| [`docs/API.md`](API.md) | CLI 命令、参数、输出格式与 Web 工作台接口 |
| [`docs/chat-features.md`](chat-features.md) | Chat 工作区命令手册（TUI / 纯文本 CLI 差异） |
| [`docs/COMPLIANCE_AND_ORIGINALITY.md`](COMPLIANCE_AND_ORIGINALITY.md) | 合规、原创性与团队权属声明 |
| [`docs/DEV_RECORD.md`](DEV_RECORD.md) | 开发过程记录（时间线、决策、验收数据） |
| `website/` | 官网：文档中心、命令速查与合规入口 |

---

*本文档由团队依据**当前源码与文档**整理：文中字段名、路径与默认值均可在仓库中核对；
早期设计阶段的讨论记录见 `docs/DEV_RECORD.md`。*