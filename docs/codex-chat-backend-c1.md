# Chat 后端第二批（codex-chat-backend-c1）

> 任务：`.agent-bus/tasks/codex-chat-backend-c1.json`
> 契约：本任务的字段名与前端组（mimo）第二批按 **契约 v1** 对接，见下方 §2。
> 背景文档：`docs/chat-experience-plan.md`、`docs/reasoning-effort-probe.md`、
> `docs/model-reasoning-probe.md`（本地端点实测）。

---

## 0. 执行记录（诚实版）

codex（GLM-5.3-Flash · tuluo 中转）完成了全部代码与测试改动，但在收尾阶段
被中转配额挡住：`{"error":{"code":"1214","message":"输入不能为空"}}`
连续 5 次重试耗尽后进程退出（exit 1），**未写报告与本文档**。

主控（codex-in-Codex）在其落盘基础上完成验收，发现并修复 4 处缺陷，
补写本文档：

| # | 缺陷 | 性质 | 修复 |
|---|---|---|---|
| 1 | `_chat()` 内 `assistant.reasoning_delta` 事件引用未定义的 `request_id` | 真实 bug（NameError） | `_chat` 增加 `request_id` 参数，调用点传入 |
| 2 | 同一回调引用未定义的 `events`（属于调用者作用域） | 真实 bug（NameError） | 改为**调用者注入 `on_reasoning` 回调**，与其他回调一致；`_chat` 内部只做 `reasoning_parts` 捕获 |
| 3 | `/history` 分支顺序错误：`<run_id>` 详情语义不可达、无 session 直调即 `Session not found` | 真实 bug（旧语义被吞） | 重排为「`--runs` → 运行列表；`<run_id>` → 详情+绑定；其余 → 对话消息（无 session 时降级运行列表）」 |
| 4 | `test_compact_replaces_old_messages_with_a_summary` 断言笔误（`old 0` 应为 `old 1`）+ 缺 `ProviderResponse` import | 测试缺陷 | 已更正 |

---

## 1. 交付清单

| 项 | 内容 | 关键位置（jsonl_server.py） |
|---|---|---|
| C4 | `assistant.finished.duration_seconds` | 事件构造 ~2120；会话落盘 ~2076 |
| C5 | `assistant.reasoning_delta` 事件 + `finished.reasoning`；回调链 `base.stream_chat(on_reasoning=...)` → `openai.py` 解析 `reasoning_content` → `jsonl_server` | 事件 ~2047（现在由调用者发布）；`capture_reasoning` ~2040 |
| C6 | `preferences.chat_reasoning_effort`（off/low/high/max/auto）+ `/think` 命令 + 档位预算预留；本地 Ollama 置灰（`state:"unsupported"`，见 ~3368） | `_chat_reasoning_effort` ~1460；预算 ~2025-2046 |
| A4 | `assistant.finished.warning`（`"over_budget"` / null） | ~2112 |
| A5 | `assistant.finished.usage` + `context{used_tokens,budget_tokens,used_percent,trimmed_messages,compacted}` | `_chat_usage_payload` ~2171-2194；事件 ~2118 |
| A6 | `/compact [指令]`：保留最近 10 轮（20 条）原文，更早压缩为摘要并替换；失败保留原历史 | `_compact_chat_history` ~2258；命令分支 ~2314 |
| A7 | `/history` 默认列对话消息；`/history --runs` 保留审查历史；`/history <run_id>` 载入并绑定 | `_chat_history_payload` ~2225；命令分支 ~3001 |

支撑改动：`services/model_providers/base.py`（`ProviderResponse.usage/reasoning` +
`_normalize_usage`）、`services/model_providers/openai.py`（`on_reasoning` 线程安全
emit + usage/reasoning 透传）。`config.py` 增加 `chat_reasoning_effort` 偏好与归一化。

### 本地模型的预算兜底（主控补充）

实测：本地端点对 `thinking`/`reasoning_effort` 的处理**取决于路径**——非流式被忽略
（`docs/model-reasoning-probe.md`；且 12/16 次思考吃满 `max_tokens=2000` 导致**答案为空**），
流式 `think=false` 生效（`docs/chat-live-verification.md`）。产品决策（2026-09-26）：
本地固定快速模式、不展示思考（`OllamaProvider` 的 `think=False` 保留）。
因此 `auto` 档 + 本地 provider 时：保留尽力而为的 `reasoning_effort="none"`，
并额外预留 `CHAT_REASONING_TOKEN_BUDGETS["high"]`（8000）预算，保证答案落地。

---

## 2. 契约 v1（前端消费，已冻结）

```text
assistant.finished: {
  text, session_id, request_id,
  duration_seconds: float,
  usage: {prompt_tokens, completion_tokens, total_tokens} | null,   # 优先真实 usage
  context: {used_tokens, budget_tokens, used_percent, trimmed_messages, compacted,
            budget_source} | null,   # budget_source: config|model_spec|fallback（2026-09-26 扩键）
  reasoning: string | null,
  warning: "over_budget" | null
}
assistant.reasoning_delta: { session_id, request_id, text }        # 与 assistant.delta 平行
/think off|low|high|max|auto  → { kind:"think", state:"set"|"unsupported", ... }
/compact [指令]               → { kind:"compact", kept_turns, replaced_messages,
                                   before_tokens, after_tokens, summary_chars } | error
/history [N]                  → 对话消息（有 session）；--runs → 审查历史；<run_id> → 详情
```

---

## 3. 验证（主控独立复跑）

```text
TEMP/TMP=.pytest_codex  python -m pytest -q --no-cov
→ 1057 passed, 1 skipped, 2 warnings in 91.49s

单文件: tests/test_jsonl_backend.py → 194 passed
语法: ast.parse(jsonl_server.py) OK
```

覆盖：C4/C5 事件字段与历史隔离、/think 持久化与本地置灰、A4/A5 有/无 usage
两条路径、/compact 成功与失败保留原历史、/history 三模式、`<run_id>` 绑定。

---

## 4. 未决项

1. 前端（TUI）对契约 v1 的消费由 mimo 第二批交付（已提交 `1c1a829`，兼容字段缺失）；
2. `/compact` 的摘要调用走当前 chat provider——本地 provider 压缩长历史时同样受
   思考预算影响（已由上面的兜底覆盖，但本地压缩耗时较长属预期）；
3. `chat_reasoning_effort` 目前是全局偏好（非按 provider 记忆），多 provider 切换
   场景下的记忆粒度留待后续（B3 设置助手扩展时一并考虑）。
