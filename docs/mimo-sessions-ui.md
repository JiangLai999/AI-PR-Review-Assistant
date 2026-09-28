# mimo-sessions-ui · 会话切换弹窗 + 状态栏会话名 + 压缩压力提示

任务：`mimo-sessions-ui`（TUI 线）· 方案源：`docs/session-and-compaction-plan.md` ·
契约 v1 与后端（`jsonl_server.py`）/验收/手册三线共用。

## 1. 键位决策（Alt+S）

| 键位 | 作用 | 理由 |
|---|---|---|
| `Alt+S` | 打开会话列表（= `/sessions`） | 与现有 `Alt+L` 代码块 / `Alt+T` 思考 / `Alt+W` 工作台同一体系：单手 Alt+字母、语义首字母（**S**essions）。方案 §D.1 的 `Ctrl+X→L` 两段式手感与我们现有单键 Alt 组不一致，故选 `Alt+S`。 |
| `/sessions` | 同效（前端拦截，不发 `chat.send`） | 斜杠命令发现路径（command-menu）与键盘路径双入口；旧后端仍可打开弹窗看空态。 |
| `r` / `d` / `Enter` / `↑↓` / `Esc` | 重命名 / 删除 / 切换 / 选择 / 关闭 | 弹窗内按键，契约固定；页脚中英双语常显。 |

## 2. 弹窗状态机

```
            /sessions 或 Alt+S
                    │
                    ▼
              ┌──────────┐   Esc    ┌────────┐
              │  list    │─────────▶│ closed │
              └──────────┘          └────────┘
               │  │  │  │
      Enter    │  │  │  │ r
   (switch)    │  │  │  └──────────────▶ ┌────────┐
               │  │  │                   │ rename │──Enter→ rename RPC → list
               │  │  │   Esc ◀───────────└────────┘
               │  │  │
               │  │  └── d ──────────────▶ ┌───────────────┐
               │  │                       │ confirm-delete │
               │  │                       └───────────────┘
               │  │                        Enter/y → delete RPC → list
               │  │                        Esc/n   → list
               │  │
               ▼  ▼
        switch RPC 成功后：重建消息区 + 提示「已切换到《标题》」+ 关闭弹窗
```

- **list**：`↑↓` 选择、`Enter` 切换、`r` 重命名、`d` 删除、`Esc` 关闭。
- **rename**：内联 `<input>` 预填当前标题；`Enter` 调 `session.rename`，`Esc` 取消。
- **confirm-delete**：`Enter`/`y` 调 `session.delete`，`Esc`/`n` 取消；若删的是当前会话，
  自动跟随返回的 `next`（契约 v1 `session.delete`）。
- 列表项格式：`▸ <标题> · <相对时间> · <N 条>`；当前会话用 `●` + 高亮色。

## 3. 降级策略（与后端并行）

| 场景 | 行为 |
|---|---|
| `session.list` 方法不存在 / 请求失败 | 弹窗空态「当前后端不支持会话列表」，不崩溃；`Esc` 可关。 |
| 列表项缺 `title` / `updated_at` / `message_count` | 该段省略或给占位（`未命名会话` / `时间未知`），不编造数字。 |
| `session.switch` 返回缺 `messages` | 只清空/不重建消息区，仍提示切换成功（以 `session` 块为准）。 |
| `/new` 且后端无 `session.create` | 回退现有清空行为（`resetSessionUi`），不报错打断。 |
| `context.pressure` 缺失 / `null` / 未知字符串 | 维持现状（muted），不提示不改色。 |
| 状态栏：`runtime.session_title` 优先，否则 `session.list` 的 current 标题 | 两者都缺 → 会话名段整段隐藏。 |
| 窄终端 <100 列 | 状态栏会话名段隐藏（保住路由/在线状态段）。 |

## 4. 契约 v1 字段（前端消费侧，字段名不可改）

