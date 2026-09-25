# TUI 路由细化页（claude-tui-route）交付报告

任务：`.agent-bus/tasks/claude-tui-route.json`（方案 `docs/dual-model-roles-plan.md` §4，协议 §5.4）。
写域：`frontend/tui/src/**`、`frontend/tui/scripts/**`、`docs/claude-tui-route.md`。未改任何 Python 后端。

---

## 1. 协议字段来源（以实际实现为准，不是方案文档）

改造前先只读核对了后端当前返回的形状，前端只消费这些真实字段：

| 字段 | 位置 | 实际形状 |
|---|---|---|
| 预设清单 | `jsonl_server.py:628` `_setup_options()["runtime_profiles"]` | `[{value: "cloud"\|"local"\|"hybrid"\|"custom", label: "云端"…"自定义"}]`（来自 `RUNTIME_PROFILES` `jsonl_server.py:118`，中文 label，无描述） |
| 路由快照 | `jsonl_server.py:501` `_routing_snapshot()`，挂在 `config.snapshot` `:574`、`config.options` `:695`、`model.status` `:914` | `{profile, chat: {slot, label, model}, review: {slot, label, model}}`；`profile` 是预设名（`custom` 只在显式槽位时出现） |
| 槽位取值 | `config.py:611` | 聊天 `remote\|local`；审查 `remote\|local\|hybrid` |
| 提交 | `jsonl_server.py:808` `_apply_setup` 的 `custom` 分支 | 只读 `chat_slot` / `review_slot`（`:813`），**不读** provider/local 字段；非 custom 分支清空两个槽位 |
| 模型名 | `config.options.current.remote_model` / `local_model`（`:686`、`:690`） | 细化页两行模型名的唯一来源，前端不硬编码 |

方案文档 §5.1 第 6 项提到的 `slots: {chat: [...], review: [...]}` **后端没有实现**（现有 `config.options` 只给 `routing` + `current`），所以槽别名表只能在前端保留一份，见 `frontend/tui/src/setup-routing.ts:73`（与 `ROUTE_SLOT_LABELS` 逐字一致，列为未决项 §7）。

## 2. 屏幕流转

```
runtime ──(选 custom 才进)──▶ route_chat ──▶ route_review ──▶ github ──▶ ui_language ──▶
        │                                                                    response_language ──▶ output_format ──▶
        │                                                                    auto_publish ──▶ chat_layout ──▶ workbench ──▶ summary
        └──(cloud/hybrid)──▶ provider ──▶ base_url ──▶ api_format ──▶ api_key ──▶ model ──▶ github ──▶ …
        └──(local)─────────▶ local_base_url ──▶ local_model ──▶ github ──▶ …
```

- `route_chat` / `route_review` 同属第 1 阶段（`screenStages: 1`），细化页是 custom 预设的展开，不是新阶段。
- custom 顺序（`app.tsx:1423`）里**没有** Provider / API Key / 本地端点屏幕：`_apply_setup` 的 custom 分支根本不读这些字段，显示出来只会让用户以为"填了会保存"。这与后端语义一致（细化页只决定"用哪个槽"）。
- 两屏都渲染同样的两个方框，只有焦点不同；Esc 在细化页是"返回上一屏"（方案 §4.2 键盘矩阵），在其它屏幕仍是"取消助手"（改造前的语义）。

## 3. 键盘矩阵（`app.tsx:1609-1675`：`moveRouteSelection` / `moveRouteFocus` / `useKeyboard`）

| 键 | 行为 |
|---|---|
| `↑` `↓` | 改**焦点方框**的选中项，首尾回绕；不跨方框 |
| `Tab` / `Shift+Tab` | 在 对话模型 ⇄ 审查模型 两个方框之间移动焦点（回绕） |
| `←` `→` | 同 Tab（方向性循环）；`Ctrl/Alt+←` 仍是"返回上一屏" |
| `Enter` | 前进：`runtime → route_chat → route_review → github`；确认页上是保存 |
| `Esc` | 细化页：返回上一屏；其它屏幕：取消助手 |

选中项 = accent 底色 `#5a2e1c` + `▸` 前缀 + 白色文字（沿用现有 `select` 的像素风配色）；非焦点方框的边框转为 `muted`。

## 4. 提交载荷

