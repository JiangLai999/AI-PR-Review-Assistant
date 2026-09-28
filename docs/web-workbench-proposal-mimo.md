# Web 审查工作台下一阶段方案（mimo）

> 任务：`web-wb-mimo`（方案商讨，只读源码、只写本文档）
> 范围：`web/` 前端 + `src/ai_pr_review/web_server.py` / `web_jobs.py` / `web_config.py`，以及 CLI 侧可复用的 chat 上下文能力。
> 证据口径：结论均给 `文件:行号`；不确定处显式写「未确认」。截图仅作辅证，且见 §1.3 的时效警告。

---

## 0. 一句话结论

审查结果问答**可以最小落地**，而且不必搬 `JsonlBackend` 整套会话机：`services/review_context.py` 已是纯函数服务，Web 只需新增一个**无状态 `POST /api/chat`**（请求体带 `run_id` + 问题 + 可选历史），服务端复用 `build_review_context_meta` / 仓库结构注入逻辑装配 system prompt。不建议在 Web MVP 做 TUI 命令面、SSE 流式、会话管理 UI。

工作台视觉/UX 的最大问题不是「不够好看」，而是**键盘焦点被删掉**、**中英混排**、以及 **`.shots/` 截图已过期到不能当验收基线**。优先级上，「只做 3 件」应选：**审查结果问答 MVP + 报告 Markdown 导出 + CI 构建前端**。

---

## 1. 现状核对（对照主控审计）

### 1.1 与主控审计一致的部分

| 主控说法 | 核对结果 | 证据 |
|---|---|---|
| 前端 hash 路由 6 页 | ✅ 准确 | `web/src/App.tsx:18-27`（overview/review/history/benchmark/api/settings） |
| `ReviewPage.tsx` 是核心，计划=同步 `/api/plan`，完整审查=异步 job + SSE | ✅ 准确 | `web/src/pages/ReviewPage.tsx:156-185`（runPlan / runReviewJob）、`:204`（`new EventSource('/api/jobs/${jobId}/events')`）、`web/src/web_server.py:177-183`（plan 同步 / async_job 202） |
| 结果区证据四态、严重度/证据筛选、FindingCard 等面板 | ✅ 准确 | `ReviewPage.tsx:35-36`（SEVERITIES/EVIDENCE）、`:589-600`（证据摘要）、`:666-715`（筛选 toolbar）、`components/ReviewPanels.tsx` |
| `HeroKnot` + `ParticleBackground`(21K) | ✅ 准确 | `web/src/components/HeroKnot.tsx:60`、`ParticleBackground.tsx`（21420 bytes） |
| `components.css` 约 57K | ✅ 准确 | `web/src/styles/components.css`（57059 bytes / 1126 行） |
| `web_server.py` 手写路由 + SSE + 静态托管 | ✅ 准确 | `web_server.py:83-136`（GET）、`:140-209`（POST）、`:321-406`（job SSE）、`:213-278`（静态） |
| `web_jobs.py` 线程 + queue，取消在文件边界生效 | ✅ 准确 | `web_jobs.py:13-14`（取消语义注释）、`:157-160`（thread）、`:101-123`（queue 订阅）、`:136-138`（`_check_cancelled`） |
| CLI 有 `pr-review chat` / `chat.send` / `session.*` / `/context` | ✅ 准确 | `cli.py:3710`（chat_command）、`jsonl_server.py:4284`（chat.send）、`:4210-4282`（session.\*）、`:2981`（`_context_status`） |
| 仓库结构注入三段 | ✅ 准确 | `jsonl_server.py:2582`（`_repo_files_for_chat`）、`:2857`（`_chat_repo_inventory`）、`:2920`（`_repo_tree_section`） |
| 思考档位 `/think`、压缩 `/compact` | ✅ 准确 | `jsonl_server.py:2334`（`_chat_reasoning_effort`）、`:3599`（`_compact_chat_history`） |
| `tests/test_web_server.py`、`web/.shots/` 40+ 张、`web/tools/*.mjs` 9 个脚本 | ✅ 基本准确 | 测试文件 561 行；`.shots/` 32 个 png + 2 个 txt；`web/tools/` 9 个 `.mjs` + 2 个辅助脚本 |

### 1.2 需要修正的审计细节

