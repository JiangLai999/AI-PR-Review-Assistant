# 开发过程记录 · Development Record

> 最后更新：2026-09-28 · 状态：过程记录
>
> **定位**：这是**过程记录**，不是产品文档。产品文档见 `docs/README.md`。
>
> 本文件由 2026-09-28 的「过程文档合并」产生：把此前 96 份分散的协作任务单、交付报告、审计与验收矩阵
> （`mimo-*` / `claude-*` / `codex-*` / `opencode-*` / 各类 `*-plan`、`*-matrix`、`*-contract`）
> 按时间线合并成一份可读的开发史。合并前的逐篇原文可在该提交之前的 git 历史中检出
> （`git show <commit>:docs/<文件名>`），索引见 §6。
>
> 记录原则：**只写有证据的结论**。每个阶段都给出提交范围或可复跑的验证命令；没验证过的事情显式标注。

---

## 1. 一页概览

| 项 | 值 |
| --- | --- |
| 项目 | AI PR Review Assistant —— 可解释、可复盘的 AI PR 审查工作台（CLI + OpenTUI + Web 工作台 + 官网） |
| 时间跨度 | **2026-05-30 → 2026-09-28**，8 个活跃开发日 |
| 提交规模 | **225 个提交**（其中 09-21 之后 160 个，由本轮开发产出） |
| 协作方式 | Codex 主控 + 四个外部 agent（claude / mimo / opencode / workbuddy），通过 `.agent-bus` 任务总线派发与回报 |
| 质量曲线 | 338 → 375 → 800 → 1495 → 1502 → 1514 → **1521** 个测试；语句覆盖率 **87%** |
| 交付状态 | 远端 `main` 已同步（PR #33 合并 `9287db8`）；CI **5 个 job 首次真跑并全绿**；官网已上线新版 |

**一句话总结**：项目从"能跑的工具"（P0）出发，经过演示阻塞修复（P1–P4）、比赛验收（P5）、收尾与大改造（P6–P7）、
Web 工作台四阶段（P8），最后在 09-28 完成"上远端 + CI 首次真跑 + 文档治理"的收尾，把交付链从
「只存在于本机」推进到「远端可交付、门禁可复现」。

---

## 2. 时间线

| 阶段 | 日期 | 提交 | 目标 | 关键交付 | 验证证据 |
| --- | --- | ---: | --- | --- | --- |
| 基线期 | 05-30 ~ 05-31 | 65 | 把单体脚本拆成可维护的命令模块并发布 0.1.0 | `config_*` / `chat_*` 命令模块化、官网与文档站、演示视频链接 | `pytest` 全绿；wheel `py3-none-win_amd64` |
| P0 / P1 启动 | 09-21 | 3 | 参赛版改造启动：Agent 系统 + 双模型协作 | `Agent` 子系统（planner/router/executor）、Chat Copilot、双模型协作骨架、前端缺陷修复报告 | 338 passed；真实 GitHub + DeepSeek 链路验证通过 |
| P1–P4 | 09-24 | 14 | 演示阻塞 → 安装版统一 → 后端健壮性 → 流式与体验 | OpenTUI 迁移、六阶段配置助手、Ctrl+O 修复、`/model local` 不再破坏配置、Anthropic 原生流式 | 375 passed + 1 skipped；用户实机键位/IME 手测通过 |
| P5 | 09-24 ~ 09-25 | 合计 | 比赛验收：演示路径与发布件 | 三尺寸帧验收、独立 TUI 包（无需 Bun，43MB wheel）、评论格式 v2、真实 PR 端到端 | `docs/P5_CLI_ACCEPTANCE_2026-09-24.md`；干净 venv 安装 `pip check` 通过 |
| P6 | 09-25 ~ 09-26 | 合计 | 四项收尾：sources 可信化 / 规则目录 / fork 元数据 / 评论冻结 | hybrid 证据贯通 + PostProcessor、评论过滤披露行、双模型三策略实跑、逐文件可取消 | Claude 独立复核 18 项；`P6_PLAN` §7 验收表 |
| P7 | 09-26 ~ 09-27 | 合计 | Chat 体验、模型目录、会话与压缩、仓库感知、思考档位 | `/think` 四档 + 消息指标 + 折叠渲染、models.dev 目录接入配置助手、多会话与 `/compact`、L1/L2 仓库上下文、20 家 provider 思考参数 | `verification-matrix.md`；真机 6/6 档位验证、74.5% 预算余量测试 · 已归档 |
| P8 | 09-27 ~ 09-28 | 合计 | Web 工作台四阶段 + 全站双语 + CI/门禁 | Phase 0.2/1/2/3/3b、追问面板、发布/导出、设置页对齐 CLI、i18n 354 条归零、CI 五 job | Web 三道自测 118 断言；`bun test` 222 项 |
| 收尾 | 09-28 | 20 | 上远端 + CI 首次真跑 + 文档治理 | PR #33（159 提交）、CI 4 轮修到全绿、官网生成器修复与重生成、`_p5_verify` 清理 372MB、文档合并 | CI run 全绿；站点仓 PR #1 合并上线 |

> 09-25 与 09-26 的提交数（15 / 67）跨两个阶段，表中按主题归属，避免重复计数。

---

## 3. 阶段详述

### 3.1 基线期（2026-05-30 ~ 05-31，65 提交）

把最初的单体实现拆成可维护结构，并发布 `0.1.0`：

