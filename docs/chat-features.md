# Chat 功能手册 / Chat Feature Guide

> 最后更新：2026-09-28 · 状态：对外文档
>
> 面向用户的 Chat 命令与交互说明。**中英双语**：每节先中文，后英文（表格内 `中文 / English`）。
> User-facing manual for Chat commands and interactions. Each section is written in Chinese first,
> then English; table cells carry both languages.
>
> 事实基线以代码为准：命令分发见 `src/ai_pr_review/backend/jsonl_server.py` 的
> `command.execute` 分支，CLI 本地命令见 `src/ai_pr_review/chat_commands.py`。
> 帮助文本与命令集合的一致性由 `tests/test_chat_commands.py` 锁定（`/help` ↔ 分发表）。

## 0. 两套界面 / Two surfaces

Chat 有两套入口，命令集合不同（手册里每条命令都会标注适用范围）。

Chat has two entry points with different command sets (each command below is tagged).

| 界面 Surface | 启动方式 How to run | 命令处理 Where commands run |
|---|---|---|
| **TUI**（交互式终端界面 / interactive terminal UI） | `pr-review chat` | 后端 `command.execute`（`/setup`、`/history`、`/retry`、`/workbench`、`/demo`、`/publish` 等先由前端本地截获） |
| **CLI**（本地命令 / local-only chat） | `pr-review chat --message "..."` 或逐行输入 | `chat_commands.handle_basic_chat_slash_command` + `cli.py`（`/review`）+ `chat_runtime`（`/exit`） |

TUI 的 `/help` 与 CLI 的 `/help` 是**两份不同的文本**，分别与各自实现的命令集合一一对应。

The TUI `/help` and the CLI `/help` are two different texts, each matching exactly the commands its
own surface implements.

---

## 1. 会话管理 / Session management

### 中文

会话的"开始、查看、清空、退出"。TUI 会话由后端持有（`session_id`），CLI 会话保存在本地会话文件里。

多会话（契约 v1）：

- **`/sessions`（或快捷键 `Alt+S`）**打开会话列表，每行形如 `▸ 标题 · 3 分钟前 · 12 条`；
  列表内 `↑↓` 选择、`Enter` 切换、`r` 重命名、`d` 删除、`Esc` 关闭。
- **`/new` = 新建会话并切换**（旧会话保留，不再是"清空当前会话"）。
- 标题默认取**首条用户消息前 40 字**，可重命名。
- 旧版单会话数据（`chat_session.json`）首次启动**自动迁移**为 `"legacy"` 会话，无需手工操作。
- 会话各自**独立保存消息与审查上下文绑定**：`/context` 的绑定随会话走，切换会话即切换绑定。

### English

Starting, inspecting, clearing and leaving a session. TUI sessions live on the backend
(`session_id`); the CLI session is persisted to a local session file.

Multi-session (contract v1):

- **`/sessions` (or the `Alt+S` shortcut)** opens the session list, one row per session in the form
  `▸ 标题 · 3 分钟前 · 12 条`; inside the list `↑↓` selects, `Enter` switches, `r` renames,
  `d` deletes, `Esc` closes.
- **`/new` creates a new session and switches to it** (the old session is kept — it no longer clears
  the current session).
- The title defaults to the **first 40 characters of the first user message** and can be renamed.
- Legacy single-session data (`chat_session.json`) is **migrated automatically** into a `"legacy"`
  session on first launch — no manual step.
- Sessions **store their messages and review-context binding independently**: the `/context` binding
  follows the session, so switching sessions switches the binding.

