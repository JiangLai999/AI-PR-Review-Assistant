# Web 审查工作台下一阶段方案（claude）

**任务**：`web-wb-claude`（方案商讨，非编码）。重点方向＝端到端闭环：**发布审查评论到 GitHub** + **报告导出/复制**。
**方法**：只读源码 + 一次离线探测（临时端口 8799，已关闭），所有结论给 `文件:行号`。本文档是唯一被写入的文件。

---

## 0. 结论摘要（先看这段）

1. **主控 7 条缺口里有 1 条已经不成立**：CI **已经**构建前端并有"产物必须与源码同步"的校验
   （`.github/workflows/ci.yml:46-83`：`npm ci` → `npx tsc --noEmit` → `npm run build` → `git diff --quiet -- src/ai_pr_review/web_static`）。
   缺口 #7 应从待办列表移除。
2. **两条重点方向的真实工作量不对称**：发布评论**几乎不用写新的业务代码**（`PublishService` 已经是完整的两阶段实现，
   `src/ai_pr_review/services/publish_service.py:372-415`），代价集中在**安全**（新增的写端点会把本地服务变成
   "任何网页都能替你向 GitHub 发帖"的糊涂代理，我已实测复现，见 §5.1）；导出则需要**先定一个真相源**
   —— 仓库里现在有 **3 个 markdown 生产者**，`export-run` 和 TUI `/report` 输出的**不是同一份东西**（§3.1）。
3. **两个必须知道的事实级坑**：① `POST` 的 `Content-Type` 服务端从不校验，且没有 `do_OPTIONS`（实测 `501`），
   所以同源策略挡不住跨站 `text/plain` 简单请求直打到 `do_POST`；② `export-run` 读的元数据键 **永远不存在**
   （`cli.py:3096-3097` 读 `metadata["pr"]`，而编排器只写 `pr_title`/`pr_author`），所以 CLI 导出的 markdown 里
   PR 标题一直是 `Stored review <run_id>`、作者一直是 `unknown`——Web 导出**不要**照抄这段。
4. **如果只做 3 件**：① 发布评论 ② 报告导出/复制 ③ 接口文档补齐（S 号活，且 README/API 文档现在写着
   "全部 HTTP 接口"，是**假话**，见 §1.3-D）。

---

## 1. 现状核对

### 1.1 我实际读到的关键位置

| 关注点 | 位置 | 我读到的结论 |
|---|---|---|
| 发布两阶段 | `services/publish_service.py:372-381`(preview) / `:383-400`(publish) / `:402-415`(_post_comment) | preview **不构造 GitHub 客户端**（模块 docstring `:1-13`）；publish 只有一次 `create_issue_comment` |
| 发布错误码 | `publish_service.py:33-39` | `missing_credentials / not_found / not_publishable / publish_failed / invalid_request`，五个码已冻结 |
| 目标解析顺序 | `publish_service.py:301-325` | 先 `not_found`/`not_publishable`，**再** `missing_credentials`（`:324-325`）——顺序有意义，别重排 |
| 评论正文构造 | `publish_service.py:329-358` | `ReportRenderer.render_github_comment` + `GitHubCommentMeta`；`ui_language` 取自 `config.preferences`（`:338`） |
| 北京时间 | `publish_service.py:152-175` | 裸时间戳按 UTC 解释再转 UTC+8，输出 `YYYY-MM-DD HH:MM:SS 北京时间`；解析失败**原样透传**。我实测：`format_reviewed_at("2026-09-27 06:39:00")` → `2026-09-27 14:39:00 北京时间` |
| 统计尾注 | `publish_service.py:178-204` | `comment_filter_disclosure` 缺值保持 `None`→渲染器整段省略，**不打印没人测过的 0**；实测 `comment_filter_disclosure(None)` → 三键全 `None` |
| 历史 Run 重建 | `publish_service.py:224-266` | 只填库里真有的字段；`pr_title`/`pr_author` 缺失时用 `""`/`unknown` 占位（`:47-49`） |
| 幂等/去重 | `publish_service.py:57`(警告文案) / `:383-400`(`published_run_ids`) | **账本是调用方传入的 `MutableSet[str]`，本模块不持久化**；重复发布**照样发**，只置 `already_published` 并加警告 |
| 账本真正的家 | `backend/jsonl_server.py:782-785`(Session 字段) + `:3956-3961`(_publish_ledger) | 挂在 **per-session 对象**上，注释明写"in-memory only … nothing here may survive a restart" |
| 契约 | `docs/review-workspace-contract.md:557-612` §12.2 | 两阶段**强制**；preview 必须零网络写；payload 逐字段冻结；`:611-612` "ledger lives on the session object, **never on disk**" |
| CLI 的发布 | `cli.py:1782-1792`(`maybe_publish_comment`) + `:2884-2888`(`--publish-comment`) | **不存在 `pr-review publish` 子命令**（15 个命令全表见 `cli.py` 的 `@main.command`）；CLI 是"审查跑完顺带发"，**没有 preview/confirm** |
| CLI 的导出 | `cli.py:3066-3128` | `export-run --format markdown\|json --output <FILE>`，`markdown` 走 `ReportRenderer.render_markdown`（`:3122-3126`） |
| TUI 的导出 | `backend/jsonl_server.py:4128-4159`(`_export_text`) + `:4438-4464` | **手写渲染器**，输入是 `current_report` 的 `pr/counts/findings` 形状，**不经过 `ReportRenderer`** |
| TUI 的发布交互 | `frontend/tui/src/app.tsx:4896-4963` | 五态 `preview/publishing/published/failed/cancelled`（`review-report.ts:173`）；`publishing` 不可客户端中断 |
| Web 路由 | `web_server.py:83-136`(GET) / `:140-209`(POST) | POST 白名单在 `:161`，**15 行之外**才进业务分支；`:153-159` 的 cancel 分支先于白名单 |
| Web 报告 | `web_server.py:427-455` | 只返回 JSON；**无格式参数**；`record` 靠 `list_runs(limit=200)` 线性找（`:439-440`） |
| Web 响应工具 | `web_server.py:548-565`(`_send_json`/`_send`) | `_send` **不带自定义响应头**能力，也没有 `Content-Disposition` |
| 请求体上限 | `web_server.py:29` + `:529-546` | 64KB；`_declared_body_too_large` 只读 `Content-Length` 就拒绝 |
| 设置页可写字段 | `web_config.py:21-33` + `:94` | `EDITABLE_AI_FIELDS` 11 项**全是 `ai_client`**；`preferences` 一个都没有 |
| 配置保存会重建对象 | `config.py:1491-1521`(`_sync_runtime_sections`) | `save()` 会 `self.ai_client = AIClientConfig(...)`（`:1503`）**换新对象**；`github_token` 是原地赋值（`:1501`）所以跨保存仍有效 |
| plan 模式不落库 | `review_orchestrator.py:267-277` + `:219` | `plan_only` 不调 `save_result`，`run_id` 保持 `None` → Web 响应里 `run.id = null` |
| 前端结果区 | `web/src/pages/ReviewPage.tsx:553-772` | 已有复制按钮（`:748-770`，`navigator.clipboard.writeText`）；`result.run?.id` 在 `:736` 已用于反馈 |
| 历史页报告区 | `web/src/pages/HistoryPage.tsx:173-229` | 自带只读报告面板，`CardHead` 有 `extra` 插槽（`:185-188`）可挂动作按钮 |
| 前端错误通道 | `web/src/api/client.ts:44-60` | 非 JSON 响应体一律当错误抛出（`:50`）→ **服务端不要为导出返 `text/markdown`** |
| 前端无单测 | `web/package.json:7-12` | scripts 只有 `dev/build/preview/typecheck`，devDeps 无 vitest/jest → 前端逻辑只能靠 `tsc --noEmit` + playwright |

