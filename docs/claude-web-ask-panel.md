# Web 追问面板（Phase 3）· 实现记录

**任务**：`p3-ask-panel`（前端）。后端 `POST /api/chat` 由主控接线 + opencode 提供服务层，
接口契约在任务书里已冻结；本文件只记录我改的**前端**、实测数字与未决项。
**状态**：已完成（前端侧）。`npm run typecheck` exit 0；Playwright 断言 **44/44**（exit 0）。

---

## 1. 改动点（file:line）

| 文件 | 位置 | 改动 |
|---|---|---|
| `web/src/api/types.ts` | `:325-353` | 新增 `ChatContextMeta`、`ChatResponse`（与冻结契约逐字段对齐） |
| `web/src/api/client.ts` | `:3`、`:152-156` | 新增 `api.chat(runId, text)` → `POST /api/chat`；失败形状交给既有的 `ApiError.status` |
| `web/src/components/AskPanel.tsx` | 新建（266 行） | 追问面板：四态 + 多轮会话 + 错误映射 + 键盘交互 |
| `web/src/pages/ReviewPage.tsx` | `:6`、`:650-655` | DELIVER 之后新增 `FOLLOW-UP` Section，挂 `<AskPanel runId={resultRunId ?? undefined} />` |
| `web/src/pages/HistoryPage.tsx` | `:4`、`:213` | 打开报告后，紧跟 `ReportActions` 挂同一个组件（`runId={report.run_id}`） |
| `web/src/styles/components.css` | `:1176-1212` | `.ask-panel*` 样式，全部走 design tokens（警告/危险复用 `.notice-warn/.notice-error`） |
| `.pytest_claude/claude/verify-ask-panel.mjs` | 证据脚本 | Playwright 44 条断言，离线打桩（**不在** `web/` 里，避免动 `web/tools/`） |
| `.pytest_claude/claude/ask-panel.png` | 截图 | 截断警告条 + 转义后的 HTML 回答（场景 4） |

**未改**：`src/ai_pr_review/**`、`web/package.json`（**未新增任何依赖**）、`web/tools/*`。
未运行 `npm run build`（任务书禁止，主控统一重建）；`web_static/` 保持原样 —— 见 §6 未决项。

---

## 2. 组件契约

```tsx
<AskPanel runId?: string language?: string className?: string />
```

| prop | 语义 |
|---|---|
| `runId` | 要追问的那次审查。缺省/undefined → 面板进入**未绑定**态，服务端按普通对话处理 |
| `language` | 预留：当前只落到 `.ask-panel-head` 的 `lang` 属性，**不做文案切换**（界面文案统一由 i18n 任务处理）。它**不会**进请求体 —— 契约里 body 只有 `run_id`/`text` |
| `className` | 追加到 `Card` 上（与 `ReportActions` 一致） |

**请求**（`client.ts:152`）：

```
POST /api/chat
带 runId:  {"run_id": "<id>", "text": "<问题>"}   // 恰好两个键
无 runId:  {"text": "<问题>"}                      // 连 run_id 键都不出现
```

两个分支都被证据脚本用 `Object.keys(body)` 逐字断言过（场景 1/2）。

**响应**：只读 `reply` / `model` / `context_meta`；`usage` 拿到但当前不展示
（避免在没有成本口径的情况下编数字），类型里保留。

**不持久化**：对话只存在组件 state 里，不写库、不写 localStorage；离开页面（组件卸载）
或刷新即清空。这一点写进了面板的副标题文案，**没有**对用户谎称"会记住"。

---

## 3. 状态机

`AskPanel.tsx:16` —— 四态只描述**最后一次请求**，历史由 `turns: Turn[]` 承载。

| 态 | 触发 | 界面 |
|---|---|---|
| `idle` | 初始 / 换 `runId` | 空态提示 + 可用输入框 |
| `asking` | 提交（Enter 或点「追问」） | 输入框**disabled**、按钮 disabled、`role="status"` + Spinner「正在追问…」；输入框立即清空 |
| `answered` | 200 | 追加一轮问答；输入框重新可用并**拿回焦点** |
| `failed` | 非 2xx / 连不上 | 追加一轮"失败轮"（问题保留 + 错误块 + 「重试」），输入框重新可用 |

多轮：每轮是 `.ask-panel-turn`（问题气泡 → [警告条] → `<pre>` 回答 → 元信息行），
新一轮只追加、不改写旧轮（证据脚本断言第 1 轮回答在 2 轮后仍是原文）。