| 命令 Command | 用途 Purpose | 用法 Usage | 示例 Example | 注意 Note |
|---|---|---|---|---|
| `/help` | 显示当前界面的命令帮助 / List the commands of the current surface | `/help` | `/help` | TUI 与 CLI 文案不同，见 §0 / Different text per surface |
| `/status` | 显示运行状态：provider、模型、Base URL、语言、消息数、会话路径 / Show runtime status | `/status` | `/status` | 两套界面都支持 / Available in both surfaces |
| `/new` | 新建会话并切换 / Create a new session and switch to it | `/new` | `/new` | 旧会话保留（不再清空/删除旧会话）；CLI 落盘细节见实现文档 / The old session is kept (no more clearing); see the implementation doc for CLI persistence details |
| `/sessions` | 打开会话列表 / Open the session list | `/sessions`（或 `Alt+S` / or `Alt+S`） | `/sessions` | 列表行格式 `▸ 标题 · 3 分钟前 · 12 条`；`↑↓` 选择、`Enter` 切换、`r` 重命名、`d` 删除、`Esc` 关闭 / Row format `▸ 标题 · 3 分钟前 · 12 条`; `↑↓` select, `Enter` switch, `r` rename, `d` delete, `Esc` close |
| `/clear` | 清空当前会话历史 / Clear the current transcript | `/clear` | `/clear` | **仅 CLI**；会连同已保存的会话文件一起删除 / **CLI only**; also deletes the saved session file |
| `/restore` | 恢复上一次保存的会话记录 / Restore the last saved session | `/restore` | `/restore` | **仅 CLI**；找不到历史文件时提示"没有找到历史会话记录" / **CLI only** |
| `/usage` | 显示消息/字符统计 / Show message & character counts | `/usage` | `/usage` | **仅 CLI** / CLI only |
| `/config` | 显示当前会话配置（JSON）/ Show session config as JSON | `/config` | `/config` | **仅 CLI**；TUI 用 `Ctrl+P` 打开配置助手 / **CLI only**; TUI uses `Ctrl+P` |
| `/session` | 显示当前 chat 会话信息（JSON）/ Show session info as JSON | `/session` | `/session` | **仅 CLI** / CLI only |
| `/stats` | 显示审查统计（run 数、PR 数、findings、成本）/ Show review statistics | `/stats` | `/stats` | **仅 CLI**；TUI 用 `/history` 看列表 / **CLI only** |
| `/exit` | 退出聊天 / Quit the chat | `/exit`（也接受 `exit`/`quit`/`q`） | `/exit` | **仅 CLI**；TUI 不支持 `/exit`，用 `Ctrl+C` 连按两次退出 / **CLI only**; TUI quits with `Ctrl+C` twice |
| `/history` | 查看历史列表 / List history | 见 §2 / see §2 | `/history` | CLI 中只有一种形态：列审查历史（默认 5 条）/ In the CLI there is a single form: review runs (default 5) |

---

## 2. 上下文与压缩 / Context & compaction

### 中文

Chat 把消息发给模型前会按上下文预算裁剪（窗口 80 条消息，超出部分以提示注入）。
状态栏用 `上下文 12% · 2.4k/20k` 汇报占用；接近上限时给出 `/compact`、`/new` 提示。

`/history` 默认列**审查历史**（2026-09-27 按用户反馈调整——"history" 的直觉含义就是这个
工具的核心记录；会话级管理的主入口是 `/sessions`）：

- `/history [N]`：**审查历史**（Run 列表：Run ID / PR / 模型 / findings 数），默认 10 条，1–50 条，附统计。
- `/history --runs [N]`：与默认等价（**兼容别名**，既有习惯与脚本不受影响）。
- `/history --chat [N]`：列**当前会话**最近 N 条对话消息（省略 N 则列全部；超出 80 条窗口的条目标注"已在窗口外"）。
- `/history <run_id>`：**载入**该 Run 的报告并**绑定**为当前对话上下文——之后的提问都在解读这次审查。

`/compact` 在两套界面的行为不同：

- **TUI**：保留策略为**按 token 预算的最近若干轮**（不再是固定"最近 10 轮"）——尾部预算默认
  `compaction_tail_tokens` = **40000 token**，且**不超过模型窗口的 25%**；**整轮保留**
  （一条 user 与其后的 assistant 不会被拆到两侧），**至少保留 1 轮**。更早的消息由模型生成的摘要替换
  （摘要作为一条 `（历史摘要）…` 消息插在最前面），可用 `/compact <指令>` 指定"压缩时必须保留"的内容；
  返回 `kept_turns`、`replaced_messages`、`before_tokens`、`after_tokens`、`summary_chars`。
- **摘要结构**为 `<conversation-summary>` XML，含属性 `trigger`（`manual` / `auto`）、
  `replaced_messages`、`kept_turns`，正文含 **`## 已压缩对话涉及的文件`** 清单——压缩之后仍能追问
  "改过哪些文件"。
