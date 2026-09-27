# API 文档

本文档描述 `ai-pr-review` 的命令行接口与 Web 工作台 HTTP 接口（18 条 API + 静态资源）。

## 命令概览

安装后会暴露一个可执行命令：

```bash
pr-review
```

默认行为等价于：

```bash
pr-review review <PR_URL>
```

## 主命令

### `pr-review <PR_URL>`

对指定 GitHub Pull Request 执行完整审查。

参数：

- `PR_URL`：GitHub Pull Request URL，例如 `https://github.com/owner/repo/pull/123`

选项：

- `--model TEXT`：覆盖配置中的模型名。
- `--format [terminal|markdown|json]`：报告输出格式，默认 `terminal`。
- `--output FILE`：把报告写入目标文件。若文件后缀为 `.md` 或 `.json`，会自动推断输出格式。
- `--publish-comment`：将 GitHub 评论格式的报告发布到对应 PR。
- `--verbose`：显示逐文件处理进度。
- `--dry-run`：抓取与过滤 PR 文件，不调用模型。
- `--only-fetch`：只抓取 PR 元数据。
- `--only-filter`：抓取并过滤 PR 文件。
- `--show-filter-reasons`：在 `--dry-run` 或 `--only-filter` 下显示每个文件的过滤原因。

限制：

- `--dry-run`、`--only-filter`、`--only-fetch` 不能同时使用。

示例：

```bash
pr-review https://github.com/owner/repo/pull/123
pr-review https://github.com/owner/repo/pull/123 --format markdown --output review.md
pr-review https://github.com/owner/repo/pull/123 --only-filter --show-filter-reasons
pr-review https://github.com/owner/repo/pull/123 --publish-comment
```

## 审查规划与反馈命令

### `pr-review plan <PR_URL>`

抓取并过滤 PR，生成透明的审查计划，不调用 AI 模型。输出包含：

- 风险等级和风险类别；
- 优先审查文件；
- 跳过文件；
- 审查策略；
- 是否需要跨文件分析。

### `pr-review demo`

运行离线演示，不需要 GitHub Token 或模型 API Key，用于展示审查规划、静态规则和证据验证能力。

### `pr-review benchmark`

用内置的已知缺陷样例衡量分析策略的实际效果，不调用模型、不需要网络。

选项：

- `--strategy [static|ast|combined|all]`：选择策略，默认 `combined`；`all` 会横向比较全部策略。
- `--json-output`：输出完整 JSON 报告（含每个样例的明细）。

输出指标：

- `Precision`：报出的问题里有多少是真缺陷；
- `Recall`：预埋的缺陷有多少被找到；
- `F1`：精确率与召回率的调和平均；
- `False positive rate`：误报占全部报出的比例；
- `Line accuracy`：命中的缺陷中，行号完全准确的比例。

内置样例（`src/ai_pr_review/benchmark/cases.py`）：

| 样例 | 预埋缺陷数 | 用途 |
|------|-----------|------|
| `security-python-01` | 7 | 硬编码凭证、unsafe 反序列化、shell=True、关闭 TLS 校验、SQL 插值、弱哈希、缺超时 |
| `correctness-python-01` | 2 | 可变默认参数、`is` 字面量比较 |
| `error-handling-python-01` | 3 | 裸 except、未关闭文件句柄、不安全 YAML |
| `clean-python-01` | 0 | 对照组，用于衡量误报 |

> 注意：样例库是**精选的回归样例集**，用于防止规则退化与误报增加，
> 并不代表在真实 PR 上的泛化准确率。

### `pr-review feedback <RUN_ID> <FINDING_ID> --status <STATUS>`

记录人工对 finding 的判断。`STATUS` 可选：`accepted`、`rejected`、`fixed`、`needs_review`。

## 配置命令

### `pr-review config`

启动交互式配置向导。

选项：

- `--quick`：使用最小化向导。
- `--advanced`：额外询问 headers 和 extra params。
- `--save-key`：允许把 API Key 明文保存到配置文件。