### 1.2 主控审计的更正（4 处）

| # | 审计原文 | 实际 | 证据 |
|---|---|---|---|
| A | "CI 不构建前端（`vite build` 不在 workflow）" | **已经在构建**，还额外校验产物与源码同步 | `.github/workflows/ci.yml:46-83`；`web/vite.config.ts:17-24` 的 `outDir` 指到 `src/ai_pr_review/web_static` |
| B | "`tests/test_web_server.py`（13 个测试类）" | **12 个类**（另有 1 个模块级测试函数，共 45 个用例） | `grep -c '^class '` = 12；模块级 `def test_serve_command_hands_the_resolved_config_path_to_the_web_layer` 在 `tests/test_web_server.py:540`；实跑 `45 passed` |
| C | "API 16 条" | **17 条**（12 GET + 5 POST） | GET：`web_server.py:87,90,103,106,109,112,115,118,121,126,129(→321),330`；POST：`:153,165,168,177,179/185` |
| D | "CLI 有 `pr-review publish`" | **没有这个子命令**；CLI 侧是 `--publish-comment` 旗标（审查完成后一次性直发，**无 preview/confirm**） | `cli.py:2884-2888`、`cli.py:1782-1792`；`@main.command` 全表 15 条无 `publish` |

> 另有两处**轻微**计数偏差（不影响结论）：`web/.shots/` 是 **31 张 PNG + 1 个 txt**，不是"40+ 张"；
> 缺口 #4 的"7/16"应为 **7/17**。

### 1.3 主控审计的遗漏（我另外发现的，按重要性）

**A.「接口只文档化了 7 条」有三个发生地，不是一处。**
除 `web/src/pages/ApiPage.tsx:11-57`（`ENDPOINTS` 7 条）外，还有：
- `docs/API.md:117-127` 的表格同样只有那 7 条；
- `README.md:416` 写着接口页包含"**全部** HTTP 接口与 CLI 命令参考"——这是可直接被用户证伪的表述；
- `ApiPage.tsx:59-68` 的 CLI 列表 8 条，而 CLI 实际 15 条命令（缺 `doctor/explain/export-run/trace/preferences/chat/showcase`）。
- 附带：`README.md:408` 与 `docs/API.md:108` 都写"界面包含**五个**视图"，实际是 6 个（`web/src/App.tsx:20-27` 的 `NAV`，第 6 个是**设置**）。

**B. 发布出去的评论**拿不到**评论自身的链接。**
`_post_comment`（`publish_service.py:402-415`）把 `create_issue_comment(...)` 的返回值**丢弃**，
所以 payload 里的 `url` 是 **PR 链接**，不是评论链接（`_published_payload` `:446-464`）。
"成功后可点击的评论链接"这条需求**必须**在 `publish_service` 上加一个字段才成立（§2.3），
而现有测试替身的 `create_issue_comment` 一律 `return None`（`tests/test_jsonl_backend.py:2274-2277`、`tests/test_cli.py:77-78`），
所以新字段**必须容忍空值**，否则会打红一批 out-of-scope 测试。

**C. `export-run` 的 markdown 一直丢标题与作者（既有缺陷）。**
`cli.py:3096-3097` 读 `metadata["pr"]`，但全仓**没有任何地方**往 run metadata 写 `"pr"` 键：
编排器写的是 `pr_title`/`pr_author`（`review_orchestrator.py:443-450`、`hybrid_orchestrator.py:531-536`），
`save_result` 原样 `json.dumps(metadata)`（`result_store.py:107-111`）。
于是 `pr_meta = {}` → 标题回落成 `f"Stored review {run_id}"`（`:3100`）、作者 `unknown`（`:3102`）。
**同一次 run 的 GitHub 评论有真标题，CLI 导出却没有** —— Web 导出若照抄这段，会把这个 bug 一起抄进去。

**D. 三个 markdown 生产者，互不一致。**
| 生产者 | 位置 | 输入形状 | 用在哪 |
|---|---|---|---|
| `ReportRenderer.render_markdown` | `report_renderer.py:362-413` | `ReviewResult` + `PRData` | `pr-review export-run`（`cli.py:3122-3126`） |
| `JsonlBackend._export_text` | `jsonl_server.py:4128-4159` | `current_report` 的 `pr/counts/findings` | TUI `/report`、`/export`（`:4438-4464`） |
| `ReportRenderer.render_github_comment` | `report_renderer.py:423-429` | 同上 + `GitHubCommentMeta` | 发布评论（两处调用点：`publish_service.py:410`、`cli.py:1792`） |

也就是说 **TUI 的 `/report` 与 CLI 的 `export-run` 不是同一份产物**。Web 必须显式选一个并写下来（§3.1 我选 `render_markdown`）。

**E. `plan_only` 的产物没有 run 记录。**
`plan_only` 不落库（`review_orchestrator.py:267-277`），`ReviewArtifacts.run_id` 默认 `None`（`:219`），
Web 的 `/api/plan` 响应因此是 `run.id = null`（`web_server.py:199-203`）。
→ 计划模式结果上**不能**出现发布/导出按钮（否则必然 `not_found`），且 `/api/publish` 收到空 `run_id` 时
**不能**去猜"最近一次 run"（Web 没有会话，猜=替用户发错帖子）。

