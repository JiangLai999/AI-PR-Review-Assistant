# TUI 配置助手「仓库上下文」屏（claude-tui-repo-context）交付报告

任务：`.agent-bus/tasks/claude-tui-repo-context.json`（方案 `docs/repo-aware-review-plan.md` §4.6）。
写域：`frontend/tui/src/**`、`frontend/tui/scripts/**`、`docs/claude-tui-repo-context.md`。**未改任何 Python**。

**一句话结论**：配置助手第 5 阶段多了「仓库上下文」三选一（off / 仅测试文件 / 测试+依赖，推荐档默认），
选项清单与 label 都来自后端 `config.options.repo_context`，提交 `config.setup` 时显式带 `repo_context`，
确认页多出「仓库上下文 <label>」一行；`bun run typecheck` exit 0，`bun test src` 136 pass / 0 fail（基线 128），
新增的 120×30 渲染证据脚本 50/50 PASS，既有路由细化页证据脚本 65/65 PASS（回归）。

---

## 1. 协议字段来源（只读核对，以实际实现为准）

| 字段 | 位置 | 实际形状（本次改造后重新核对过一遍） |
|---|---|---|
| `config.options.repo_context` | `jsonl_server.py:724`，组装点 `_repo_context_options()` `:597` | `{value: "off"\|"tests"\|"tests+imports", options: [{value, label}]}`；`options` 逐项来自 `config.REPO_CONTEXT_MODES`（`config.py:629`），`label` 来自 `REPO_CONTEXT_LABELS`（`jsonl_server.py:127`）：`"关闭 / Off"`、`"仅测试文件 / Tests only"`、`"测试与依赖 / Tests + imports"` |
| `config.snapshot.repo_context` | `jsonl_server.py:575` | **纯字符串**当前值（与 `workbench_mode` 同形；同名键两种形状是后端既定设计，见 `docs/claude-repo-config.md` §6.2） |
| `model.status.repo_context` | `jsonl_server.py:1051` | 与 `config.options` 同键同形（本任务不消费） |
| `config.setup` 的 `repo_context` | `_apply_setup` `jsonl_server.py:893-902` | `strip().lower()` 后必须 ∈ `REPO_CONTEXT_MODES`；非法值 `ConfigValidationError`（整单失败）；**字段缺失 / `null` / `""` = 保持不变** |
| 默认档 | `config.py:630` `DEFAULT_REPO_CONTEXT = "tests+imports"` | 加载期非法值只告警回退到它（`config.py:684`） |

`config.setup` 的 JSON-RPC 分派（`jsonl_server.py:1796` 附近）**没有参数白名单**：多带一个后端不认识的键会被忽略。
这决定了第 5 节里"旧后端也能安全收到 `repo_context`"的取舍。

## 2. 屏幕流转

```
runtime ─┬─(cloud/hybrid)─▶ provider ─▶ base_url ─▶ api_format ─▶ api_key ─▶ model ─┐
         ├─(local)────────▶ local_base_url ─▶ local_model ────────────────────────┤
         └─(custom)───────▶ route_chat ─▶ route_review ───────────────────────────┤
                                                                                  ▼
   github ─▶ ui_language ─▶ response_language ─▶ output_format ─▶ auto_publish ─▶
   chat_layout ─▶ workbench ─▶ 【repo_context】 ─▶ summary
```

- 新屏 `repo_context` 挂在第 5 阶段（`app.tsx:1218` `screenStages.repo_context = 5`），
  三条顺序数组（`cloudOrder` `:1455`、`localOrder` `:1469`、`customOrder` `:1490`）都在
  `workbench` 与 `summary` 之间插入它——三个分支都必须有，否则 custom 用户就改不到这一项。
- 屏标题走 `bilingualScreenTitle()`（`app.tsx:1260`，原 `routeScreenTitle` 改名而来）：
  zh `仓库上下文 · 审查预取` / en `Repository context · review prefetch`。改名是因为它现在不止管
  路由页；调用点只有一处（`app.tsx:1828`）。

## 3. 键盘与选中态