1. **测试类数**：主控写「13 个测试类」，实测 `tests/test_web_server.py` 为 **12 个测试类 + 1 个模块级测试函数**（`test_serve_command_hands_the_resolved_config_path_to_the_web_layer`，`tests/test_web_server.py:540`）。其余为 `TestFrontendAssets`…`TestPrPayload` 共 12 类（`:102-530`）。
2. **ApiPage「7/16 端点」**：`web/src/pages/ApiPage.tsx:11-52` 的 `ENDPOINTS` 数组实际是 **7 条**（health/plan/review/history/report/benchmark/feedback）。服务端真实路由见 `web_server.py:87-131`（GET 11 个入口）+ `:153-170`（POST 5 个入口）——若把 `/api/jobs/{id}` 与 `/api/jobs/{id}/events` 分开数约 16，口径成立。
3. **「报告无导出/复制」应写成「无 Markdown/JSON 导出，仅有原始 JSON 复制」**：`ReviewPage.tsx:753-760` 已有 `navigator.clipboard.writeText(JSON.stringify(result))`。缺的是结构化导出——而后端 `ReportRenderer.render_markdown` / `render_json` / `render_github_comment` **已经存在**（`services/report_renderer.py:362 / 415 / 423`），Web 只是没接。

### 1.3 主控审计遗漏项（本节为补充发现）

| # | 遗漏 | 证据 | 影响 |
|---|---|---|---|
| M1 | **`web/.shots/` 已过期，不能当视觉验收基线** | 截图 mtime 均为 2026-09-14/15；`App.tsx` / `ReviewPage.tsx` / `components.css` mtime 为 2026-09-20。`web/.shots/review-1440.png`、`overview-390.png` 是**浅色顶栏**布局，而当前 `tokens.css:123-160` 只有 dark 令牌、`App.tsx:115-134` 已是侧边栏布局 | 任何「照截图修 UI」都会改错方向；需先重拍 |
| M2 | **`JsonlBackend` 进程内状态与 `ThreadingHTTPServer` 不兼容** | `jsonl_server.py:810-820`（`self.sessions` / `chat_inventory` / `chat_cancellations` 均为普通 dict）；`web_server.py:609`（`ThreadingHTTPServer`） | Web 若直接 new 一个 `JsonlBackend` 多线程调用，会话表/取消表会竞态。这是 A 方案必须避开的坑（§3.1） |
| M3 | **设置页缺口的真实成因是白名单，不是「忘了做」** | `web_config.py:20-33` `EDITABLE_AI_FIELDS` 只含 11 个 ai_client 字段；注释写明「其余配置项不通过设置页修改」 | 补设置页应先扩白名单 + 安全审查，而不是只加表单 |
| M4 | **错误态硬编码服务端地址** | `ReviewPage.tsx:522` 写死 `服务端：127.0.0.1:8787` | `pr-review serve --port` 换端口后提示错误（端口可配，`web_server.py:595`） |
| M5 | **`build_review_context` 已是可独立复用的纯服务** | `services/review_context.py:64-72`（`RunReader` Protocol）、`:95-103`（`build_review_context`）、`:106-166`（`build_review_context_meta`）——只读 store、不碰 Session、不联网 | A 方案的成本比表面看起来低很多 |
| M6 | **多会话磁盘存储已存在，Web 无需再造** | `chat_session.py:247-637`（`ChatSessionStore`：create/switch/rename/delete/save） | 若将来做 Web 会话 UI，直接复用；MVP 不需要 |
| M7 | **CLI 的 `/export` 与 `/publish` 能力在 Web 完全缺失** | `jsonl_server.py:4445-4462`（export json/markdown 到文件）、`publish_service.py`（GitHub 评论） | 对应缺口 1、2 的可复用后端已就绪 |

---

## 2. A 方案：审查结果问答（最小实现）

### 2.1 可行性判断：哪些能复用、哪些不能

| 能力 | 位置 | 是否依赖 TUI Session / 进程内状态 / 事件流 | Web 复用方式 |
|---|---|---|---|
| 审查上下文渲染（L1–L4 + 预算裁剪） | `services/review_context.py:95-166` | **否**（只读 `RunReader`） | **直接 import 复用** |
| 诚实约束包裹 | `services/review_context.py:169-175`（`wrap_review_context`） | 否 | 直接复用 |
| 审查上下文入口（带降级） | `jsonl_server.py:2522-2536`（`_review_context_for_chat`） | 轻度（`self.config`） | 抽 5 行到 `web_chat` 或复制调用形态 |
| 仓库源码注入 | `jsonl_server.py:2582-2694`（`_repo_files_for_chat` / `_collect_repo_files`） | 轻度（`session.current_run_id` 可改成入参） | **逻辑复用**；建议抽成 `services/` 函数，入参 `(config, run_id, text)` |
| 仓库结构注入（PR 变更清单 + 目录树） | `jsonl_server.py:2857-2949` | 同上 + `self.chat_inventory` 缓存 | 同上；缓存可按进程放 `web_server` handler 类属性 |
| 路径识别 / 结构意图识别 | `jsonl_server.py:386`（`_mentioned_repo_paths`）、`:420`（`_wants_repo_structure`） | **否**（模块级纯函数） | 直接 import |
| system prompt 组装 | `jsonl_server.py:2433-2488`（`_chat_system_prompt`） | **是**（`session.current_run_id`、`session.context_candidates`、`_other_runs_note`） | **摘抄段落顺序**，不要整方法搬 |
| 对话收发 `_chat` | `jsonl_server.py:3063-3236` | **是**（写 `session.messages`、`_persist_session`、`chat_cancellations`、streaming 回调） | **不直接复用**；Web 自己做一层薄调用 |
| 会话存储 | `chat_session.py:247+` | 磁盘，无 TUI 依赖 | MVP **不用**；后续会话 UI 再用 |
| `/context` 绑定与「第 N 个」解析 | `jsonl_server.py:2967-3061`、`:3705-3746` | **是**（Session + `context_candidates`） | **MVP 不做**（Web 已有显式 `run_id`） |

