# 审查结果问答服务层（Phase 3 后端 · p3-chat-service）

**一句话结论**：`POST /api/chat` 的服务层落在新模块 `src/ai_pr_review/web_chat.py` ——
参数校验 + **复用** `services/review_context.py` 装配审查上下文 + 复用 CLI 的建客户端方式调模型，
输出冻结契约的 `{reply, model, usage, context_meta}`；`web_server.py` 一行未改（它已有的
`_handle_chat` 只做 code ↔ HTTP 映射）。

改动面：`src/ai_pr_review/web_chat.py`（新增）、`tests/test_web_chat.py`（新增）、本文档。
`web_server.py` / `web_config.py` / `web/src/**` 未改；未做任何 git 操作。

## 1. 契约与错误码

响应形状（服务层产出，路由原样转发，`web_server.py:742-743`）：

| 字段 | 取值 | 来源 |
| --- | --- | --- |
| `reply` | `response.text` | 模型原文（`web_chat.py:121`） |
| `model` | `provider_config.model_name or name` | 本轮实际所用槽位的模型（与 `jsonl_server._chat` 同口径） |
| `usage` | `{prompt_tokens, completion_tokens, total_tokens}` \| `null` | 供应商报多少转多少，拿不到回 `null`（`_usage_payload` `:269`） |
| `context_meta.bound_run` | `run_id` \| `null` | 传了 `run_id` 才有值 |
| `context_meta.token_estimate` | `int` \| `null` | 绑定时 = **实际注入**上下文的 `estimate_tokens`（可能为 0）；未绑定 = `null` |
| `context_meta.sections` | `list[str]` | 按最终文本里真实存在的段登记（`_sections_of` `:210`） |
| `context_meta.truncated` | `bool` | 内层裁过 **或** 外层裁过 |
| `context_meta.note` | `str` | 降级/裁剪说明；正常为空串 |

错误码 → HTTP（映射表在 `web_server.py:52`，本模块只抛 code + message）：

| code | 触发条件 | 位置 | HTTP |
| --- | --- | --- | --- |
| `invalid_request` | `text` 缺失/全空白/非字符串 | `web_chat.py:91` | 400 |
| `not_found` | `run_id` 查不到（`get_run_summary` / `get_result` 任一为空） | `web_chat.py:99` | 404 |
| `missing_api_key` | 非本地槽且 `ai_client.api_key` / `provider.api_key` 全空 | `_require_api_key` `:256` | 503 |
| `chat_failed` | 建客户端或 `provider.chat` 抛任何异常 | `web_chat.py:118` | 502 |

`ChatError`（`:67`）与 `services/publish_service.py:60` 的 `PublishError` 同形（`code` + `message`）。
校验顺序也沿用 `PublishService.load_target`（`publish_service.py:305-317`）的**先请求自身、后机器配置**：
配好 Key 不会让一个不存在的 run 变存在，所以 `not_found` 先于 `missing_api_key` 报。

## 2. 复用了哪些既有函数（file:line）

上下文装配**没有第二套 Markdown**，全部走 CLI 侧已冻结的渲染器：

| 复用点 | 位置 | 在本模块的用法 |
| --- | --- | --- |
| `build_review_context_meta` | `services/review_context.py:106` | `_bound_context` `:153`：渲染 L1 摘要 + L2 清单 + L3 全文（含文件/行号/严重度/证据状态）+ L4 过滤计数，并自带内层预算阶梯与裁剪标记 `trimmed` |
| `wrap_review_context` | `services/review_context.py:169` | `answer_with_context` `:110`：把渲染结果包进 `<review_context run_id=...>` + 诚实约束 `CONTEXT_RULES` |
| `estimate_tokens` | `services/review_context.py:88` | `token_estimate` `:178`：与注入预算同一口径（4 字符 ≈ 1 token） |
| `_budget_plans`（内层阶梯，经上面第一个函数间接复用） | `services/review_context.py:178` | L4 → L3（逐条减）→ L2（只留 critical/high）的裁剪顺序 |
| `ResultStore.get_run_summary` / `get_result` | `services/result_store.py:215` / `:227` | `answer_with_context` `:98-100` 的存在性校验（PR 链接来自 summary 的 `pr_url`，由 L1 渲染） |
| `create_model_provider` | `services/model_providers/factory.py:18` | `answer_with_context` `:115`：与 `cli._send_chat_message`（`cli.py:2456-2474`）同一条建客户端路径 |
| `resolve_chat_slot` / `CHAT_SLOT_VALUES` / `to_model_provider` | `config.py:1168` / `:792` / `:622` | `_chat_provider_config` `:234` 的槽位判定词汇 |
| `DEFAULT_CHAT_CONTEXT_BUDGET` | `config.py:754` | `_context_budget` `:215`：`chat_context_budget` 缺失/坏值的回落默认 |

