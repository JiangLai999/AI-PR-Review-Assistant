# 多会话与压缩操作指南 / Multi-session & Compaction Guide

> 教程向：按场景给分步操作（命令 + 预期界面反馈）。**中英双语**：每节先中文，后英文。
> Tutorial-style: step-by-step operations per scenario (command + expected UI feedback).
> Each section is written in Chinese first, then English.
>
> 本文按**契约 v1** 描述对外行为；契约未规定的细节一律标注"见实现文档"，
> 不做额外承诺。速查表见 `docs/chat-features.md`，方案与取舍见
> `docs/session-and-compaction-plan.md`。
>
> This guide describes the **contract v1** behaviour. Anything the contract does not fix is marked
> "see the implementation doc". For a quick reference see `docs/chat-features.md`; for design
> rationale see `docs/session-and-compaction-plan.md`.

---

## 场景 1：同时跟进两个 PR，如何来回切换对话 / Scenario 1: juggling two PRs

### 中文

**预期结果**：两个 PR 的对话与各自的审查上下文绑定互不干扰，随时用 `/sessions` 来回切。

| # | 操作 Action | 预期界面反馈 Expected UI feedback |
|---|---|---|
| 1 | 启动 `pr-review chat` | 进入 TUI，状态栏显示当前会话标题 |
| 2 | 在第一个 PR 的对话里 `/review <PR URL>`，随后正常提问 | 审查完成后该 Run 绑定为当前上下文（`/context` 可查看） |
| 3 | 输入 `/new` | **新建会话并切换**：旧会话保留，界面进入一个空白对话；标题默认取首条用户消息前 40 字 |
| 4 | 在新会话里 `/review <另一个 PR URL>` 并提问 | 第二个 PR 的对话与绑定独立进行，不影响第一个 |
| 5 | 想回第一个 PR：输入 `/sessions`（或按 `Alt+S`） | 弹出会话列表，每行形如 `▸ 标题 · 3 分钟前 · 12 条` |
| 6 | `↑↓` 选中目标会话，按 `Enter` | 切换到该会话：消息与 `/context` 的绑定随会话一起恢复 |
| 7 | （可选）`r` 重命名 / `d` 删除 / `Esc` 关闭 | `r` 改标题；`d` 删除该会话（当前会话的删除细则见实现文档）；`Esc` 关闭列表回到对话 |

### English

**Expected outcome**: the two PR conversations and their review-context bindings stay independent;
switch back and forth with `/sessions`.

| # | Action | Expected UI feedback |
|---|---|---|
| 1 | Start `pr-review chat` | The TUI opens; the status line shows the current session title |
| 2 | `/review <PR URL>` in the first conversation, then chat as usual | On success the run is bound as the current context (check with `/context`) |
| 3 | Type `/new` | **Creates a new session and switches to it**: the old session is kept and you land in an empty conversation; the title defaults to the first 40 characters of your first user message |
| 4 | `/review <other PR URL>` in the new session | The second PR's conversation and binding stay independent of the first |
| 5 | To go back: type `/sessions` (or press `Alt+S`) | The session list opens, one row per session: `▸ 标题 · 3 分钟前 · 12 条` |
| 6 | `↑↓` to select, `Enter` to switch | The target session loads with its messages and its `/context` binding |
| 7 | (optional) `r` rename / `d` delete / `Esc` close | `r` renames, `d` deletes the session (deleting the *current* session: see the implementation doc), `Esc` closes the list |

---

## 场景 2：长会话快满了怎么办 / Scenario 2: a long session is running out of context

### 中文

**预期结果**：先看到压力提示，再用 `/compact` 按 token 预算压缩；历史不会因失败而丢失。

| # | 操作 Action | 预期界面反馈 Expected UI feedback |
|---|---|---|
| 1 | 看状态栏的上下文行 `上下文 12% · 2.4k/20k` | 上下文占比分四级 `pressure`：`low` / `medium` / `high` / `critical` |
| 2 | 占比升到 `high` 及以上 | 状态栏出现提示「**上下文接近上限：可用 /compact 压缩**」；状态栏同时显示当前会话标题（窄终端隐藏） |
| 3 | 输入 `/compact`（可带指令，如 `/compact 保留未完成的修复项`） | 调用当前 chat 模型生成摘要：更早的消息被一段摘要替换，摘要作为 `（历史摘要）…` 插在最前面 |
| 4 | 检查压缩结果 | 摘要是 `<conversation-summary>` XML，带 `trigger`（`manual` / `auto`）、`replaced_messages`、`kept_turns` 属性，并含 `## 已压缩对话涉及的文件` 清单 |
| 5 | 确认保留口径 | 按 token 预算保留**最近若干轮**：默认尾部预算 `compaction_tail_tokens` = 40000 token，且不超过模型窗口的 25%；**整轮保留**（一问一答不拆开），至少保留 1 轮 |
| 6a | 压缩失败（模型不可用等） | **原历史完整保留**，修复后重试即可 |
| 6b | 想改为自动压缩 | 在配置中打开 `compaction_auto`（默认 `false`）。相关配置：`compaction_tail_tokens`（默认 40000）、`compaction_trigger_ratio`（默认 0.9）、`compaction_auto`（默认 false）；配置入口见实现文档 |