`runId` 变化时整体复位（`AskPanel.tsx:90-95`）：上一条审查的问答挂在新报告下面会误导人；
同时 `token_estimate` 只在"服务端确认绑定的就是当前这块面板的 run"时才显示
（`AskPanel.tsx:110-112`），避免旧数字挂到新上下文上。

### 3.1 错误映射（`AskPanel.tsx:38-63`，`ApiError.status` → 文案）

| HTTP | 服务端 code | 前端标题 | 备注 |
|---|---|---|---|
| 0 | （连不上本地服务） | 无法连接到本地服务 | 提示 `pr-review serve` 是否还在跑 |
| 400 | `invalid_request` | 问题内容不合法 | 请求缺 `text`；界面本身不会发出空问题（按钮禁用） |
| 404 | `not_found` | **该审查记录已不存在** | 建议换一条历史记录或重跑审查 |
| 415 | （跨站守卫，无 code） | 请求被本地服务拒绝 | 正常路径遇不到，保留以防后端细分 |
| 502 | `chat_failed` | 模型调用失败 | **原文展示**服务端 message（`原始信息：…`） |
| 503 | `missing_api_key` | 未配置模型 API Key | 引导去「设置」页配 Key / 切本地模型，并给 `#/settings` 入口按钮 |
| 其它 | — | 追问失败（HTTP n） | 通用文案 + 原始 message |

每条文案都**追加服务端原始串**（`describeChatFailure`，导出以便复用/测试），
所以映射不准时用户仍能看到真相。

### 3.2 其它交互

- **键盘**：`Enter` 提交（走 `<form onSubmit>`，另在 `onKeyDown` 显式拦截）；
  单行输入，`Shift+Enter` 不适用。**输入法保护**：`isComposing || keyCode === 229` 时
  `preventDefault()`（`AskPanel.tsx:188-192`）—— 中文/日文输入法用 Enter 上屏候选词，
  不拦住会把半成品问题发出去。
- **焦点**：`asking` 期间输入框是 `disabled`，浏览器会**忽略** `focus()`；所以还焦点放在
  `phase` 落地的 `useEffect` 里（`AskPanel.tsx:100-104`），而不是请求回调里。这个 bug 是
  证据脚本先测出来的（同步 focus 后 `document.activeElement` 不是输入框），已修。
  只在**真的提交过**时才抢焦点（`refocusRef`），避免页面加载时把视口拽到面板上。
- **渲染**：回答用 `<pre className="ask-panel-answer">` + `white-space:pre-wrap`，
  等宽、保留换行、**不引入 Markdown 依赖**。React 默认转义，模型输出里的 HTML 是纯文本 ——
  证据脚本用 `'<img src=x onerror=...>'` 作为回答，断言页面里没有 `img` 元素、`onerror` 没执行。
- **截断警告**：`context_meta.truncated === true` 时，在回答**上方**插入 `<Notice kind="warn">`
  （note 为空时有兜底文案）。DOM 顺序与几何位置都在证据脚本里断言过。
- **只读提示**：绑定态显示 `只读上下文 · 审查记录 <run 前 8 位>`（首答后再加 `约 N tokens 上下文`）；
  未绑定态显示 `未绑定审查记录，将按普通对话回答`，用 warning 语义色，输入框照常可用。

### 3.3 一处刻意的实现选择（与任务书文字的偏差）

任务书写"`ReviewPage.tsx`（有 `result.run.id` 时）"挂载。我改成**只要有结果就渲染**，
无 run 时传 `undefined`。原因：计划模式（`plan_only` 不落库）的 `run.id` 恒为 `null`，
若按字面只在有 run 时才挂，**"未绑定 → 普通对话"这条分支在真实界面里根本走不到**，
验证第 1 条就只能靠伪造 DOM。现在它是一条真路径（计划模式出结果即可复现），
与 `ReportActions` 在无 run 时渲染"禁用态 + 说明"的处理也一致。
历史页无此问题：`report.run_id` 必然存在。

---

## 4. 验证（真跑，数字为实测）

### 4.1 编译

```bash
cd web && npm run typecheck        # tsc --noEmit，exit 0（无任何诊断输出）
```

### 4.2 前端行为（Playwright，离线打桩，不发任何真实请求）