**结论**：核心「读审查 → 渲染上下文 → 注入」三段是纯/轻依赖逻辑，**可以复用**；真正绑死 TUI 的是 `Session` 消息账本、取消表、候选序号解析、命令分发。Web 最小实现只需前者。

### 2.2 接口契约：无状态 `POST /api/chat`（推荐）

**推荐：无状态，不引入会话存储。** 理由：

1. Web 端在审查完成后已有 `run_id`（`ReviewPage.tsx:736` 使用 `result.run?.id`；job snapshot 也带 `run_id`，`web_jobs.py:69`）。
2. `JsonlBackend` 的 `sessions` / `chat_cancellations` / `chat_inventory` 是普通 dict（`jsonl_server.py:810-820`），而 `serve()` 用 `ThreadingHTTPServer`（`web_server.py:609`）——多线程共享一个 backend 实例会竞态；无状态请求则每次局部装配，天然安全。
3. 历史消息由前端持有并随请求回传（浏览器刷新即清，语义诚实）；服务端若落盘会话，会遇到 TUI 已有的「幽灵会话」问题（`jsonl_server.py:3352-3355` 明确警告过）。
4. 与现有 Web 风格一致：`/api/plan` 就是「同步一次、无状态」（`web_server.py:177-178`）。

#### 请求

```http
POST /api/chat
Content-Type: application/json

{
  "run_id": "a1b2c3d4",                 // 可空：空 = 普通聊天（无审查上下文）
  "text": "第 6 条为什么判 medium",
  "messages": [                          // 可选：客户端持有的历史，服务端截断
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ]
}
```

#### 响应（200）

```json
{
  "text": "…完整回答…",
  "model": "deepseek-chat",
  "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
  "context": {"used_percent": 0, "pressure": "ok", "compacted": false},
  "warning": null,
  "bound_run_id": "a1b2c3d4",
  "context_meta": {
    "token_estimate": 1234,
    "token_budget": 8000,
    "budget_source": "model_spec",
    "trimmed": ["L4"]
  }
}
```

#### 错误

| 状态 | 条件 | body |
|---|---|---|
| 400 | `text` 为空 / body 非对象 | `{"error": "..."}` |
| 503 | 聊天槽无 API Key（本地 Ollama 除外） | `{"error": "未配置模型 API Key，请到设置页完成配置", "code": "missing_api_key"}` |
| 409 | 同一 `run_id` 已有进行中的 chat（若做并发闸） | `{"error": "busy"}` |
| 400 | 上下文装配致命失败（仅当未做降级时） | `{"error": "..."}` |

> **降级优先于报错**：run 读不到、源码拉不到、预算超限都应返回 200 + 文本内说明（见 §2.4），与 TUI 语义一致（`jsonl_server.py:2440-2441`：「绝不因为解读不了这次审查而让对话失败」）。

### 2.3 上下文装配方式

**段落顺序**照抄 TUI 的已验证顺序（`jsonl_server.py:2443-2445` 注释 + `docs/claude-repo-structure-context.md` §3）：

```
1. 语言指令（web 可直接固定中文，或读 preferences.language）
2. 能力边界说明（可复用 jsonl_server.py:2454-2457 的 capability_note 文案）
3. wrap_review_context(run_id, build_review_context(...))     ← review_context.py:169
4. repo_inventory：PR 变更清单（每轮） + 目录树（用户问结构时） ← jsonl_server.py:2878+
5. repo_files：用户点名 / findings 点名的源码窗口              ← jsonl_server.py:2641+
```

**预算怎么算**（三档优先级，与 TUI 同口径，`jsonl_server.py:2257-2299`）：

1. `config`：`preferences.chat_context_budget` 为**非默认**显式值 → 用它；
2. `model_spec`：`min(context_window * 0.5, CHAT_CONTEXT_BUDGET_MAX)`（`CHAT_CONTEXT_BUDGET_RATIO = 0.5`，`jsonl_server.py:370`）；
3. `fallback`：`DEFAULT_TOKEN_BUDGET = 8000`（`review_context.py:34`）。

