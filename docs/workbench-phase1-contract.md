# 审查工作台 Phase 1 契约（2026-09-25）

用户诉求：**不审查时聊天区保持现状**；发起审查时自动进入工作台分栏；不需要时用快捷键退出；
并在配置里提供个性化开关。Phase 1 交付状态机 + 快捷键 + 配置项 + 120×30 两栏 + 窄屏状态条，
Phase 2（≥140 三栏）随后。

## 1. 状态机

```
idle ──发起审查──▶ running ──完成──▶ done ──Alt+W──▶ collapsed
 ▲                                                    │
 └──────────── /new（清空会话） ◀──────────────────────┘
                        collapsed ──Alt+W / 再次审查──▶ running / done
```

| 状态 | 触发 | 界面 |
|---|---|---|
| `idle` | 无审查（会话内没跑过，或 `/new` 之后） | **与今天逐字节一致**：76 列居中聊天，无审查面板 |
| `running` | `/review` 或粘贴 PR URL 且审查已启动 | 按尺寸展开工作台；`collapsed` 时只留状态条 |
| `done` | 审查完成 / 失败 / 取消 | 保持展开（结果要留给人看）；`collapsed` 时状态条显示结果摘要 |
| `collapsed` | 用户按 `Alt+W` | 聊天全宽 + 一行状态条（数据保留，`/new` 才清空） |

配置 `preferences.workbench_mode`：

| 值 | 语义 |
|---|---|
| `auto`（默认） | 审查开始自动展开；`Alt+W` 可收起；再次审查自动展开 |
| `always` | 工作台常驻（等价于今天的行为），`Alt+W` 仍可临时收起 |
| `off` | 不自动展开；仅 `Alt+W` / `/workbench` 打开 |

## 2. 响应式档位（`layout`）

| 终端 | layout | 分配 |
|---|---|---|
| ≥140 列 | `three` | 左 26 ｜ 聊天 flex（≥76）｜ 右 52 |
| 100–139 列 | `two` | 聊天 flex（≥60）｜ 右 44（进度+摘要纵向堆叠） |
| <100 列 或 height < 26 | `bar` | 聊天全宽 + 一行状态条 |

`collapsed === true` 时无论宽度都用 `bar`。断点由 Codex 在 `app.tsx` 决定，
展示层只接收 `layout`，不自己读终端尺寸（便于渲染矩阵单测）。

## 3. 展示层 API（MiMo Code 交付）

`frontend/tui/src/review-ui/ReviewWorkbench.tsx`：

```ts
export type ReviewWorkbenchLayout = "three" | "two" | "bar"

export type ReviewWorkbenchProps = {
  layout: ReviewWorkbenchLayout
  /** 折叠时只渲染状态条 */
  collapsed?: boolean
  progress?: ReviewProgressPanelProps
  summary?: ReviewSummaryPanelProps
  findings?: ReviewFinding[]
  status?: ReviewStatusBarProps
  onOpenFindings?: () => void
  onExplain?: () => void
  onFeedback?: () => void
  onExport?: () => void
  onPublish?: () => void
  onFilter?: () => void
  onToggle?: () => void
  language?: string
  /** 聊天列原样透传，工作台只在它左右排布 */
  children: JSX.Element
}

export type ReviewStatusBarProps = {
  phase: "running" | "done" | "idle"
  progress?: number
  stageLabel?: string
  filesDone?: number
  filesTotal?: number
  findingCount?: number
  severity?: SeverityCounts
  threshold?: number | null
  belowThreshold?: number | null
  toggleKey?: string
  language?: string
}
```

语义要求：