```bash
cd web && npx vite --port 5211 --strictPort     # 只起 dev server；未执行 npm run build
node .pytest_claude/claude/verify-ask-panel.mjs
# 通过 44 项，失败 0 项（exit 0）；5 个场景，日志 .pytest_claude/claude/ask-panel-verify.log
```

任务书要求的 4 条自证，对应断言：

1. **无 runId → 普通对话提示且可提交**：计划模式结果渲染面板、`data-bound="false"`、
   文案命中"未绑定审查记录，将按普通对话回答"、输入框可用、body **无** `run_id` 键。
2. **body 恰好是 `{run_id, text}`**：`Object.keys(body).sort().join(',') === 'run_id,text'`，
   且 `run_id`/`text` 取值逐一比对（第二轮也查）。
3. **错误映射**：503 → "未配置模型 API Key" + 含"设置"/"本地模型" + `a[href="#/settings"]`；
   502 → 页面出现后端原文 `upstream exploded: 429 rate limited`；404 → "该审查记录已不存在"。
4. **truncated 警告条 + 多轮历史**：`truncated=true` 时出现 `.notice-warn` 且文案为 note 原文，
   DOM 顺序与动画结束后的几何位置都在回答上方；两轮追问后 `.ask-panel-turn` = 2，
   第 1 轮回答仍是原文、第 2 轮是新内容。

另附断言：asking 期间输入/按钮禁用 + Spinner + `role="status"`、提交即清空、答完焦点回到输入框、
回答 `white-space: pre-wrap`、HTML 不解析、历史页挂载点可用且收起报告后面板卸载。

> 脚本用 `page.route(谓词)` 而不是 glob `**/api/**`：后者会把 vite 的模块请求
> `/static/src/api/client.ts` 一起拦掉，页面根本加载不出来。BASE 用 `localhost` 而不是
> `127.0.0.1`（本机 vite 只绑 localhost/::1）。
> 脚本位置：任务书的 write_scope 不含 `web/`（除源码），所以证据脚本放在 `.pytest_claude/claude/`。

---

## 5. 未跑的东西（诚实清单）

- **没跑 `npm run build`**（任务书禁止）；因此**没有**任何真实构建产物验证，`web_static/` 未更新。
- **没有对真实后端跑过 `/api/chat`**：契约是任务书给的冻结版，全部行为断言都在打桩下完成，
  前端与真实后端的对齐**未验证**。本轮末尾看到主控已把 HTTP 路由接进
  `web_server.py`（`_CHAT_STATUS_CODES` = 400/404/502/503，`_handle_chat` 延迟导入
  `ai_pr_review.web_chat`），但 `web_chat.py` 此刻**尚未落盘** —— 也就是说现在直接打
  `/api/chat` 会走 `except Exception` 返回 500，真实链路仍不可验。
  好消息：`run_id = str(payload.get("run_id","") or "").strip()` 与前端"无 run 时省掉
  `run_id` 键"的写法一致（缺键 → 空串 → 按普通对话处理）。
- 没有跑 Python 侧测试（改动纯前端，未碰 `src/**`）。

---

## 6. 未决项 / 交给主控

1. **`web_static/` 需要统一重建**：CI 有 "Verify build output is committed"（`.github/workflows/ci.yml:72-82`），
   要求 `src/ai_pr_review/web_static` 与 `web/` 源码同步。本轮按任务书没跑 `npm run build`，
   所以合并前必须由主控重建并提交产物，否则 CI 会红。
2. **契约联调**：`web_chat.py`（opencode 的服务层）落盘后，建议用真实后端复跑一次 §4.2 脚本
   （把 `page.route` 打桩换成真代理），重点看 502/503 的实际 code 与 `context_meta`
   的字段名/类型是否与冻结契约一致 —— 我的 `ChatContextMeta` 是按任务书写的，还没被真实响应验过。
   若服务层返回的字段名有出入，改 `web/src/api/types.ts:334-353` 一处即可，组件读的是
   `context_meta.token_estimate / truncated / note / bound_run / sections`。
3. **`language` 语义**：目前只写 `lang` 属性。若 i18n 任务要给追问面板做双语，需要在这里接入词表
   （或由外层传入已翻译的文案），当前实现没有预留文案键。
4. **`usage` 未展示**：`ChatResponse.usage` 已进类型但界面不显示，等成本口径确定后再决定要不要展示。