| 键 | 行为 |
|---|---|
| `↑` `↓` | 在三个档位间移动高亮；`select` 默认 `wrapSelection=false`，到头不回绕、不越界 |
| `Enter` | 前进到确认页（`app.tsx:1738-1741` 的通用分支，不是路由页那套） |
| `←` / `Ctrl+←` | 返回上一屏（`workbench`） |
| `Esc` | **取消助手**（普通屏语义） |

**这一屏刻意不进 `isRouteScreen()`**：路由细化页的 `Esc`/`←→`/`Tab` 是它自己的矩阵（`Esc` = 返回上一屏），
而"键盘模型与现有单选屏一致"（任务原文）意味着沿用 `ui_language` / `output_format` / `chat_layout` / `workbench`
那几屏的行为——`Esc` 取消、`←` 返回、页脚用通用文案。选中态沿用现有 `select` 的像素风配色
（`selectedBackgroundColor="#5a2e1c"` + `selectedTextColor="#ffffff"` + 说明行 `#ffd0bb`），与其它屏逐字段一致。

## 4. 选项清单与双语文案（`frontend/tui/src/setup-repo-context.ts`）

- **后端优先**：`repoContextChoices()`（`:76`）先读 `config.options.repo_context.options`，**前端不硬编码取值集合**；
  后端将来加档位（渲染证据脚本里用 `full-tree` 单测过）会原样出现在屏幕上。
- **兜底表**：只有旧后端 / `options` 缺块时才用 `FALLBACK_REPO_CONTEXT_OPTIONS`（`:38`，与 `REPO_CONTEXT_MODES`
  同序同 label），与 `fallbackRuntimeProfiles` 同一惯例——不是第二份真值来源。
- **双语**：后端 label 是 `"中文 / English"`，`bilingualLabel()`（`:69`）按 `ui_language` 取一侧；
  万一后端只给单语（没有 `" / "`），原样返回，不拼空串。
- **推荐档**：`RECOMMENDED_REPO_CONTEXT = "tests+imports"`（`:31`，= `DEFAULT_REPO_CONTEXT`）。
  说明行由前端补（后端 `options[].label` 只有名字）：`tests+imports · 测试文件 + 它们导入的模块（推荐）` /
  `test files + their imports (recommended)`。
- **预选**（`repoContextIndexOf()` `:99`）：精确匹配 → 推荐档 → 第一项。为什么不是"回落到第一项"：
  清单第一项是 `off`，而"用户不动这一屏"必须等于后端默认档 `tests+imports`；只有当前值缺失/未来档位时才走这条路，
  正常配置（`value` 必合法）永远精确命中。

## 5. 提交载荷

`app.tsx:1546` 把 `setupRepoContextField(selectedRepoContext())` 展开进 `config.setup` 载荷：

```json
{"runtime_profile":"cloud","github_token":"","ui_language":"zh-CN","response_language":"zh-CN",
 "output_format":"terminal","auto_publish_comment":false,"chat_layout":"compact",
 "workbench_mode":"auto","repo_context":"tests+imports","provider_name":"deepseek", "...": "..."}
```

（上面是 120×30 渲染证据脚本 [A] 场景里假后端实际收到的载荷，逐字来自运行输出。）

- **永远显式发送**，不做"等于默认值就不发送"的特例，与 `ui_language` / `output_format` / `workbench_mode` 一致：
  用户在这一屏看到什么就保存什么。**未改动**时载荷里的值 = 后端当前值，全新配置的当前值就是推荐档
  `tests+imports`（`DEFAULT_REPO_CONTEXT`）——两种说法（"发 tests+imports" 与"不发"）后端的落盘结果相同，
  这里选前者，因为屏幕上本来就摆着这一项，静默省略会让"我看到的档位到底存没存"变成悬念。
- 空串才不发送（`setupRepoContextField("") → {}`）：清单为空且无兜底时才会发生（实际不可达），
  语义交回后端的"保持不变"。
- **旧后端兼容**：老 `jsonl_server` 的 `_apply_setup` 不读这个键、分派层也没有参数白名单（§1），
  多带一个 `repo_context` 不会报错、不会改变任何行为；前端兜底表保证这一屏在旧后端上仍然可用。
