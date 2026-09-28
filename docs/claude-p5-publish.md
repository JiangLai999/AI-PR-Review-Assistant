# P5 后端：publish / demo / showcase（任务 `claude-p5-publish`）

本文说明契约 `docs/review-workspace-contract.md` §12.2 / §12.3 / §12.5 中属于
Claude Code 的后端实现：`command.execute` 的 `publish` 命令、`demo` / `showcase`
命令，以及 CLI 与后端共用的 payload builder。

## 1. 交付文件

| 文件 | 作用 |
|---|---|
| `src/ai_pr_review/services/publish_service.py`（新增） | 两阶段发布：目标解析、预览、确认、错误码、评论正文再生成 |
| `src/ai_pr_review/services/demo_runner.py`（新增） | 离线 Demo payload builder（CLI + Chat 后端共用） |
| `src/ai_pr_review/services/showcase_runner.py`（新增） | 参赛演示路径 payload builder（CLI + Chat 后端共用） |
| `src/ai_pr_review/cli.py` | `demo` / `showcase` 改为调用共享 builder（输出逐字节不变） |
| `src/ai_pr_review/backend/jsonl_server.py` | `Session.published_run_ids`、`publish` / `demo` / `showcase` 命令、`/help` 文案 |
| `src/ai_pr_review/services/review_orchestrator.py` | 新 run 的 metadata 增加 `pr_title` |
| `src/ai_pr_review/services/hybrid_orchestrator.py` | 同上 |
| `tests/test_jsonl_backend.py`、`tests/test_cli.py` | 发布 / 离线 / 字节不变测试 |

## 2. `publish` 命令（契约 §12.2）

### 2.1 目标解析

`args = [<run_id>] [--confirm]`（也接受 `-c`）。

- 有 `run_id`：从 `ResultStore` 读取该 run；
- 无 `run_id`：使用 `current_report.run.id`（当前会话报告，包括用
  `/history <run_id>` 打开的历史报告）；会话没有报告 → `invalid_request`；
- 其他参数（未知 flag、两个 run_id）→ `invalid_request` 并回显用法。**故意不猜测
  拼错的 `--confirm`**，否则可能替用户发出一次他没要求的 GitHub 写入。

### 2.2 两阶段

1. **preview（无 `--confirm`）**：只读本地 SQLite 与本地配置，**不构造 GitHub 客户端、
   不发任何网络请求**。测试用假的 `PRFetcher` 断言 `create_issue_comment` 未被调用，
   连 `_get_pull_request` 都没有被调用。
2. **publish（有 `--confirm`）**：走
   `PRFetcher._get_pull_request(owner, repo, number).create_issue_comment(body)`，
   全模块只有 `PublishService._post_comment` 会触网。

### 2.3 载荷

preview 与 published 的字段顺序与契约示例一致：

```
status, [requires_confirmation,] run_id, repository, pr_number, url,
comment_body, comment_chars, findings, already_published, text
```

- `comment_body` 与 `comment_chars = len(comment_body)`；
- `findings` 为该 run 存储的 Finding 数；
- published 去掉 `requires_confirmation`，`text` 里带上目标 `owner/repo#N` 与 URL；
- 重复发布时 `text` 追加一行警告，**不新增字段**，以免 TUI 侧契约字段集变化。

### 2.4 错误码

| 场景 | 错误码 |
|---|---|
| 会话无报告、参数非法 | `invalid_request` |
| run_id 不存在（或结果不可读） | `not_found` |
| 存储的 `pr_url` 不是 GitHub PR URL | `not_publishable` |
| 没有 GitHub Token | `missing_credentials`（文案指向 `pr-review config`） |
| GitHub API / 网络失败 | `publish_failed`（携带上游 message） |

判定顺序：`not_found` → `not_publishable` → `missing_credentials`。**这是刻意选择**：
未知 run、非 GitHub URL 这两类问题配置 Token 也解决不了，报更具体的原因才诚实；
而凭据检查同时作用于 preview 与 confirm —— 预览的语义是"告诉你会发生什么"，
在机器根本没有 Token 时仍然返回一份可发布的预览会误导用户。

### 2.5 重复发布与会话账本

- 账本在 `Session.published_run_ids`（内存），**从不落盘**；
- 同一会话内第二次发布：照常发帖（**绝不静默跳过**），返回
  `already_published: true` 并附警告 "注意：该 Run 在本会话中已发布过一次…"；
- 只有发布**成功**后才记账：`create_issue_comment` 抛错时该 run 不进入账本，
  重试仍视为首次发布，因此绝不会出现"没发出去却已记账"；
- 不同会话互不影响（新会话再发一次是用户的明确意图）；
- 为了让不带 `session.create` 握手的调用方也能获得重复检测，`publish` 在
  `session_id` 非空而会话不存在时会按需创建该会话；`session_id` 为空时不记账
  （TUI 始终会带 session_id）。

### 2.6 评论正文的确定性再生成

正文由 `ReportRenderer.render_github_comment(result, pr_data)` 现算，不存储副本：
`result` 来自 `ResultStore.get_result`，`pr_data` 由 run 记录重建。

历史 run 从未保存 PR 标题与作者，因此：

- `pr_title`：优先取 metadata 中的 `pr_title`；缺失时用**空串** `""`；
- `author`：历史 run 无从得知，用固定占位符 `"unknown"`；`state` 用 `"unknown"`，
  `head_ref` / `base_ref` / `base_sha` 用 `""`。