- `children`（聊天列）在三种 layout 下都**必须渲染**，`bar`/`two` 下宽度自适应；
- `three`：左栏 = 进度/阶段/文件，右栏 = 摘要+证据+Top 问题+动作；聊天居中；
- `two`：右栏 = 进度 + 摘要纵向堆叠；聊天在左，≥60 列；
- `bar`：仅一行状态条（高度 1），文案随 `phase` 变化：
  - `running`：`审查中 ████░░ 70% · 文件 7/18 · Alt+W 展开 · Ctrl+C 取消`
  - `done`：`审查完成 · 2 问题（🛑1 ⚠️1） · Alt+W 打开工作台`
  - 有过滤信息时附 `· 门槛 0.60 过滤 3 条`
- 缺数据不臆造：字段缺失时省略对应片段；
- 中文按显示宽度裁剪（复用 `clampLine`/`displayWidth`），不得出现半个汉字；
- 组件只做展示，不调用后端（既有约定）。

## 4. 配置层交付（Claude Code）

1. `config.py`：`PreferencesConfig.workbench_mode: str = "auto"`，取值校验 `auto|always|off`，
   非法值回退 `auto` 并记录一次 warning（不抛异常，避免旧配置直接崩）；
2. 配置助手第 6 阶段新增「审查工作台」三选一（auto/always/off，含中英文与说明）；
3. 命令 `pr-review config preferences --workbench auto|always|off`（非交互可脚本化）；
4. `AppConfig.save/load` 往返保留该字段；配置快照（后端 `config.snapshot` / `model.apply` 等）
   把它带给 TUI；
5. 测试：默认值、非法值回退、向导写入、命令写入、保存往返、快照携带。

## 5. Codex 集成交付

- `app.tsx`：状态机（`idle/running/done` + `collapsed`）、`Alt+W` 切换、
  `layout` 由 `useTerminalDimensions()` 推导、`workbench_mode` 生效、`/workbench` 命令、
  **Composer 实例不重建**（草稿/光标不丢）；
- 无审查时：布局与今天逐字节一致（用基线帧回归钉住）；
- 状态条与现有底部状态栏的分工：状态条在聊天列内、输入框上方；底部 `hybrid · 就绪 · …` 不动；
- 验收：`pytest` 全绿、`bun test src` 全绿、`bun run typecheck` 0、
  渲染矩阵 80×24 / 102×51 / 120×30 / 209×51 全过、PTY 实测（审查中收起→展开→完成→收起，草稿不丢）。

## 6. 任务与写入边界

| 任务 ID | 执行方 | 写入范围 |
|---|---|---|
| `claude-p6-workbench-setting` | Claude Code | `src/ai_pr_review/config.py`、`src/ai_pr_review/cli.py`、`src/ai_pr_review/config_commands.py`、`tests/test_config.py`、`tests/test_cli.py`、`docs/claude-p6-workbench-setting.md` |
| `mimo-p6-workbench-panels` | MiMo Code | `frontend/tui/src/review-ui/**`、`frontend/tui/scripts/manual-review-workspace-check.tsx` |
| `codex-p6-workbench-integration` | Codex | `frontend/tui/src/app.tsx`、契约文档、集成与验收、`tui_static` 重建 |

不重叠：MiMo 不碰 `app.tsx`，Claude 不碰 `frontend/`，Codex 不改 `review-ui/**` 与后端。

## 7. 执行状态（2026-09-25）

| 任务 | 执行方 | 状态 | 证据 |
|---|---|---|---|
| `claude-p6-workbench-setting` | Claude Code | completed | `PreferencesConfig.workbench_mode` + `WORKBENCH_MODES` + `normalize_workbench_mode`（非法值回退 `auto` 并告警）、CLI 配置助手第 6 阶段三选一、`pr-review preferences --workbench`；pytest **639 passed / 1 skipped**（+26 用例，3 组变异检查） |
| `mimo-p6-workbench-panels` | MiMo Code | completed | `ReviewWorkbench.tsx`（three/two/bar，collapsed 强制 bar）、`ReviewStatusBar.tsx` + `statusBarView`（running/done 文案、门槛/过滤可选、宽度安全裁剪）；`bun test src` **120 passed**、typecheck 0、渲染矩阵 three/two/bar × 80×24 / 102×51 / 120×30 / 209×51 全过 |
| `codex-p6-workbench-integration` | Codex | completed | 状态机 + `Alt+W` + `/workbench` + 响应式分栏 + TUI 配置助手选项 + 后端快照/选项/apply 三处接线；见 §8 |