`app.tsx:1491` + `setup-routing.ts:190` `setupSlotFields()`：

- `runtime_profile="custom"` → 载荷附 `chat_slot` / `review_slot`，且**不带** `provider_name` / `model_name` / `base_url` / `api_key` / `local_*`；
- 其它预设 → 返回空对象，载荷与改造前逐字节一致（含 `provider_name` 等）；预设分支的槽位清空由后端 `_clear_route_slots` 负责。

确认页三行（`app.tsx:2012-2014`）：`运行模式`（`presetLabel`，中文取后端 label、英文取本地表）+ `对话模型` + `审查模型`。custom 用细化页的实时选择；其它预设显示**该预设定义**的槽位（`routeSummary` `setup-routing.ts:205`），这只是保存前预览，保存后一律以 `routing` 快照为准。

状态栏（`RuntimeStatusLine` `app.tsx:147`，渲染于 App 页脚）：`custom · 就绪 · CHAT deepseek-flash · REVIEW qwen3.5:4b · …`，审查为 hybrid 时显示 `REVIEW 混合 (local↔remote)`；后端没有 `routing`（旧版）时回落到原来的单模型文案。为让这一段可验证，把它从 App 内联 JSX 抽成了导出组件（App 自身要连真后端才能跑到页脚）。

## 5. 交付文件

| 文件 | 内容 |
|---|---|
| `frontend/tui/src/setup-routing.ts` | 新增：槽别名/预设文案表、`routeBoxes()`、`setupSlotFields()`、`routeSummary()`、`routingStatusText()`、`presetIndexOf()`、`slotIndexOf()`（纯函数，无 solid 依赖） |
| `frontend/tui/src/setup-routing.test.ts` | 新增：8 个用例，覆盖双槽选项、custom-only 载荷、预设预选、三行摘要、状态栏 hybrid 标记、中英文案 |
| `frontend/tui/src/app.tsx` | 改：`SetupScreen` 增两屏、预设列表改读 `runtime_profiles`、细化页两方框 + 键盘、custom 顺序、载荷、确认页三行、状态栏组件、对话框高度 accessor（见 §6 缺陷） |
| `frontend/tui/scripts/manual-route-wizard-check.tsx` | 新增：120×30 fixture 渲染真实 `SetupWizardDialog` + 状态栏，逐键断言并落帧 |
| `docs/claude-tui-route.md` | 本文档 |

## 6. 顺带修掉的两个真实缺陷（都在写域内）

1. **对话框高度写成了常量**（`app.tsx:1680-1697`）。改造前是
   `const dialogHeight = screen() === "provider" || screen() === "summary" ? 24 : 22`，
   在组件初始化时求值一次——那一刻 `screen()` 恒为 `"runtime"`，于是**所有屏幕都是 22 行**，
   `provider`/`summary` 想要的 24 行从未生效。改成 accessor 后按屏幕返回高度（确认页 26、
   供应商/细化页 24、其余 22），`left`/`top` 同样变成 accessor（原来窗口尺寸变化也不会重新居中）。
2. **内容超出内容区时 opentui 会静默截断**：内容区 = `height - padding 4 - 边框 2`，超出部分
   丢掉溢出行（首行）+ 保留上一次的字符残影（实测 `qwen3.5:4blash`、`API Keye保留现有ash`）。
   确认页云端分支的内容是 19 行（三行摘要 + 5 行 Provider 明细 + 6 行通用项 + 提示 + 页脚），
   22 行对话框只有 16 行内容区，实测被截成 12 行（"运行模式"、"模型"、"自动发布" 三行直接消失）。
   修法是给足高度（26 行 → 20 行内容区），并把确认页底部那句会换行的长提示压成一行。
   细化页的内容固定 16 行（+ 最多 1 行错误 = 17 ≤ 18），同样按这个预算设计。

> 这两条是本任务里最容易复发的坑：**新增/修改 TUI 屏幕时先算内容行数**，否则症状是"文字莫名消失/串行"而不是报错。

## 7. 验证与证据

命令（PowerShell，在 `frontend/tui` 下，`TEMP/TMP` 指向 `.pytest_claude`）：