### English

**Expected outcome**: you see a pressure hint first, then `/compact` trims by a token budget;
a failed compaction never loses history.

| # | Action | Expected UI feedback |
|---|---|---|
| 1 | Look at the status line `上下文 12% · 2.4k/20k` | Context usage is graded by `pressure`: `low` / `medium` / `high` / `critical` |
| 2 | Usage reaches `high` or above | The status line shows 「**上下文接近上限：可用 /compact 压缩**」; it also shows the current session title (hidden on narrow terminals) |
| 3 | Type `/compact` (optionally with an instruction, e.g. `/compact 保留未完成的修复项`) | The chat model generates a summary: older messages are replaced by a summary inserted up front as `（历史摘要）…` |
| 4 | Inspect the result | The summary is a `<conversation-summary>` XML block with the attributes `trigger` (`manual` / `auto`), `replaced_messages`, `kept_turns`, plus a `## 已压缩对话涉及的文件` file list |
| 5 | Check the retention rule | The **newest turns within a token budget** are kept: default tail budget `compaction_tail_tokens` = 40000 tokens, capped at 25% of the model window; **whole turns** are kept (a question is never separated from its answer), at least 1 turn |
| 6a | Compaction fails (model unavailable, …) | The **original history is kept intact**; retry once the model is back |
| 6b | You want auto-compaction | Turn on `compaction_auto` in the config (default `false`). Related settings: `compaction_tail_tokens` (default 40000), `compaction_trigger_ratio` (default 0.9), `compaction_auto` (default false); see the implementation doc for the config entry point |

---

## 场景 3：压缩后如何继续追问改过的文件 / Scenario 3: asking about changed files after compaction

### 中文

**预期结果**：压缩不会让你失去"动过哪些文件"的记忆——摘要里带着文件清单。

| # | 操作 Action | 预期界面反馈 Expected UI feedback |
|---|---|---|
| 1 | `/compact` 完成压缩 | 摘要正文末尾包含 `## 已压缩对话涉及的文件` 清单（被压缩消息里出现过的路径） |
| 2 | 直接提问：`刚才我们改过哪些文件？` | 模型依据摘要中的文件清单回答，指代关系（哪个文件讨论了什么）在压缩时已被要求保留 |
| 3 | 需要回到审查原文 | 用 `/context` 查看/切换绑定，或 `/history <run_id>` 载入该 Run 的报告继续解读（绑定随会话走） |
| 4 | 想看未压缩时的完整往返 | 另开一个会话（`/new`）重跑同一 PR，两个会话互不影响 |

### English

**Expected outcome**: compaction does not erase "which files did we touch" — the summary carries a
file list.

| # | Action | Expected UI feedback |
|---|---|---|
| 1 | `/compact` finishes | The summary body ends with a `## 已压缩对话涉及的文件` list (paths that appeared in the compacted messages) |
| 2 | Ask directly: `刚才我们改过哪些文件？` | The model answers from the summary's file list; the summary prompt requires keeping file/conclusion references intact |
| 3 | You need the original review text | Use `/context` to inspect/switch the binding, or `/history <run_id>` to load that run's report (bindings follow the session) |
| 4 | You want the full un-compacted exchange | Start another session (`/new`) and rerun the same PR; the sessions do not affect each other |

---

## 数据存在哪里 / Where the data lives

### 中文

多会话数据与配置文件同目录：

```
<config 同目录>/
├── sessions/
│   ├── index.json          # 会话索引（id、标题、时间戳、消息数，以实现为准）
│   └── <id>.json           # 单个会话的完整消息与该会话的上下文绑定
└── chat_session.json       # 旧版单会话文件：首次启动自动迁移后只读保留
```

- **迁移**：升级后首次启动会把旧的 `chat_session.json` **自动迁移**为名为 `"legacy"` 的会话，
  无需手工操作；迁移完成后旧文件只读保留。