## 8. Codex 集成说明与验收

**集成方式**：`app.tsx` 里聊天列保持**固定树位置**，工作台只在它左右增减面板，
因此切换布局不会重建 `Composer`（草稿/光标不丢）。为此**没有**直接使用
`ReviewWorkbench`（它在 three/two/bar 三个分支里各自渲染 `children`，切换会重建聊天列），
而是复用它内部的展示组件：`ReviewProgressPanel`（左栏/两栏顶部）、
`ReviewSummaryPanel` + `ReviewActionBar`（右栏）、**`ReviewStatusBar`（状态条，含宽度安全裁剪）**。
`ReviewWorkbench` 保留为已测试的等价组合，Phase 2（≥140 三栏增强）再决定是否切换。

**断点**：`≥140 且 height ≥26 → three`；`≥100 且 height ≥26 → two`；否则 `bar`。
`collapsed` 或 `workbench_mode=off` 时面板不出现，但状态条仍在（80 列下也能看到进度）。

**验收（Codex 独立执行）**：

| 检查 | 结果 |
|---|---|
| 无审查时帧与改造前对比（80×24、120×30） | **逐字节一致**（`_p5_verify/workbench/baseline-before` vs `baseline-after`） |
| App 级状态机（`P5_CHECK_ONLY=workbench`，120×30 真实组件渲染） | 9/9：加载 Run 后两栏出现、**聊天记录仍在视野内**、Alt+W 提示出现、**草稿在 Alt+W 后不丢**、收起后只剩状态条、摘要隐藏、再展开、80×24 降级为状态条且不硬塞摘要 |
| 真实 PTY（80×24） | `/history <run>` 后显示 `审查完成 · 1 问题（🛑1） · Alt+W 打开工作台`；按 **Alt+W** 实际按键生效（transcript 出现「审查工作台已收起」） |
| Python 全量 | **639 passed / 1 skipped** |
| TUI 全量 + 手动矩阵 | `bun test src` 120 passed；typecheck 0；渲染矩阵含 workbench 四尺寸 |
| `tui_static` | 已重建（stage） |

**已知取舍**：

1. 120×30 采用**两栏**（聊天 ~74 列 + 右栏 44 列）；三栏需要 ≥140 列（全屏 209×51 即满足）。
2. `workbench_mode=off` 时审查进行中仍显示一行状态条（便于取消/查看进度），只是不自动展开面板；
   `Alt+W`/`/workbench` 可随时手动展开。
3. 收起只折叠 UI，数据保留；清空仍由 `/new` 负责。

## 9. 用户实测反馈后的调整（2026-09-25 第二轮）

用户在 209×51 全屏实测后提出四条，全部已改：