**F. 前端没有单测框架，但服务端有现成夹具。**
`web/package.json:7-12` 无 test script；而 `tests/test_web_server.py:25-93` 的 `server` 夹具
已经提供"临时 SQLite + 已存好的一条 run + 假 token"，`:87` 的 `call()` 直打 HTTP。
**新功能的验证重心应放在 pytest 侧**（§4），前端只做 `tsc --noEmit` + playwright 可见性/截图。

---

## 2. 实现方案：发布审查评论到 GitHub

### 2.1 事实：载荷构造与冻结约束（先对齐，再设计）

Web 侧的**正确做法是把 `PublishService` 当黑盒复用**，不要在 `web_server.py` 里重写任何渲染：

```
Web 请求 → PublishService(config).preview/publish(run_id=…, published_run_ids=ledger)
         → load_target()  重建 PRData(publish_service.py:224-266) + render_github_comment(:334-358)
         → _post_comment() 唯一一次网络写(:402-415)
```

复用的理由（都是硬约束，不是偏好）：
- **评论格式已冻结**：`docs/P6_PLAN_2026-09-25.md:150-166` 记录 34 项结构要素全部有测试钉住，
  线上 PR #31 的正文与当前渲染器**逐字节一致**（sha256 `1c81b6c1…`）。Web 不得产生第四种正文。
- **同一 run 重复渲染必须逐字节相同**：`tests/test_jsonl_backend.py:2558` 已钉
  `second["comment_body"] == first["comment_body"]`。
- 北京时间（`:152-175`）与统计尾注（`:178-204`）都在 `publish_service` 内，Web 只要不插手就自动正确。

### 2.2 接口契约：`POST /api/publish`

**请求**

```json
{ "run_id": "9f3c…", "confirm": false }
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `run_id` | string | **是** | 库里已存在的 run。**不接受空值回退**（Web 无会话；空值→`invalid_request`） |
| `confirm` | bool | 否，默认 `false` | `false` = 预览（dry-run），`true` = 真发 |

- **不新增 `dry_run` 参数**：`confirm:false` 就是 dry-run，契约 §12.2 已把 preview 定义为"绝不写网络"。
  两个参数表达同一语义必然分叉。预览连 `PRFetcher` 都不构造（`publish_service.py:372-381`），
  所以"预览不会误发"是**结构保证**，不是纪律保证。
- **不复用 `parse_publish_args`**（`publish_service.py:102-123`）：它是 CLI 词法解析器（`["run1","--confirm"]`），
  HTTP 已经有结构化字段。目标解析与错误码仍由 `PublishService` 单点负责，两端不会漂移。

**响应（200）**＝ §12.2 冻结 payload **原样**（`publish_service.py:424-443` / `:446-464`）＋ **一个附加键** `comment_url`：

```json
{
  "status": "published",
  "run_id": "…", "repository": "owner/repo", "pr_number": 31, "url": "https://github.com/owner/repo/pull/31",
  "comment_body": "## 🤖 …", "comment_chars": 12523, "findings": 15,
  "already_published": false,
  "comment_url": "https://github.com/owner/repo/pull/31#issuecomment-123456",
  "text": "已向 owner/repo#31 发布审查评论（12523 字符）：…"
}
```

- `comment_url` **附加**、可空（`""`）。`status: "preview"` 时恒为 `""`。
- 得到它的最小改动见 §2.3；**注意契约 §12.2 是冻结文档，加键要同步回写契约与 `docs/claude-p5-publish.md`**。

**错误**：沿用现有 `{"error": …}`（`web_server.py:548-554`）并**加一个 `code`**：

| HTTP | `code` | 何时 | 前端该做什么 |
|---|---|---|---|
| 400 | `invalid_request` | `run_id` 缺失/空白 | 不该发生（按钮有闸门）；提示刷新 |
| 404 | `not_found` | run 不存在（含计划模式误传） | 提示"该结果没有审查记录"，隐藏按钮 |
| 409 | `not_publishable` | 存的 `pr_url` 不是 GitHub PR URL | 提示不可发布，隐藏按钮 |
| 412 | `missing_credentials` | 未配置 GitHub Token | **给"去设置页填写 Token"按钮** |
| 502 | `publish_failed` | GitHub 侧任何失败（含 403/限流） | 展示上游原文 + 重试 |
| 415 | `unsupported_media_type` | 非 `application/json` 请求体（**新增守卫**，见 §2.5） | 不该发生（前端固定发 JSON） |

- 5 个 `code` 与 `PUBLISH_ERROR_CODES`（`publish_service.py:33-39`）**一一对应**，Web 不新增语义。
- 状态码选择理由：区分码是为了让 UI 能分支（缺 token 要跳设置页、403 只能重试）；
  非 2xx 能让 `client.ts:54-60` 现有错误通道原样工作。
- `client.ts:18-26` 的 `ApiError` 需要**附加**一个可选 `code` 字段（增量改动，不破坏既有调用方）。

### 2.3 唯一需要动 `publish_service` 的改动：把评论链接带回来

```python
# publish_service.py:402-415
def _post_comment(self, target: PublishTarget) -> str:      # 由 None 改为返回评论链接
    try:
        ...
        comment = pull_request.create_issue_comment(target.comment_body)
    except Exception as exc:
        raise PublishError("publish_failed", f"发布评论失败：{exc}") from exc
    # PyGithub 的 IssueComment.html_url；替身返回 None 时降级为空串（不臆造链接）
    return str(getattr(comment, "html_url", "") or "")