- **压缩失败保留原历史**（不会丢消息）。
- **自动压缩默认关闭**（`compaction_auto` 默认 `false`）：默认只有状态栏压力提示（见 §6），不静默压缩。
  可配三项：`compaction_tail_tokens`（默认 40000）、`compaction_trigger_ratio`（默认 0.9）、
  `compaction_auto`（默认 false）。
- **CLI**：本地裁剪，不调用模型——保留**首条 + 最近 4 条**消息（不走上述模型摘要路径）。

### English

Before sending messages, Chat trims the transcript to a context budget (an 80-message window;
anything older is injected as a note). The status line reports usage as `上下文 12% · 2.4k/20k`,
and near the limit you get a `/compact` / `/new` tip.

`/history` lists **review runs** by default (adjusted 2026-09-27 per user feedback — "history"
intuitively means this tool's core record; session-level management lives in `/sessions`):

- `/history [N]` — list the **review runs** (Run ID / PR / model / findings), default 10, range 1–50, plus statistics.
- `/history --runs [N]` — equivalent to the default (**compatibility alias**).
- `/history --chat [N]` — list the last N messages of the **current session** (all of them if N is omitted;
  entries outside the 80-message window are marked).
- `/history <run_id>` — **load** that run's report and **bind** it as the active review context, so
  the following questions are answered against that review.

`/compact` differs per surface:

- **TUI**: retention is now **the newest turns that fit a token budget** (no longer a fixed
  "newest 10 turns") — the tail budget defaults to `compaction_tail_tokens` = **40000 tokens** and is
  **capped at 25% of the model window**; **whole turns are kept** (a user message is never split from
  its assistant reply) and **at least 1 turn always survives**. Everything older is replaced by a
  model-generated summary (inserted as a `（历史摘要）…` message); `/compact <instruction>` pins what
  the summary must preserve. Returns `kept_turns`, `replaced_messages`, `before_tokens`,
  `after_tokens`, `summary_chars`.
- The **summary structure** is a `<conversation-summary>` XML block carrying the attributes `trigger`
  (`manual` / `auto`), `replaced_messages` and `kept_turns`, plus a **`## 已压缩对话涉及的文件`** file
  list in the body — so you can still ask "which files did we touch?" after compaction.
- **A failed compaction keeps the original history** (no messages are lost).
- **Auto-compaction is off by default** (`compaction_auto` defaults to `false`): you only get the
  status-line pressure hint (see §6); nothing is compressed silently. Three settings apply:
  `compaction_tail_tokens` (default 40000), `compaction_trigger_ratio` (default 0.9) and
  `compaction_auto` (default false).
- **CLI**: a local trim that never calls a model — it keeps the **first message + the newest 4**
  (it does not go through the model-summary path above).

| 命令 Command | 用途 Purpose | 用法 Usage | 示例 Example | 注意 Note |
|---|---|---|---|---|
| `/compact` | 压缩会话历史 / Compress the transcript | `/compact [指令]` | `/compact 保留未完成的修复项` | TUI 按 token 预算保留最近若干轮（整轮保留；默认尾部 40000 token、≤ 窗口 25%、至少 1 轮），调用当前 chat 模型生成 `<conversation-summary>` 摘要；失败则**保留原历史**；自动压缩默认关闭 / TUI keeps the newest turns within a token budget (whole turns; tail 40000 tokens, ≤ 25% of the window, ≥ 1 turn), calls the chat model for a `<conversation-summary>`; on failure the history is kept; auto-compaction is off by default. CLI trims locally |
| `/context` | 查看/切换/解除审查上下文绑定 / Show, switch or drop the review context binding | `/context` · `/context <run_id>` · `/context off` | `/context`、`/context off` | 未绑定时会提示先跑一次 `/review` 或用 `/context <run_id>`；`off`/`none` 等价 / `off` and `none` are equivalent |
| `/history [N]` | 列当前会话对话消息 / List session messages | `/history` · `/history 20` | `/history 20` | **TUI 默认形态**；无会话（CLI/测试直调）时降级为审查历史 / TUI default; falls back to run history without a session |
| `/history --runs` | 列审查历史 / List review runs | `/history --runs` · `/history --runs 20` | `/history --runs` | 返回 `runs` + `statistics`，供工作台载入 / Feeds the workbench |
| `/history <run_id>` | 载入报告并绑定上下文 / Load a report and bind it | `/history <run_id>` | `/history 3f2a91c4` | 返回 `bound` 字段：会话未带 `session_id` 时绑定会静默失败，`bound=false` 就是没有绑定 / A false `bound` means no binding happened |

状态栏与提示 / Status line & tips：

- 上下文提示行 `上下文 12% · 2.4k/20k`（英文界面为 `context …`）：无 context 数据时不渲染；`used_percent` 优先，缺失时用 `used/budget` 推算。
  Context hint `上下文 12% · 2.4k/20k`; hidden when the backend sends no context.
- 超额 tips（`warning = over_budget`，用提示色不用报警红）：`上下文接近上限：可用 /compact 压缩，或 /new 重新开始`。
  Over-budget tip: compress with `/compact`, or start over with `/new`.

---

## 3. 思考档位 / Reasoning effort

### 中文

`/think` 控制这一轮对话的思考深度（`preferences.chat_reasoning_effort`，默认 `auto`，写入配置文件）。
不带参数时只回显当前档位。

**为什么本地 Ollama 上档位是灰的**：本地走 OpenAI 兼容端点，端点会**收下** `reasoning_effort` 但**忽略**它。
`docs/DEV_RECORD.md` 的结论是：

> **端点收下参数 ≠ 参数生效**：只有 reasoning 长度（或行为）出现可复现的、单调的差异才算生效；否则一律按"忽略"处理。

该文档对本机 Ollama `qwen3.5:4b` 的**非流式**探测判定是 `NOT-SUPPORTED / none`；后续产品链路
的**流式**实测（`docs/DEV_RECORD.md`）发现 `think=false` 在流式下**生效**。据此产品
做出明确决策（2026-09-26 用户裁定）：**本地固定快速模式、不展示思考**，档位**置灰**并如实说明
（`state = "unsupported"`，文案：「本地模型固定使用快速模式（不展示思考），档位不可调；
需要思考强度请切换云端模型」），而不是假装可以切换。

### English

`/think` sets the reasoning depth for chat (`preferences.chat_reasoning_effort`, default `auto`,
persisted to the config). Without arguments it only reports the current level.

**Why the levels are greyed out on local Ollama**: the probe below classified the local model as
`NOT-SUPPORTED / none` on the **non-streaming** path (`docs/DEV_RECORD.md`), while a later
**streaming** measurement (`docs/DEV_RECORD.md`) showed `think=false` *does* take effect
on the wire. The product therefore made an explicit decision (user ruling, 2026-09-26): **local chat
is fixed to fast mode and never shows thinking**, with the levels greyed out and stated honestly:

> **Accepting a parameter ≠ honouring it** ("端点收下参数 ≠ 参数生效"): a level only counts as effective
> when reasoning length/behaviour shows a reproducible, monotonic difference; otherwise treat it as ignored.

The backend returns `state = "unsupported"` with: 「本地模型固定使用快速模式（不展示思考），档位不可调；
需要思考强度请切换云端模型」 (“Local models run in fast mode and never show thinking; switch to a cloud
model for reasoning levels.”) instead of pretending the switch works.

| 命令 Command | 用途 Purpose | 用法 Usage | 示例 Example | 注意 Note |
|---|---|---|---|---|
| `/think` | 查看当前思考档位 / Show the current level | `/think` | `/think` | 回显 `当前思考档位：auto` / Echoes the current level |
| `/think <档位>` | 设置思考档位 / Set the level | `/think off\|low\|high\|max\|auto` | `/think high` | 仅 5 个合法值，其他值报错；**仅 TUI** / Only these five values; TUI only |
| （本地端点 local endpoint） | 档位置灰 / Levels greyed out | `/think high`（在 `ollama`/`local` provider 下） | `/think max` | 返回 `state="unsupported"`，**不改配置** / Returns `unsupported`; the config is not changed |

### 3.1 审查（review）的思考档位 / Reasoning level for reviews

**中文**

review 与 chat 是**两个独立的档位**（`preferences.review_reasoning_effort`，**默认 `off`**）：
审查是"成本/质量取舍"，默认沿用今天的快速模式，不会因为你在聊天里选了 `max` 就悄悄变贵。

| 值 | 含义 | 请求体（以 deepseek 为例） |
|---|---|---|
| `off`（默认） | 不思考（现状） | `thinking: {"type": "disabled"}`，无 `reasoning_effort` |
| `low` / `high` / `max` | 思考，按档位给预算 | `thinking: {"type": "enabled"}` + `reasoning_effort: "low\|high\|max"` |
| `auto` | 不干预：由供应商默认 / policy 决定 | 与 `off` 相同（deepseek 的 policy 就是显式关闭） |

- **怎么设**：`pr-review config preferences --review-reasoning-effort high`（`pr-review preferences ...`
  等价；词表 `off|low|high|max|auto`，非法值由命令行直接拒绝）。也可以直接改配置文件的
  `preferences.review_reasoning_effort`，或走配置助手的后端字段
  （`config.options.review_reasoning_effort` / `config.setup`；**TUI 界面尚未接入**，另行排期）。
- **成本**：开启档位会给审查的输出额度加思考预留（`low/high/max` → **+4000/+8000/+12000**
  tokens，仍受模型规格的 `max_output` 封顶）。真机实测（`docs/DEV_RECORD.md` §2）：
  `max` 档约 **3.6× 输出 tokens、2.9× 单文件耗时**；按逐文件 × 并发 × 文件数放大，请按需选择。
- **本地与不支持思考参数的供应商**：本地 `ollama`/`local` 固定快速模式，档位**不生效**；
  官方文档没有思考参数的供应商（如 baichuan）、未收录的供应商，以及**配成 Anthropic 协议
  （`api_format=anthropic`）的中转端点**（这类端点会丢弃透传参数）**都不注入任何参数**——
  这几种情况会在出口给出说明（配置助手的 `state`/`reason`、CLI 的 `review_reasoning_note`），
  不会假装生效。
- `off` 是**维持现状**而不是"对所有供应商强制关闭思考"：它不注入任何参数（表里 deepseek 的
  `disabled` 来自审查策略本身），其它供应商维持各自的默认行为。混合策略下档位只作用于远端
  文件，低复杂度文件仍由本地模型以快速模式审查。

**English**

Reviews have their **own level** (`preferences.review_reasoning_effort`, **default `off`**) — the
chat level never leaks into reviews, so picking `max` for chat does not silently make reviews
expensive.

| Value | Meaning | Wire body (deepseek example) |
|---|---|---|
| `off` (default) | No thinking (today's behaviour) | `thinking: {"type": "disabled"}`, no `reasoning_effort` |
| `low` / `high` / `max` | Think, with a per-level budget | `thinking: {"type": "enabled"}` + `reasoning_effort: "low\|high\|max"` |
| `auto` | Don't touch anything: leave it to the vendor/policy | Same as `off` for deepseek (its policy disables thinking) |

- **How to set it**: `pr-review config preferences --review-reasoning-effort high` (the same
  command is also reachable as `pr-review preferences …`). The value can also be edited directly in
  the config file, or through the setup wizard's backend fields (`config.options` / `config.setup`);
  the TUI does not render it yet.
- **Cost**: enabling a level adds a thinking reservation to the review output budget
  (low/high/max → **+4000/+8000/+12000** tokens, still capped by the model spec's `max_output`).
  Measured on the live DeepSeek endpoint: `max` costs about **3.6× output tokens and 2.9× wall
  clock per file**.
- **Local and non-thinking providers**: local `ollama`/`local` stays in fast mode (the level has no
  effect); providers without official thinking parameters, unknown providers, and **relays
  configured for the Anthropic protocol (`api_format=anthropic`, which drops passthrough params)**
  get **no injected parameters at all** — the exits say so (`state`/`reason` in the wizard,
  `review_reasoning_note` in the CLI) instead of pretending the level works.
- `off` means **keep today's behaviour**, not "force thinking off everywhere": nothing is injected
  (the deepseek `disabled` above comes from the review policy itself) and other providers keep their
  own defaults. Under the hybrid strategy the level applies to remote files only; low-complexity
  files are still reviewed locally in fast mode.

---

## 4. 审查命令 / Review commands

### 中文

审查是"跑一次 → 看报告 → 解读 → 反馈/发布"的闭环；`/review` 成功后会自动把该 Run 绑定为当前上下文。

### English

Reviewing is a loop: run → read the report → discuss → feedback/publish. A successful `/review`
auto-binds that run as the current context.

| 命令 Command | 用途 Purpose | 用法 Usage | 示例 Example | 注意 Note |
|---|---|---|---|---|
| `/review` | 运行 PR 审查 / Run a PR review | `/review <PR URL>` | `/review https://github.com/owner/repo/pull/42` | 同一会话已有审查在跑时返回 busy，需等它完成或 `/cancel`；成功后绑定 run / Busy while a review runs; binds the run on success |
| `/cancel` | 取消当前对话或审查 / Cancel the running chat or review | `/cancel` | `/cancel` | 两者都取消；没有任务时提示"当前没有正在运行的任务" / Cancels both; reports when nothing runs |
| `/retry` | 重试上一次审查 / Retry the last review | `/retry` | `/retry` | **TUI 本地**（`Ctrl+R` 等价），不进后端 / TUI-local, never reaches the backend |
| `/report` | 查看当前报告 / Show the current report | `/report` | `/report` | 以 Markdown 输出；没有报告时提示 / Markdown; warns when empty |
| `/export` | 导出当前报告 / Export the current report | `/export json\|markdown [路径]` | `/export markdown out.md` | 不给路径=直接返回文本；给路径=写文件 / Without a path it prints, with a path it writes |
| `/explain` | 解释某次 Run 的 Finding 与证据 / Explain a run's findings and evidence | `/explain <run_id>` | `/explain 3f2a91c4` | **不调用模型**；成功即绑定该 run / No model call; binds the run |
| `/feedback` | 记录 Finding 反馈 / Record finding feedback | `/feedback <run_id> <finding_id> <status> [note]` | `/feedback 3f2a91c4 F-12 fixed 已处理` | `status ∈ accepted\|rejected\|fixed\|needs_review`，按 finding id 匹配 / Matched by finding id |
| `/publish` | 预览并发布审查评论到 GitHub / Preview then publish comments | `/publish [run_id] [--confirm]` | `/publish` → 检查 → `/publish --confirm` | **只有带 `--confirm` 才会真正调 GitHub API** / Only `--confirm` reaches GitHub |
| `/demo` | 运行离线演示用例 / Run an offline demo case | `/demo [case_key\|list]` | `/demo list` | 纯离线（fixtures + 规则），不联网不调模型 / Offline by construction |
| `/showcase` | 查看参赛演示路径 / Show the contest demo path | `/showcase` | `/showcase` | 离线，只读配置 / Offline, read-only |
| `/workbench` | 展开/收起审查工作台 / Fold or unfold the workbench | `/workbench` | `/workbench` | **TUI 本地**（`Alt+W` 等价）；收起后数据保留 / TUI-local; data is kept while folded |
| `/model` | 查看/切换模型与运行模式 / Show or switch model & runtime | `/model` · `/model status` · `/model chat\|review <模型ID>` · `/model local\|cloud\|hybrid` · `/model <模型ID>` | `/model cloud`、`/model chat deepseek-flash` | 运行模式档位是 `local`/`cloud`/`hybrid`（旧值 `offline` 仍兼容），界面里的"本地/云端"槽位即 local/cloud；裸模型名等同 `/model chat <名>` / Runtime profiles are `local`/`cloud`/`hybrid` (`offline` kept for compatibility); a bare name means the chat slot |
| `/setup` | 打开配置助手 / Open the setup wizard | `/setup` | `/setup` | TUI 中由前端本地打开（`Ctrl+P`）；后端仅回提示 / TUI opens it locally via `Ctrl+P` |
| `/stats` | 查看审查统计 / Show review statistics | `/stats` | `/stats` | **仅 CLI** / CLI only |

---

## 5. 快捷键 / Shortcuts

### 中文

以下为 TUI 快捷键（`Ctrl` 类全局有效，`Alt` 类需输入框持有焦点）。Findings 列表另有单键操作。

### English

TUI shortcuts: `Ctrl` keys are global; `Alt` keys need composer focus. The findings list has its own
single-letter keys.

| 快捷键 Key | 作用 Action | 中文 / English |
|---|---|---|
| `Enter` | 发送 / Send | 发送当前输入 / Send the draft |
| `Shift+Enter` | 换行 / New line | 输入框内换行 / Insert a newline |
| `Tab` | 补全命令 / Complete | 命令菜单里补全带参数的命令，不直接执行 / Completes an argument-taking command instead of running it |
| `↑` `↓` | 菜单选择 / Menu | 命令菜单上下移动 / Move in the command menu |
| `Esc` | 关闭/取消 / Close or cancel | 先关命令菜单；再按一次请求取消 / Closes the menu first, then requests cancel |
| `Ctrl+C` | 复制 / 取消 / 退出 / Copy · cancel · quit | 有选区=复制；无选区第一次提示、1.5 秒内再按一次退出；任务运行中=取消 / Copy with selection; otherwise press twice within 1.5s to quit; cancels while busy |
| `Ctrl+A` | 全选 / Select all | 输入框内全选 / Select all in the composer |
| `Ctrl+P` | 设置 / Settings | 打开配置助手 / Open the setup wizard |
| `Ctrl+L` | 历史 / History | 打开审查历史 / Open review history |
| `Ctrl+K` | 模型 / Model | 打开模型选择 / Open the model picker |
| `Ctrl+R` | 重试 / Retry | 重试上一次审查（= `/retry`）/ Retry the last review |
| `Ctrl+O` | Findings | 打开问题列表（对话框打开时也生效）/ Open the findings list even while a dialog is open |
| `Ctrl+F` | 筛选 / Filter | Findings 筛选浮层：`Tab` 严重级别 · `Shift+Tab` 证据 · `Ctrl+S` 排序 · `Enter` 应用 · `Esc` 清除 / Findings filter overlay |
| `Alt+W` | 工作台 / Workbench | 展开/收起审查工作台（= `/workbench`）/ Toggle the workbench |
| `Alt+S` | 会话列表 / Session list | 打开会话列表（= `/sessions`）；`↑↓` 选择、`Enter` 切换、`r` 重命名、`d` 删除、`Esc` 关闭 / Open the session list (`= /sessions`); `↑↓` select, `Enter` switch, `r` rename, `d` delete, `Esc` close |
| `Alt+L` | 代码块 / Code block | 折叠/展开当前长代码块；也可直接**点击块尾角标** / Toggle the fold badge on a long code block (or click it) |
| `Alt+T` | 思考区 / Thinking block | 折叠/展开最近一条带思考的消息（落定后默认折叠）/ Toggle the latest reasoning block (folded once settled) |
| `Alt+E` | 解释 / Explain | 解释当前 Run（= `/explain`）/ Explain the active run |
| `Alt+F` | 反馈 / Feedback | 记录 Finding 反馈（= `/feedback`）/ Record finding feedback |
| `Alt+X` | 导出 / Export | 导出当前报告（= `/export`）/ Export the current report |
| `Alt+P` | 发布 / Publish | 进入发布流程：先预览，再按 `Enter` 才真正发帖 / Publish flow: preview first, `Enter` posts |
| `Alt+D` | 演示 / Demo | 打开离线演示面板（= `/demo`）/ Open the offline demo panel |

Findings 列表内 / Inside the findings list：`↑↓` 选择、`←→` 翻页、`Ctrl/Alt+↑↓` 或 `PgUp/PgDn` 滚动详情、`Tab` 切到详情、
`E` 解释 · `F` 反馈 · `X` 导出、`Esc` 返回。

Select with `↑↓`, page with `←→`, scroll details with `Ctrl/Alt+↑↓` / `PgUp`/`PgDn`, `Tab` focuses the
detail pane, `E`/`F`/`X` explain/feedback/export, `Esc` goes back.

---

## 6. 提示与状态栏说明 / Hints & status line

### 中文

| 位置 Where | 内容 What you see | 含义 Meaning |
|---|---|---|
| 状态行 Status line | `CHAT · <model> <provider>` | 当前模式、模型与供应商 / mode, model, provider |
| 输入框占位 Placeholder | `输入消息或粘贴 PR URL；输入 / 查看命令` | 空闲；审查中变为 `审查进行中...(Esc / Ctrl+C 取消)`；请求中为 `正在处理...` / idle → reviewing → busy |
| 命令菜单 Command menu | 输入 `/` 开头即弹出 | 只列出**当前 TUI 与后端都实现了**的命令 / Lists only commands implemented by the current TUI and backend |
| 上下文行 Context line | `上下文 12% · 2.4k/20k` | 本轮占用/预算；无 context 数据不渲染 / used vs budget; hidden without data |
| 会话标题 Session title | 状态栏显示当前会话标题 | 窄终端隐藏 / shown in the status line; hidden on narrow terminals |
| 压力分级 Pressure | `pressure`：`low` / `medium` / `high` / `critical` | 上下文占比分级；从 `high` 起显示提示「上下文接近上限：可用 /compact 压缩」 / graded context usage; from `high` on you get the tip `上下文接近上限：可用 /compact 压缩` |
| 超额提示 Over-budget tip | `上下文接近上限：可用 /compact 压缩，或 /new 重新开始` | `assistant.finished.warning = over_budget`，提示色非报警红 / warning tint, not alarm red |
| 流式正文 Streaming | 末尾闪烁光标 `▌`；首 token 前显示 `⠋ 思考中` / `Thinking…` | 正在流式接收 / streaming in flight |
| 思考区 Reasoning block | 落定后默认折叠，`Alt+T` 展开 | 避免长思考淹没正文 / keeps long reasoning out of the way |
| 代码块 Code block | 右下角折叠角标，点击或 `Alt+L` 切换 | 长代码块可折叠 / long blocks are foldable |
| Findings 空态 Empty findings | `审查仍在进行中；完成后按 Ctrl+O 查看问题。` 等 | 提示先 `/review` 或 `/history <run_id>` / run a review first |
| 恢复提示 Recovery hint | `可用恢复：Ctrl+R /retry · /model status · /model local · /model cloud · /new` | 模型/连接出错时的恢复入口 / recovery entry points after an error |
| 底部快捷键行 Footer | `Enter 发送 · Shift+Enter 换行 · Ctrl+P 设置 · Ctrl+L 历史 · Ctrl+K 模型`（有工作台时加 `Alt+W`，有可折叠代码块时加 `Alt+L`） | 按条件显示 / conditional items appear only when relevant |

### English

The same table applies in English: the UI switches labels (`context …`, `Thinking…`,
`Context near limit: run /compact to compress, or /new to start over`) while the layout and
conditions stay identical.

The two rows added for contract v1 render as:

- **Pressure**: `pressure` takes one of `low` / `medium` / `high` / `critical`; from `high` on the
  status line shows 「上下文接近上限：可用 /compact 压缩」 (the English wording comes from the UI
  translation table — see the implementation doc).
- **Session title**: the status line also shows the current session title; it is hidden on narrow
  terminals.

---

## 7. 帮助文本与一致性 / Help text consistency

- **TUI `/help`**（`jsonl_server.py` 的 `command.execute` → `help` 分支）：逐行列出后端分发的全部命令，
  外加前端本地截获的 `/retry`、`/workbench`；已不再支持的 `/exit` 已从该文本移除。
- **CLI `/help`**（`chat_commands.build_chat_help_text()`）：逐行列出 CLI 本地实现的 14 条命令
  （`/help /status /usage /new /clear /restore /compact /history /stats /config /session /model /review /exit`）。
- 两份文本与实现的对应关系由 `tests/test_chat_commands.py` 断言：
  从源码 grep 出 `elif command ==` 的分发集合，与帮助文本里出现的命令做**双向**比对
  （多一条、少一条、残留已删除命令都会失败）。

- **TUI `/help`** lists every backend-dispatched command plus the frontend-local `/retry` and
  `/workbench`; the unsupported `/exit` was removed from it.
- **CLI `/help`** lists the 14 commands the CLI implements locally.
- `tests/test_chat_commands.py` greps the `elif command ==` dispatch set from the source and compares
  it **both ways** against each help text — a missing command, an extra command, or a removed command
  still being advertised all fail the suite.
