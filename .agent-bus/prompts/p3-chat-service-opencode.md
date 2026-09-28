你是本项目的协作 agent（opencode）。**Phase 3 后端任务**：实现"审查结果问答"的**服务层**（新增独立模块），
HTTP 路由由主控在 `web_server.py` 接线（**你不要改 web_server.py**）。

## 目标
让用户在 Web 工作台里对**某次已审查的 run** 追问（例如"第 3 条为什么判中风险？"），
复用 CLI 侧已有的 review 上下文装配能力，而不是重写一套。

## 冻结的 HTTP 契约（主控接线用，你的服务层必须能产出这个形状）
```
POST /api/chat   { "run_id": "<可选>", "text": "<问题>" }
200 {
  "reply": "<模型回答>",
  "model": "<模型名>",
  "usage": { "prompt_tokens": 812, "completion_tokens": 120, "total_tokens": 932 } | null,
  "context_meta": {
    "bound_run": "<run_id>" | null,
    "token_estimate": 382 | null,
    "sections": ["run_summary", "findings", ...],
    "truncated": false,
    "note": "<降级说明，正常为空串>"
  }
}
错误（由主控映射成 HTTP）：
- `text` 缺失 → 抛 ChatError("invalid_request", ...)
- `run_id` 给了但查不到 → 抛 ChatError("not_found", ...)
- 没配模型 Key → 抛 ChatError("missing_api_key", ...)
- 上游模型报错 → 抛 ChatError("chat_failed", ...)
```

## 要做的事
1. 新建 `src/ai_pr_review/web_chat.py`：
   - `class ChatError(Exception)`：`code` + `message`（与 `services/publish_service.py` 的 `PublishError` 同形）；
   - `async def answer_with_context(config: AppConfig, *, run_id: str = "", text: str = "") -> dict[str, Any]`：
     a) `text` 为空 → `ChatError("invalid_request", "text is required")`；
     b) `run_id` 非空 → 用 `ResultStore(config.result_store)` 取 `get_result` / `get_run_summary`；
        取不到 → `ChatError("not_found", f"未找到审查记录：{run_id}")`；
     c) **上下文装配优先复用 `ai_pr_review/services/review_context.py`**（`build_review_context` /
        `build_review_context_meta` / `wrap_review_context` / `estimate_tokens` 中能用上的全用上，
        不要自己拼一套 Markdown）；把 run 摘要 + findings（含文件/行号/严重度/证据状态）+ PR 链接
        包进上下文，并在 `context_meta.sections` 里如实列出实际注入了哪些段；
     d) 未给 `run_id` → 纯对话（`bound_run=null`、`token_estimate=null`、`sections=[]`）；
     e) 用**现有**的模型客户端创建方式（参考 `backend/jsonl_server.py` 的 `_chat` 或
        `services/model_providers/factory.py:create_model_provider`，选依赖最少、最稳的那条），
        `await` 调用并把 `reply` / `model` / `usage` 取出来；`usage` 拿不到就回 `null`（不要编造）；
     f) 缺少 Key（`config.ai_client.api_key`/`provider.api_key` 都为空且不是 local）→
        `ChatError("missing_api_key", "未配置模型 API Key：请先在设置页或 CLI 配置，或切换到本地模型。")`；
     g) 上游异常 → `ChatError("chat_failed", f"模型调用失败：{exc}")`；
     h) 预算/截断：若拼出的上下文超过 `config.preferences.chat_context_budget`（缺失回落到既有默认），
        先裁 findings，再裁 PR 摘要，最后只留问题本身，并在 `truncated=true` + `note` 里说明裁掉了什么。
2. `tests/test_web_chat.py`（新文件，**不要改 tests/test_web_server.py**）：至少 8 条用例
   - `test_requires_text`
   - `test_unknown_run_is_not_found`
   - `test_missing_api_key_raises`
   - `test_plain_chat_without_run_has_empty_context_meta`
   - `test_bound_run_injects_findings_and_reports_sections`
   - `test_context_meta_token_estimate_is_int`
   - `test_over_budget_truncates_and_notes`（用极小 budget 触发）
   - `test_upstream_failure_becomes_chat_failed`
   模型调用**必须打桩**（`monkeypatch.setattr` 替换 provider 工厂或答案函数内部调用点），
   **绝不发起真实网络请求**。
3. `docs/DEV_RECORD.md`：设计（复用了哪些既有函数，file:line）、降级矩阵、
   截断策略、用例清单、验证数字、未决项。

## 约束
- 只写：`src/ai_pr_review/web_chat.py`、`tests/test_web_chat.py`、`docs/DEV_RECORD.md`；
- 禁止改 `web_server.py` / `web_config.py` / `web/src/**`；禁止 git；禁止读取或输出任何真实凭据（测试里用假串）。

## 验证（必须真跑，报数字）
```bash
TEMP=.pytest_opencode TMP=.pytest_opencode python -m pytest tests/test_web_chat.py -q --no-cov
TEMP=.pytest_opencode TMP=.pytest_opencode python -m pytest tests/test_web_server.py -q --no-cov
```

完成后按总线报告：
`python scripts/agent_bridge.py report p3-chat-service --agent opencode --status completed --summary "<一句话>" --evidence "<文件:行号 + 两段测试数字 + 复用了哪些既有函数>" --blocker "<未决项，没有写无>"`