- **索引与文件**：`sessions/index.json` 是索引，`sessions/<id>.json` 存该会话的完整消息；
  字段级细节（索引修复、原子写）见 `docs/session-and-compaction-plan.md` §A2 与实现文档。
- **隔离性**：每个会话独立保存消息与审查上下文绑定（`/context` 的绑定随会话走）。
- 本文不涉及任何凭据；存储目录中不写入密钥。

### English

Multi-session data lives next to the config file:

```
<same dir as the config>/
├── sessions/
│   ├── index.json          # session index (id, title, timestamps, message count — see the implementation)
│   └── <id>.json           # one session's full messages and its context binding
└── chat_session.json       # legacy single-session file: migrated on first launch, then kept read-only
```

- **Migration**: the first launch after upgrading **automatically** migrates the old
  `chat_session.json` into a session named `"legacy"` — no manual step; the old file is then kept
  read-only.
- **Index vs files**: `sessions/index.json` is the index, `sessions/<id>.json` holds that session's
  full messages; field-level details (index repair, atomic writes) are in
  `docs/session-and-compaction-plan.md` §A2 and the implementation doc.
- **Isolation**: every session stores its messages and review-context binding independently (the
  `/context` binding follows the session).
- This guide never touches credentials; no keys are written to the storage directory.

---

## 常见问题 / FAQ

### 中文

**Q1：删除当前会话会怎样？**
契约 v1 只规定列表内 `d` 删除，未规定"当前会话被删"的细则（禁止删除，或删后自动切到最近一个会话）——**见实现文档**。删除前的确认交互也以实现为准。

**Q2：压缩会不会丢历史？**
分两种情况：

- **压缩成功**：更早的消息被摘要**替换**（这正是压缩的目的），保留策略保证**整轮保留**、
  **至少保留 1 轮**，且摘要带 `trigger` / `replaced_messages` / `kept_turns` 统计与
  `## 已压缩对话涉及的文件` 清单；
- **压缩失败**：**原历史原样保留**，不会丢消息，可修复后重试。

**Q3：自动压缩为什么默认关闭？**
契约规定 `compaction_auto` 默认 `false`——默认**只提示不静默压缩**：状态栏在 `pressure = high`
起提示「上下文接近上限：可用 /compact 压缩」，由你决定何时压缩。设计取舍（自动压缩会额外消耗
一次模型调用；本地小模型的摘要质量不稳定）见 `docs/session-and-compaction-plan.md` §B4/§B7。
想开启：在配置中设置 `compaction_auto`，同时可调 `compaction_tail_tokens`（默认 40000）与
`compaction_trigger_ratio`（默认 0.9）。

**Q4：升级后我原来的对话去哪了？**
自动迁移为名为 `"legacy"` 的会话，在 `/sessions` 列表里可见，用 `Enter` 切换回去即可。

**Q5：会话可以导出吗？**
契约 v1 **没有**约定导出能力——需要时见实现文档，本文不作承诺。

### English

**Q1: What happens if I delete the current session?**
Contract v1 only specifies `d` to delete inside the list; it does not fix what happens when the
*current* session is deleted (blocked, or auto-switch to the most recent one) — **see the
implementation doc**, including the confirmation interaction.

**Q2: Does compaction lose history?**
Two cases:

- **Success**: older messages are **replaced** by a summary (that is the point of compaction), with
  **whole turns kept**, **at least 1 turn**, plus the `trigger` / `replaced_messages` /
  `kept_turns` statistics and the `## 已压缩对话涉及的文件` file list;
- **Failure**: the **original history is kept as-is** — no messages are lost, retry later.

**Q3: Why is auto-compaction off by default?**
Contract v1 sets `compaction_auto` to `false` — the default is **hint only, never silent**: once
`pressure = high` the status line shows 「上下文接近上限：可用 /compact 压缩」 and you decide when to
compact. Rationale (an auto-compaction costs an extra model call; local small models summarise
unreliably) is in `docs/session-and-compaction-plan.md` §B4/§B7. To enable it set
`compaction_auto`, and optionally `compaction_tail_tokens` (default 40000) and
`compaction_trigger_ratio` (default 0.9).

**Q4: Where did my old conversation go after upgrading?**
It is migrated automatically into a session named `"legacy"`; find it in the `/sessions` list and
press `Enter` to switch back.

**Q5: Can I export a session?**
Contract v1 does **not** define any export capability — check the implementation doc if you need it;
this guide makes no promise.