刻意**没有**直接用的两处（及原因）：

- `build_review_context`（`review_context.py:95`）：它只是 `build_review_context_meta` 的薄封装
  （`:102`），本模块需要 `trimmed` 元数据来填 `truncated`，所以用带元数据的那一个；
- `jsonl_server._chat`（`backend/jsonl_server.py:3063`）与 `_chat_slot_config`（`:1823`）：
  都是 `JSONLBackend` 的方法/私有方法，实例化整个后端（`__init__` 会建会话存储、事件计数、
  审查超时等运行态）只为读一段配置太重。槽位判定在 `_chat_provider_config` `:234-253`
   **逐条镜像** `_chat_slot_config`，`usage` 解析在 `_usage_payload` `:269-301` 逐条镜像
  `_chat_usage_payload`（`jsonl_server.py:3250`），两者都用 `config.py` 的公开词汇写，
   并在 §7 未决项 1 记录漂移风险。

## 3. 截断策略

预算是 `config.preferences.chat_context_budget`（默认 8000，`config.py:754`；合法区间
`CHAT_CONTEXT_BUDGET_RANGE` `config.py:757`）。裁剪分两层，**顺序是冻结的**：

1. **内层（复用）**：`build_review_context_meta(token_budget=budget)` 自己的阶梯 ——
   L4（被过滤计数）→ L3（重点 finding 全文，逐条减到 0）→ L2（只留 critical/high）。
   L1 运行摘要永不裁剪（否则模型不知道在说哪一次审查，`review_context.py:19`）。
   裁过会在文本末尾附一行提示，并进 `context_meta.note` 的前半句
   （`已按 L4 → L3 → L2 顺序裁剪 ...`）。
2. **外层（本模块新增兜底）**：`_shrink_to_budget` `:185` —— 内层到底（L1 + critical/high L2）
   仍超预算时按任务书冻结的顺序继续裁：
   - 先裁 findings（删 L2/L3/L4，只留 L1 运行摘要）→ 装得下就停；
   - 仍超 → 再裁运行摘要（L1），**最后只留问题本身**（上下文为空，不注入 system prompt）。

   每一步把被裁的段名写进 `context_meta.note` 的后半句（`已继续裁剪 findings、run_summary，仅保留问题本身`）。

`truncated` 在任一层发生过裁剪时为 `true`；`sections` 永远按**最终文本**重新登记，
所以被裁掉的段不会出现在 `sections` 里（裁空时为 `[]`、`token_estimate` 为 `0`）。

## 4. 降级矩阵

| 情况 | 行为 | 用户可见 |
| --- | --- | --- |
| `text` 空 | 抛 `invalid_request` | 400 + `text is required` |
| `run_id` 查不到 | 抛 `not_found`（**先于** Key 检查） | 404 + `未找到审查记录：<run_id>` |
| 未绑定 run | 纯对话，不注入 system prompt | `bound_run=null`、`token_estimate=null`、`sections=[]` |
| run 存在但上下文装配失败（读库异常） | 按 `review_context` §9.2 C 的既定降级转普通对话，不中断 | `note=审查上下文装配失败，本轮按普通对话回答。`（`_bound_context` `:161-165`） |
| 本地槽（`ollama`/`local`）无 Key | 放行（本地豁免），并注入 `reasoning_effort="none"` | 正常回答 |
| 远端无 Key | 抛 `missing_api_key` | 503 + `未配置模型 API Key：请先在设置页或 CLI 配置，或切换到本地模型。` |
| 供应商报错 / 返回不可解析 | 抛 `chat_failed`，`str(exc)` 原样进 message | 502 + `模型调用失败：<exc>` |
| 供应商没报 usage | `usage=null`，**不编造** total | `usage: null` |
| 超预算 | 见 §3 | `truncated=true` + `note` |

## 5. 用例清单（`tests/test_web_chat.py`，10 条）

模型调用全部打桩：`monkeypatch.setattr(web_chat, "create_model_provider", ...)`（`_stub` `:79`），
断言打桩后的 fake provider 捕获的 `system_prompt` / `messages` / `kwargs`；**零真实网络请求**，
Key 一律用 `FAKE_KEY`（`:20`）这类可识别假串。

