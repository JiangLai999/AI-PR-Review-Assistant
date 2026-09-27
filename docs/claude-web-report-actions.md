# Web 发布 / 导出前端（Phase 1）· 实现记录

**任务**：`web-p1-frontend`（实现）。后端 `POST /api/publish` 与 `GET /api/report/export` 由主控（codex）
**并行**实现；本文件只记录我改的前端与实测数字。
**状态**：已完成。`tsc --noEmit` exit 0；Playwright 断言 **51/51**；真实后端契约探测 **30/30**。

---

## 1. 改动点（file:line）

| 文件 | 位置 | 改动 |
|---|---|---|
| `web/src/api/types.ts` | `:150-168` | 新增 `PublishStatus`、`PublishResponse`、`ReportExportFormat` |
| `web/src/api/client.ts` | `:124-131` | 新增 `api.publish(runId, confirm)`（固定 JSON 通道，未动 `request()` 的 content-type 行为） |
| `web/src/api/client.ts` | `:134-137` | 新增 `api.exportReportUrl(runId, format)`——导出走 `<a download>`，**故意**不经过 `request()`：`request()` 把任何非 JSON 响应体当错误抛（`client.ts:44-52`），而 markdown 导出就是 `text/markdown` 附件响应 |
| `web/src/components/ReportActions.tsx` | 新建（367 行） | 发布/导出一体组件（五态 + 失败态 + 复制 + 下载） |
| `web/src/pages/ReviewPage.tsx` | `:91` | 新增 `resultRunId` 状态（初值取持久化的 `initialResult.run.id`） |
| `web/src/pages/ReviewPage.tsx` | `:167,173,190,303` | 每次开始新运行先清空，成功时写入本次 run |
| `web/src/pages/ReviewPage.tsx` | `:643-648` | 风险总览之后新增 `DELIVER` Section，挂 `<ReportActions runId={resultRunId} />` |
| `web/src/pages/HistoryPage.tsx` | `:209` | 打开某条运行报告后挂同一个 `<ReportActions runId={report.run_id} />` |
| `web/src/styles/components.css` | `:1132-1174` | 新增 `.btn-danger` 与 `.report-actions*` 样式（全部走 design tokens） |
| `.pytest_claude/claude/verify-report-actions.mjs` | 证据脚本 | Playwright 断言 51 条（**不在** `web/` 里，避免动 `web/tools/`） |
| `.pytest_claude/claude/probe_publish_contract.py` | 证据脚本 | 对着真实后端探测契约 30 条 |

**未改**：`src/ai_pr_review/**`（后端是主控的）、`ApiPage.tsx`、`web/tools/*`、`web/package.json`（未新增任何依赖）。
未运行 `npm run build`；`web_static/` 保持原样。

### 1.1 两个刻意的实现选择

1. **计划模式结果渲染「禁用态」而不是整块隐藏**。`plan_only` 不落库（`review_orchestrator.py:267-277`），
   `result.run.id` 为 `null`。隐藏的话用户只会觉得"功能没做"；禁用态 + 一句"先生成一次完整审查再发布"
   能解释"为什么没有发布按钮"，并且组件在 `runId === null` 时**一次请求都不发**（`ReportActions.tsx:119-121`）。
2. **`resultRunId` 独立成 state，不用 `job.run_id` 兜底**。先跑完整审查、再跑一次计划模式时，
   `job` 状态还留着旧 run；若拿它兜底，旧 run 的发布按钮会挂在新结果下面（发错帖）。初值取
   `initialResult?.run?.id`，保证切页返回后不丢 run（`ReviewPage.tsx:89-91`）。

---

## 2. 五态与错误映射

### 2.1 状态机（`ReportActions.tsx:13`）