说明：

- 不带子命令执行时，会直接进入交互向导。
- 配置文件默认路径由 `DEFAULT_CONFIG_PATH` 决定。

### `pr-review config show`

输出当前持久化配置，`api_key` 会做脱敏处理。

示例输出字段：

- `config_path`
- `model_provider.name`
- `model_provider.model_name`
- `model_provider.base_url`
- `model_provider.api_format`

### `pr-review config test`

校验当前 provider 配置是否合法。

成功时输出 provider、model 和 format；失败时以 CLI 错误退出。

## 历史命令

### `pr-review history`

读取 SQLite 历史库中的运行记录。

选项：

- `--pr-url TEXT`：按 PR URL 过滤。
- `--limit INTEGER`：返回记录数量上限，默认 `10`。

返回 JSON，包含：

- `runs`
- `statistics`

### `pr-review stats`

输出 SQLite 历史库的聚合统计信息。

返回 JSON，包含：

- `total_runs`
- `unique_prs`
- `total_findings`
- `critical_findings`
- `high_findings`
- `medium_findings`
- `low_findings`
- `info_findings`
- `total_cost`
- `latest_run_at`

---

# Web 工作台 HTTP 接口

## 启动

```bash
pr-review serve            # 默认 http://127.0.0.1:8787
```

服务端基于 Python 标准库 `ThreadingHTTPServer`，只监听本机回环地址。
界面为 React + Vite 应用，构建产物随包分发在 `src/ai_pr_review/web_static/`，
因此 `pip install` 后无需 Node 即可运行。

界面包含 **6 个视图**：

| 视图 | 路由 id | 内容 |
|------|---------|------|
| **概览** | `overview` | 产品定位、审查流水线、关键能力、实时统计与基准准确率 |
| **审查工作台** | `review` | 计划生成、完整审查、风险总览、审查计划、证据校验、文件过滤、跨文件接口影响、可筛选 Findings、人工反馈、原始 JSON |
| **历史审查** | `history` | 运行记录、聚合统计、按 run_id 载入完整报告 |
| **准确率** | `benchmark` | 策略对比、混淆矩阵、逐样例指标 |
| **接口** | `api` | 接口与 CLI 参考、运行边界 |
| **设置** | `settings` | Provider / 模型 / Token 配置、连通性探测 |

## 全局约定

- **请求体上限**：64 KB。超限请求在读取请求体之前即被拒绝。
- **写端点同源守卫**：全部 `POST` 要求 `Content-Type: application/json` 且请求同源；
  否则返回 `415`。`OPTIONS` 预检一律返回 `405`，且**不返回任何 `Access-Control-*` 头**，
  以阻断跨站表单/`fetch` 写入。
- **凭据**：接口只回掩码，绝不明文返回 GitHub Token 或模型 API Key。
- **编码**：所有 JSON 响应为 `application/json; charset=utf-8`。

## 端点总表（19 条 API + 静态资源）

| # | 方法 | 路径 | 说明 |
|---|------|------|------|
| 1 | GET | `/api/health` | 存活探针 |
| 2 | GET | `/api/meta` | 运行环境 |
| 3 | GET | `/api/history` | 历史 run 列表 + 统计 |
| 4 | GET | `/api/report` | 单次 run 完整报告 |
| 5 | GET | `/api/report/export` | 报告导出（markdown / json） |
| 6 | GET | `/api/benchmark` | 准确率基准 |
| 7 | GET | `/api/credentials` | 凭证健康（掩码） |
| 8 | GET, POST | `/api/config` | 配置视图 / 保存配置 |
| 9 | GET | `/api/jobs` | 最近任务（10 条） |
| 10 | GET | `/api/jobs/{id}` | 任务快照 |
| 11 | GET | `/api/jobs/{id}/events` | 任务 SSE 进度 |
| 12 | GET | `/api/demo/cases` | 离线演示用例清单 |
| 13 | GET | `/api/demo/run` | 离线演示结果 |
| 14 | POST | `/api/plan` | 生成审查计划 |
| 15 | POST | `/api/review` | 同步 / 异步审查 |
| 16 | POST | `/api/jobs/{id}/cancel` | 取消任务 |
| 17 | POST | `/api/feedback` | 人工反馈落库 |
| 18 | POST | `/api/publish` | 预览 / 发布 GitHub 评论 |
| 19 | POST | `/api/chat` | 对某次审查追问（带 `run_id` 注入上下文并落库；不带则普通对话） |
| 20 | GET | `/api/chat/history` | 某次审查的追问历史（问题 + 回答） |
| 21 | POST | `/api/chat/history/clear` | 清空某次审查的追问历史（幂等） |
| — | GET | `/static/*` | 前端构建产物（含 SPA fallback） |