```

- `publish()`（`:395-400`）把返回值透传给 `_published_payload(target, already_published, comment_url="")`，新参数**带默认值**。
- **兼容性**：所有现存替身 `create_issue_comment` 都 `return None`（`tests/test_jsonl_backend.py:2274-2277`、`tests/test_cli.py:77-78`），
  `getattr(None, "html_url", "")` → `""`，**不臆造、不报错**。§12.2 的键集是"至少这些键"，加键是增量。
- **未确认**：`IssueComment.html_url` 的存在性我**没有实测**（无 token、不联网），按 PyGithub 公开 API 应当存在；
  若不存在，`getattr` 兜底为空串，UI 走"在 PR 会话页可见"的降级文案，不会崩。
- 另一条**零改动**方案：不返回 `comment_url`，前端只能链到 PR（`payload.url`），文案写"已发布，可在 PR 会话页看到"。
  我**不建议**——"成功后能点进评论"是这次需求的原话，而它只值一个 5 行改动。

### 2.4 幂等 / 去重：账本放哪

**现状**：账本是 `MutableSet[str]`，由调用方持有（`publish_service.py:383-400`）；
TUI 把它挂在 per-session 对象上（`jsonl_server.py:782-785`、`:3956-3961`），契约明令**不得落盘**（§12.2 `:611-612`）。
两个已知细节：① `_publish_ledger("")` 会在每次调用时新建 Session → **空 session_id 等于没有去重**（`:3957-3961`）；
② 重启后账本清空 → 同一 run 会被当成"首次发布"。

**Web 方案**：把账本挂在 handler 子类上，与 `jobs` 同一模式（`web_server.py:72-79`）：

```python
publish_ledger: set[str]                       # 进程内，重启即清空
publish_lock: threading.Lock                   # 与 web_jobs.py:86 同风格
```

- **`serve()` 里显式挂一份**（`web_server.py:599-608` 的 `type(...)` 已经挂了 `config/jobs/config_path`），
  测试通过同类属性注入，互不串味。
- **为什么不落盘**：契约禁止；且"重启=新会话"正是 TUI 的语义（`jsonl_server.py:782-784` 的注释原话）。
- **语义代价（必须写进 UI）**：① 服务重启后同一 run 会再发一条；② **同一浏览器的两个标签页共享一个账本**
  （TUI 是按 session 隔离的，Web 不是）——所以 `already_published: true` 在 Web 上可能"莫名出现"。
  文案要解释这点，而不是让用户以为出 bug 了。
- **行为**：重复发布**照发**并置 `already_published: true`（§12.2 明令"never silently skip"），
  警告文案直接用常量 `REPEAT_PUBLISH_WARNING`（`publish_service.py:57`），前端**不得自己写一份**。
- 若将来要"每标签页独立"，再加 `session_id` cookie 并把它作为账本 key（本阶段不做，S/M 之外的复杂度不值得）。

### 2.5 权限与安全

**威胁模型**：服务只监听 `127.0.0.1`（`web_server.py:592-609`），没有鉴权——这对本地单机工具是合理设计，
**但新增一个"向 GitHub 写内容"的端点会让它变成糊涂代理**：用户浏览任意恶意网页时，那个页面可以盲发请求，替你发评论。

**实测证据**（我在 8799 端口起了一次服务，探测后已关闭）：

```
POST /api/feedback  Content-Type: text/plain   → 200 语义（业务已执行；返回 "Unknown run_id: nope"）
POST /api/feedback  Content-Type: text/plain + Origin: https://evil.example → 同上，Origin 被完全忽略
OPTIONS /api/plan                              → HTTP/1.0 501 Unsupported method ('OPTIONS')
```

根因在代码里：`_read_json`（`web_server.py:536-546`）只检查长度、直接 `json.loads`，**从不校验请求
`Content-Type`**；`web_server.py` 里也没有 `do_OPTIONS`、没有 `Access-Control-*`、没有 `Origin`/`Sec-Fetch-*` 判断
（全文件 grep 只命中响应侧 `Content-Type`：`:272,371,558`）。
于是跨站 `Content-Type: text/plain` 的"简单请求"**不触发预检**，直接进入 `do_POST`。

**必须做的三件事**（成本都很低）：

1. **只给新端点加媒体类型守卫**：`/api/publish` 要求 `Content-Type` 为 `application/json`，否则 415。
   这样跨站请求必须走预检，而 `OPTIONS` 会 501 → 浏览器侧直接掐断。
   ⚠️ **不能全局加这个守卫**：`tests/test_web_server.py:478-482`（`test_empty_body_is_treated_as_missing_url`）
   发的就是**无 Content-Type、无 body** 的 POST 并期望 400 `pr_url`——全局守卫会打红这条 out-of-scope 测试。
   先只护新端点，`/api/config`（同样会写盘）作为**后续**加固项，并同步修那条测试。
2. **要求一个自定义请求头**（如 `X-PR-Review-Client: web`）：自定义头必然触发预检 → 跨站发不出去。
   比 `Origin` 判断稳（`Origin` 可缺失：from 同源 GET 或某些隐私设置）。
3. **二段确认是服务端强制的**：不带 `confirm:true` 的请求在服务端**永不发帖**（`publish_service.py:383-400`
   只有 `publish()` 会写，而 Web 只在 `confirm` 为真时才调它）。

**权限/限流的诚实说明**：
- GitHub 侧 **403（无 repo 权限）/ 404（私有库不可见）/ 429（限流）** 在 `_post_comment` 的
  `except Exception`（`:411-415`）里**统一变成 `publish_failed`**，上游原文保留在 message 里。
  我**未实测** PyGithub 对各状态码的异常类型，所以 UI 不做细分类，只把原文显示出来 + 允许重试。
- **没有任何客户端限流**：连点两次"确认发布"就是两条评论（`already_published` 只警告不拦，§12.2 要求如此）。
  UI 侧的防护是**按钮在请求进行中禁用** + 成功后把按钮切成"已发布"。
- **dry-run**：`confirm:false`（§2.2）。预览**不构造 `PRFetcher`**，因此连 token 都不消费网络。

### 2.6 同步 or 异步？与 `web_jobs.py` 的取舍 → **选同步**

**证据化的时间上界**：
- `_get_pull_request` 走 `_execute_with_retry`（`pr_fetcher.py:197-202`），配置
  `max_retries=3, retry_base_delay=1.0, retry_max_delay=30.0, request_timeout=30`（`config.py:1221-1225`）
  → GET 最坏 ≈ 30s×4 + 退避 ≈ **150s**；
- `create_issue_comment`（`:410`）是**裸 PyGithub 调用，不重试** → 单次 30s 超时 → 合计最坏 **≈3 分钟**。

**为什么仍然选同步**：
- `ThreadingHTTPServer` 每请求一线程（`web_server.py:609`），慢发布**不阻塞**其它请求；
- 用户在对话框里**明确点过"确认发布"**，等待有心理预期——这正是 `/api/review` 当初必须任务化的原因
  （`web_jobs.py:1-15` 的注释：盲等 + 取消只是断连），而发布**没有可推进度**，做成任务只会换来一个
  永远 0% → 100% 的假进度条；
- 走 `web_jobs` 还要额外背 SSE 的线程模型：`_stream_job_events` 每个订阅者占一个线程 + 15s 心跳
  （`web_server.py:380-398`）。为一个亚秒级写操作付这个代价不合理。

**但必须配两条**：① 服务端侧不额外加超时（PyGithub 自带 30s）；② 前端 `fetch` **不设 AbortSignal**，
且 UI 明确显示"正在发布，不要关闭页面"；③ 若将来发布要变成"批量发 N 个 PR"，再复用 `ReviewJobManager`
同一形状任务化——**接口形状不变**（`POST` 返回 `job_id` → 轮询/SSE），所以现在选同步不会锁死未来。

### 2.7 函数级改动清单（发布）

| 文件 | 改动 | 量 |
|---|---|---|
| `services/publish_service.py` | `_post_comment` 返回 `comment_url`；`publish()` 透传；`_published_payload` 增参数（默认 `""`）；`_preview_payload` 增 `"comment_url": ""` | ~15 行 |
| `web_server.py` | ① `:161` 白名单加 `/api/publish`；② 新 `_handle_publish(payload)`（解析 `run_id`/`confirm` → 媒体类型守卫 → `PublishService(self.config).preview/publish` → 按 `PublishError.code` 映射状态码）；③ `publish_ledger` 类属性 + `serve()` 挂载（`:599-608`） | ~45 行 |
| `web/src/api/client.ts` | `ApiError` 加可选 `code`；`api.publish(runId, confirm)` | ~12 行 |
| `web/src/api/types.ts` | `PublishPayload`（= §12.2 payload + `comment_url`） | ~16 行 |
| `web/src/components/PublishDialog.tsx`（新） | 五态对话框：预览（目标/字数/条数/正文折叠预览/重复警告）→ 确认 → 结果（`text` + `comment_url`）/ 失败（按 `code` 分支） | ~150 行 |
| `web/src/components/ReportActions.tsx`（新，与导出共用） | 参数 `runId`，渲染 4 个按钮并持有对话框 | ~120 行 |
| `web/src/pages/ReviewPage.tsx` | 在风险总览后插 `<ReportActions runId={result.run?.id ?? null} />`——`runId` 为 `null`（计划模式）时不渲染 | ~6 行 |
| `web/src/pages/HistoryPage.tsx` | `CardHead` 的 `extra`（`:185-188`）挂同一个组件 | ~4 行 |

**明确不改**：`report_renderer.py`（格式冻结）、`web_jobs.py`、`AppConfig`/`PreferencesConfig` 的任何字段。

---

## 3. 实现方案：报告导出 / 复制

### 3.1 先定真相源：选 `ReportRenderer.render_markdown`

| 候选 | 选它的后果 |
|---|---|
| **`render_markdown`** ✅ | 与 `pr-review export-run --format markdown` **逐字节一致**，可写进验收（§7）。代价：与 **TUI `/report` 的输出不同**（`_export_text` 是另一份手写渲染器，`jsonl_server.py:4128-4159`） |
| `_export_text` | 与 TUI 一致，与 CLI 不一致，且它读的是 `current_report` 的会话形状——Web 手上是 SQLite 里的 `ReviewResult`，形状对不上 |
| `render_github_comment` | **不行**：那是给 GitHub 看的（含折叠块、24k 软截断 `report_renderer.py:195-197`），不是给人下载的报告 |

→ 选 `render_markdown`，并在文档里写死"**Web 导出 ≡ CLI `export-run`**；TUI 的 `/report` 是历史遗留的第三份实现，
建议后续单独收敛（不在本轮范围）"。

### 3.2 接口契约：`GET /api/report/export?run_id=…&format=markdown|json`

**为什么是 JSON 包文本，而不是 `Content-Disposition` 下载响应**：
1. `client.ts:44-52` 把**任何非 JSON 响应体**当错误抛（"服务返回了非 JSON 内容"）→ 返 `text/markdown` 需要另开一条
   fetch 路径，且丢掉统一的 JSON 错误通道；
2. `_send`（`web_server.py:556-565`）**不支持附加响应头**，做下载响应就得改底层 plumbing；
3. "复制"和"下载"在前端**需要同一个字符串**（剪贴板 + Blob），一次请求服务两种交互；
4. 错误语义统一：未知 run 仍是 `{"error": …}` + 404。

**响应 200**

```json
{
  "run_id": "9f3c…",
  "format": "markdown",
  "filename": "pr-review-owner-repo-31-9f3c1a2b.md",
  "text": "# Pull Request Review…",
  "chars": 18742,
  "files_changed": 12
}
```

- `format=markdown` → `ReportRenderer(config.report_renderer).render_markdown(result, pr_data, files_changed=…)`
  （与 `cli.py:3122-3126` 同一调用）。
- `format=json` → 与 `export-run --format json` **同构**：`{"run": <summary 行>, "result": <ReviewResult dump>}`
  （`cli.py:3118-3120`）。
- `filename` **不含时钟**（用 `owner/repo/pr_number/run_id[:8]`）：库里 `created_at` 是无时区标记的 UTC
  （`publish_service.py:152-159` 解释过这个坑），文件名里塞日期必然踩时区歧义。稳定文件名还有个好处：
  可断言（§4）。
- 错误：`400` 缺 `run_id` / 非法 `format`（`format` 白名单 `markdown|json`，错误里列出可选值）；
  `404` 未知 run。

**`PRData` 重建必须与发布共用同一个 builder**：把 `publish_service._stored_run_pr_data`（`:224-266`）
提为公有 `build_stored_run_pr_data(...)`，导出与发布都调它。这样：
- 顺带**修掉 §1.3-C**：Web 导出会拿到真 `pr_title`/`pr_author`（因为读的是 `pr_title`/`pr_author` 而不是幽灵键 `"pr"`）；
- 副作用：**Web 导出与今天的 CLI `export-run` 不再逐字节相同**（标题/作者那两行会不一样）。
  这是**修 bug 而非回归**，但必须同步决定：要么把 `cli.py:3090-3117` 也改成同一个 builder（推荐，`cli.py` 不在本任务写域，
  留给实现轮次），要么在验收里把差异**显式断言**下来（§7 我给的是"改成同一 builder 之后"的断言）。

### 3.3 前端交互

- **复制 Markdown** → `navigator.clipboard.writeText(text)`。代码库已有同样写法（`ReviewPage.tsx:756-758`），
  但它**不处理失败**：`navigator.clipboard` 在非安全上下文是 `undefined`（本地默认 `127.0.0.1` **是**安全上下文，
  但 `pr-review serve --host 0.0.0.0` + 局域网 IP 就不是）→ 抽一个 `copyText()` helper：
  先试 Clipboard API，失败则回退隐藏 `<textarea>` + `document.execCommand('copy')`，再失败就在对话框里给
  一个已全选的只读 textarea 让用户手动 `Ctrl+C`。**绝不**静默失败后显示"已复制"。
- **下载 Markdown / JSON** → `new Blob([text], {type})` + `URL.createObjectURL` + 临时 `<a download={filename}>`，
  之后 `revokeObjectURL`。文件名用响应里的 `filename`（服务端定，前端不拼）。
- **位置**：新增 `ReportActions` 组件，两处挂载：
  - `ReviewPage`：风险总览 Section 之后（`ReviewPage.tsx:553-632` 之后即插），**仅当 `result.run?.id` 非空**时渲染；
  - `HistoryPage`：报告区 `CardHead` 的 `extra`（`:185-188`）。
  两处共用同一组件 → 行为不可能分叉（这也是选"组件复用"而不是"各写一份"的原因）。
- **RAW 区既有的 JSON 复制按钮保留不动**（`:748-770`）；它复制的是**响应对象**，与"导出报告文件"是两件事，
  不要合并（合并会把"给人读的报告"和"给机器读的 API 响应"混为一谈）。

### 3.4 函数级改动清单（导出）

| 文件 | 改动 | 量 |
|---|---|---|
| `services/publish_service.py` | `_stored_run_pr_data` → 公有 `build_stored_run_pr_data`（名字进 `__all__` 或就近导出） | ~5 行 |
| `web_server.py` | 新 `_handle_report_export(query)`：解析 `run_id`/`format` → `ResultStore.get_result` + `get_run_summary` → 复用 builder → `render_markdown`/json dump → JSON 包文本；`:109` 之后加一条路由（**注意必须放在 `path.startswith("/api/")` 兜底之前**，`web_server.py:132-134`） | ~55 行 |
| `web/src/api/client.ts` | `api.exportReport(runId, format)` | ~6 行 |
| `web/src/api/types.ts` | `ExportResponse` | ~8 行 |
| `web/src/lib/clipboard.ts`（新） | `copyText()` 三级降级 | ~30 行 |
| `web/src/components/ReportActions.tsx` | 见 §2.7（与发布共用） | — |

---

## 4. 测试点：`tests/test_web_server.py` 新增用例（用例名级）

夹具复用现成的 `server`（`:25-93`，已含临时库 + 一条 run + 假 token）与 `call()`（`:87`）。
GitHub 替身用**已被验证过的打桩点**：`monkeypatch.setattr(publish_service, "PRFetcher", lambda **kw: fake)`
（`tests/test_jsonl_backend.py:2286` 的同款做法；handler 在别的线程跑，但 monkeypatch 是进程级的，照样生效）。

```python
class _FakeGitHub:                       # 放在 tests/test_web_server.py 顶部
    posted, targets, fail_with, comment_url  # create_issue_comment 返回 None 或带 html_url 的替身