- 非法值不可能发出：值来自后端选项清单（或与之同字的兜底表），后端 `config.setup` 只回一份合法值或报错。

## 6. 顺带修掉的两个真实缺陷（都在写域内）

| # | 症状 | 证据 | 修法 |
|---|---|---|---|
| 1 | 确认页 26 行高度下内容区只有 20 行（26-2 边框-4 padding），云端分支原本是 2 表头 + 1 间距 + 15 行 + 1 页脚 = 19，还有 1 行余量给错误提示；加了「仓库上下文」一行后是 20/20 **顶满**，一旦同时显示 1 行校验错误就溢出——渲染器会静默丢掉溢出块首行并留下字符残影（`app.tsx:1746-1762` 的注释记着同类事故） | 云端分支行数由源码逐行数出（15 → 16）；120×30 实测：改造后 28 行高的确认页内容区 22 行 | `dialogHeight` 的 summary 分支 26 → 28（`app.tsx:1763`），内容区 22 行；证据脚本断言确认页首行、末行、提示行、页脚四行同时在（120×30） |
| 2 | 新加的「仓库上下文」行比其它行右移一列 | `app.tsx:2139` 最初写成 JSX 文本 `<span>仓库上下文 </span>`，实测值列 = 11；而 `运行模式  ` / `Runtime   ` 这几行用**字符串字面量**，值列 = 10——JSX 文本节点里的连续空格会被编译器折叠成一个（`模型       ` → `模型 `） | 标签改走字符串字面量分支并保留 1 个空格（`"Repo ctx  "` / `"仓库上下文 "`），注释写明原因，防止下一个人再踩 |

## 7. 测试与证据

命令都在 `frontend/tui` 下执行，**原始数字**：

| # | 命令 | 结果 |
|---|---|---|
| 1 | `bun run typecheck` | `exit=0`（`tsc --noEmit` 无输出） |
| 2 | `bun test src` | **136 pass / 0 fail / 658 expect() calls / 13 files**（3.17s → 2.65s 复跑）。基线（去掉新文件重跑）：**128 pass / 0 fail / 615 expect / 12 files**，即新增 8 用例 / 43 断言 / 1 文件 |
| 3 | `bun --preload @opentui/solid/preload scripts/manual-repo-context-wizard-check.tsx` | **ALL PASS（50 项断言，0 FAIL）**，帧存 `.pytest_claude/ai-pr-review-repo-context-check/`（`TEMP` = 仓库内 `.pytest_claude`） |
| 4 | `bun --preload @opentui/solid/preload scripts/manual-route-wizard-check.tsx`（**回归**） | **ALL PASS（65 项断言）**——确认页加高与标题函数改名没有动到路由细化页 |
| 5 | `bun --preload @opentui/solid/preload scripts/p5-app-integration-check.tsx`（**回归**） | **ALL P5 UI CHECKS PASSED**（`failures: []`）——工作台/发现/发布等既有 UI 未受 `app.tsx` 改动影响 |

单测 `frontend/tui/src/setup-repo-context.test.ts`（8 例）覆盖：后端清单优先 / 未来档位原样渲染 / 兜底表；双语 label 切分与
单语 label 原样返回；推荐标记；预选精确匹配 → 推荐档 → 第一项（含清单里没有推荐档、空清单）；
取值不越界；载荷字段（含 `" OFF "` 归一化、空串不发送）；"不动的助手"载荷 = 后端当前值（含 `off` 不被悄悄改回推荐档）。

渲染证据脚本 `frontend/tui/scripts/manual-repo-context-wizard-check.tsx`（fixture 渲染**真实** `SetupWizardDialog`，不 spawn Python、
不读配置、不联网）三个场景：