- 命令层模块化：`config_entry` / `config_helpers` / `config_commands` / `config_wizard` / `config_diagnostics`、
  `chat_command` 拆出，`cli.py` 从"什么都干"变成入口编排。
- 文档与官网：`docs/` 设计书与 API 文档成形，`website/`（GSAP 静态站）+ `scripts/build_website_docs.py` 生成文档数据，
  第三方素材清理（保留 `tui_static` 必需的产物）。
- 发布件：`scripts/hatch_build.py` 让 wheel 标签固定为 `py3-none-win_amd64`（因为 `tui_static` 内含 Windows x64 专用 `opentui.dll`）。

### 3.2 P0 / P1 启动（2026-09-21，3 提交）

- 引入 `services/agent/`（planner / router / executor / actions / events），把"审查计划"从提示词里提到结构化的 `ReviewPlan`。
- 双模型协作骨架（本地 Ollama + 云端）与 Chat Copilot 打通；`fix: resolve AIClient initialization bug in history analysis` 修掉历史分析路径的初始化缺陷。
- 基线数据：**338 passed**，真实 GitHub PR + DeepSeek 云端链路验证通过（`docs/P0_ACCEPTANCE.md`（已归档） 时代）。
- 同轮产出 `COMPETITION_UPGRADE_PLAN.md`（已归档），确定参赛版目标：可现场演示、可解释、可复盘、可信赖。

### 3.3 P1–P4：演示阻塞 → 安装版 → 健壮性 → 流式（2026-09-24，14 提交）

这一轮的价值在于**把"能跑"变成"敢演示"**：

- **P1 演示阻塞**：小窗（80×24）可用、Esc/Ctrl+C 语义、锁与超时；`Ctrl+O` 在任何 chat 状态都能弹出 findings；
  finding 详情可读可滚动；对话框文字不再与自身行重叠。
- **P2 安装版统一**：wheel 内含前端产物，`pipx install` 后的 `pr-review chat` 与源码版同屏；
  干净 venv 安装 + `pip check` 通过。
- **P3 后端健壮性**：`/model local` 不再破坏配置、`AI_PR_REVIEW_PROVIDER` 不再静默改写 `hybrid_strategy`、
  `config test/health` 校验激活槽位而不是 anthropic 槽位。
- **P4 流式与体验**：Anthropic 原生流式、取消/迟到事件语义闭合；中文输入法（微软拼音）Enter 只选词不误发。
- **独立复核发现的问题（Claude 只读审计）**：`pr-review config model` 在 `local_only` 下静默失效并污染远程槽位、
  环境变量覆盖被持久化、F17 的"子类化"修复没有测试覆盖 —— 补测试后**证明原修复无效**，改为复用
  `review_orchestrator.ReviewCancelled` 才真正生效。这是本阶段最有价值的一条记录：**没有测试的修复不算修复**。
- 验收：**375 passed + 1 skipped**（`docs/phase9-acceptance-matrix.md`（已归档）），OpenTUI typecheck、mypy、`git diff --check` 全通过。

### 3.4 P5：比赛验收（2026-09-24 ~ 09-25）

- 三尺寸字符帧验收（80×24 / 120×30 / 160×40），`prefers-reduced-motion` 降级；
- 独立 TUI 包：`AI_PR_REVIEW_STANDALONE_TUI=1` 打出的 wheel（43,264,372 字节）内含 92MB 编译产物，
  **无需 Bun** 即可进入 OpenTUI；
- 评论格式 v2（`claude-p5-comment-format` 只读审计 + `mimo-p6-comment-freeze-audit` 冻结），
  明确"证据优先"在 GitHub 评论里的呈现方式；
- 真实 PR 端到端 + 干净安装验证；结论与口径固化进 `docs/P5_CLI_ACCEPTANCE_2026-09-24.md`。

### 3.5 P6：四项收尾 + 双模型 + 评论冻结（2026-09-25 ~ 09-26）

`P6_PLAN_2026-09-25.md`（已归档） 定了四件事，全部按"实现 → 独立验收"闭环：

1. **sources 可信化**（`claude-p6-rule-trust-i18n`）：finding 的 `sources` 只能来自真实执行过的规则/AST 通道；
2. **规则目录与中文覆盖**：规则清单模板化，`get_json_schema()` 收敛，UI 规则数与 `all_rule_ids()` 对齐（18 条）；
3. **fork 元数据贯通**（`claude-p6-fork-and-terms`）：fork PR 的 head/base 元数据一路传到报告与事件；
4. **评论格式冻结**：阈值与过滤结果在评论里显式披露（`claude-p6-comment-filter-line`），避免"少报了问题却不说明"。

同时完成：hybrid 路径补 `PostProcessor` 与证据校验贯通（`claude-p6-hybrid-postprocess` /
`claude-p6-hybrid-evidence-author`）、逐文件阶段可中断（`claude-p6-cancel-interrupt`）、
双模型三策略实跑结论（`claude-p6-dual-model-strategies`）。

### 3.6 P7：Chat 体验 + 目录 + 会话 + 仓库感知 + 思考档位（2026-09-26 ~ 09-27）

这是**提交最密集**的一轮（09-26 单日 67 个提交），四条线并行：

- **Chat 体验（mimo）**：思考流式展示、`/think` 四档、消息指标行（模型/耗时/输出长度）、
  长代码块折叠与可点击角标、宽屏表格紧凑化、命令菜单与状态栏会话名；
