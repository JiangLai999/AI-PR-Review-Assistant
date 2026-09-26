# Chat 契约 v1 独立验收报告

> 任务：`mimo-chat-contract-verify`（独立验收方）
> 契约：`docs/codex-chat-backend-c1.md` §2（契约 v1，字段名以此为准）
> 后端提交：`fa04897` · 前端提交：`1c1a829`
> 验收测试：`tests/test_chat_contract_events.py`（10 条，全绿）
> 日期：2026-09-26

---

## 1. 事件序列真实 dump 样例

摘自 `test_contract_event_sequence_is_legal_and_reasoning_is_isolated` 运行输出
（`python -m pytest -q --no-cov tests/test_chat_contract_events.py -s`，非手写）：

```jsonl
{"event": "assistant.started", "session_id": "668d823c27b44f75ba9b4002b0234039", "request_id": "turn"}
{"event": "assistant.reasoning_delta", "session_id": "668d823c27b44f75ba9b4002b0234039", "request_id": "turn", "text": "思考第一步。"}
{"event": "assistant.reasoning_delta", "session_id": "668d823c27b44f75ba9b4002b0234039", "request_id": "turn", "text": "思考第二步。"}
{"event": "assistant.delta", "session_id": "668d823c27b44f75ba9b4002b0234039", "request_id": "turn", "text": "你好"}
{"event": "assistant.delta", "session_id": "668d823c27b44f75ba9b4002b0234039", "request_id": "turn", "text": "，世界"}
{"event": "assistant.finished", "session_id": "668d823c27b44f75ba9b4002b0234039", "request_id": "turn", "text": "你好，世界", "duration_seconds": 0.016, "reasoning": "思考第一步。思考第二步。", "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}, "context": {"used_tokens": 20, "budget_tokens": 8000, "used_percent": 0.2, "trimmed_messages": 0, "compacted": false}, "warning": null}
```

**序列解读**：started → 2×reasoning_delta → 2×delta → finished。reasoning 流与正文流平行、互不混入；finished 携带完整元数据。

---

## 2. 断言清单与结果

| # | 断言维度 | 测试函数 | 结果 |
|---|---------|---------|------|
| a | 事件序列合法：started 最先、finished 最后、reasoning_delta/delta 只在中间 | `test_contract_event_sequence_is_legal_and_reasoning_is_isolated` | ✅ PASS |
| b | reasoning 文本不出现在任何 assistant.delta 的累积结果中 | 同上 | ✅ PASS |
| b | 累积 delta == finished.text（一致） | 同上 | ✅ PASS |
| c | finished.duration_seconds > 0 | 同上 | ✅ PASS（0.016） |
| c | finished.usage 三键齐全（prompt/completion/total_tokens） | 同上 | ✅ PASS |
| c | finished.context 五键齐全（used/budget/percent/trimmed/compacted） | 同上 | ✅ PASS |
| c | finished.warning 为 null | 同上 | ✅ PASS |
| d | 无 usage 时 context 走估算：used_tokens > 0 且 < budget | `test_contract_context_estimated_when_provider_omits_usage` | ✅ PASS |
| d | 无 usage 时 finished.usage 为 null | 同上 | ✅ PASS |
| e | provider 抛错 → assistant.failed 出现 | `test_contract_provider_error_emits_failed_without_finished` | ✅ PASS |
| e | provider 抛错 → 无 assistant.finished | 同上 | ✅ PASS |
| /think | state="set"（支持的 provider） | `test_contract_think_set_state` | ✅ PASS |
| /think | state="unsupported"（本地 Ollama） | `test_contract_think_unsupported_state` | ✅ PASS |
| /compact | 成功：kind + kept_turns + replaced_messages + before/after_tokens + summary_chars | `test_contract_compact_success_shape` | ✅ PASS |
| /compact | 失败：ok:False（协议级 error），原历史不变 | `test_contract_compact_failure_is_protocol_error` | ✅ PASS |
| /history | 有 session 默认：kind="history" + items 列表 | `test_contract_history_chat_messages_mode` | ✅ PASS |
| /history | --runs：runs 列表，无 kind 键 | `test_contract_history_runs_mode` | ✅ PASS |
| /history | \<run_id\>：详情 + bound 绑定 | `test_contract_history_run_detail_mode` | ✅ PASS |