源码注入另有硬闸（与审查上下文预算分开）：

- 单文件最多 `CHAT_REPO_FILE_MAX_CHARS = 8000`（`jsonl_server.py:314`）
- 本轮全部源码最多 `CHAT_REPO_FILES_TOTAL_CHARS = 12000`（`:315`）
- finding 行窗口 ±80 行（`CHAT_REPO_FINDING_WINDOW_LINES`，`:341`）
- 历史消息上限 `CHAT_HISTORY_MESSAGE_LIMIT = 80`（`:343`）

**实现建议**：新建 `src/ai_pr_review/web_chat.py`（约 150–250 行），职责：

```python
def build_chat_system_prompt(config, run_id: str | None, text: str) -> tuple[str, dict]:
    """返回 (system_prompt, context_meta)。纯装配，不调模型。"""

def chat_once(config, *, run_id, text, messages) -> dict:
    """装配 → create_model_provider(...).chat/stream_chat → 组装响应。"""
```

复用点：

- `from ai_pr_review.services.review_context import build_review_context_meta, wrap_review_context`
- `from ai_pr_review.services.result_store import ResultStore`
- `from ai_pr_review.backend.jsonl_server import _mentioned_repo_paths, _wants_repo_structure`（模块级纯函数，`:386`、`:420`）
- 源码/清单注入：**优先抽函数**，而不是在 Web 里 new `JsonlBackend`。若要抢时间，可临时在 `web_chat` 内联一份 `_collect_repo_files` 的精简版（只保留 finding 窗口 + 头部截断 + 诚实标注，语义见 `jsonl_server.py:2641-2851`）。

模型调用侧对齐 TUI 的两条硬规则：

- 无 Key 且非本地 → 直接 503，不发请求（`jsonl_server.py:3082-3083` 同语义）。
- `max_tokens` 用 `_chat_max_tokens` 的封顶思路（`jsonl_server.py:2305-2332`）：`min(ai_client.max_tokens, model_spec.max_output)`，本地端点不封顶。

### 2.4 SSE 流式：MVP 取舍

**MVP 不做 SSE，整段 JSON 返回。**

| | 整段 JSON（推荐 v1） | SSE 流式 |
|---|---|---|
| 实现成本 | 低：`web_server.py` 已有 `_send_json` | 中：需把 provider 的 async 流桥到 `ThreadingHTTPServer` 的响应套接字 |
| 取消 | 简单（超时即可） | 需要 per-request cancel 事件（TUI 有 `chat_cancellations`，`jsonl_server.py:820`） |
| 用户体验 | 回答前有等待（可用 spinner） | 逐字输出，体验更好 |
| 现有基建 | — | `_write_sse` / `_stream_job_events` 已存在（`web_server.py:367-406`），但那是 **job 进度事件**，不是 token 流 |

审查 job 的 SSE 解决的是「几分钟进度可见」；chat 单轮通常数秒到数十秒，整段返回可接受。若后续做流式，建议复用 `_write_sse` 形态，但**不要**把 chat 塞进 `ReviewJobManager`（那是文件级进度模型，`web_jobs.py:184-196`）。

### 2.5 降级矩阵

| 场景 | 行为 | 依据 |
|---|---|---|
| 未绑定 run（`run_id` 空） | 普通聊天 + 在 prompt 里给「最近审查候选」提示（可选） | `jsonl_server.py:2459-2466` |
| `run_id` 无效 / 已清理 | 200，回答中明说「该审查记录当前无法读取」；`context_meta.token_estimate = null` | `jsonl_server.py:3010-3027`（绑定不自动消失，只报读不到） |
| 无模型 Key | **503**，不发请求，错误文案指向设置页 | `jsonl_server.py:3082-3083` |
| 上下文超预算 | 自动裁剪 L4→L3→L2（`review_context.py:185-201`），响应 `warning="over_budget"`，`trimmed` 如实回传 | `review_context.py:154-166` |
| 仓库源码拉不到 | 注入 `(未能读取 <path>：<原因>)`，**绝不编造**；整轮不失败 | `jsonl_server.py:2677-2683`、`:2841-2851` |
| 无 head_sha 的老 run | 注入说明「该 Run 未记录仓库 / head 提交」 | `jsonl_server.py:2658-2666` |
| 历史过长 | 截断到 `CHAT_HISTORY_MESSAGE_LIMIT` 并在 `warning` 标记 | `jsonl_server.py:3189-3200`、`:3238-3247` |

### 2.6 测试点（可直接写进 pytest）