| 场景 | fixture `repo_context.value` | 断言要点 |
|---|---|---|
| [A] zh-CN | `off` | 预选 = `off`（不是推荐档）；三档位/描述/提示/页脚；`↓↓` 选到 `tests+imports`；末项再 `↓` 不越界；`←` 回 `workbench` 且选项保持；确认页「仓库上下文 测试与依赖」+ 高度不截断；载荷 `repo_context="tests+imports"`，`provider_name` 等旧字段不变 |
| [B] en-US | `tests+imports` | 英文档位名（`Off` / `Tests only` / `Tests + imports`，屏上不混中文）；英文推荐说明与提示；**不动这一屏**直接保存 → 载荷 = 后端当前值 `tests+imports`；另起一个 `value="tests"` 的助手验预选，并验 `Esc` 触发 `onClose`（普通屏语义） |
| [C] 旧后端 | 无 `repo_context` 键 | 兜底表仍出三档位；预选推荐档；确认页显示兜底 label；载荷 `tests+imports`（= 后端默认） |
| [D] 本地 / custom 分支（回归） | `tests` / `tests+imports` | 两条顺序数组都真的经过这一屏（本地：`↓` 到「本地」后一路 Enter；custom：`↓↓↓` 进细化页再 Enter）；确认页带这一行；载荷带 `repo_context` **且** custom 仍带 `chat_slot`/`review_slot`、本地仍带 `local_provider`——既有流程与细化页载荷未被破坏 |

## 8. 交付文件

| 文件 | 变更 |
|---|---|
| `frontend/tui/src/setup-repo-context.ts` | 新增：取值清单/双语 label/描述/预选/确认页文案/载荷字段的纯函数（`:31` 推荐档、`:38` 兜底表、`:69` `bilingualLabel`、`:76` `repoContextChoices`、`:99` `repoContextIndexOf`、`:137` `setupRepoContextField`） |
| `frontend/tui/src/setup-repo-context.test.ts` | 新增：8 个用例 |
| `frontend/tui/src/app.tsx` | `RuntimeSnapshot.repo_context?`（`:141`）、`SetupOptions.repo_context?`（`:826`）、屏幕联合/阶段/标题（`:1195/1218/1249`）、`bilingualScreenTitle`（`:1260`）、屏内提示语（`:1285`）、选项与选中项 accessor（`:1354/1373`）、确认页行（`:1430`）、三处顺序数组（`:1455/1469/1490`）、载荷（`:1546`）、预选（`:1658`）、渲染块（`:2085`）、确认页那一行（`:2139`）、确认页高度 28（`:1763`） |
| `frontend/tui/scripts/manual-repo-context-wizard-check.tsx` | 新增：120×30 三场景渲染证据脚本 |
| `docs/claude-tui-repo-context.md` | 本文件 |

## 9. 未决项 / 未覆盖

1. **`repo_context_max_files` / `repo_context_budget_tokens` / `repo_cache_max_mb` 仍未进协议**（后端 `docs/claude-repo-config.md` §6.5 的未决项），
   所以助手也改不到；本任务只做档位三选一。
2. **屏内提示语与页脚在 en-US 下是混合语言**：提示语双语（新屏），页脚仍是既有中文文案
   （`↑↓ 选择 · Enter 下一步 · ← 返回 · Esc 取消`）——助手除新增屏外仍是中文单语，这是改造前的现状，
   本次刻意没顺手翻译（会改变既有屏的可见文本）。证据脚本 [B] 显式断言了这一点。
3. **`config.snapshot.repo_context` 只被当作预选兜底**：正常路径读 `config.options.repo_context.value`；
   快照侧的值没有单独回显（状态栏仍只有 `routing`，方案 §4.7 的"已参考 N 个文件"属可选展示，未做）。
4. **未做真实后端联调**：本任务的验证是 `tsc` + 单测 + `testRender` fixture（不 spawn Python）。
   `config.setup` 的真实往返由后端测试覆盖（`docs/claude-repo-config.md` §5），前端只保证载荷键名/取值与协议一致。
5. **`bun test src` 不含渲染**：`select` 的键盘行为（`wrapSelection=false` 等）由渲染证据脚本覆盖，
   不进 `bun test`（沿用仓库既有分工：`testRender` 脚本单独跑）。
6. **`docs/claude-repo-config.md:203` 的未决项已过时**：那里写着"配置助手的第 5 阶段还没有 `repo_context` 三选一"，
   本任务已补上。该文件不在本任务写域（`docs/claude-tui-repo-context.md` 之外只读），留给后端任务的作者更新。