**测试命令与数字**：

```
TEMP/TMP=.pytest_mimo  python -m pytest -q --no-cov tests/test_chat_contract_events.py
→ 10 passed in 1.30s

TEMP/TMP=.pytest_mimo  python -m pytest -q --no-cov
→ 1096 passed, 1 skipped, 1 warning in 96.61s
```

---

## 3. 边界结论

| 边界场景 | 行为 | 评估 |
|---------|------|------|
| provider 返回 usage | finished.usage 优先真实值，context.used_tokens 取 prompt_tokens | ✅ 符合契约（"优先真实 usage"） |
| provider 不返回 usage | finished.usage=null，context.used_tokens 由 estimate_tokens(JSON wire_history) 估算 | ✅ 符合契约（"估算"路径） |
| provider 抛异常 | assistant.failed 事件 + 协议级 error 回复；无 finished | ✅ 干净退出，不泄漏半截 finished |
| reasoning 混入正文 | 累积 delta 不含任何 reasoning chunk | ✅ 严格隔离 |
| /compact 摘要失败 | 原 session.messages 一字不动 | ✅ 失败安全 |
| /compact 无可压缩内容 | replaced_messages=0，before==after_tokens | ✅ 幂等空操作 |
| /think 本地 Ollama | state="unsupported" + reason 说明；不写偏好 | ✅ 置灰不误写 |
| /history 无 session + 无 --runs | 降级为审查历史列表（不报 "Session not found"） | ✅ 防死路 |
| duration_seconds 精度 | round(perf_counter 差值, 3)，最小 0.001s | ✅ 快速 stub 需 sleep 才能 >0；实测 0.016s |

---

## 4. 与前端 1c1a829 消费字段对照表

对照 `frontend/tui/src/protocol.ts`（1c1a829）的类型定义与 `parseXxx` 函数：

| 契约 v1 字段 | 后端输出 | 前端类型 / 解析 | 匹配 |
|---|---|---|---|
| `assistant.started.session_id` | ✅ | `isForeignSessionEvent` 读 `event.session_id` | ✅ |
| `assistant.started.request_id` | ✅ | `isCurrentAssistantEvent` 读 `event.request_id` | ✅ |
| `assistant.reasoning_delta.event` | `"assistant.reasoning_delta"` | `parseReasoningDelta` 检查 `event.event === "assistant.reasoning_delta"` | ✅ |
| `assistant.reasoning_delta.text` | ✅ | `parseReasoningDelta` 返回 `event.text` | ✅ |
| `assistant.delta.text` | ✅ | 前端累积为正文（app.tsx） | ✅ |
| `assistant.finished.duration_seconds` | float | `AssistantFinishMeta.durationSeconds` via `asFiniteNumber` | ✅ |
| `assistant.finished.usage.prompt_tokens` | int | `AssistantUsage.prompt_tokens` via `asFiniteNumber` | ✅ |
| `assistant.finished.usage.completion_tokens` | int | `AssistantUsage.completion_tokens` | ✅ |
| `assistant.finished.usage.total_tokens` | int | `AssistantUsage.total_tokens` | ✅ |
| `assistant.finished.context.used_tokens` | int | `AssistantContext.used_tokens` | ✅ |
| `assistant.finished.context.budget_tokens` | int | `AssistantContext.budget_tokens` | ✅ |
| `assistant.finished.context.used_percent` | float | `AssistantContext.used_percent` | ✅ |
| `assistant.finished.context.trimmed_messages` | int | `AssistantContext.trimmed_messages` | ✅ |
| `assistant.finished.context.compacted` | bool | `AssistantContext.compacted` | ✅ |
| `assistant.finished.reasoning` | string \| null | `AssistantFinishMeta.reasoning` via `asOptionalString` | ✅ |
| `assistant.finished.warning` | `"over_budget"` \| null | `AssistantWarning` 判定 `=== "over_budget"` | ✅ |
| `assistant.failed.message` | string | 前端通用 error 处理 | ✅ |
| `/think` → `kind:"think"` | ✅ | `parseThinkCommandResult` 检查 `kind === "think"` | ✅ |
| `/think` → `state:"set"` | `"set"` | 前端类型 `"applied" \| "unsupported" \| string` | ⚠️ 命名差异（见 §5.1） |
| `/think` → `state:"unsupported"` | `"unsupported"` | 同上 | ✅ |
| `/think` → `effort` | `effort: "low"` 等 | 前端读 `record.level` | ❌ 字段名不匹配（见 §5.2） |
| `/compact` → `kind:"compact"` | ✅ | `parseCompactCommandResult` 检查 `kind === "compact"` | ✅ |
| `/compact` → `kept_turns` | int | `CompactCommandResult.kept_turns` | ✅ |
| `/compact` → `replaced_messages` | int | **前端未消费** | ⚠️ 见 §5.3 |
| `/compact` → `before_tokens` | int | `CompactCommandResult.before_tokens` | ✅ |
| `/compact` → `after_tokens` | int | `CompactCommandResult.after_tokens` | ✅ |
| `/compact` → `summary_chars` | int | **前端未消费** | ⚠️ 见 §5.3 |
| `/history` 三模式 | 三套结构 | 前端无专用类型，通用展示 | ✅（无冲突） |