| 态 | 触发 | 界面 |
|---|---|---|
| `idle` | 初始 / 「取消」/「重新预览」 | 入口按钮「发布到 GitHub PR」+ 下载 ×2；说明"第一步只生成预览" |
| `previewing` | 点击入口（**固定 `confirm:false`**） | Spinner +「正在生成评论预览…」 |
| `previewed` | 收到 `status: "preview"` | 只读正文预览（`<pre>`，等宽，`pre-wrap`）+ 危险色「确认发布到 GitHub PR」+「取消」 |
| `publishing` | 点击确认（**唯一致 `confirm:true` 的路径**） | Spinner +「发布请求无法中断，请不要关闭页面」 |
| `published` | 收到 `published` / `already_published` | 成功/警告 Notice + `comment_url` 链接 +「重新预览」 |
| `failed` | 任一请求抛错 | 可读文案（下表）+「重试发布」/「重试预览」 |

**不误发的结构保证**：`confirmPublish()`（`ReportActions.tsx:150-166`）是唯一发送 `confirm:true` 的函数，
而它只被「确认发布到 GitHub PR」与失败后的「重试发布」两个按钮调用；入口按钮只调 `requestPreview()`。
服务端侧 `PublishService.preview` 根本不构造 GitHub 客户端，所以是**双重**保证（前端纪律 + 后端结构）。

### 2.2 错误映射（`ReportActions.tsx:22-42`，`ApiError.status` → 文案）

| HTTP | 服务端 code（实测） | 前端文案 |
|---|---|---|
| 0 | （连不上本地服务） | 无法连接到本地服务 · 请确认 `pr-review serve` 仍在运行 |
| 400 | `invalid_request` | 请求不合法 · 缺少或非法的 run_id |
| 401 | —（预留） | GitHub 凭证无效 · 到「设置」页更新 Token |
| 403 | —（预留，上游失败实际走 502） | GitHub 拒绝了这次请求 · 权限不足或限流 |
| 404 | `not_found` | 找不到这次审查记录 · 该运行可能已被清理 |
| 409 | `not_publishable` | 这次运行没有可发布的 PR 链接 |
| 415 | （跨站守卫，无 code） | 请求被本地服务拒绝 · 跨站或非 JSON |
| 502 | `publish_failed` | GitHub 侧发布失败 · 附上游原文 |
| 503 | `missing_credentials` | 未配置 GitHub Token · 到「设置」页填写 |
| 其它 | — | 发布失败（HTTP n）+ 原始 message |

每条文案都**追加服务端原始 `error` 串**，所以分类不准时用户仍能看到真相。
401/403 在服务端被 `_post_comment` 的 `except Exception` 统一包成 `publish_failed`（502），
所以这两条在真实链路里通常不会出现；保留它们是为了将来后端细分时不改前端。

### 2.3 其它交互

- **幂等**：`already_published` → 警告色 Notice「该运行已发布过评论，本次又发了一条。」+ `comment_url` +
  「重复发布不会被拦截」。**不谎称去重**：主控落地的账本是**落盘**的（`web_server.py:63-95`
  `<db 目录>/published-comments.json`），我最初按提案写的"仅在内存"是错的，已改成"本地落盘的发布记录"。
- **复制**：`navigator.clipboard.writeText` → 失败回退隐藏 `<textarea>` + `document.execCommand('copy')`
  （`ReportActions.tsx:55-78`）；成功才显示「已复制」并 2 秒后消失，失败显示"复制失败，请手动选中正文复制"。
- **下载**：markdown 用裸 `download`（文件名由服务端 `Content-Disposition: pr<N>-<run8>.md` 决定）；
  JSON 是内联 JSON 响应、没有该头，所以显式给 `download="pr-review-<run8>.json"`，否则浏览器会用 URL
  末段当文件名。
- **无 `run_id`**：整卡禁用 + 一句说明；下载链接不给 `href`。

---

## 3. 验证（真跑，数字为实测）

### 3.1 编译

```bash
cd web && npx tsc --noEmit      # exit 0（改动前基线同样 exit 0）
```

### 3.2 前端行为（Playwright，离线打桩）

```bash
cd web && npx vite --port 5199 --strictPort        # 只起 dev server，未执行 npm run build
node .pytest_claude/claude/verify-report-actions.mjs
# 断言：51 passed, 0 failed（exit 0）；6 个场景
```