| 用例 | 行号 | 断言要点 |
| --- | --- | --- |
| `test_requires_text` | `:88` | 空白 `text` → `invalid_request` / `text is required` |
| `test_unknown_run_is_not_found` | `:98` | 未知 run → `not_found`，message 含 run id |
| `test_missing_api_key_raises` | `:108` | 无 Key → `missing_api_key`；且**工厂在 Key 检查前不得被构造**（fail 断言） |
| `test_upstream_failure_becomes_chat_failed` | `:123` | provider 抛 `RuntimeError` → `chat_failed`，含原文 |
| `test_plain_chat_without_run_has_empty_context_meta` | `:140` | 无 run：`context_meta` 五键全空、无 `system_prompt`、usage 透传 |
| `test_bound_run_injects_findings_and_reports_sections` | `:168` | `sections == [run_summary, findings, finding_details]`；上下文里有 PR 链接、`SQL injection risk`、`src/app.py:3`、`[high]`、`证据: unverified` |
| `test_context_meta_token_estimate_is_int` | `:193` | `token_estimate` 是 `int` 且 > 0，并等于从 `wrap_review_context` 里剥出的上下文本体的 `estimate_tokens` |
| `test_over_budget_truncates_and_notes` | `:210` | `chat_context_budget=1` → `truncated=true`、note 同时提到 `findings` 与 `run_summary`、`sections=[]`、`token_estimate=0`、不再注入 system prompt |
| `test_usage_is_null_when_provider_reports_none` | `:237` | 供应商无 usage → `usage is None`（不编造） |
| `test_local_slot_without_key_is_allowed` | `:246` | `chat_slot=local` + 无 Key → 放行，且 `reasoning_effort="none"` |

任务书点名的 8 条全部覆盖（同名）；另加 2 条（usage 空值、本地槽豁免）。

## 6. 验证数字（真跑）

```
TEMP=.pytest_opencode TMP=.pytest_opencode python -m pytest tests/test_web_chat.py -q --no-cov
    -> 10 passed in 0.38s
TEMP=.pytest_opencode TMP=.pytest_opencode python -m pytest tests/test_web_server.py -q --no-cov
    -> 68 passed in 35.19s
.venv313/Scripts/mypy.exe src/ai_pr_review/web_chat.py
    -> Success: no issues found in 1 source file
.venv313/Scripts/black.exe --check --line-length 100 src/ai_pr_review/web_chat.py tests/test_web_chat.py
    -> 2 files would be left unchanged
```

`tests/test_web_server.py` 的 68 条里含 `TestChatEndpoint` 5 条（`:823-896`）：其中
`test_missing_text_is_rejected` / `test_unknown_run_is_not_found` 走的是**真实**服务层
（路由接线 + code ↔ HTTP 映射），另 3 条按该文件既定做法 mock `answer_with_context` 只锁协议层。

## 7. 未决项

1. **槽位判定有两份实现**：`_chat_provider_config`（`web_chat.py:234`）镜像
   `jsonl_server._chat_slot_config`（`backend/jsonl_server.py:1823`）。后端改判定规则时这里会漂移
   （今天两边逐条一致：remote → 主 Provider；显式 `chat_slot=local` → 本地槽；环境覆盖 → 主 Provider；
   由 `local_only` 推导 → 主 Provider 是 Ollama/Local 时以主槽为准）。根治办法是把它抽成 `config.py`
   的公开函数，但那要改 `jsonl_server.py` / `web_server.py`，超出本任务 write_scope。
2. **自定义中转站请求头不进 chat 链路**：`ProviderConfig.to_model_provider()`（`config.py:622`）不带
   `headers` / `extra_params`。这不是本任务引入的——后端 `_chat_slot_provider` 走的同一条转换
   （`jsonl_server.py:2172`）；`cli._send_chat_message` 用的 `ai_client.model_provider` 则会带上。
   两边现状就不一致，本任务选择与后端 chat 对齐，未改既有代码。
3. **纯对话不注入 system prompt**：未绑定 run（或上下文被裁空）时只发用户消息，语言偏好
   （`preferences.language`）没有显式告知模型，依赖"按提问语言回答"的默认行为。与 CLI 的差异来自
   `cli._response_language_instruction`（`cli.py:1807`）要 import 整个 `cli`（click/rich），
   为保持本模块依赖最小未引；需要时可把它下沉到公共模块再复用。
4. **`token_estimate` 对"装配失败/裁空"记 `0` 而非 `null`**：`null` 保留给"未绑定 run"这一种情况，
   `0` 表示"绑定了但确实没注入任何上下文"。若主控前端想把两者合并展示，需要确认这个口径。