| 测试 | 断言 |
|---|---|
| `test_chat_requires_text` | 空 `text` → 400 |
| `test_chat_without_api_key_is_503` | 清空 key（非本地）→ 503 且 body.code=`missing_api_key` |
| `test_chat_with_run_injects_review_context` | stub provider；捕获 system_prompt，断言含 `<review_context` 与 run_id |
| `test_chat_with_unknown_run_degrades` | 无效 run_id → 200，`bound_run_id` 仍回传，`context_meta.token_estimate is None` |
| `test_chat_budget_trim_reports_trimmed` | 极小 `chat_context_budget` → `context_meta.trimmed` 非空 |
| `test_chat_repo_file_injection_marks_missing` | 找不到的文件路径 → system_prompt 含 `(未能读取` |
| `test_chat_history_is_truncated` | 传 100 条 history → 上线消息 ≤ 80 |
| `test_chat_never_returns_plaintext_key` | 响应序列化后不含 api_key 明文 |

测试放 `tests/test_web_chat.py`，沿用 `tests/test_web_server.py` 的 `server` fixture 形态（`:1-100` 一带，注入临时 `config_path` / `result_store`）。

### 2.7 明确不建议做（防范围膨胀）

| 不做 | 理由 |
|---|---|
| Web 端完整 TUI 命令面（`/think` `/compact` `/model` `/publish` `/retry` …） | 命令分发耦合 Session 与 TUI 事件流（`jsonl_server.py:4388+`）；Web 有自己的 UI 控件。做「问答」就够 |
| 会话列表 / 重命名 / 删除 / 多会话侧栏 | `ChatSessionStore` 可复用，但 UI + 同步成本高；MVP 的「无状态 + 前端持有历史」已覆盖 80% 价值 |
| 自动语义绑定（「第 N 个」「PR #29」） | 依赖 `session.context_candidates`（`jsonl_server.py:790-793`、`:3741-3746`）；Web 场景 run_id 是显式点选，不需要猜 |
| token 级 SSE 流式 | 见 §2.4；先整段返回，验证价值再上流式 |
| 把 `JsonlBackend` 整实例挂进 `web_server` | 线程不安全（M2）；且会把 TUI 的取消/持久化语义拖进来 |
| Web 内嵌完整仓库浏览 / 文件树交互 | 注入已够回答问题；做成 IDE 是另一个产品 |
| 聊天记录持久化到 SQLite | 与 `sessions/` 目录重复；需要持久化时用 `ChatSessionStore`，不要第三套 |

---

## 3. B 方案：工作台 UX / 视觉一致性

> 说明：`web/.shots/` 与当前 UI **不同代**（M1），下列问题以**当前代码**为准；截图仅用于「移动端曾经如此」类旁证。建议先按 §3.2 的 P0 修完再重拍截图。

### 3.1 具体可用性问题（8 条）

| # | 现象 | 证据 | 严重度 |
|---|---|---|---|
| U1 | **键盘焦点不可见**：`.input:focus` / `.select:focus` 直接 `outline: none`，只改边框色，弱视/键盘用户难以定位焦点 | `web/src/styles/components.css:313-317`、`:329` | 高（a11y） |
| U2 | **中英混排**：状态栏与侧栏英文（`Connected`/`Offline`/`Review session`/`WORKSPACE`/`AI runtime`）与中文导航/正文混用 | `web/src/App.tsx:122`、`:131`、`:139`、`:158`、`:161`；对照中文 NAV `App.tsx:20-26` | 中 |
| U3 | **移动端导航被截断**：旧截图 390px 下顶栏只露出单字「概/审/历/准」；当前侧栏在 ≤900px 变横向条，未见完整标签的滚动/缩略策略 | 旧：`web/.shots/review-390-vp.png`；现：`components.css:909`、`:944`（`max-width:900px` 侧栏变 sticky 行） | 高（移动端） |
| U4 | **长报告被困在 380px 的 JSON 盒里**：原始响应区 `maxHeight: 380`，无 Markdown 导出/下载，只能复制整包 JSON | `web/src/pages/ReviewPage.tsx:748-769`（尤其 `:765`） | 高 |
| U5 | **Finding 详情层级弱**：默认只展开第 1 条（`index === 0`），其余 11 条要逐个点开；标题与证据徽章同行挤压 | `web/src/components/FindingCard.tsx:31`、`:90-112` | 中 |
| U6 | **错误态硬编码端口** | `web/src/pages/ReviewPage.tsx:522` | 中 |
| U7 | **空/错/加载态风格不统一**：`Empty` 用 `[ i ]` / `[ ? ]` 标记，错误用 `Notice`，运行态自绘 pipeline，设置页用 `Spinner`；取消态文案与错误态并列但样式不同 | `ReviewPage.tsx:518-550`、`:640`、`:721`、`:478-516`；`SettingsPage.tsx`（Spinner） | 低 |
| U8 | **粒子背景在小屏喧宾夺主**：全视口固定 canvas；`prefers-reduced-motion` 只降透明度不关停 | `components.css:915-924`、`:920`；`ParticleBackground.tsx`（21K WebGL）；旁证 `web/.shots/review-390-vp.png` 表单后方强光带 | 中（移动端） |