覆盖：完整审查后出现组件（含切页返回仍带该 run）· **自证 1**（`confirm:false` 序列里没有 `confirm:true`，
且二次确认后序列恰为 `[false, true]`）· 幂等提示 · **自证 2**（9 个状态码 → 文案逐条断言）·
复制正文写进剪贴板 · 下载 URL · 计划模式禁用态 · 历史页挂载。

> 脚本位置说明：任务书说"用你已有的 `web/tools/*.mjs`"，但 `web/tools/` **不在 write_scope**，
> 所以新脚本放在 `.pytest_claude/claude/`（证据目录），没有往 `web/` 里加文件。
> 脚本用 `page.route(谓词)` 而不是 glob `**/api/**`：后者会把 vite 的模块请求
> `/static/src/api/client.ts` 一起拦掉，页面根本加载不出来。

### 3.3 与真实后端对齐（临时 DB + 随机端口，不联网、不发帖）

```bash
TEMP=... TMP=... python .pytest_claude/claude/probe_publish_contract.py
# 契约探测：30 passed, 0 failed
```

用前端**同款请求头**（`content-type: application/json` + `Origin: http://127.0.0.1:5199` +
`Sec-Fetch-Site: same-origin`）打真实 handler，实测到：

- preview：`status=preview`、`requires_confirmation=true`、`comment_url=""`、`comment_chars==len(comment_body)`，
  正文含真 finding（"SQL injection risk"）；
- 错误码：未知 run→404 `not_found`、非 GitHub PR→409 `not_publishable`、缺 run_id→400、
  跨站 Origin→**415**、`text/plain`→415、`OPTIONS`→405 且**无** `Access-Control-*`；
- markdown 导出：`attachment; filename="pr7-<run8>.md"`，正文用落库的**真** `pr_title`/`pr_author`
  （没退化成 `Stored review <run_id>`）；
- json 导出：顶层键恰为 `run_id/run/review/plan/validation/cross_file_impacts/interface_impacts/feedback`。

**没有**调用过 `confirm:true` 打真实后端；**没有**向任何 GitHub PR 发过评论。
脚本只读临时目录，不读也不打印任何真实凭据（假 token 是现场填的字符串）。

### 3.4 回归（别人的测试，只读不跑改）

```bash
TEMP=... TMP=... python -m pytest tests/test_web_server.py -q --no-cov   # 60 passed in 31.41s
```

（改动前基线 45 passed；主控并行加了 15 条发布/导出用例，此处仅作对照，未修改任何测试。）

---

## 4. 未决项 / 诚实清单

1. **发布成功链路没有真实发帖验证**：`confirm:true` 只在**打桩**下跑过（Playwright 场景 2），
   真实 GitHub 写路径（PyGithub `create_issue_comment`、`html_url` 是否存在）我**未实测**——
   无 token、不联网。若上游不返回 `html_url`，界面已降级为"GitHub 没有返回评论链接，请在 PR 会话页查看"。
2. **导出失败没有 UI 提示**：下载是原生 `<a download>`，若服务端返 409/404（`x.json`/`x.md` 里是
   `{"error": …}`），浏览器仍会存成文件，界面不弹错。要么将来改成 `fetch` + Blob 才能捕获，
   要么接受这个降级（当前选择后者，与任务书"给一个 `<a download>`"一致）。
3. **`requires_confirmation` 在类型里是可选的**：契约 200 响应列了它，但已发布分支的实际载荷里
   主控用 `setdefault` 补成 `false`（`web_server.py:103`）。前端一律以 `status` 判定，不依赖该字段。
4. **未跑 `npm run build`**（任务书禁止）：`web_static/` 仍是旧产物，**开发服务器/生产页面上看不到本次改动**，
   需要主控在整合时统一重建。
5. **未跑 `web/tools/audit-pages.mjs`**：它要连 8787，而该端口已被别的进程占用（health 返回 200），
   为避免干扰他人服务我没有连它，也没有杀进程。
6. **`docs/API.md` / `ApiPage.tsx` 未同步新接口**：接口文档是另一个 agent 的 write_scope，我没碰。
   `ApiPage.tsx:11-57` 的 `ENDPOINTS` 现在仍然只有 7 条，需要在文档轮次补 `/api/publish` 与
   `/api/report/export`。