---

## 端点明细

### GET `/api/health`

存活探针，用于确认本地服务已就绪。

响应：

```json
{ "ok": true, "service": "ai-pr-review" }
```

```bash
curl http://127.0.0.1:8787/api/health
```

### GET `/api/meta`

运行环境快照：规则数、供应商数、tree-sitter 是否可用、跨文件开关、静态分析开关、当前模型。

响应要点：

```json
{ "rules": 12, "providers": 4, "tree_sitter": true, "cross_file": true, "static_analysis": true, "model": "..." }
```

```bash
curl http://127.0.0.1:8787/api/meta
```

### GET `/api/history`

历史 run 列表 + 聚合统计。

查询参数：

- `limit`：可选，范围 1–200。

响应：

```json
{ "runs": [ ... ], "statistics": { ... } }
```

```bash
curl "http://127.0.0.1:8787/api/history?limit=30"
```

### GET `/api/report`

单次 run 的完整报告，包含 `review` / `plan` / `validation` / `interface_impacts` / `feedback`。

查询参数：

- `run_id`：必填。

响应：

```json
{ "run_id": "...", "run": { ... }, "review": { ... }, "plan": { ... }, "validation": { ... }, "interface_impacts": [ ... ], "feedback": [ ... ] }
```

错误码：`400`（run_id 缺失）、`404`（run 不存在）。

```bash
curl "http://127.0.0.1:8787/api/report?run_id=<run_id>"
```

### GET `/api/report/export`

导出报告。

查询参数：

- `run_id`：必填。
- `format`：`markdown` 或 `json`。

行为：

- `format=markdown`：返回 `Content-Type: text/markdown`，并附带
  `Content-Disposition: attachment; filename="pr<N>-<run8>.md"`
  （`N` 为 PR 编号，`run8` 为 run_id 前 8 位）。
- `format=json`：与 `GET /api/report` 同形，`Content-Type: application/json`。

错误码：`400`（参数缺失或 format 非法）、`404`（run 不存在）。

```bash
curl -OJ "http://127.0.0.1:8787/api/report/export?run_id=<run_id>&format=markdown"
curl "http://127.0.0.1:8787/api/report/export?run_id=<run_id>&format=json"
```

### GET `/api/benchmark`

准确率基准报告。

查询参数：

- `strategy`：`static` / `ast` / `combined` / `all`。

响应要点：

```json
{ "strategy": "combined", "precision": 1.0, "recall": 0.9, "f1": 0.95, "false_positive_rate": 0.0, "line_accuracy": 0.88, "cases": [ ... ] }
```

```bash
curl "http://127.0.0.1:8787/api/benchmark?strategy=combined"
```

### GET `/api/credentials`

凭证健康检查。**只返回掩码，绝不明文。**

查询参数：

- `probe`：`0` 只读本地状态；`1` 额外做一次连通性探测。

响应要点：

```json
{ "github": { "ok": true, "masked": "ghp_****" }, "model": { "ok": true, "masked": "sk-****" } }
```

```bash
curl "http://127.0.0.1:8787/api/credentials?probe=1"
```

### GET `/api/config` / POST `/api/config`

**GET**：配置视图。

响应字段：