- **模型目录（codex + claude）**：`models.dev` 目录服务接入配置助手，模型规格（上下文窗口 / 输出上限）可编辑，
  中转站（custom endpoint）逐项自定义；`max_output` 反向影响 chat token 预算；
- **会话与压缩（claude + mimo）**：多会话存储与切换、`/compact` 按 token 计量（保留最近 10 轮原文）、
  压缩压力提示；
- **仓库感知（mimo + claude）**：L1（repo context 预取）与 L2（符号级定位 `RepoSymbolLocator`：trees + grep）、
  PR 变更清单与目录树注入；配套 `l2-symbol-acceptance` 真实仓库验收。
- **思考档位规格（opencode 调研 + codex 落地）**：按官方文档为 **20 家 provider** 写入 thinking 参数，
  并对不支持的通道显式置灰说明（`reasoning-specs-research.md`（已归档））。

### 3.7 P8：Web 工作台四阶段 + 全站双语（2026-09-27 ~ 09-28）

Web 工作台按 Phase 推进，每个 Phase 都有契约与验收：

- **Phase 0.2**：修掉 Web 配置写入的三个静默缺陷（`opencode-web-config-fix`）；
- **Phase 1**：发布 / 导出闭环 + 安全地基（`claude-web-report-actions`）；
- **Phase 2**：设置页对齐 CLI 六阶段配置助手（`claude-web-settings-parity` + `opencode-web-config-view`），
  配置读写的"单一真相源"；
- **Phase 3 / 3b**：审查结果问答（追问面板 + 无状态 `/api/chat`，`opencode-web-chat-service` / `claude-web-ask-panel`）
  与全站中英双语（i18n 运行时 + 354 条文案归零，`mimo-i18n-audit` 提供覆盖度审计）；
- **配置隔离**：Web 工作台写 `config.web.json`，**不再影响 CLI** 的行为（`config-isolation.md`（已归档））。

### 3.8 收尾（2026-09-28，20 提交）

从"本机绿"到"远端可交付"，这一步最费劲，也最值得记录：

1. **上远端**：把积压在本地、从未推送的 **155 个提交**以 PR #33 同步到远端 `main`（merge commit，不 squash）。
   推送前做了凭据扫描（真实 token/API key 在所有已提交文件中 0 命中）。
2. **CI 首次真跑 → 4 轮修到全绿**：首轮 13 个失败，全部是"只在本机成立"的差异，逐条定位并修复：

| # | 现象 | 根因 | 修复 |
| --- | --- | --- | --- |
| 1 | 9 个 chat 用例红 | **真 bug**：`_build_prompt_session()` 不判 TTY 就启用 prompt_toolkit，Linux 上管道输入立刻 EOF | 仅在交互式终端启用；非 TTY 回落 Rich `Prompt.ask` |
| 2 | frontend 守卫必红 | `web_static/index.html` blob 是 CRLF 且源模板 CRLF + vite 注入用 LF，混用留下孤立 `\r`（Windows 766B / ubuntu 765B） | 源模板与产物统一 LF + `.gitattributes` 钉死 |
| 3 | 文档守卫报断链 | 守卫把 **gitignored** 的构建/缓存目录（`frontend/tui/dist/`、`node_modules`、`web/.shots/`）当成真断链 | 用 `git check-ignore` 批量放行，并同时探测 `dir`/`dir/` |
| 4 | 2 个 tree-sitter 用例 + 1 个 TUI 用例红 | 依赖"本机才有的东西"（可选 extra、Windows 专属 `.exe` 名） | `pytest.importorskip` + 按 `os.name` 取名 |
| 5 | black 报 3 个文件 | 手写改动没跑格式化 | 用 pin 版 black 就地格式化 |

3. **官网修复与刷新**：`website/assets/docs-data.js` 是"无法再生成的冻结快照"（生成器锚点因 README 章节改名全部失效），
   修通生成器 → 补表格/引用块渲染 → 重生成产物 → 通过 PR #1 上线站点仓；线上三个文件与本地
   **LF 归一化后字节级一致**。
4. **文档治理**：25 条断链清零并加防漂移守卫、README/CHANGELOG 数字对齐（CI 徽章替代写死数字）、
   `.gitignore` 兜底（`.pytest_*/`、工具缓存、`.shots/`）、`_p5_verify` 一次性环境清理（372.7MB → 0.56MB）、
   过程文档合并为本文件。

### 3.9 交付收尾（2026-09-28，官网口径与提交包素材）

上线之后的收尾同样走 PR 流程，三次合并都经过 CI 与线上验证：

1. **官网命令口径校准（PR #40 / #41）**：官网「Chat 工作区」标签页直接渲染 README 的斜杠命令表，
   而该表混用了 TUI 与纯文本 CLI 两套界面的命令 —— `/usage` `/stats` `/restore` `/clear` `/exit`
   实际**仅 CLI**（TUI 后端实测返回 `Unsupported command`），`/explain` `/feedback` `/publish` `/demo`
   `/showcase` 实际**仅 TUI**，且漏掉 `/setup` `/think` `/context` `/sessions` `/rename` 等 11 条 TUI 命令。
   - README 表改为「命令 / 说明 / 可用界面」三列，29 条命令逐条标注；
   - 新增守卫测试：README 命令表必须等于「后端分发集合 ∪ TUI 前端拦截集合 ∪ CLI 实现集合」，界面标注必须与实现一致；
   - 首页命令卡补齐 `pr-review config`，标题计数与卡片数量由测试锁定；
   - TUI 后端 `/help` 补列 `/sessions` 与 `/rename`，与命令菜单对齐（`sessions` 从"已废弃命令"清单移除）。