补充（对应缺口 3，归入 B 是因为它是「工作台一致性」）：

| # | 现象 | 证据 |
|---|---|---|
| U9 | **设置页覆盖面约为 CLI 的一半**：仅 provider/base_url/model/api_key/github_token + 6 个数值 + 2 个开关；缺 language、hybrid_strategy、chat/review 槽位、thinking 档位、workbench_mode、repo_context 等 | `web_config.py:21-33`（白名单）；`SettingsPage.tsx:8-22`（NUMERIC/BOOL 字段）；对照 CLI `cli.py:1131-1224`（preferences 向导） |

### 3.2 改进清单（现象 → 改法 → 影响文件 → 验证）

按性价比排序（收益/成本）：

| 优先 | 现象 | 改法 | 影响文件 | 验证方式 | 量级 |
|---|---|---|---|---|---|
| B1 | U1 焦点不可见 | 去掉 `outline: none`，改为 `:focus-visible { outline: 2px solid var(--ds-color-brand); outline-offset: 2px }`；输入框保留边框变色作辅助 | `web/src/styles/components.css:313-317`、`:329` | Tab 遍历表单，截图焦点环；`web/tools/audit-pages.mjs` 加焦点检查 | S |
| B2 | U6 硬编码端口 | 从 `/api/meta` 或 `/api/health` 回传实际 `host:port`，错误提示用变量 | `web/src/pages/ReviewPage.tsx:522`、`web_server.py:482+`（`_handle_meta`） | `pr-review serve --port 9000` 后断网，提示不含 8787 | S |
| B3 | U4 导出 | 后端加 `GET /api/report/export?run_id=&format=markdown|json`（复用 `ReportRenderer.render_markdown/render_json`）；前端「导出 Markdown / 复制 Markdown」按钮 | `web_server.py`（新路由）、`services/report_renderer.py:362/415`（只读复用）、`ReviewPage.tsx:748+`、`HistoryPage.tsx:173+` | 对同一 run：CLI `pr-review export` 与 API 导出内容 diff 为空（或仅时间戳行） | S |
| B4 | U2 中英混排 | 统一中文：`Connected→已连接`、`Offline→未连接`、`Review session→审查会话`、侧栏 kicker 可保留英文小字（视觉标签）或一并翻译 | `web/src/App.tsx:122-161` | 全局搜 `[A-Z]{3,}` 用户可见文案清单 | S |
| B5 | U3 移动导航 | ≤900px：`overflow-x: auto` + `white-space: nowrap` 保完整标签；或折叠为图标 + `aria-label`/`title` | `components.css:909`、`:944`、`:846-860` | Playwright 390px 截图对比 `web/.shots/review-390-vp.png` 重拍版；`probe-layout.mjs` 测溢出 | S |
| B6 | U8 粒子干扰 | `prefers-reduced-motion` 时**不挂载** canvas（而非降透明度）；≤768px 默认 `mode="idle"` 且降低粒子数 | `ParticleBackground.tsx`、`App.tsx:114`、`components.css:920` | 390px 对比前后截图；DevTools 确认 reduce 时无 canvas | S |
| B7 | U5 Finding 层级 | 折叠态显示「问题摘要一行」+ 证据徽章；展开改 `details/summary` 或保留现结构但默认全部收起、给「展开全部/收起全部」 | `FindingCard.tsx:31`、`:115-169` | 12 条 findings 的 run：一次操作内可达全部 problem 文本 | M |
| B8 | U7 状态一致性 | 统一 `Empty`/`Notice`/`Spinner`/`run-pipeline` 的语义色与图标表（tokens 已有 state 色：`tokens.css:249-256`） | `components/ui.tsx`、`ReviewPage.tsx:518-550`、`:774-806` | 空/错/取消/成功四态截图清单 | M |
| B9 | U9 设置页 | 按 CLI 分组补齐只读展示 + 可写白名单；**先**扩 `EDITABLE_AI_FIELDS` 并做安全审查（尤其 publish/密钥相关），再做表单 | `web_config.py:21-33`、`SettingsPage.tsx`、`web_server.py:292+` | 对照 `cli.py` preferences 全集生成缺口清单测试 | M |
| B10 | M1 截图基线 | 在 B1–B6 落地后重跑 `web/tools/shoot.mjs` / `audit-pages.mjs`，覆盖 1440/1280/900/390 | `web/tools/*.mjs`、`web/.shots/` | 新截图 mtime 晚于 `components.css` | S |

---

## 4. 风险与坑（来自代码证据）