- `provider`
- `base_url`
- `model`
- `api_format`
- `api_key`（掩码）
- `available_providers`

**POST**：保存配置。请求体为 JSON 部分字段：

- 掩码值或留空 = **不修改**该字段；
- 未知键 → `ok=false`，整次写入拒绝。

响应：

```json
{ "ok": true, "changed": ["model_provider.model_name"], "rejected": [] }
```

错误码：`415`（跨站或非 JSON）。

```bash
curl http://127.0.0.1:8787/api/config
curl -X POST http://127.0.0.1:8787/api/config \
  -H "Content-Type: application/json" \
  -d '{"api_key":""}'
```

### GET `/api/jobs`

最近任务列表，固定返回 10 条。

```bash
curl http://127.0.0.1:8787/api/jobs
```

### GET `/api/jobs/{id}`

任务快照。

响应字段：

- `status`
- `total_files`
- `completed_files`
- `current_file`
- `progress`
- `error`
- `elapsed_seconds`
- `run_id`

错误码：`404`（任务不存在）。

```bash
curl http://127.0.0.1:8787/api/jobs/<job_id>
```

### GET `/api/jobs/{id}/events`（SSE）

逐文件进度事件流。

- `Content-Type: text/event-stream`
- 每条事件为一行 `data: {json}`，字段与任务快照对齐（`completed_files` / `total_files` / `current_file` / `progress` 等）
- 连接在任务结束时由服务端关闭；客户端可用 `EventSource` 或 `curl -N` 消费

错误码：`404`（任务不存在）。

```bash
curl -N http://127.0.0.1:8787/api/jobs/<job_id>/events
```

### GET `/api/demo/cases`

离线演示用例清单。

```bash
curl http://127.0.0.1:8787/api/demo/cases
```

### GET `/api/demo/run`

离线演示结果，**无需 Token / API Key**。

查询参数：

- `case`：用例 id，例如 `sql-injection`。

错误码：`404`（case 不存在）。

```bash
curl "http://127.0.0.1:8787/api/demo/run?case=sql-injection"
```

### POST `/api/plan`

只做抓取 / 过滤 / 规划，**不调用模型**。

请求体：

```json
{ "pr_url": "https://github.com/owner/repo/pull/123" }
```

响应：

```json
{ "pr": { ... }, "filter": { ... }, "plan": { ... }, "validation": { ... }, "interface_impacts": [ ... ], "run": { ... } }
```

错误码：`400`（pr_url 缺失）、`415`（跨站或非 JSON）。

```bash
curl -X POST http://127.0.0.1:8787/api/plan \
  -H "Content-Type: application/json" \
  -d '{"pr_url":"https://github.com/owner/repo/pull/123"}'
```

### POST `/api/review`

同步审查；`async_job: true` 时任务化。

请求体：

```json
{ "pr_url": "https://github.com/owner/repo/pull/123", "async_job": true }
```

行为：

- 默认同步：返回完整审查产物（与 `/api/report` 中 `review` 部分同形，外加 `pr` / `filter` / `plan` 等）。
- `async_job: true`：返回 `202` + 任务快照（含 `job_id`），进度走
  `GET /api/jobs/{id}/events`，可 `POST /api/jobs/{id}/cancel` 真取消。

错误码：`400`（pr_url 缺失）、`415`（跨站或非 JSON）。

```bash
curl -X POST http://127.0.0.1:8787/api/review \
  -H "Content-Type: application/json" \
  -d '{"pr_url":"https://github.com/owner/repo/pull/123","async_job":true}'
```

### POST `/api/jobs/{id}/cancel`

服务端真取消，**取消在文件边界生效**（不会把半个文件的审查结果写回）。

响应：

```json
{ "ok": true, "job_id": "...", "message": "已请求停止。" }
```

错误码：`404`（任务不存在或已结束）、`415`（跨站或非 JSON）。

```bash
curl -X POST http://127.0.0.1:8787/api/jobs/<job_id>/cancel \
  -H "Content-Type: application/json" -d '{}'
```

### POST `/api/feedback`