- `session.list` → `{sessions: [{id, title, updated_at, message_count, current}], current}`
- `session.switch {session_id}` → `{session, messages}`
- `session.rename {session_id, title}` → `{id, title}`
- `session.delete {session_id}` → `{deleted, next}`
- `session.create` → 新建并切换（`/new` 语义升级）
- `assistant.finished.context` 第七键 `pressure`: `"low"|"medium"|"high"|"critical"|null`

解析器：`protocol.ts` 的 `parseSessionListResult` / `parseSessionSwitchResult` /
`parseSessionRenameResult` / `parseSessionDeleteResult` / `parseSessionCreateResult` +
`parseContext` 内的 `pressure`。全部容忍缺字段，不抛错。

## 5. 压力提示（B-P3 前端 · 只提示不自动压缩）

| pressure | 上下文段颜色 | 尾部提示 |
|---|---|---|
| `low` / `null` / 缺失 | muted `#808080`（现状） | 无 |
| `medium` | 黄 `#f3c742` | 无 |
| `high` | 黄 `#f3c742` | 「上下文接近上限：可用 /compact 压缩」 |
| `critical` | 红 `#ff6b6b` | 同上 |

颜色复用现有色系（muted / 黄 / 红），不引入新色。中英双语。

## 6. 帧路径（TEMP=`.pytest_mimo`）

`frontend/tui/scripts/manual-chat-markdown-check.tsx` 追加 §N：

| 帧文件 | 断言内容 |
|---|---|
| `frame-sessions-120x30.txt` | 会话弹窗：`●`/`▸`、相对时间、条数、页脚键位、超长标题截断 |
| `frame-sessions-209x51.txt` | 宽档同上 + 无行宽溢出 |
| `frame-sessions-rename.txt` | 重命名态：输入框预填 + Enter/Esc 提示 |
| `frame-sessions-empty.txt` | 空态「当前后端不支持会话列表」+ Esc 关闭 |
| `frame-sessions-loading.txt` | 首次打开：`正在读取会话列表…`（**不再**冒充"后端不支持"） |
| `frame-sessions-no-sessions.txt` | 支持但暂无会话：`暂无会话：发送一条消息即可创建` |
| `frame-sessions-late-arrival.txt` | **回归**：列表晚于弹窗创建到达 → 列表项必须渲染出来 |
| `frame-sessions-refresh-failed.txt` | 刷新失败：`会话列表读取失败：<原因>`（不冒充"后端不支持"） |
| `frame-status-session-120.txt` | 状态栏会话名段（≥100 列） |
| `frame-status-session-80.txt` | <100 列隐藏会话名段 |
| `frame-pressure-high.txt` | pressure=high 黄段 + 「可用 /compact」提示 |
| `frame-pressure-low.txt` | pressure=low 无提示 |

## 7. 验证数字（TEMP/TMP = `C:\Users\21986\Desktop\ican\AI-PR-Review-Assistant\.pytest_mimo`）

| 命令 | 结果 |
|---|---|
| `cd frontend/tui && bun run typecheck` | **exit 0** |
| `cd frontend/tui && bun test src` | **222 pass / 0 fail**（222 tests · 13 files） |
| `bun --preload @opentui/solid/preload scripts/manual-chat-markdown-check.tsx` | **ALL PASS**（新增 §N2 首次 `/sessions` 回归 10 条断言） |
| `bun --preload @opentui/solid/preload scripts/manual-route-wizard-check.tsx` | **145 PASS / 0 FAIL（ALL PASS）** |

### 未决项（blocker）

- `frontend/tui/src/backend.test.ts` 的 `unexpected backend exit invalidates old in-memory sessions`
  失败（1 fail）：断言「后端重启后旧 session_id 应 `not_found`」，但并行后端已把会话
  持久化到 `sessions/` 目录（`jsonl_server.py` 的 `session.get` 从磁盘恢复），重启后
  仍能命中。该文件**不在 write_scope** 内，本任务未改动；需后端/验收线确认语义后
  由其更新断言（或改为断言「重启后会话可恢复」）。