---

## 5. 发现的差异（不阻塞验收，供前端组参考）

### 5.1 `/think` state 命名差异

- **契约 v1 / 后端**：`state: "set"`
- **前端 protocol.ts**：`state?: "applied" | "unsupported" | string`

前端类型把成功态命名为 `"applied"`，后端返回 `"set"`。由于前端类型是 `"applied" | "unsupported" | string`（含兜底 `string`），**不会崩溃**，但前端若精确匹配 `"applied"` 将永远不命中。

**建议**：前端把 `"set"` 加入联合类型，或后端改返回 `"applied"`。当前行为安全。

### 5.2 `/think` effort 字段名不匹配（潜在 bug）

- **后端返回**：`{kind:"think", state:"set", effort: "low", ...}`
- **前端读取**：`parseThinkCommandResult` 读 `record.level`（不是 `record.effort`）

前端 `ThinkCommandResult.level` 将始终为 `undefined`，用户在界面上看不到当前档位。

**建议**：后端返回 `level` 字段（或前端改读 `effort`）。这是契约 v1 定义时的字段遗漏——契约只写了 `{kind:"think", state:"set"|"unsupported"}`，未规定档位字段名。

### 5.3 `/compact` 前端未消费 `replaced_messages` 与 `summary_chars`

前端 `CompactCommandResult` 只读 `kept_turns / before_tokens / after_tokens / ok / error / message`，不读 `replaced_messages` 和 `summary_chars`。这不影响功能（前端只是不展示这两个数），但契约 v1 定义了它们，属于**前端展示层未覆盖**。

### 5.4 `/compact` 失败路径是协议级 error 而非 `kind:"compact"` 结果

后端在摘要失败时返回 `ok:False + error{code, message}`（协议级错误），而不是 `{kind:"compact", ok:false, ...}`。前端 `parseCompactCommandResult` 只处理 `kind==="compact"` 的结果，失败时走通用错误提示。契约 v1 写的是 `| error`，与此一致。

---

## 6. 验收结论

**契约 v1 端到端验收通过**。10 条独立验收测试全绿，事件序列、字段完整性、隔离性、错误路径、命令结构均与 `docs/codex-chat-backend-c1.md` §2 一致。与前端 1c1a829 的消费字段交叉核对发现 3 处命名/覆盖差异（§5.1–5.3），均不导致前端崩溃，建议前端组下批修复 §5.2 的 `effort`/`level` 字段名。