人工反馈落库。

请求体：

```json
{ "run_id": "...", "finding_id": "...", "status": "accepted", "note": "" }
```

`status` 可选：`accepted` / `rejected` / `fixed` / `needs_review`。

错误码：`400`（字段缺失）、`404`（run / finding 不存在）、`415`（跨站或非 JSON）。

```bash
curl -X POST http://127.0.0.1:8787/api/feedback \
  -H "Content-Type: application/json" \
  -d '{"run_id":"<run_id>","finding_id":"f-1","status":"accepted","note":""}'
```

### POST `/api/publish`

预览 / 发布审查评论到 GitHub PR。

请求体：

```json
{ "run_id": "<run_id>", "confirm": false }
```

行为：

- `confirm=false`：**只预览**，不触碰 GitHub。返回 `status=preview` 与 `comment_chars`（将要发布的评论长度）。
- `confirm=true`：真正发布。返回 `status=published` 或 `status=already_published`，
  以及 `comment_url` / `comment_id`。

错误码：

| 状态码 | 含义 |
|--------|------|
| 400 | `run_id` 缺失 |
| 404 | run 不存在 |
| 409 | 无 GitHub PR 链接 |
| 415 | 跨站或非 JSON |
| 502 | GitHub 侧失败 |
| 503 | 未配置 GitHub Token |

```bash
curl -X POST http://127.0.0.1:8787/api/publish \
  -H "Content-Type: application/json" \
  -d '{"run_id":"<run_id>","confirm":false}'
```

### POST `/api/chat`

对**某次已完成的审查**追问（例如"第 3 条为什么判中风险？"）。每次请求自带 `run_id`
与问题；**带 `run_id` 的追问会落库**（见「追问历史」一节），不带 `run_id` 的普通
对话无归属、不落库。

请求体：

```json
{ "run_id": "<run_id，可选>", "text": "<问题>" }
```

行为：

- 带 `run_id` 时把该 run 的摘要与 findings（文件/行号/严重度/证据状态）装配进上下文
  （复用 CLI 侧的 `services/review_context.py`，受 `preferences.chat_context_budget` 约束）；
  上下文超预算时**先裁 findings、再裁摘要**，并在 `context_meta.truncated` + `note` 里说明。
- 不带 `run_id` 时退化为普通对话（`context_meta.bound_run` 为 `null`）。
- system prompt 恒定注入两段：**排版规则**（前端是受限 Markdown 渲染器：只认三级标题、
  列表、加粗、行内码、围栏代码块、表格、引用；禁止 HTML/图片）与**回复语言**指令
  （取自 `preferences.language`，与 CLI chat 同一份文案）。绑定 run 时另有审查上下文块。
- `usage` 直接来自模型返回；拿不到就为 `null`（不估算、不编造）。
- `duration_ms` 是本次模型调用的墙钟耗时；`persisted=true` 表示这一轮已写入追问历史。

响应要点：

```json
{
  "reply": "…",
  "model": "deepseek-chat",
  "usage": { "prompt_tokens": 812, "completion_tokens": 120, "total_tokens": 932 },
  "duration_ms": 1820,
  "language": "zh-CN",
  "run_id": "<run_id>",
  "persisted": true,
  "turn_id": 2,
  "question_turn_id": 1,
  "created_at": "2026-09-27 12:00:00",
  "context_meta": {
    "bound_run": "<run_id>",
    "token_estimate": 382,
    "sections": ["run_summary", "findings"],
    "truncated": false,
    "note": ""
  }
}
```

`turn_id` / `question_turn_id` / `created_at` 只在 `persisted=true` 时出现。

错误码：

| 状态码 | 含义 |
|--------|------|
| 400 | `text` 缺失 |
| 404 | `run_id` 查不到 |
| 415 | 跨站或非 JSON |
| 502 | 上游模型调用失败 |
| 503 | 未配置模型 API Key |

```bash
curl -X POST http://127.0.0.1:8787/api/chat \
  -H "Content-Type: application/json" \
  -d '{"run_id":"<run_id>","text":"这次审查有几个 finding？"}'
```