## 8. 修复记录 · 第一次 `/sessions` 看不到列表（2026-09-27 用户实测）

### 现象

打开 chat 后**第一次** `/sessions`，弹窗只有「共 0 个会话 / 当前后端不支持会话列表」；
`Esc` 关掉再敲一次（第二次）才列出会话。用户原话：
「chat 使用 `/sessions` 后第一次打开还是当前后端不支持展示会话列表，我第二次使用
`/sessions` 后才显示会话列表。」

### 定位过程（证据优先）

1. **请求级探针**（新建临时脚本，复用真实 `BackendClient` + 真实 `%APPDATA%` 配置，
   按 `onMount → ensureSession → /sessions` 的顺序发请求）：第一次 `session.list`
   就 `ok=true / 2ms`，内容正确 → **排除后端、协议、超时、并发竞态**。
2. **真实 TUI 复现**（PTY 里跑 `pr-review chat`，直接敲 `/sessions`）：第一帧只有空态，
   列表项不出现；同一帧里副标题的会话数却从 `0` 变成 `2`。
   在 `BackendClient` 里挂临时请求日志（`request/settled/rejectPending/stdout closed`）
   再跑一次：整轮只有 **1 个** `session.list` 请求，且 `settled … ok=true`——
   说明**数据到了、界面没渲染**。
3. **代码级**：`SessionsDialog` 里
   ```tsx
   const empty = !props.supported || props.sessions.length === 0   // ← 一次性快照
   ```
   Solid 的 `props` 是响应式 getter，但这行只在**组件创建那一刻**求值一次；弹窗打开时
   `sessions` 还是 `[]`，于是 `empty` 永久为 `true`，列表的 `<Show when={!empty}>`
   永远不挂载 → 关掉再开（新组件实例）才会用新的快照值 `false`。

### 根因

**派生状态写成了常量而不是取值函数**（同一文件里 `selected` / `label` 都是
`() => …`，只有 `empty` 漏了）。它同时解释了上一轮用户报的「共 6 个会话 +
当前后端不支持会话列表」自相矛盾：副标题 `props.sessions.length` 是响应式的，
列表与空态却卡在首帧快照上。

### 修复

| 项 | 改动 |
|---|---|
| 反应性（根因） | `const empty = () => …`；列表/空态两处 `Show` 改用 `empty()` |
| 文案分家 | 新增 `formatSessionListNoSessions`（支持但暂无会话）与 `formatSessionListLoading`（读取中）——「不支持」只在**确实没有失败原因**时出现 |
| 失败可见 | 新增 `formatSessionListError`：刷新失败时把后端原因（超时/报错）显示出来，不再冒充"后端不支持"（`supported=false` 同时覆盖两种语义） |
| 读取中态 | `App` 新增 `sessionListLoading`（带 request token 守卫），首次打开显示「正在读取会话列表…」 |
| 选中项钳位 | `activeIndex()`：列表晚到/删除变短时不会取到 `undefined`（高亮、Enter 仍正确） |

### 回归验证

- 新断言（`manual-chat-markdown-check.tsx` §N2）：
  `首帧：读取中文案可见`、`首帧：不再把「读取中」说成「后端不支持」`、
  `空列表：提示「暂无会话」`、**`迟到列表：列表项渲染（首次打开也能看到会话）`**、
  `迟到列表：空态文案已撤下`、`刷新失败：显示失败原因` 等 10 条。
- **反证**：把 `empty` 临时改回快照写法 → `迟到列表：列表项渲染` 与
  `迟到列表：空态文案已撤下` **双双 FAIL**（`FAILURES: 2`）；改回取值函数 → `ALL PASS`。
- 真机验收（PTY）：第一帧 `共 0 个会话 / 正在读取会话列表…`，数据到达后同一弹窗
  直接渲染 `● 新会话 · 13:40 · 11 分钟前 · 0 条` / `▸ 你好 · 39 分钟前 · 4 条`，
  `↓` 键高亮可移动——**首次打开即可用**。
