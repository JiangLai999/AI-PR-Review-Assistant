# Chat 真实链路验收（本机 Ollama）

> 脚本：`scripts/verify_chat_live.py`（可复跑）· 执行：主控（codex）
> 背景：stub 契约验收见 `docs/chat-contract-verification.md`（`35f54c1`）；
> 本文是**第二层证据**——不打桩，走项目自己的 `JsonlBackend` + 真实 Ollama provider。
> 环境：Ollama `127.0.0.1:11434`，模型 `qwen3.5:4b`。

---

## 1. 运行记录（两次，真实输出）

```bash
python scripts/verify_chat_live.py --timeout 600
python scripts/verify_chat_live.py --timeout 600 --prompt "<三箱标签问题>"
```

| 轮次 | 提示词 | 实测耗时 | 事件计数 | 思考长度 | 答案长度 |
|---|---|---|---|---|---|
| #1 | "用一句话说明什么是 SQL 注入" | 0.7s | delta×29 + started + finished | **0 字符** | 61 字符 |
| #2 | 三箱标签问题（长链推理） | 46.3s | delta×2065 + started + finished | **0 字符** | 4361 字符 |

`finished` 关键字段（两轮一致）：

```
duration_seconds : 0.718 / 46.291（真实且 >0）
warning          : null
usage            : {prompt_tokens: 0, completion_tokens: 0, total_tokens: 0}   ← 真实差异 ①
context          : {used_tokens: 16/33, budget_tokens: 8000, used_percent: 0.2/0.4,
                    trimmed_messages: 0, compacted: false}                     ← 走估算，符合口径
```

## 2. 六条断言结果

| # | 断言 | 结果 | 说明 |
|---|---|---|---|
| a | 事件顺序 `started → … → finished` | ✅ PASS | 无 failed/cancelled |
| b | 思考与正文隔离 | ✅ PASS（空真） | 本地 reasoning 为空，隔离断言不具区分力（见差异 ②） |
| c | `duration_seconds > 0` | ✅ PASS | 0.718s / 46.291s，与墙钟一致（0.73s / 46.30s） |
| d | `usage` 真实返回 | ❌ **真实差异** | 端点返回的 usage 三键全 0（见差异 ①） |
| e | `context.used_tokens` 有值 | ✅ PASS | 16 / 33 — usage 为 0 时自动走估算，符合"优先 usage、缺失才估算" |
| f | 答案非空（预算兜底有效） | ✅ PASS | 61 / 4361 字符，未出现"思考吃满预算→空答案" |

## 3. 两个真实差异（stub 测试覆盖不到）

### 差异 ①：Ollama 兼容端点的 usage 全为 0

`assistant.finished.usage` 三键均为 0（非 null）。行为链路正常（字段结构齐全），
但**数值不可用于计费或精确预算**；`context.used_tokens` 因此走 `estimate_tokens` 估算
（16 / 33 tokens），`budget_source` 语义上属"fallback 估算"。

**影响**：本地 chat 的上下文占用提示是估算值（云端 DeepSeek 走真实 usage）。
**建议**：产品文案无需改（估算已是兜底口径）；若要精确，需改走 Ollama 原生
`/api/chat` 的 `prompt_eval_count`（另开任务）。

### 差异 ②：本地链路永远收不到 `assistant.reasoning_delta`

抓包证据（同端点、同模型、去掉 `think` 参数）：

```
frame 1: delta keys = ('content', 'reasoning', 'role')
    content   = ''
    reasoning = 'Here'
```

→ **Ollama 的 OpenAI 兼容端点在有思考时会返回 `delta.reasoning`**，
我们的 `OpenAICompatibleProvider`（`openai.py:226-240`）也确实解析该字段。

但产品链路上 `reasoning_delta` 为 0 帧。根因在 provider 选择：

```python
# src/ai_pr_review/services/model_providers/ollama.py
async def stream_chat(self, messages, on_delta, **kwargs):
    kwargs.setdefault("think", False)      # ← 所有流式调用都被强制关思考
    return await super().stream_chat(...)
```

`OllamaProvider.stream_chat` 对**所有**流式请求强制 `think=False`（历史注释说明它
是为 Copilot routing 设计的快速模式）。实测该参数在流式模式下生效
（模型不再返回 reasoning 帧），因此：

- 本地 chat 没有思考内容可展示（C5 对本地为空）；
- 这也解释了 46s 长答案：模型仍在生成很长内容，只是不回流思考通道。

**与 probe 结论的关系**：`docs/model-reasoning-probe.md` 用**非流式**请求测出
`think=false` 被忽略（R1 FAIL）——本次证实**流式模式下该参数有效**。
两处结论都需要保留：**同一参数在流式/非流式路径下行为不同**。

**影响与选项**（改动另开任务，本轮只记录）：

1. 维持现状：本地 chat 不做思考展示（档位已置灰，UI 语义一致），速度优先；
2. 想开放本地思考展示：把 `setdefault("think", False)` 限定到 routing 调用路径
   （或由 `_chat` 显式传 `think`），代价是本地回复明显变慢（本轮已观测 46s 级）。

## 4. 结论

- 契约 v1 在真实本地链路上**结构全部成立**（事件顺序/隔离/耗时/context/非空答案）；
- 两处"真实差异"都是**端点或 provider 行为**，不是契约破坏：
  usage 全 0（估算兜底已生效）、本地无 reasoning 帧（provider 强制关思考）；
- 是否开放本地思考展示属产品取舍，等用户决策后再动代码。

## 5. 复跑方式

```bash
python scripts/verify_chat_live.py                      # 默认短提示
python scripts/verify_chat_live.py --json               # 机器可读
python scripts/verify_chat_live.py --model <name> --timeout 900
```

退出码：`0` 全部断言通过；`1` 有断言失败；`2` 环境不可用（Ollama 不在线 / chat 失败）。