| 风险 | 证据 | 缓解 |
|---|---|---|
| **`JsonlBackend` 非线程安全** | `jsonl_server.py:810-820` 普通 dict 状态；`web_server.py:609` `ThreadingHTTPServer` | Web chat 自建无状态函数；不要共享 backend 实例 |
| **asyncio 双模型**：`web_server` 同步 handler 里 `asyncio.run`，`web_jobs` 后台线程再 `asyncio.run` | `web_server.py:178/185`、`web_jobs.py:168` | chat 沿用「请求内 `asyncio.run`」即可；不要试图跨请求复用 loop |
| **取消语义是文件边界，不是即时** | `web_jobs.py:13-14` | chat 用超时 + 前端 Abort；不要承诺「立即停止已在飞的模型调用」 |
| **token 预算口径容易做错** | `review_context.py:32-34`（4 字符≈1 token）、`jsonl_server.py:2257-2299`（预算三来源） | 一律复用 `build_review_context_meta` 与 `_chat_context_budget_plan` 语义，不要另写估算法 |
| **上下文重复膨胀** | `jsonl_server.py:2438-2441`：源码/结构**只进本轮 system prompt，不写 session.messages** | Web 无状态时天然满足；若将来落盘历史，禁止把 system 段写进 messages |
| **老 run 缺 `head_sha`** | `jsonl_server.py:2658-2666` | 如实标注「未记录 head 提交」，禁止猜文件内容 |
| **结果库可写性 / 临时目录** | `web_server.py:615-630`（fallback 路径与临时目录警告） | chat 读 store 失败必须降级，不能 500 |
| **SSE 与线程模型** | `web_server.py:367-406` 已有 job SSE；chat 流式需另开桥 | v1 不做流式（§2.4） |
| **模型规格 `max_output` 与思考预留冲突** | `jsonl_server.py:2305-2332`（封顶公式与 Anthropic 400 教训） | Web chat 同样封顶；本地端点除外 |
| **前端构建产物缺失** | `web_server.py:612-613` 仅打印警告 | CI 构建前端（缺口 7）才能根治 |
| **截图基线失效** | M1 | 先修 UI 再重拍，禁止用旧图做回归 |

---

## 5. 优先级建议

### 5.1 七条缺口排序（性价比 = 价值 / 成本）

| 序 | 缺口 | 量级 | 为什么这个位置 |
|---|---|---|---|
| 1 | **#6 审查结果问答** | S–M | 产品差异化核心；后端 `review_context.py` 已纯函数化（M5），Web 端成本低于表面；CLI 用户已验证该交互（`docs/chat-features.md`） |
| 2 | **#2 报告导出/复制补全** | S | 后端 `render_markdown/json` 现成（`report_renderer.py:362/415`）；日常工作高频；只缺 API + 两个按钮 |
| 3 | **#7 CI 构建前端** | S | 防止 `web_static` 缺失静默腐烂（`web_server.py:612-613`）；一次配置长期收益 |
| 4 | **#3 设置页补全** | M | 真实成因是白名单（M3）；要安全审查，不能只加表单 |
| 5 | **#1 发布 GitHub 评论** | M–L | 高价值但高权限风险；CLI `publish_service.py` 已有实现与 `--confirm` 语义，Web 需要预览 + 明确确认 |
| 6 | **#4 ApiPage 文档 7/16** | S | 低风险纯文档；`docs/API.md` 已存在，属收尾 |
| 7 | **#5 i18n** | L | 当前主受众中文；U2 的中英混排可以先用「统一中文」解决文案层，真正 i18n 框架投入产出比低 |

> 注：B 包里的 U1（焦点）/ U3（移动导航）不在七条缺口内，但属于「必须穿插修」的可用性缺陷，建议搭车 B1/B5 两个 S 项一起做，不单独占优先级槽位。

### 5.2 「只做 3 件」选哪 3 件

**选：#6 审查结果问答 MVP、#2 报告 Markdown 导出、#7 CI 构建前端。**

理由：

1. **#6** 是下一阶段 Web 工作台的主命题（本任务 A），且可行性已确认——不做等于把 CLI 已验证的能力继续留在 TUI 里。
2. **#2** 成本极低、每天都能用到，还能反向支撑 #6（用户可把「报告 + 问答结论」一起导出）。
3. **#7** 是工程卫生底线：没有它，`npm run build` 产物缺失只会在启动日志里出现一行警告（`web_server.py:612-613`），前端改动可能根本到不了用户机器。

暂缓但明确表态：

- **#1 发布评论**：做，但放第二批；必须带「预览 + 二次确认 + 幂等」（参考 CLI `/publish --confirm`，`jsonl_server.py:4395` 帮助文本）。
- **#3 设置页**：做，但先扩白名单并做安全审查（M3）。
- **#4 ApiPage**：文档收尾，可搭车任意批次。
- **#5 i18n**：仅先做「统一中文文案」（B4），完整 i18n 不进本阶段。