```

**`class TestPublishEndpoint`**

| 用例名 | 断言要点 |
|---|---|
| `test_publish_preview_never_calls_github` | `fake.posted == []`（§12.2 硬规则） |
| `test_publish_preview_reports_target_and_size` | `status=="preview"`、`requires_confirmation is True`、`repository=="owner/repo"`、`pr_number==7`、`comment_chars==len(comment_body)`、`findings==1` |
| `test_publish_confirm_posts_body_verbatim` | `fake.posted == [payload["comment_body"]]`；`fake.targets == [("owner","repo",7)]` |
| `test_publish_confirm_drops_requires_confirmation` | `"requires_confirmation" not in payload`（§12.2 明文） |
| `test_publish_requires_run_id` | `{}` 与 `{"run_id":"   "}` → 400 + `code=="invalid_request"` |
| `test_publish_unknown_run_is_404` | `code=="not_found"`；`fake.posted == []` |
| `test_publish_non_github_run_is_not_publishable` | 夹具里另存一条 `pr_url="https://gitlab.com/…"` 的 run → 409 + `code=="not_publishable"` |
| `test_publish_missing_token_reports_setup_hint` | 清 `config.github_token` 与 `config.pr_fetcher.github_token` → 412 + `code=="missing_credentials"` + message 含 `pr-review config` |
| `test_publish_upstream_failure_never_claims_success` | `fake.fail_with=RuntimeError("boom")` → 502 + `code=="publish_failed"`；**全响应中不得出现 `"published"`** |
| `test_repeat_publish_warns_and_posts_twice` | 两次 confirm：`already_published` 由 `False`→`True`，`len(fake.posted)==2`（"never silently skip"） |
| `test_publish_preview_does_not_mutate_ledger` | 连续两次 preview 都是 `already_published is False` |
| `test_publish_comment_url_is_empty_when_upstream_returns_none` | 替身返回 `None` → `comment_url == ""`（诚实降级，钉住 §2.3 的 `getattr` 兜底） |
| `test_publish_comment_url_is_returned_when_available` | 替身返回带 `html_url` 的对象 → 原样透出 |
| `test_publish_rejects_non_json_content_type` | 用 `urllib` 发 `Content-Type: text/plain` → **415**（§2.5 守卫；这条同时是跨站防护的回归测试） |
| `test_publish_rejects_cross_origin_simple_request` | 带 `Origin: https://evil.example` + `text/plain` → 415（并顺带断言服务端**不**回 `Access-Control-Allow-Origin`） |
| `test_publish_ignores_unrelated_extra_keys` | 多传 `{"foo": 1}` 不影响结果（与 `/api/config` 的宽松风格一致） |
| `test_publish_does_not_leak_secrets` | 响应体不含夹具里的三个假密钥（对齐既有 `secrets` 夹具的用法，`:82-92`） |

