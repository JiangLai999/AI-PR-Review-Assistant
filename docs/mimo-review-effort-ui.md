# TUI 配置助手 · review 思考档位（mimo-review-effort-ui）

> 任务：`.agent-bus/tasks/mimo-review-effort-ui.json`（agent `mimo`）· 日期：2026-09-26
> 后端契约：提交 `4321852`（`preferences.review_reasoning_effort` + `config.options` / `config.setup`）
> 语义与成本：`docs/review-reasoning-assessment.md` · 用户向说明：`docs/chat-features.md` §3.1

---

## 1. 目标

在 TUI 配置助手中接入 **review 独立思考档位**（`review_reasoning_effort`，五档
`off | low | high | max | auto`，默认 `off` = 现状），补齐 `docs/chat-features.md` §3.1
里"TUI 界面尚未接入，另行排期"的那一步。

## 2. 后端契约（只读确认）

| 出口 | 形状 | 说明 |
|---|---|---|
| `config.options.review_reasoning_effort` | `{value, options:[{value,label}], state?, reason?}` | `state`/`reason` 仅在 review 槽供应商**不注入**思考参数时出现 |
| `config.setup` | `review_reasoning_effort: "off"\|"low"\|"high"\|"max"\|"auto"` | 字符串；缺失 = 保持落盘值 |
| `model.status.review_reasoning_effort` | 同 `config.options` | 三出口同键同形 |
| `config.snapshot.review_reasoning_effort` | 纯字符串 | 当前档位 |

**置灰判据**（前端只认后端显式字段，不自行推导供应商能力）：

- `state === "unsupported"` → 置灰 + 显示 `reason`
- 无 `state` 字段（正常注入 set/transparent、旧后端）→ 不置灰

## 3. 设计决策

### 3.1 选项屏（`review_effort`）

- **位置**：配置助手第 5 阶段"界面与输出"，紧跟"仓库上下文"屏（同为 review 行为设置）
- **选项清单 owner 是后端**：`config.options.review_reasoning_effort.options` 给什么就渲染什么；
  缺字段时用 `FALLBACK_REVIEW_EFFORT_OPTIONS`（`setup-routing.ts`）兜底，词表与后端
  `REVIEW_REASONING_EFFORTS` 逐字一致
- **缺字段不显示**：旧后端没有 `review_reasoning_effort` 时，`order()` 过滤掉该屏，
  确认页也不显示审查思考行
- **label 中英双语**：后端 label 是 `中文 / English` 双语串，按 `ui_language` 取一侧
  （`reviewEffortBilingualLabel`，与 `setup-repo-context.ts` 的 `bilingualLabel` 同口径）
- **成本提示**（用户必须看到代价）：
  - 选项 description 行：每档显示对应成本短语
  - 屏底动态成本行：随 ↑↓ 选择切换，`off` 灰色、思考档橙色
  - `off` = 与现状相同（基线）；`low/high/max` = 输出 tokens 约 ×3.6、耗时约 ×2.9（真机实测，max 档）；
    `auto` = 不干预，由供应商默认决定
- **置灰**：`state=unsupported` 时顶部显示 `⚠ reason`（红色），select 配色降为灰色系

### 3.2 载荷构造

`setupReviewEffortField(value)` 显式发送屏幕上这一档（与 `repo_context` / `ui_language`
一致）；空串返回空对象 = 不发送。

### 3.3 确认页

新增一行 `审查思考 / Review th`：显示双语 label（`reviewEffortSummary`）。

## 4. 修改文件

| 文件 | 改动 |
|---|---|
| `frontend/tui/src/protocol.ts` | `ReviewEffortLevel` / `ReviewEffortOption` / `ReviewReasoningOptions` 类型 + `parseReviewReasoningOptions` |
| `frontend/tui/src/format.ts` | `reviewEffortBilingualLabel` / `formatReviewEffortCost` / `formatReviewEffortDisabled` / `formatReviewEffortSummary` |
| `frontend/tui/src/setup-routing.ts` | `FALLBACK_REVIEW_EFFORT_OPTIONS` / `reviewEffortChoices` / `reviewEffortIndexOf` / `reviewEffortValue` / `reviewEffortStoredValue` / `reviewEffortSummary` / `setupReviewEffortField` / `reviewEffortIsDisabled` |
| `frontend/tui/src/app.tsx` | 新屏 `review_effort`（类型/阶段/标题/顺序/状态/渲染/确认页/载荷） |
| `frontend/tui/src/protocol.test.ts` | 4 条解析器测试 |
| `frontend/tui/src/format.test.ts` | 3 条格式化测试 |
| `frontend/tui/src/setup-routing.test.ts` | 7 条选项/预选/载荷/置灰测试 |
| `frontend/tui/scripts/manual-route-wizard-check.tsx` | [H]–[H5] 帧断言（120×30 / 209×51 / en-US / 置灰 / 旧后端） |

## 5. 帧路径

帧输出到 `TEMP/ai-pr-review-route-check/`（TEMP 指向 `.pytest_mimo`）：

| 帧 | 场景 |
|---|---|
| `frame-review-effort-zh.txt` | 120×30 zh-CN 选项屏（五档 + 成本提示 + off 高亮） |
| `frame-review-effort-max-zh.txt` | ↓×3 到 max 档（×3.6 / ×2.9 成本提示） |
| `frame-review-effort-summary-zh.txt` | 确认页含审查思考行 |
| `frame-review-effort-zh-large.txt` | 209×51 选项屏 |
| `frame-review-effort-en.txt` | en-US 文案 |
| `frame-review-effort-disabled-zh.txt` | 置灰态（state=unsupported） |
| `frame-review-effort-legacy-summary.txt` | 旧后端缺字段 → 跳过该屏 |

## 6. 验证命令与真实数字

```bash
cd frontend/tui
# typecheck
bun run typecheck                    # exit 0

# 单测
bun test src                         # 191 pass, 0 fail, 933 expect() calls (13 files, 2.89s)

# 帧断言
TEMP/TMP=.pytest_mimo bun --preload @opentui/solid/preload scripts/manual-route-wizard-check.tsx
#   ALL PASS（含新增 [H]–[H5] 共 19 条断言）
TEMP/TMP=.pytest_mimo bun --preload @opentui/solid/preload scripts/manual-chat-markdown-check.tsx
#   ALL PASS
```

## 7. 未决项

无。