2. **P2 配图入库（PR #42）**：10 张应用方案 PDF / 演示视频配图入库 `docs/assets/p2/`，
   并在 `docs/COMPLIANCE_AND_ORIGINALITY.md` §七 逐条登记为"AI 生成展示素材（核心逻辑不依赖）"；
   与官网 OG 图逐字节相同的重复副本不入库。
3. **官网渲染补链接**：文档中心渲染器原先只支持反引号与 `**粗体**`，README / API / 合规文档里的
   `[文本](链接)` 会被原样显示（实测 10 处）。生成器新增行内链接渲染（只放行 `http` / `https` /
   `mailto` 与相对路径，其它协议保持字面量）并补单测，重新生成 `docs-data.js` 后同步站点仓并线上验证。
4. **文档规范化**：13 份文档统一「最后更新 + 状态」元信息行、补齐 19 处代码围栏语言、
   修正 `docs/API.md` 的双 H1，并刷新 `SUBMISSION_PACKAGE_PLAN.md` 的交付状态（PDF 18 页已成稿、
   视频待录制）与 `P5_CLI_ACCEPTANCE_2026-09-24.md` 的证据归档说明（`_p5_verify/` 已清理）。

---

## 4. 跨阶段的关键工程决策

| 决策 | 原因（当时的反例） |
| --- | --- |
| **证据优先**：finding 必须带 `file:line` + 代码片段，并由校验器判定 `valid / needs_review / invalid` | 只信模型会给"听起来对但指错行"的结论；校验器把"位置或片段对不上"的降级标注 |
| **local / remote 只共享账本，不共享 controller** | 共用 `CostController` 会让本地未知模型按云端价计费（曾出现 local_only 报 $0.0311）；共享 `CostLedger` 后跨槽位预算才不再被稀释 |
| **CHAT / REVIEW 双槽路由 + `config.web.json` 隔离** | 单一 `provider` 字段被多处读写，改 chat 模型会顺带改审查模型；Web 改配置会污染 CLI |
| **非 TTY 禁用 prompt_toolkit** | Linux 上管道/CI 输入会立刻 EOF，chat 静默退出（CI 首跑暴露，Windows 不复现） |
| **格式工具钉版本 + `.gitattributes` 钉 LF** | `.venv313` 里的 black 26.x 与 CI 的 24.10.0 结论相反（假红）；CRLF/LF 混用让构建产物漂移一个字节 |
| **任何"防漂移"都要配守卫** | 25 条文档断链、官网冻结快照、README 写死的测试数字，都是"没人检查就会烂掉"的东西 |
| **协作必须有写入边界与回报** | 多 agent 并行时，越界写文件与"自述完成但没有证据"是最大风险；任务单强制 `write_scope` + claim/report |

## 5. 踩过的坑（按主题，供后来者避雷）

**成本与路由**

- 预算字段读错对象 / 逐文件新建客户端 / 全局 findings 污染单文件判定 —— 三处"看起来在跑、实际失效"的缺陷在 P7 一并修掉。
- 本地模型与云端模型价格表不同，**共享计数器 ≠ 共享价目**。

**输入与终端**

- `Ctrl+C`、`Esc`、`Shift+↑↓` 这类键位必须在真实终端（PTY）验证，进程内模拟不算。
- prompt_toolkit 只在 TTY 下启用；否则用 Rich。

**平台差异（CI 首跑暴露）**

- 行尾：Windows 工作区 CRLF、ubuntu LF，构建产物必须与 git 内一致。
- 可选依赖（tree-sitter）与本地产物（编译 exe、`node_modules`、`.shots/`）不能让测试与守卫依赖。
- `subprocess` 用 `text=True` 在 Windows 会把 `\n` 翻成 CRLF，解析 git 输出时要按 bytes 处理并解引号。

**文档与产物**

- 文档里的路径引用必须有守卫，否则文件一挪就变成断链。
- 官网文档数据要从源文档**生成**，不能提交"无法再生成的冻结快照"。
- README 里写死的测试数字必然漂移，改用 CI 徽章 + 实测快照。

**Web 安全**

- 写端点的跨站守卫不仅要返回 415，还必须**读取/丢弃未读请求体再关闭**，否则内核回 RST，浏览器看到 `Failed to fetch`。

## 6. 质量与验证快照

| 日期 | 测试 | 覆盖率 | 其他门禁 | 备注 |
| --- | ---: | ---: | --- | --- |
| 09-21 | 338 passed | — | mypy / black / isort / tsc / vite | P0 验收基线 |
| 09-22 | 375 passed + 1 skipped | — | OpenTUI typecheck、`git diff --check` | 阶段九验收矩阵 |
| 09-26 | 800 passed + 1 skipped | — | 同上 | 仓库上下文与 Chat 线合流后的全量 |
| 09-27 | 1495 ~ 1497 passed | — | Web 三道自测、bun test | Web 四阶段收尾 |
| 09-28（合并前） | 1502 → 1511 → 1514 passed | 87%（12,947 stmts / 1,677 miss） | mypy 89 clean、black/isort pin 版 138 clean、TUI 222 pass、Web 118 断言 | P7/P8 轮 |
| **09-28（远端现状）** | **1521 passed**（0 xfailed） | 87% | **CI 5 个 job 全绿**：Python 3.12/3.13 + black/isort/mypy、Windows wheel 构建、Node 前端（含产物同步守卫）、Bun TUI | PR #33 合并后 main = `9287db8` |