| # | 反馈 | 处理 |
|---|---|---|
| 1 | 「209×51 全屏也分为两栏，就我当前终端中的样子」 | **取消三栏档**：`reviewLayout()` 只返回 `two`/`bar`，任何 ≥100 列（含 209×51）都是**聊天在左 + 审查在右**；右栏宽度按 `clamp(33% × 宽度, 38, 宽度-62)` 自适应（120→40、209→69），聊天列始终 ≥60 列。`ReviewWorkbench` 的 three 档仅保留为组件能力，主界面不再使用 |
| 2 | 「收起审查台后最小化那一行文字位置不对」 | 收起/窄屏的状态条从**聊天列内部**移到**顶部通栏**（紧跟标题行之下、占满整宽），不再挤占或跟随聊天列；`ReviewStatusBar` 宽度改为 `终端宽度 - 4` |
| 3 | 「REVIEW ACTION 说明框不要停留在 chat 聊天区」 | 该框从聊天滚动区**移除**：面板可见时渲染在**右栏**（摘要下方、动作栏上方，标题简化为 `REVIEW ACTION`）；收起/窄屏时渲染在**顶部通栏**状态条下方。聊天记录里不再出现该框 |
| 4 | 「ESC 取消审查失败或等待过长」 | 根因：`_review_file_contexts` 未接收 `cancel_check`，逐文件并发审查阶段完全不可中断（`cancel_check` 只在阶段边界被调用）。后端修复见 `claude-p6-cancel-interrupt`（每文件前检查 + `asyncio.Task` 取消飞行中的模型调用）；TUI 侧同时改进反馈：Esc 立即显示「已请求取消：正在中止当前模型调用…」，成功后显示「取消已确认，正在等后端收尾（不会写入历史记录）」，失败/超时显示可操作的重试提示，不再只显示「取消中」而不解释 |

验收（Codex 执行）：

| 检查 | 结果 |
|---|---|
| 两栏几何（`P5_CHECK_ONLY=rail`） | 6/6：120×30 与 209×51 都是「聊天在左、审查在右」，左半边无任何审查面板，`REVIEW ACTION` 落在右栏（120→列 80、209→列 140） |
| 无审查时帧对比 | 80×24 / 120×30 仍与改造前**逐字节一致** |
| 工作台状态机 | 9/9（含 80×24 降级为顶部状态条、草稿在 Alt+W 后不丢） |

### 9.1 取消能力的真实端到端验证（Codex，2026-09-25）

用真实配置（DeepSeek/flash，ONLINE）在 80×24 PTY 里对 PR #29 发起真实审查，
进度到「执行 AI 审查 37%」（模型调用在飞）时按 **Esc**：

```
Esc  → 已请求取消：正在中止当前模型调用，通常几秒内结束（若某个文件调用刚发出，最多等它返回）。
     → 取消已确认，正在等后端收尾（不会写入历史记录）。
     → 顶部状态条 完成 · 0 问题 · Alt+W 打开工作台；聊天记录 ● 审查已取消；底部 就绪
```

全部在**同一秒内**完成（此前要等整个逐文件阶段跑完）。取消后复核结果库：
最新 run 仍是更早的 `16924de8`，**没有为被取消的审查写入任何 run**。

后端修复（`claude-p6-cancel-interrupt`）：`call_with_cancellation()` 把模型调用包成
`asyncio.Task` 并每 0.25s 轮询取消标志，命中后 `task.cancel()` 并等待收尾，再抛
`ReviewCancelled`；逐文件循环在**每个文件前**以及拿到并发额度后再检查一次，取消时把同批
在飞任务全部取消（`gather` 不会做这件事）；hybrid 侧补 `except ReviewCancelled: raise`
排在通用异常之前，避免取消被误报成"该文件失败"；`AIClient._release_cost` 不再抢额度锁
（取消路径里等锁会被二次取消打断）。pytest **644 passed / 1 skipped**（+5 用例，含
0.37s/0.57s 内抛出的在飞取消与"取消发生在文件之间"两类，及 2 组变异检查）。

已知残余：OpenAI 兼容 provider 的 `chat` 走 `asyncio.to_thread`，取消会中止 await 侧，
但工作线程要等自己的 socket 超时才退出；默认 Anthropic SDK 异步客户端不受影响。

### 9.2 启动时状态条噪音（用户实测后同轮修复）

用户配置为 `workbench_mode=always`，于是**未发起审查时**顶部也显示
`就绪 ░░░░░░ 0% · 0 问题`。已改为：`always` 仍让面板常驻，但**状态条只在有内容可报
（审查进行中/已完成）或用户手动打开时出现**，空闲状态不再占用一行。
