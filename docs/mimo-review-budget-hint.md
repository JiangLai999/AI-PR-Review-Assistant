# 小 max_output 模型 · 高档位思考预算封顶提示（mimo-review-budget-hint）

> 任务：`.agent-bus/tasks/mimo-review-budget-hint.json`（agent `mimo`）· 日期：2026-09-27
> 来源：`docs/review-reasoning-assessment.md` §10.7 #3（真机复验未决项）
> 前置：`docs/mimo-review-effort-ui.md`（review 思考档位屏）

---

## 1. 背景

review 的 `high`/`max` 档会预留 **+8000 / +12000** 思考预算（`CHAT_REASONING_TOKEN_BUDGETS`），
但预留仍受模型规格 `max_output` 封顶（`ai_client._review_tokens_with_budget`）。小
`max_output` 模型（能力档案/review 预设里 4096/8192 的模型）会把这笔预留**封顶吃光**
——用户选了 max 却拿不到对应的思考深度，界面上没有任何提示。

## 2. 后端字段来源（只读确认）

| 路径 | 字段名 | 构造点 |
|---|---|---|
| `config.options.model.slots.remote.max_output` | `max_output` | `jsonl_server._model_spec_options` → `_slot_spec_block("remote")` → `_spec_block_for` → `resolve_model_spec` |
| `config.options.model.slots.local.max_output` | `max_output` | 同上，`_slot_spec_block("local")` |
| `config.options.routing.review.slot` | `slot` | `_routing_snapshot`（`remote` \| `local` \| `hybrid`） |

- 精确键名是 **`max_output`**（`resolve_model_spec` 返回 dict 的顶层键，`config.py:724`）。
- 前端读取路径：`config.options.model.slots[routing.review.slot].max_output`。
- `hybrid` 槽无法指向单一模型 → 不取值、不提示。
- `slots` / `routing` 缺字段（旧后端）→ 不取值、不提示（兼容 + 不打扰）。

## 3. 阈值选择

**阈值：`max_output ≤ 16384`（含），且档位为 `high` 或 `max` 时显示提示。**

理由：

1. **总需求估算**：max 档预留 +12000，加上答案基础额度（4096–8192），总需求约 16k–20k；
   high 档预留 +8000，总需求约 12k–16k。16384 落在这个区间内，high/max 的预留
   几乎必然被封顶吃掉。
2. **业界常见小输出上限档**：anthropic claude-sonnet 8192、glm 系 4096、
   gpt-4o-mini 16384——16384 是"中等偏小"的分界。
3. **比 8192 更保守**：8192 以下 high 也会被封顶，但 12288–16384 之间 max 仍会被
   吃掉——用 16384 一并覆盖，避免漏报。
4. **不误报大模型**：deepseek-flash 384000、deepseek-chat 32768 都远大于此，
   不会误触提示。

阈值常量：`format.ts` 的 `REVIEW_BUDGET_CAP_MAX_OUTPUT = 16384`。

## 4. 提示文案

条件同时满足才显示（否则空串 = 不显示）：

1. `max_output` 是有限数字且 ≤ 16384；
2. 当前档位是 `high` 或 `max`（`off`/`low`/`auto` 不预留或预留较小，不打扰）。

| 语言 | 文案 |
|---|---|
| zh-CN | `该模型输出上限 N，高档位的思考预算会被封顶；建议 low 或更换模型` |
| en-US | `This model caps output at N; the thinking budget for high tiers will be capped. Prefer low or switch models.` |

- `N` 是实际 `max_output` 数值。
- 置灰态（`state=unsupported`）不显示提示——整档已置灰，封顶提示无意义。

## 5. 修改文件

| 文件 | 改动 |
|---|---|
| `frontend/tui/src/format.ts` | `REVIEW_BUDGET_CAP_MAX_OUTPUT` / `formatReviewBudgetCapHint` / `reviewSlotMaxOutput` |
| `frontend/tui/src/format.test.ts` | 4 条单测（阈值判定 + 文案组合 + 槽位取值） |
| `frontend/tui/src/app.tsx` | review_effort 屏追加封顶提示行（`reviewSlotOutputLimit` + `reviewBudgetCapHint`） |
| `frontend/tui/scripts/manual-route-wizard-check.tsx` | [H6]–[H8] 帧断言（提示出现 / off 不出现 / 大输出不出现） |
| `docs/mimo-review-budget-hint.md` | 本文档 |

## 6. 帧路径

帧输出到 `TEMP/ai-pr-review-route-check/`（TEMP 指向 `.pytest_mimo`）：

| 帧 | 场景 |
|---|---|
| `frame-review-budget-cap-hint-zh.txt` | 小 max_output（8192）× max → 提示出现 |
| `frame-review-budget-cap-off-zh.txt` | 小 max_output × off → 不出现 |
| `frame-review-budget-cap-roomy-zh.txt` | 大 max_output（384000）× max → 不出现 |

## 7. 验证数字

| 命令 | 结果 |
|---|---|
| `cd frontend/tui && bun run typecheck` | exit 0 |
| `cd frontend/tui && bun test src` | **205 pass / 0 fail**（995 expect） |
| `bun --preload @opentui/solid/preload scripts/manual-route-wizard-check.tsx` | **145 PASS / 0 FAIL**（ALL PASS） |
| `bun --preload @opentui/solid/preload scripts/manual-chat-markdown-check.tsx` | **87 PASS / 0 FAIL**（ALL PASS） |

## 8. 未决

无。产品决策"是否自动降档"（`docs/claude-backend-followup.md` §6.6）不在本任务范围，
本任务只补 UI 提示。