| 命令 | 结果 |
|---|---|
| `bun run typecheck` | exit 0（`tsc --noEmit` 无输出） |
| `bun test src` | **128 pass / 0 fail**，615 expect()，12 文件（改造前基线 120 pass / 11 文件；新增 `setup-routing.test.ts` 8 个用例） |
| `bun --preload @opentui/solid/preload scripts/manual-route-wizard-check.tsx` | **ALL PASS**（64 条断言，0 fail），帧落在 `.pytest_claude/ai-pr-review-route-check/` |

`manual-route-wizard-check.tsx` 覆盖：

- **[A] custom 全流程**：第 1 屏列出后端 4 档预设 → ↓↓↓ + Enter 进 `route_chat`（帧含 `云端 deepseek-flash` / `本地 qwen3.5:4b` / `混合 按文件复杂度自动分流`）→ ↓ 只动对话方框 → Tab + ↓ 只动审查方框 → ← + ↑ 让对话回绕 → Enter 进 `route_review` → ↓ 选到 混合 → Esc 退回 `route_chat` → Enter 直达 GitHub Token（证明 custom 顺序无 Provider/Key 屏）→ 确认页三行 + 载荷
  `{"runtime_profile":"custom","chat_slot":"local","review_slot":"hybrid",…}`，无 `provider_name` / `local_model`。
- **[B] 预设分支**：云端预设直接进 Provider 屏、不经过细化页；确认页显示 `运行模式 云端` + 两行模型预览；载荷 `runtime_profile=cloud` 且**不含** `chat_slot` / `review_slot`。
- **[E] 本地预设分支（回归）**：本地预设进入本地端点屏、不经过 Provider 屏与细化页；确认页 `运行模式 本地` + 三行摘要 + 本地引擎明细；载荷 `runtime_profile=local`、含 `local_provider=ollama`、**不含**槽位字段。
- **[C] en-US**：屏标题 `Route detail · chat model`、方框 `Chat model / Review model`、`Hybrid auto-route by complexity`、页脚 `↑↓ select · Tab/←→ switch box · Enter next · Esc back`。
- **[D] 状态栏**：`CHAT deepseek-flash · REVIEW qwen3.5:4b`；hybrid → `REVIEW 混合 (local↔remote)`（en：`Hybrid (local↔remote)`）；无 `routing` → `cloud · 就绪 · deepseek-flash · …`。

### 未验证 / 未覆盖

- **真终端**：以上是 `testRender` 的帧证据（120×30），没有在真实 Windows Terminal 里手工跑过 Ctrl+P 全流程。
- **未跑真后端**：`config.setup` 只到"载荷"这一层（stub 后端记录 payload），没有让 Python `_apply_setup` 真正落盘验证 `chat_slot`/`review_slot` 的写回；不过载荷字段名/取值与 `_setup_ack` 的读取（`jsonl_server.py:813-820`）逐字对应，且有 `tests/test_jsonl_backend.py` 覆盖后端侧。
- **`frontend/tui/dist/` 未重建**：该目录是 gitignore 的构建产物（`.gitignore:47`），本任务只改 `src/**`；打包入口需要重建时由构建流程负责。

## 8. 未决项

1. **槽别名表在前端留了一份**（`setup-routing.ts:73`）：后端没在 `config.options` 暴露"所有槽别名的 label 列表"（只有当前生效槽位的 `routing.*.label`）。建议后端补 `slots` 或 `slot_labels`，前端删掉这张表。
2. **custom 不校验槽位是否真的可用**：后端 `_apply_setup` 的 custom 分支只写槽位，不检查远端 Provider 是否有 Key、本地模型是否存在。前端只能显示实情（模型名缺失时写"未配置"）而不能阻止保存——选 custom + 云端槽但从未配置过远端时，会保存成功、首次请求才报错。建议后端在 custom 分支加一条软校验（或在 TUI 里补一个"该槽未配置"的确认步骤）。
3. **对话框内容区预算是隐式契约**：目前靠注释说明（`app.tsx:1783-1787`）。若后续再往细化页/确认页加行，需要同时调整 `dialogHeight()`，否则又会静默截断。
4. **`offline` 旧值**：`runtime_profiles` 已不再提供，但旧的 `runtime_profile="offline"` 快照仍可能来自历史配置；前端兜底表与 `presetLabel` 保留了它（读取时等价"本地"）。