**禁止编造作者或标题**：占位符是唯一允许的取值。默认模板（`## 🤖 AI PR Review
Report`）本来只使用报告标题而不使用 PR 标题/作者，所以占位符不会污染默认评论；
只有自定义 `github_comment_template` 引用 `{pr_title}` / `{author}` 时才会显示，
此时显示的也是"未记录"而不是虚构值。

"Files Changed" 一行取 run 记录的 `total_files`（PR 变更文件总数的快照）：
数据库没有保存逐文件列表，若直接传空文件列表会渲染成 `Files Changed: 0`，
那是错误的数字而非缺失的数字。`_StoredRunPRData` 用一个私有属性覆盖
`changed_files_count` 来提供该计数。

新 run 的 metadata 现在写入 `pr_title`（两个 orchestrator），因此**从此以后**的 run
能渲染真实标题；历史 run 维持诚实占位符。

## 3. `demo` / `showcase`（契约 §12.3）

| 命令 | args | 返回 |
|---|---|---|
| `demo` | `["list"]` | `{"cases": [{key,title,description}], "text"}` |
| `demo` | `[<case_key>]`（默认 `sql-injection`） | `pr-review demo --case <key> --json-output` 的对象 + `text` |
| `showcase` | `[]` | `pr-review showcase --json-output` 的对象 + `text` |

- 未知 case → `invalid_request`，message 列出可用 keys
  （`sql-injection, tls-disabled, clean-change`）；
- CLI 与后端共用 `services/demo_runner.py` / `services/showcase_runner.py`，
  `text` 通过 `{**payload, "text": …}` 追加在末尾，不改变原有键集合与顺序；
- 三个命令**严格离线**：不调用模型、不调用 GitHub、不写文件、不写历史库；
  `showcase` 的 `real_review_ready` 仅由已加载的配置推导。

> 说明：`src/ai_pr_review/demo_runner.py`（顶层，Web workbench 在用）不在本次
> 改动范围内，保持原样；新的共享 builder 位于 `services/` 下，两者互不影响。

### 3.1 字节不变的证据

重构前后分别对 CLI 真实输出取 SHA-256（Windows 文本流会把 `\n` 转成 `\r\n`，
下表为去掉该平台转换后的规范化摘要，也就是 `CliRunner` 看到的内容）：

| 命令 | 重构前 | 重构后 |
|---|---|---|
| `demo --case sql-injection --json-output` | `91e9948d…8e08d95` | 同 |
| `demo --case tls-disabled --json-output` | `d277f194…a54795e2d1e18` | 同 |
| `demo --case clean-change --json-output` | `d1245bae…b1d644203015` | 同 |
| `showcase --json-output`（同一 workspace 配置） | `bceda361…99e735e923` | 同 |

`tests/test_cli.py` 用两种方式固定：与共享 builder 的输出逐字节比较，以及与上表的
摘要常量比较（`DEMO_JSON_SHA256`）；`showcase` 另有一份字面量 golden payload。

## 4. 测试

新增 31 条用例（`tests/test_jsonl_backend.py` 19 条、`tests/test_cli.py` 12 条），覆盖：

- preview 不调用 `create_issue_comment`（连 `_get_pull_request` 都没调用）；
- `--confirm` 恰好发布一次，正文与预览一致；
- 缺 token（preview 与 confirm 都是 `missing_credentials`）、未知 run、非 GitHub URL、
  API 失败（且失败不记账）、重复发布 `already_published` + 警告 + 真的再发一次、
  跨会话账本隔离、未知参数；
- 正文由存储结果再生成（含 `Files Changed` 取存储计数）；
- `pr_title` 占位符规则（自定义模板下可观测），以及 CLI 真实审查流程写入 `pr_title`；
- `demo list` / `demo <case>` / `showcase` 与 CLI 对象一致、未知 case 报错、三个命令
  在 `PRFetcher` 与模型工厂被替换成"一旦构造就报错"时仍能成功且不产生任何文件。

运行（PowerShell，任务指定方式）：

```powershell
New-Item -ItemType Directory -Force -Path .\.pytest_x
$env:TEMP = (Resolve-Path .\.pytest_x).Path; $env:TMP = $env:TEMP
python -m pytest -q --no-cov
```

结果：`498 passed, 1 skipped`。

## 5. 未决 / 残余不确定项

1. **hybrid 路径的 `Files Changed`**：`hybrid_orchestrator` 渲染评论时用的是过滤后的
   PR 数据，而落库的 `total_files` 是过滤前的数量。发布历史 hybrid run 时表格显示的是
   `total_files`（PR 总变更数），与"当时那条评论"可能相差被过滤掉的文件数。选择一个
   口径而非两个，是为了确定性；若评审要求逐字段复刻历史渲染，需要额外存列。
2. **凭据检查也作用于 preview**：契约未明说 preview 是否需要 token。这里选择报错
   （见 §2.4），若产品希望"先看预览、配置后再发布"，把 check 只留在 confirm 即可。
3. **`pr_title` 只对新 run 生效**：历史 run 的标题无法追溯，占位符为 `""`，
   前端若把空标题直接展示会显示空白；建议 TUI 侧对空值显示"未记录标题"。
4. **无 session_id 的调用**：不记账、不做重复检测（TUI 始终带 session_id）。
5. `tests/test_review_orchestrator.py` 不在本次写入范围内，因此 hybrid orchestrator 的
   `pr_title` 只有全量回归覆盖，没有专门的断言用例。
