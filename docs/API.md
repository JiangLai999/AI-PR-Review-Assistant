# CLI API 文档

本文档描述 `ai-pr-review` 当前已实现的命令行接口。

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

- `--dry-run`、`--only-fetch`、`--only-filter` 不能同时使用。

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

### `pr-review serve`

启动本地浏览器工作台，默认监听 `127.0.0.1:8787`。

界面为 React + Vite 应用，构建产物随包分发在 `src/ai_pr_review/web_static/`，
因此 `pip install` 后无需 Node 即可运行。界面包含五个视图：

- **概览**：产品定位、流水线、关键能力、实时统计与基准准确率；
- **审查工作台**：计划生成、完整审查、风险总览、审查计划、证据校验、文件过滤、
  跨文件接口影响、可筛选 Findings、人工反馈、原始 JSON；
- **历史审查**：运行记录、聚合统计、按 run_id 载入完整报告；
- **准确率**：策略对比、混淆矩阵、逐样例指标；
- **接口**：接口与 CLI 参考、运行边界。

服务端接口：

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/health` | 健康检查 |
| `POST` | `/api/plan` | 生成审查计划（不调用模型） |
| `POST` | `/api/review` | 执行完整审查 |
| `GET` | `/api/history?limit=N` | 历史运行记录与聚合统计（limit 1–200） |
| `GET` | `/api/report?run_id=…` | 取回某次运行的完整报告与元数据 |
| `GET` | `/api/benchmark?strategy=…` | 基准报告，strategy 可选 static / ast / combined / all |
| `POST` | `/api/feedback` | 记录 finding 人工反馈 |

静态资源路由约定：

- `/` 与 `/index.html` 返回 SPA 入口；
- `/static/<file>` 映射到包内 `web_static/` 下的文件；
- 其它非 `/api/` 路径回退到 SPA 入口（供前端 hash 路由使用）；
- 越出静态目录的路径被拒绝。

请求体上限 64 KB，服务仅监听本机回环地址。

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