**`class TestReportExport`**

| 用例名 | 断言要点 |
|---|---|
| `test_export_markdown_matches_renderer_bytes` | `payload["text"] == ReportRenderer(config.report_renderer).render_markdown(result, pr_data, files_changed=…)` |
| `test_export_markdown_uses_stored_pr_title_and_author` | 夹具 metadata 带 `pr_title`/`pr_author` → 正文含真标题与作者（**这条就是 §1.3-C 的回归钉子**） |
| `test_export_json_matches_export_run_shape` | 顶层恰为 `{"run","result"}`；`result["findings"][0]["title"]` 一致 |
| `test_export_includes_files_changed_from_stored_column` | 库里只存聚合列 → 正文 `Files Changed` 不是 0（复用 `cli.py:3086-3088/3117` 的口径） |
| `test_export_requires_run_id` | 400 |
| `test_export_unknown_run_is_404` | 404 |
| `test_export_rejects_unsupported_format` | `format=pdf` → 400，错误里含 `markdown`/`json` |
| `test_export_filename_is_derived_from_run_id_not_clock` | `filename == f"pr-review-owner-repo-7-{run_id[:8]}.md"`；正则断言**不含** `\d{4}-\d{2}-\d{2}` |
| `test_export_chars_matches_text_length` | `chars == len(text)` |
| `test_export_does_not_leak_secrets` | 同发布那条 |

