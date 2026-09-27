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
| `frame-status-session-120.txt` | 状态栏会话名段（≥100 列） |
| `frame-status-session-80.txt` | <100 列隐藏会话名段 |
| `frame-pressure-high.txt` | pressure=high 黄段 + 「可用 /compact」提示 |
| `frame-pressure-low.txt` | pressure=low 无提示 |

## 7. 验证数字（TEMP/TMP = `C:\Users\21986\Desktop\ican\AI-PR-Review-Assistant\.pytest_mimo`）

| 命令 | 结果 |
|---|---|
| `cd frontend/tui && bun run typecheck` | **exit 0** |
| `cd frontend/tui && bun test src` | **219 pass / 1 fail**（220 tests · 13 files） |
| `bun --preload @opentui/solid/preload scripts/manual-chat-markdown-check.tsx` | **114 PASS / 0 FAIL（ALL PASS）** |
| `bun --preload @opentui/solid/preload scripts/manual-route-wizard-check.tsx` | **145 PASS / 0 FAIL（ALL PASS）** |

### 未决项（blocker）

- `src/backend.test.ts` 的 `unexpected backend exit invalidates old in-memory sessions`
  失败（1 fail）：断言「后端重启后旧 session_id 应 `not_found`」，但并行后端已把会话
  持久化到 `sessions/` 目录（`jsonl_server.py` 的 `session.get` 从磁盘恢复），重启后
  仍能命中。该文件**不在 write_scope** 内，本任务未改动；需后端/验收线确认语义后
  由其更新断言（或改为断言「重启后会话可恢复」）。