---

## 6. 验收方式（可执行命令与断言）

### 6.1 现状基线（本次已实测）

```powershell
$env:TEMP = "$PWD\.pytest_mimo"; $env:TMP = "$PWD\.pytest_mimo"
.\.venv313\Scripts\python.exe -m pytest `
  tests/test_web_server.py tests/test_jsonl_backend.py `
  tests/test_chat_session.py tests/test_chat_commands.py -q --tb=line --no-cov
```

**实测数字（2026-09-27）**：`361 passed, 1 warning in 35.71s`
（warning 来自 `tests/test_jsonl_backend.py::test_chat_context_budget_can_be_set_in_the_config_file` 对越界预算的预期回退，属正常）

分文件规模：

| 文件 | 测试类 | 测试函数 |
|---|---|---|
| `tests/test_web_server.py` | 12 | 45 |
| `tests/test_jsonl_backend.py` | 2 | 232 |
| `tests/test_chat_session.py` | 0 | 20 |
| `tests/test_chat_commands.py` | 0 | 8 |

### 6.2 A（问答 MVP）验收断言

```powershell
# 1) 单元/接口测试
.\.venv313\Scripts\python.exe -m pytest tests/test_web_chat.py -q --tb=short
# 期望：全部通过；含 §2.6 的 8 个用例

# 2) 服务冒烟（需先配置好模型 Key，或用 stub provider 的测试）
pr-review serve --port 8787
# 新终端：
# - POST /api/chat {run_id, text} → 200 且 response.context_meta 存在
# - POST /api/chat {run_id:"", text} → 200 普通聊天
# - POST /api/chat {run_id:"not-exist", text} → 200 且 token_estimate 为 null（降级）
# - 临时清空 API Key 后 → 503 code=missing_api_key

# 3) 不回归
.\.venv313\Scripts\python.exe -m pytest tests/test_web_server.py tests/test_jsonl_backend.py -q --no-cov
# 期望：仍为原有全部通过（基线 361 中的对应子集）
```

断言清单：

- [ ] `POST /api/chat` 在无 Key 时 **不产生模型调用** 且返回 503
- [ ] system prompt 含 `<review_context run_id=...>`（stub 捕获）
- [ ] 无效 run_id 不 500，`context_meta.token_estimate is None`
- [ ] 超预算时 `trimmed` 非空且 `warning="over_budget"`
- [ ] 响应体永不包含明文 api_key / github_token

### 6.3 B（UX）验收断言

```powershell
# 构建
cd web && npm run build
# 焦点可见：Tab 遍历 /api 页与设置页表单，每一站可见 2px 焦点环
# 移动端：390px 下侧栏/顶栏标签不被截断（Playwright，web/tools/shoot.mjs）
# 导出：对已有 run 执行 GET /api/report/export?format=markdown，内容含 "[L1" 或 findings 标题
# 文案：全局检索状态栏无 "Connected"/"Offline" 裸英文
```

断言清单：

- [ ] `.input:focus`/`.select:focus` 不再 `outline: none` 而无替代
- [ ] 390px 截图中导航标签完整可读
- [ ] Markdown 导出内容与 `ReportRenderer.render_markdown` 同源
- [ ] `web/.shots/` 重拍时间晚于 `components.css` 修改时间

### 6.4 本提案文档自身

- 路径：`docs/web-workbench-proposal-mimo.md`（唯一写入文件）
- 未修改任何源码/配置；未做 git 操作；未读取或输出任何凭据。

---

## 附：关键文件速查

| 主题 | 文件 |
|---|---|
| 审查上下文纯服务 | `src/ai_pr_review/services/review_context.py` |
| TUI 聊天与上下文装配 | `src/ai_pr_review/backend/jsonl_server.py`（`_chat` `:3063`、`_chat_system_prompt` `:2433`、`_review_context_for_chat` `:2522`、`_repo_files_for_chat` `:2582`、`_chat_repo_inventory` `:2857`） |
| 会话磁盘存储 | `src/ai_pr_review/chat_session.py`（`ChatSessionStore` `:247`） |
| Web 路由/SSE | `src/ai_pr_review/web_server.py` |
| Web 异步任务 | `src/ai_pr_review/web_jobs.py` |
| Web 配置白名单 | `src/ai_pr_review/web_config.py`（`EDITABLE_AI_FIELDS` `:21`） |
| 报告导出后端 | `src/ai_pr_review/services/report_renderer.py` |
| 前端核心页 | `web/src/pages/ReviewPage.tsx`、`web/src/App.tsx` |
| 设计令牌 / 布局 | `web/src/styles/tokens.css`、`web/src/styles/components.css` |
| 截图与探测脚本 | `web/.shots/`（**已过期**）、`web/tools/*.mjs` |