复跑命令（与 CI 一致）：

```bash
pytest                                     # 含覆盖率
black --check src tests                    # 必须用 pin 版本：black==24.10.0
isort --check-only src tests               # isort==5.13.2
mypy src
cd web && npm run typecheck && npm run build && node tools/markdown-lite-check.mjs
cd frontend/tui && bun run typecheck && bun test src
```

---

## 7. 附录 A：合并前的过程文档索引

下表是本次合并的 96 份过程文档 —— 保留它是为了**可追溯**：想查某一轮的原始细节时，用
`git show <提交>:docs/<文件名>` 取回原文（`git log --diff-filter=A -- docs/<文件名>` 可查）。

共 **96** 份。原文取回：`git show <引入提交>:docs/<文件名>`，引入提交用 `git log --diff-filter=A -- docs/<文件名>` 可查。

| 原文档 | 加入日期 | 一句话内容 | 归入 |
| --- | --- | --- | --- |
| `docs/COMPETITION_UPGRADE_PLAN.md` | 2026-09-21 | AI PR Review Assistant 参赛版改造升级执行计划 | §3.2 P0/P1 启动 · 已归档 |
| `docs/FIX_REPORT.md` | 2026-09-21 | 前端缺陷修复报告 | §3.2 P0/P1 启动 · 已归档 |
| `docs/P0_ACCEPTANCE.md` | 2026-09-21 | P0 验收记录 | §3.2 P0/P1 启动 · 已归档 |
| `docs/P2_FINAL_ACCEPTANCE.md` | 2026-09-21 | P2 最终交付验收记录 | §3.2 P0/P1 启动 · 已归档 |
| `docs/AGENT_COLLABORATION_BRIEF.md` | 2026-09-24 | CLI / OpenTUI 协作任务单（2026-09-23） | §3.3–3.4 P1–P5 · 已归档 |
| `docs/DEV_PLAN_2026-09-24.md` | 2026-09-24 | 后续开发方案（2026-09-24） | §3.3–3.4 P1–P5 · 已归档 |
| `docs/claude-p3p4-review.md` | 2026-09-24 | 独立复核报告：P3（后端健壮性 11 项）/ P4（流式与体验 8 项） | §3.3–3.4 P1–P5 · 已归档 |
| `docs/claude-tui-audit.md` | 2026-09-24 | Claude 后端审计报告 | §3.3–3.4 P1–P5 · 已归档 |
| `docs/mimo-p5-terminal.md` | 2026-09-24 | MiMo · mimo-p5-terminal 只读验收报告 | §3.3–3.4 P1–P5 · 已归档 |
| `docs/mimo-tui-audit.md` | 2026-09-24 | MiMo TUI 审计报告 | §3.3–3.4 P1–P5 · 已归档 |
| `docs/mimo-tui-p4-review.md` | 2026-09-24 | P4 OpenTUI 独立只读复核报告 | §3.3–3.4 P1–P5 · 已归档 |
| `docs/modern-tui-migration.md` | 2026-09-24 | AI PR Review Assistant — Modern OpenTUI Migration Plan | §3.3–3.4 P1–P5 · 已归档 |
| `docs/phase9-acceptance-matrix.md` | 2026-09-24 | 阶段九：CLI / OpenTUI 测试与比赛验收矩阵 | §3.3–3.4 P1–P5 · 已归档 |
| `docs/P6_PLAN_2026-09-25.md` | 2026-09-25 | P6 计划：四项收尾改造（2026-09-25） | §3.4–3.5 P5/P6 · 已归档 |
| `docs/claude-chat-routing.md` | 2026-09-25 | 运行时与协议层交付报告：CHAT/REVIEW 双槽路由（任务 `claude-chat-routing`） | §3.4–3.5 P5/P6 · 已归档 |
| `docs/claude-p5-comment-format.md` | 2026-09-25 | P5 前端：GitHub 评论 v2 格式与可渲染性只读审计（任务 `claude-p5-comment-format`） | §3.4–3.5 P5/P6 · 已归档 |
| `docs/claude-p5-publish.md` | 2026-09-25 | P5 后端：publish / demo / showcase（任务 `claude-p5-publish`） | §3.4–3.5 P5/P6 · 已归档 |
| `docs/claude-p6-cancel-interrupt.md` | 2026-09-25 | P6 交付报告：逐文件审查阶段可中断（任务 `claude-p6-cancel-interrupt`） | §3.4–3.5 P5/P6 · 已归档 |
| `docs/claude-p6-comment-filter-line.md` | 2026-09-25 | P6 交付报告：评论过滤披露行（任务 `claude-p6-comment-filter-line`） | §3.4–3.5 P5/P6 · 已归档 |
| `docs/claude-p6-dual-model-strategies.md` | 2026-09-25 | P6 · 双模型三策略实跑结论 | §3.4–3.5 P5/P6 · 已归档 |
| `docs/claude-p6-fork-and-terms.md` | 2026-09-25 | P6 项③+项②终端侧 交付报告：fork 元数据贯通与终端证据术语统一（任务 `claude-p6-fork-and-terms`） | §3.4–3.5 P5/P6 · 已归档 |
| `docs/claude-p6-hybrid-evidence-author.md` | 2026-09-25 | P6 收尾交付报告：hybrid 证据校验贯通 + 作者元数据 + 发布时间 UTC（任务 `claude-p6-hybrid-eviden | §3.4–3.5 P5/P6 · 已归档 |
| `docs/claude-p6-hybrid-postprocess.md` | 2026-09-25 | P6 收尾交付报告：hybrid 路径补上 PostProcessor（任务 `claude-p6-hybrid-postprocess`） | §3.4–3.5 P5/P6 · 已归档 |
| `docs/claude-p6-report-filtered-payload.md` | 2026-09-25 | P6 交付报告：报告载荷与 review.completed 事件携带过滤信息（任务 `claude-p6-report-filtered- | §3.4–3.5 P5/P6 · 已归档 |
| `docs/claude-p6-rule-trust-i18n.md` | 2026-09-25 | P6 项①+项④ 交付报告：sources 可信化与规则目录中文覆盖（任务 `claude-p6-rule-trust-i18n`） | §3.4–3.5 P5/P6 · 已归档 |
| `docs/claude-p6-workbench-setting.md` | 2026-09-25 | P6 交付报告：审查工作台配置项与配置助手/命令支持（任务 `claude-p6-workbench-setting`） | §3.4–3.5 P5/P6 · 已归档 |
| `docs/claude-review-actions.md` | 2026-09-25 | Claude Review Actions — per-file callbacks + explain/feedback (Phase 3 | §3.4–3.5 P5/P6 · 已归档 |
| `docs/claude-review-context.md` | 2026-09-25 | 后端交付报告：审查上下文 · Review-Aware Chat（任务 `claude-review-context`） | §3.4–3.5 P5/P6 · 已归档 |
| `docs/claude-review-events.md` | 2026-09-25 | Claude Review Events — Backend Event Contract (Phase 1+2) | §3.4–3.5 P5/P6 · 已归档 |
| `docs/claude-route-slots.md` | 2026-09-25 | 配置层交付报告：CHAT/REVIEW 双槽路由 + 仓库上下文配置项（任务 `claude-route-slots`） | §3.4–3.5 P5/P6 · 已归档 |
| `docs/claude-tui-route.md` | 2026-09-25 | TUI 路由细化页（claude-tui-route）交付报告 | §3.4–3.5 P5/P6 · 已归档 |
| `docs/dual-model-roles-plan.md` | 2026-09-25 | 双模型角色分离方案（CHAT / REVIEW） | §3.4–3.5 P5/P6 · 已归档 |
| `docs/mimo-p6-comment-freeze-audit.md` | 2026-09-25 | P6 评论格式冻结审计（mimo-p6-comment-freeze-audit） | §3.4–3.5 P5/P6 · 已归档 |
| `docs/mimo-repo-context.md` | 2026-09-25 | mimo-repo-context 交付说明（L1-a） | §3.4–3.5 P5/P6 · 已归档 |
| `docs/mimo-repo-inject.md` | 2026-09-25 | mimo-repo-inject：仓库感知 L1-b 注入层 | §3.4–3.5 P5/P6 · 已归档 |
| `docs/repo-aware-review-plan.md` | 2026-09-25 | 仓库感知审查方案（Repo-Aware Review） | §3.4–3.5 P5/P6 · 已归档 |
| `docs/review-workspace-contract.md` | 2026-09-25 | Review Workspace Collaboration Contract (v1) | §3.4–3.5 P5/P6 · 已归档 |
| `docs/workbench-phase1-contract.md` | 2026-09-25 | 审查工作台 Phase 1 契约（2026-09-25） | §3.4–3.5 P5/P6 · 已归档 |
| `docs/b2b3-wiring-design.md` | 2026-09-26 | B2/B3 接线设计：models.dev 接进配置助手 + 规格可配 + 中转站逐项自定义 | §3.5–3.6 P6/P7 · 已归档 |
| `docs/chat-contract-verification.md` | 2026-09-26 | Chat 契约 v1 独立验收报告 | §3.5–3.6 P6/P7 · 已归档 |
| `docs/chat-deepseek-live-verification.md` | 2026-09-26 | Chat 真实链路验收（DeepSeek 云端 · 四档思考强度） | §3.5–3.6 P6/P7 · 已归档 |
| `docs/chat-experience-plan.md` | 2026-09-26 | Chat 体验升级统一方案（v2） | §3.5–3.6 P6/P7 · 已归档 |
| `docs/chat-live-verification.md` | 2026-09-26 | Chat 真实链路验收（本机 Ollama） | §3.5–3.6 P6/P7 · 已归档 |
| `docs/claude-b2b3-impl.md` | 2026-09-26 | B2/B3 实施记录：models.dev 接进配置助手 + 规格可编辑 + 中转站逐项自定义 | §3.5–3.6 P6/P7 · 已归档 |
| `docs/claude-backend-followup.md` | 2026-09-26 | 后端收尾：测试归位 + max_tokens 跟随 max_output + 未知键过滤 + chat 预算联动 | §3.5–3.6 P6/P7 · 已归档 |
| `docs/claude-chat-context-a.md` | 2026-09-26 | 上下文管理 A1-A3（任务 `claude-chat-context-a`）交付报告 | §3.5–3.6 P6/P7 · 已归档 |
| `docs/claude-chat-repo-files.md` | 2026-09-26 | chat 按需读取仓库文件（任务 `claude-chat-repo-files`）交付报告 | §3.5–3.6 P6/P7 · 已归档 |
| `docs/claude-l3-patch.md` | 2026-09-26 | L3 修复建议 patch 交付报告（任务 `claude-l3-patch`） | §3.5–3.6 P6/P7 · 已归档 |
| `docs/claude-repo-config.md` | 2026-09-26 | 后端与协议交付报告：repo_context 可配置化 + `/model chat/review` 子命令（任务 `claude-repo | §3.5–3.6 P6/P7 · 已归档 |
| `docs/claude-symbol-locate-config.md` | 2026-09-26 | `symbol_locate` 配置入口（协议三出口 + CLI 开关）交付报告（任务 `claude-symbol-locate-conf | §3.5–3.6 P6/P7 · 已归档 |
| `docs/claude-tui-repo-context.md` | 2026-09-26 | TUI 配置助手「仓库上下文」屏（claude-tui-repo-context）交付报告 | §3.5–3.6 P6/P7 · 已归档 |
| `docs/codex-chat-backend-c1.md` | 2026-09-26 | Chat 后端第二批（codex-chat-backend-c1） | §3.5–3.6 P6/P7 · 已归档 |
| `docs/codex-model-catalog.md` | 2026-09-26 | 模型目录服务（任务 `codex-model-catalog-b`） | §3.5–3.6 P6/P7 · 已归档 |
| `docs/l2-symbol-acceptance.md` | 2026-09-26 | L2 符号定位验收报告（真实仓库） | §3.5–3.6 P6/P7 · 已归档 |
| `docs/mimo-chat-frontend-c1.md` | 2026-09-26 | Chat 前端第二批：动画/耗时/思考区 + 上下文提示/超额 tips + 命令 UI | §3.5–3.6 P6/P7 · 已归档 |
| `docs/mimo-chat-render-c.md` | 2026-09-26 | Chat 渲染组 C：表格分档 + 代码块折叠（mimo-chat-render-c） | §3.5–3.6 P6/P7 · 已归档 |
| `docs/mimo-chat-render-c3.md` | 2026-09-26 | Chat 渲染第三批：角标可点击 + 用户消息样式 + 宽屏表格紧凑化（mimo-chat-render-c3） | §3.5–3.6 P6/P7 · 已归档 |
| `docs/mimo-config-wizard-fix2.md` | 2026-09-26 | TUI 配置助手收尾（mimo-wizard-followup） | §3.5–3.6 P6/P7 · 已归档 |
| `docs/mimo-config-wizard-ui.md` | 2026-09-26 | 配置助手 B2/B3 屏：模型规格与中转站表单（TUI） | §3.5–3.6 P6/P7 · 已归档 |
| `docs/mimo-l2-recon.md` | 2026-09-26 | L2 数据源侦察：Code Search vs Trees+Fetch+Grep | §3.5–3.6 P6/P7 · 已归档 |
| `docs/mimo-l2-symbol-locator.md` | 2026-09-26 | L2 符号级定位实施：RepoSymbolLocator（trees + grep） | §3.5–3.6 P6/P7 · 已归档 |
| `docs/mimo-message-metrics.md` | 2026-09-26 | 消息指标行 + 思考区可展开 + 状态栏思考强度（mimo-message-metrics） | §3.5–3.6 P6/P7 · 已归档 |
| `docs/mimo-review-effort-ui.md` | 2026-09-26 | TUI 配置助手 · review 思考档位（mimo-review-effort-ui） | §3.5–3.6 P6/P7 · 已归档 |
| `docs/model-metadata-sources.md` | 2026-09-26 | 模型能力信息源评估（能否省掉实测） | §3.5–3.6 P6/P7 · 已归档 |
| `docs/model-reasoning-probe.md` | 2026-09-26 | 思考档位探测工具（scripts/probe_model_reasoning.py） | §3.5–3.6 P6/P7 · 已归档 |
| `docs/reasoning-effort-matrix.md` | 2026-09-26 | 各供应商"思考强度"能力对照矩阵 | §3.5–3.6 P6/P7 · 已归档 |
| `docs/reasoning-effort-probe.md` | 2026-09-26 | DeepSeek 思考强度实测报告（v2 · 修正版） | §3.5–3.6 P6/P7 · 已归档 |
| `docs/reasoning-specs-research.md` | 2026-09-26 | 思考（reasoning/thinking）参数规格调研 | §3.5–3.6 P6/P7 · 已归档 |
| `docs/reasoning-specs.md` | 2026-09-26 | 供应商思考参数实现说明（reasoning specs） | §3.5–3.6 P6/P7 · 已归档 |
| `docs/review-context-acceptance.md` | 2026-09-26 | 审查上下文验收报告（§9.3） | §3.5–3.6 P6/P7 · 已归档 |
| `docs/review-reasoning-assessment.md` | 2026-09-26 | review 链路思考档位评估（真机验证 + 建议） | §3.5–3.6 P6/P7 · 已归档 |
| `docs/verification-matrix.md` | 2026-09-26 | 全项目验收矩阵（verification matrix） | §3.5–3.6 P6/P7 · 已归档 |
| `docs/claude-i18n-overview.md` | 2026-09-27 | Phase 3b · 概览 / 准确率 / 离线演示 中英双语（claude） | §3.7 P8 · 已归档 |
| `docs/claude-repo-structure-context.md` | 2026-09-27 | 仓库结构上下文：finding 文件放开 + PR 变更清单 + 目录树（任务 `claude-repo-structure-context | §3.7 P8 · 已归档 |
| `docs/claude-sessions-compaction.md` | 2026-09-27 | 多会话存储 + 上下文压缩改造（后端核心线） | §3.7 P8 · 已归档 |
| `docs/claude-web-ask-panel.md` | 2026-09-27 | Web 追问面板（Phase 3）· 实现记录 | §3.7 P8 · 已归档 |
| `docs/claude-web-report-actions.md` | 2026-09-27 | Web 发布 / 导出前端（Phase 1）· 实现记录 | §3.7 P8 · 已归档 |
| `docs/claude-web-settings-parity.md` | 2026-09-27 | Web 设置页对齐 CLI 配置助手 6 阶段（Phase 2 前端） | §3.7 P8 · 已归档 |
| `docs/codex-sessions-verify.md` | 2026-09-27 | 多会话 + 压缩 · 端到端验收（scripts/verify_sessions.py） | §3.7 P8 · 已归档 |
| `docs/config-isolation.md` | 2026-09-27 | Web 工作台 / CLI 配置隔离 | §3.7 P8 · 已归档 |
| `docs/mimo-i18n-audit.md` | 2026-09-27 | i18n 覆盖度审计报告（Phase 3 前期） | §3.7 P8 · 已归档 |
| `docs/mimo-i18n-review-pages.md` | 2026-09-27 | Phase 3b — 审查工作台 / 历史审查 中英双语 | §3.7 P8 · 已归档 |
| `docs/mimo-review-budget-hint.md` | 2026-09-27 | 小 max_output 模型 · 高档位思考预算封顶提示（mimo-review-budget-hint） | §3.7 P8 · 已归档 |
| `docs/mimo-sessions-ui.md` | 2026-09-27 | mimo-sessions-ui · 会话切换弹窗 + 状态栏会话名 + 压缩压力提示 | §3.7 P8 · 已归档 |
| `docs/mimo-web-api-docs.md` | 2026-09-27 | mimo · web-p0-docs-retry 变更说明 | §3.7 P8 · 已归档 |
| `docs/mimo-web-ux-focus-mobile.md` | 2026-09-27 | p2-ux · 键盘焦点可见 + 390px 窄屏导航（U1/U3） | §3.7 P8 · 已归档 |
| `docs/opencode-backend-i18n.md` | 2026-09-27 | Phase 4 · 后端生成文案的双语化（结构化键契约） | §3.7 P8 · 已归档 |
| `docs/opencode-i18n-settings.md` | 2026-09-27 | Phase 3b · 设置页 / 接口页 中英双语（agent: opencode） | §3.7 P8 · 已归档 |
| `docs/opencode-web-chat-service.md` | 2026-09-27 | 审查结果问答服务层（Phase 3 后端 · p3-chat-service） | §3.7 P8 · 已归档 |
| `docs/opencode-web-config-fix.md` | 2026-09-27 | Phase 0.2：Web 配置写入三个静默缺陷（opencode 修复报告） | §3.7 P8 · 已归档 |
| `docs/opencode-web-config-view.md` | 2026-09-27 | ConfigView 读侧三键 + 数值范围单一真相源（Phase 2 后端 · p2-config-view） | §3.7 P8 · 已归档 |
| `docs/session-and-compaction-plan.md` | 2026-09-27 | 方案：多会话切换 + 上下文压缩改造（对标 mimocode） | §3.7 P8 · 已归档 |
| `docs/web-workbench-proposal-claude.md` | 2026-09-27 | Web 审查工作台下一阶段方案（claude） | §3.7 P8 · 已归档 |
| `docs/web-workbench-proposal-mimo.md` | 2026-09-27 | Web 审查工作台下一阶段方案（mimo） | §3.7 P8 · 已归档 |
| `docs/web-workbench-proposal-opencode.md` | 2026-09-27 | Web 审查工作台下一阶段方案（opencode 提案） | §3.7 P8 · 已归档 |
| `docs/P7_ROUND_2026-09-28.md` | 2026-09-28 | P7 轮结论（2026-09-28）：死代码 / 跨槽位预算 / 文档断链 | §3.8 收尾 · 已归档 |

## 8. 附录 B：协作机制

- **角色**：Codex 作为主控（方案设计、任务分发、验收与合并），四个外部 agent 作为执行者：
  `claude`（后端/协议/复核）、`mimo`（TUI 与前端交互）、`opencode`（Web 工作台与文档治理）、`workbuddy`（评估与旁路验证）。
- **总线**：`.agent-bus/tasks/*.json` 描述任务（`objective` / `write_scope` / `prompt`），
  `scripts/agent_bridge.py` 负责 `dispatch / claim / report`，`scripts/agent_dispatch_runner.py` 以 headless 方式驱动 CLI 并回收结果。
- **纪律**：任务必须声明写入范围；agent 不执行 git 操作；完成后必须回报 `summary` + `evidence`；
  主控**不采信自述**，逐条复跑后才合并（本轮 CI 首跑就是这个纪律的最大受益者）。
- **评估轮**：外部分别产出 claude / workbuddy / opencode / MiMo 四份独立评估报告，
  主控逐条复现，其中**证伪了一条**（MiMo 的 "black 漂移" 实为使用了非 pin 版本的假红）。