**前端侧**（无单测框架，`web/package.json:7-12`）：
- `cd web && npx tsc --noEmit`（CI 同款，`:66-67`）；
- 新增 `web/tools/verify-report-actions.mjs`（Playwright，仿 `web/tools/audit-pages.mjs:1-30` 的可见性审计写法）：
  断言未出结果时**没有**发布/导出按钮、计划模式结果下按钮**不出现**、完整审查后按钮出现且点击能打开对话框、
  对话框内"确认发布"在预览返回前保持禁用。

---

## 5. 风险与坑（每条都有代码证据）

### 5.1 【高】新写端点 = 本地服务的糊涂代理（已实测复现）

见 §2.5：`_read_json` 不校验请求 `Content-Type`（`web_server.py:536-546`）、无 `do_OPTIONS`（实测 `501`）、
`Origin` 被忽略（实测）。**preview 类端点无所谓，但 `POST /api/publish` 会真的向 GitHub 写东西。**
必须按 §2.5 的三条守卫实施，否则"加功能"等于"加一个 CSRF 洞"。

### 5.2 【高】账本生命周期与 TUI 不同，用户会困惑

账本在进程内存（契约 §12.2 `:611-612` 强制）+ Web 无会话 → 重启后重复发布、多标签页共享状态（§2.4）。
**不能**靠"落盘去重"绕过（契约禁止），只能靠文案与 `already_published` 警告如实告知。

### 5.3 【中】`config.save` 会换掉 `config.ai_client` 对象

`_sync_runtime_sections`（`config.py:1491-1521`）在每次 `save()` 后**重建** `ai_client`。
所以：**任何跨请求缓存 `config.ai_client` / `PublishService` 的写法都会读到过期配置**
（评论正文的语言 `ui_language` 取自 `config.preferences`，`:338`；门槛取自 `config.post_processor`，`:331`）。
→ 每个请求现构造 `PublishService(self.config)`。它很便宜：`store` 是惰性属性（`:276-280`），构造不碰网络。
`config.github_token` 是原地赋值（`config.py:1501`），跨保存仍有效，不要"顺手缓存"别的。

### 5.4 【中】同步 POST 的时长上界 ≈3 分钟，且前端不能中止

见 §2.6。补充坑：**不要**为了"能取消"就顺手把发布塞进 `ReviewJobManager`——它的取消语义是
"文件边界生效"（`web_jobs.py:13-14`），发布没有文件边界，取消只会产生"评论也许发了也许没发"的不确定态。

### 5.5 【中】`export-run` 的元数据键是幽灵键

`cli.py:3096-3097` 读 `metadata["pr"]`，全仓无人写入（§1.3-C）。Web 若照抄会把 bug 复制一份；
若按 §3.2 共用 builder，则 Web 与今天的 CLI 输出**故意不一致**——这个差异必须在验收里写清，
否则会被当成"Web 导出有 bug"。

### 5.6 【中】三个 markdown 生产者，选错就漂移

§1.3-D 的表。Web 选 `render_markdown`（与 CLI 一致），**与 TUI `/report` 不一致**。
不写下来，下一个人会以为"Web 导出的报告缺东西"。

### 5.7 【低】计划模式结果没有 run，必须挡在 UI 层

`plan_only` 不落库（`review_orchestrator.py:267-277`）→ `run.id = null`。
按钮闸门 = `result.run?.id` 非空；服务端收到空 `run_id` 一律 400，**不做任何回退猜测**（§1.3-E）。

### 5.8 【低】64KB 请求上限与导出体积无关，但别搞混

`MAX_BODY_BYTES = 64 * 1024`（`web_server.py:29`）是**请求**侧限制。
- 发布请求只有两个字段，安全；
- 但**不要**设计成"前端把评论正文 POST 上来"——正文可达 24k（`report_renderer.py:195-197` 的软上限），
  加上 JSON 转义后仍可能逼近上限，而且会让"正文由谁生成"出现第二个真相源；
- 导出**响应**不受此限（`_send` 无大小限制）。

### 5.9 【低】路由顺序陷阱

`do_POST` 里 `/api/jobs/…/cancel` 分支（`:153-159`）**先于**白名单（`:161`）。
新路由 `/api/publish` 不冲突，但**不要**把新端点命名成 `/api/jobs/...` 之外再搞前缀匹配；
`do_GET` 侧 `/api/` 兜底 404 在 `:132-134`，导出路由必须加在它**之前**。

### 5.10 【低】前端剪贴板的上下文限制

§3.3。默认 `127.0.0.1` 安全，`--host 0.0.0.0` 不是；必须有降级路径，且不得静默报成功。

### 5.11 【低】`PublishService` 依赖 `PRFetcher` 的私有方法

`_post_comment` 调 `fetcher._get_pull_request(...)`（`:409`）——私有 API，PyGithub 升级可能咬人；
且 `PRFetcher.__init__` 在无 token 时**抛异常**（`pr_fetcher.py:63-66`），会被 `except Exception` 吞成 `publish_failed`。
**所以 `load_target` 里那个 token 检查（`:324-325`）必须留在 `_post_comment` 之前**——别为了"简化"重排。

---

## 6. 优先级建议

### 6.1 对 7 条缺口的排序

| 排位 | 缺口 | 工作量 | 我的理由 |
|---|---|---|---|
| **1** | ① 发布评论到 GitHub | **L**（后端 S + 安全 M + 前端 M；见 §2.7） | 唯一还缺的"对外写"能力；且 `PublishService` 已完整，主要成本在安全与 UI 五态 |
| **2** | ② 报告导出/复制 | **M** | 与 ① 共用 `ReportActions` 组件与 `PRData` builder，**必须与 ① 同轮做**，否则 builder 会被写两遍 |
| **3** | ④ 接口文档 7→17（`ApiPage` + `docs/API.md` + `README.md`） | **S** | 现在 `README.md:416` 写着"全部接口"是**可直接证伪的假话**；S 号成本买"界面不骗人" |
| 4 | ③ 设置页补齐 preferences | **M** | 与闭环无关但价值真实：`web_config.py:21-33` 完全没碰 `preferences`。注意 `auto_publish_comment` 在 Web 语义下**不该有**（Web 是交互式的，自动发评论很危险），要**有选择地**补 |
| 5 | ⑤ i18n | **L** | CLI 已双语，Web 全中文（`web/src` 里只有 `format.ts:23` 一个 `zh-CN`）。改动面涉及所有页面文案 + `ui_language` 的读取，收益是"对齐"而非"闭环" |
| 6 | ⑥ 对话/会话 | **XL** | Web 里**零** chat 代码（全仓 grep 无命中）。后端 `chat_runtime`/`jsonl_server` 齐全，但这是**新页面 + 流式契约 + 会话状态**，是下一阶段独立立项的量级 |
| ~~7~~ | ~~⑦ CI 构建前端~~ | **已完成** | 见 §1.2-A，`.github/workflows/ci.yml:46-83`。**建议从待办里删掉** |