### GET `/api/chat/history`

读取某次审查的追问历史（问题与回答成对，按 `turn_index` 升序）。

| 参数 | 必填 | 说明 |
|------|------|------|
| `run_id` | 是 | 审查 run id |
| `limit` | 否 | 条数上限，1–1000，默认 200 |

```json
{
  "run_id": "<run_id>",
  "count": 2,
  "turns": [
    { "turn_id": 1, "turn_index": 1, "role": "user", "content": "这次审查有几个问题？",
      "model": "", "usage": {}, "context_meta": {}, "duration_ms": null,
      "created_at": "2026-09-27 12:00:00" },
    { "turn_id": 2, "turn_index": 2, "role": "assistant", "content": "两个。",
      "model": "deepseek-flash", "usage": { "total_tokens": 150 },
      "context_meta": { "bound_run": "<run_id>" }, "duration_ms": 1820,
      "created_at": "2026-09-27 12:00:02" }
  ]
}
```

| 状态码 | 含义 |
|--------|------|
| 400 | `run_id` 缺失，或 `limit` 非 1–1000 的整数 |
| 404 | `run_id` 查不到（"run 不存在"必须与"这次没追问过"区分开） |

### POST `/api/chat/history/clear`

清空某次审查的追问记录（幂等：没有记录时返回 `deleted: 0`）。

用 POST 而非 DELETE：本服务的写端点统一走 `do_POST` 顶部的 Content-Type / Origin
跨站守卫，单独开 DELETE 通道等于绕开这层防护。

请求体与响应：

```json
{ "run_id": "<run_id>" }
```

```json
{ "ok": true, "run_id": "<run_id>", "deleted": 2 }
```

| 状态码 | 含义 |
|--------|------|
| 400 | `run_id` 缺失 |
| 404 | `run_id` 查不到 |
| 415 | 跨站或非 JSON |

---

## 静态资源 `/static/*`

- `/` 与 `/index.html` 返回 SPA 入口；
- `/static/<file>` 映射到包内 `web_static/` 下的文件（前端 `base=/static/`）；
- 其它非 `/api/` 路径回退到 SPA 入口（供前端 hash 路由使用）；
- 越出静态目录的路径被拒绝。

```bash
curl http://127.0.0.1:8787/static/
curl http://127.0.0.1:8787/
```

---

## 输出格式

### Terminal

- 使用 Rich 渲染摘要面板和分级 findings。

### Markdown

- 适合保存为审查报告文件或在外部系统中复用。

### JSON

- 适合自动化处理。
- 顶层字段包括 `pr`、`summary`、`findings`、`counts`。

### GitHub Comment

- 专门用于 PR 评论区的 Markdown 模板。
- 与普通 Markdown 报告相比，更强调摘要表格和可读性。

## 退出行为

- 正常执行返回退出码 `0`。
- GitHub 抓取错误或 AI 客户端错误返回退出码 `1`。
- 参数校验失败会由 Click 返回非零退出码。

## 环境要求

- Python 3.12+
- `GITHUB_TOKEN`
- 对应 provider 的 API Key

## 相关文件

- `src/ai_pr_review/cli.py`
- `src/ai_pr_review/review_entry.py`
- `src/ai_pr_review/web_server.py`
- `src/ai_pr_review/web_ui.py`
- `src/ai_pr_review/services/review_orchestrator.py`
- `src/ai_pr_review/services/agent/planner.py`
- `src/ai_pr_review/services/evidence/finding_validator.py`
- `src/ai_pr_review/services/analyzers/static_analyzer.py`
- `src/ai_pr_review/services/analyzers/python_ast_analyzer.py`
- `src/ai_pr_review/services/analyzers/cross_file_interface.py`
- `src/ai_pr_review/benchmark/runner.py`
- `src/ai_pr_review/services/report_renderer.py`
- `tests/test_web_api_docs.py`（接口文档防漂移）
