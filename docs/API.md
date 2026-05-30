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
- `src/ai_pr_review/services/review_orchestrator.py`
- `src/ai_pr_review/services/report_renderer.py`