### 6.2 如果只做 3 件 → ①②④

- **①+② 必须成对**：它们共享 `ReportActions` 组件与 `build_stored_run_pr_data`；拆开做等于把同一份重构做两遍，
  而且这两条合起来才构成"**端到端闭环**"的定义（能把结果送出去 / 能把结果带走）。
- **④ 作为第三件**：S 号成本，且它修的是"**文档在说假话**"——`README.md:416` 的"全部 HTTP 接口"、
  `:408` 与 `docs/API.md:108` 的"五个视图"（实际 6 个）、`ApiPage.tsx:59-68` 只列 8/15 条 CLI 命令。
  这三处是**用户可直接对照界面证伪**的表述，属于必须付的债。
- **不选 ③ 的理由**（不是它不重要）：③ 是 M 号成本但**不在闭环路径上**——需要 token 的用户，
  Web 设置页**已经有** GitHub Token 输入框（`web/src/pages/SettingsPage.tsx:330-340`），
  所以 ① 不会因为 ③ 没做而卡住。如果你更看重"配置能力对齐"而不是闭环，**把 ③ 提上来、把 ④ 推后**也成立，
  代价是 S→M，且闭环不受影响。

---

## 7. 验收方式（可执行命令 + 断言）

### 7.1 基线（我**已实跑**，作为改动前的对照）

```bash
cd C:/Users/21986/Desktop/ican/AI-PR-Review-Assistant
export TEMP=C:/Users/21986/Desktop/ican/AI-PR-Review-Assistant/.pytest_claude
export TMP=$TEMP
python -m pytest tests/test_web_server.py -q     # 实测 45 passed in 25.77s
python -m pytest -q                              # 实测 1365 passed, 1 skipped, 1 warning in 98.01s
cd web && npx tsc --noEmit                       # CI 同款（ci.yml:66-67），应无输出
```

### 7.2 新增用例

```bash
python -m pytest tests/test_web_server.py -q -k "Publish or Export"
# 断言：全绿；且总数 = 45 + 新增（发布 17 + 导出 10，允许 ±2 的实现微调）
```

### 7.3 端到端（离线，**不发真实评论**）

```bash
# 1) 起服务（换端口，避免撞上开发中的 8787）
python -c "from ai_pr_review.web_server import serve; from ai_pr_review.config import AppConfig; serve(AppConfig.load(), host='127.0.0.1', port=8799)"

# 2) 预览：绝不发帖
curl -s -X POST -H 'Content-Type: application/json' \
     -d '{"run_id":"<真实 run_id>"}' http://127.0.0.1:8799/api/publish | python -m json.tool
# 断言：status=preview；requires_confirmation=true；comment_chars==len(comment_body)；comment_url==""

# 3) 跨站守卫
curl -s -o /dev/null -w '%{http_code}\n' -X POST -H 'Content-Type: text/plain' \
     -H 'Origin: https://evil.example' -d '{"run_id":"x","confirm":true}' \
     http://127.0.0.1:8799/api/publish
# 断言：415（不是 404，也不是 200）

# 4) 导出与 CLI 逐字节一致（改成同一 builder 之后）
pr-review export-run <run_id> --format markdown --output .pytest_claude/cli.md
curl -s 'http://127.0.0.1:8799/api/report/export?run_id=<run_id>&format=markdown' \
  | python -c "import json,sys; open('.pytest_claude/web.md','w',encoding='utf-8').write(json.load(sys.stdin)['text'])"
python -c "print(open('.pytest_claude/cli.md',encoding='utf-8').read()==open('.pytest_claude/web.md',encoding='utf-8').read())"
# 断言：True
# 注意：若本轮**没有**同步改 cli.py 的 PRData 重建，则此处应为 False，
#       且差异必须恰好是「标题行/作者行」——那就改断言为 comparing 去掉这两行后的结果，
#       并把该差异记入 CHANGELOG（§5.5）。

# 5) 401/403 路径（可选，需 token）
#    在一台配了 token 的机器上，用**测试仓库的草稿 PR** 跑一次 confirm，
#    断言：status=published + comment_url 非空 + 打开该 URL 能看到正文；
#    再点一次，断言 already_published=true 且确实多了一条评论（契约要求"照发+警告"）。
```

### 7.4 前端

```bash
cd web
npx tsc --noEmit                    # 必须无输出
node tools/audit-pages.mjs          # 6 页可见性审计（BASE 默认 8787），problems 应为空
node tools/verify-report-actions.mjs   # 新增脚本；断言计划模式无按钮、完整审查后按钮可点
```

### 7.5 回归红线（改动不得触碰）

```bash
python -m pytest tests/test_jsonl_backend.py -q -k publish   # §12.2 的 TUI 路径必须原样绿
python -m pytest tests/test_cli.py -q -k publish_comment     # CLI --publish-comment 路径
python -m pytest tests/test_report_renderer.py -q            # 评论格式 34 项冻结
```
断言：**三条全绿且不修改任何既有断言**。特别是 `tests/test_jsonl_backend.py:2558`
（同一 run 两次渲染正文逐字节相同）与 `:2522`（第二次 `already_published is True`）。

---

## 8. 未确认项（诚实清单）

1. **PyGithub `IssueComment.html_url` 是否存在**：未实测（不联网、无 token）。有 `getattr` 兜底，最坏退化成空串。
2. **GitHub 403/404/429 被 PyGithub 包成哪种异常**：未实测；因此 UI 不做细分类，统一 `publish_failed` + 上游原文。
3. **线上真实评论的发布链路未跑**：本文档全部发布结论来自源码 + 离线打桩路径，未向任何 PR 发过评论。
4. **`web/.shots/` 的 31 张截图我只看了文件名清单**（覆盖 overview/review/history/benchmark/api/settings 与 report 变体），
   未逐张查看内容。
5. **`web/tools/*.mjs` 我读了 `audit-pages.mjs` 与 `_run_pr_web.ps1`，其余 8 个未逐个读完**，
   所以"9 个 Playwright 脚本"这个计数我只核了文件数（9 个 `.mjs`），未核每个脚本的用途是否都是 Playwright。
6. **`plan` 模式下 `run.id` 是 `null`** 这一点我是从代码推的（`ReviewArtifacts.run_id=None` 默认值
   `review_orchestrator.py:219` + `web_server.py:199-203` 直接取用），**没有实际发一次 `/api/plan` 看响应**。
