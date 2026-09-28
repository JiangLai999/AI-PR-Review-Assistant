# 多会话存储 + 上下文压缩改造（后端核心线）

> 任务：`claude-sessions-compaction-core`（A-P1 + B-P1/P2 + B-P3 后端）
> 契约 v1 见 `docs/session-and-compaction-plan.md`；四条线（后端 / TUI / 验收 / 手册）
> 共用同一套字段名与语义。**本文只写"落在哪个文件哪一行、为什么这么落地"**，
> 用户视角的用法见 `docs/chat-features.md` 与会话手册（opencode 线）。
>
> 写集：`chat_session.py`、`backend/jsonl_server.py`、`config.py`、
> `tests/test_chat_session.py`、`tests/test_jsonl_backend.py`、本文。
> 另：`tests/test_chat_contract_events.py` 的六键断言按 prompt 要求同步为七键（见 §5 说明）。

---

## 1. 会话协议（A 组）

### 1.1 契约落点

| 契约 | 实现位置 | 说明 |
|---|---|---|
| 存储布局 | `chat_session.py:29-65` | `<config 同目录>/sessions/index.json` + `sessions/<id>.json`；id 白名单 `^[A-Za-z0-9_-]+$` |
| 原子写 | `chat_session.py:200`（`_atomic_write_json`） | tempfile + fsync + `os.replace`；失败清理临时文件 |
| `ChatSessionStore` | `chat_session.py:236`（`create` 477 / `switch` 519 / `rename` 533 / `delete` 551 / `save` 578 / `migrate_legacy` 617） | 存储层；**文件是真相，索引是缓存** |
| 索引自愈 | `chat_session.py:364`（`_load_records`） | 见 §1.3 |
| 索引记录刷新 | `chat_session.py:340`（`_refresh_record`） | 见 §1.4（本轮修掉的 bug） |
| 标题生成 | `chat_session.py:185`（`default_session_title`） | 首条用户消息、空白折叠、截断 40 字 |
| `session.list` | `jsonl_server.py:4211`（分发）/ `:2097`（载荷） | `{sessions:[{id,title,updated_at,message_count,current}], current}` |
| `session.switch` | `jsonl_server.py:4214` / `:2109`（`_open_session`） | 先落盘当前会话，再载入目标并激活 |
| `session.rename` | `jsonl_server.py:4246` | 空标题 → `invalid_request`（列表里的一行空白看起来像坏了） |
| `session.delete` | `jsonl_server.py:4260` | 删当前 → 自动切最近一个，返回 `{deleted, next}` |
| `session.create` | `jsonl_server.py:4206` / `:2143`（`_session_create_payload`） | **新建并切换**；返回体 = 旧顶层键 + `session` |
| `/new` | `jsonl_server.py:4779` | = `session.create`（不再 `clear_chat_session`） |
| 启动迁移 | `jsonl_server.py:4857`（`serve()` 里调用 `migrate_legacy()`） | 见 §1.2 |
| 会话 id | `chat_session.py:179`（`_session_order`） | 单调 ASCII `s1`、`s2`…（不把 UUID 暴露给用户） |

**语义要点**

- **`session.create` 不再恢复历史**：旧实现每次打开 TUI 都"续上那唯一一个会话"。
  现在恢复走 `session.list`（拿 `current`）→ `session.switch`（载入消息）。TUI 重启后
  即使直接带旧 id 发 `chat.send`，后端也会按需从盘上载入（`_open_session`）。
- **返回体是"旧键 + `session`"的超集**：`session_id` / `messages` / `message_count` /
  `current_run_id` 是 TUI 现行代码与 80+ 条既有用例在读的字段，契约只要求"有 `session`"，
  没要求删旧键——两个都给，谁都不破。
- **`current_run_id`（review 绑定）随会话走**：落盘在会话文件里，`switch` 时恢复；
  `switch` 响应里的 `session` 按**内存**状态拼（绑定可能还没落盘），索引只补 title/updated_at。
- **会话列表项恰好五个键**：`current_run_id` 只出现在 `session.switch.session` 上——
  同一数组里的元素同键同形，且列表响应不随会话数变胖。
- **内存里的 `Session` 对象按 id 复用**（`_open_session` 先查 `self.sessions`）：
  `published_run_ids`（§12.2 的重复发布拦截）与 `context_candidates`（§9.2 E 的"第 2 个"）
  是按会话的进程内状态，每次切换都新建会让"切走再切回"丢掉它们（同一个 run 会被再发一次评论）。
  删除时**会**把内存那份一并丢掉——留着它，下一次 `chat.send` 会把已删会话重新落盘。

### 1.2 迁移策略

`ChatSessionStore.migrate_legacy()`（`chat_session.py:617`），在 `serve()` 启动时调用一次：

1. 旧 `<config 同目录>/chat_session.json` 不存在 / 读不出消息 → 直接返回（**不阻塞启动**）；
2. 索引里已有 `source=legacy` 的会话，或索引标记过 `legacy_imported` → 跳过
   （用户可能已经把那条会话删了，不该再长回来）；
3. 否则导入为一条 `title="legacy"`、`source="legacy"`、`title_source=user` 的会话；
   仅当**当前没有会话**时才把它设为 `current`（不顶掉用户正在聊的会话）。

**旧文件只读不改**：CLI `pr-review chat` 仍然用 `chat_session.json`（`load_chat_session` /
`save_chat_session` 原样保留，遗留兼容不动）。代价要说清楚：**迁移是一次性的**——TUI 之后
只写 `sessions/`，所以迁移之后在 CLI 里新建的对话不会再出现在 TUI 的会话列表里（反之亦然）。
这是契约"旧文件只读、CLI 照旧"的直接结果，见 §5 未决项 8。任何异常都只 stderr 告警。

### 1.3 自愈逻辑（索引是缓存）

`_load_records`（`chat_session.py:364`）每次读列表都做一次"索引 ∪ 目录扫描"：

| 分支 | 触发 | 处理 |
|---|---|---|
| 1 | 索引缺失/损坏/形状不对 | 全量扫描 `sessions/*.json` 重建 |
| 2 | 索引落后（目录里有、索引里没有） | 从会话文件补齐一条 |
| 3 | 索引超前（引用的文件没了） | 剔除该条，并把它从 `current` 上摘掉 |
| 4 | `current` 为空但目录里有会话 | 指向最近的会话（索引整个丢了的重建场景） |

任一条触发就把索引写回去。**索引写失败只告警**（`_write_index`）：会话文件已经落盘，
下一轮扫描会把索引补齐——磁盘问题不该让这一轮聊天失败。

**已知取舍**：分支 3 只做 `path.exists()`（便宜）；"索引里记录的文件内容坏了"不会被
列表发现——要发现它就得把每个会话文件都读一遍，而索引存在的意义正是不读它们。
坏会话在 `session.switch` 时报 `not_found`，索引重建后才从列表消失（见 §5 未决项）。

### 1.4 本轮修掉的存储层 bug

`save()` / `rename()` 写完会话文件后要重写索引，但 `_load_records` 对**已在索引里**的
会话不做文件扫描——于是索引里的旧 `title`/`message_count`/`updated_at` 会把刚写进文件的
新值覆盖回去：`session.list` 永远显示旧标题，`updated_at` 也不再变化（排序失真）。
修法是 `_refresh_record`（`chat_session.py:340`）：写完之后按 id 把这一条从文件重读一遍。
回归用例：`tests/test_chat_session.py::test_save_keeps_the_user_title_and_the_message_count_fresh`。

---

## 2. 压缩改造（B 组）

### 2.1 保留口径：token + 对话轮

```
tail_budget = min(preferences.compaction_tail_tokens, effective_window × 0.25)
effective_window = 聊天槽模型 context_window → 聊天预算 → 兜底 8000
```

- 实现：`_compaction_tail_budget`（`jsonl_server.py:3424`）/ `_chat_effective_window`（`:3411`）；
  比例常量 `CHAT_COMPACTION_TAIL_RATIO = 0.25`（`:350`）。
- **按轮累加**：`_conversation_turns`（`:3449`）——一轮 = 一条 user + 其后的 assistant
  （工具链、摘要等紧跟其后）；`_split_compaction_tail`（`:3475`）从最新往回累加到超预算。
  轮边界只认 user，**绝不拆散一轮**：把"问题"留在原文、把"回答"塞进摘要，会让模型看到
  一段没有问句的答案。
- **至少保 1 轮**（`CHAT_COMPACT_MIN_TURNS = 1`，`:349`）：预算比一轮还小时，那一轮**整轮**留下，
  只把更早的历史交给摘要——极端配置下也不清空对话。
- `effective_window` 拿不到模型窗口时退回**聊天预算**（默认 8000 → 尾部 2000 token）：
  内置预设刻意不参与窗口推算（见 `_chat_context_window` 的说明），宁可保守地多压一点，
  也不要按想象中的大窗口留下超长原文。
- token 估算用 `estimate_tokens`（4 字符 ≈ 1 token）逐条序列化后相加（`_messages_tokens`，`:3431`）：
  一组消息的 token 数要能单独比较，才能回答"这一轮装不装得下"。

### 2.2 摘要结构（XML）

```
<conversation-summary trigger="manual|auto" replaced_messages="N" kept_turns="M">
…（模型生成的摘要正文）…
（更早的 K 条消息已省略，未参与本次摘要）      ← 仅当触发了 §2.3 的截断
## 已压缩对话涉及的文件
- website/index.html（讨论过 3 次）
- src/app.py（本次审查点名）
</conversation-summary>
```

- 组装：`_summary_document`（`:3567`）；摘要消息的 role 是 `system`，内容**以标签开头**
  （不再有 `（历史摘要）` 前缀——XML 标签本身已经说明了这是摘要）。
- 文件清单数据源（方案 §B3）：`_mentioned_path_counts`（`:3526`，被压缩消息里的路径 +
  出现次数，URL 先剔除）+ `_findings_file_paths`（该会话绑定 run 的 finding 文件，标注
  "本次审查点名"）。排序固定为"提及次数降序 → 路径升序"（同一段历史每次压缩结果一致），
  上限 `CHAT_COMPACTION_FILE_LIMIT = 12`。
  路径正则用 `_PATH_TOKEN_PATTERN`（比注入路径宽）：清单只是**摘要里的指代锚点**，
  `.html` / `.md` 这类非源码文件恰恰最常出现在"我们改过哪些文件"里。

### 2.3 压缩自身的安全网（§B5）

- `_summary_input`（`:3502`）：发给摘要模型的正文截断到 `effective_window × 0.6`
  （`CHAT_COMPACTION_SUMMARY_INPUT_RATIO`，`:352`）。丢弃的是**最旧**的一段，
  至少留一条（哪怕它自己就超预算）。
- 省略条数是**确定性**写进摘要的（"更早的 K 条消息已省略"），同时写进提示词——
  模型可能忘，账不能忘。
- 摘要失败/摘要为空 → 抛错，**原历史一字不动**（`session.messages` 在模型返回之前不赋值），
  协议层翻成 `ok:false`。
- 装得下就不压：`old_messages` 为空时直接返回全零，**不调用模型**（用户点 `/compact` 不该
  为"没什么可压"付一次调用）。

### 2.4 配置项（`config.py`）

| 键 | 默认 | 合法范围 | 归一化 |
|---|---|---|---|
| `preferences.compaction_tail_tokens` | `40000` | 4000–200000 | `normalize_compaction_tail_tokens`（`:1011`） |
| `preferences.compaction_trigger_ratio` | `0.9` | 0.5–1.0 | `normalize_compaction_trigger_ratio` |
| `preferences.compaction_auto` | `false` | bool | `normalize_compaction_auto` |

三个键都在 `PreferencesConfig.__post_init__` 里归一化，读侧（`_compaction_preferences`，
`jsonl_server.py:3402`）只消费——加载 / 导入 / 向导三条路径共用同一套回退规则。

---

## 3. 压力分级（B-P3 后端）

- `assistant.finished.context` 的**第七键** `pressure`：`low | medium | high | critical | null`。
- 分级：`_pressure_level`（`jsonl_server.py:3283`），阈值 `<50 low`、`50–79 medium`、
  `80–99 high`、`≥100 critical`；**算不出百分比时为 `null`**（预算 ≤ 0），与"低压力"必须可区分——
  混在一起会让状态栏把"估算失败"画成绿色。
- `warning` 的 `over_budget` 判定改用 `pressure == "critical"`（等价于 `used_percent >= 100`，
  但百分比为 null 时不会炸）。
- **默认只提示不自动压缩**：`compaction_auto=false` 时后端只把 `pressure` 交给事件消费方
  （TUI 状态栏）；打开开关后，`_maybe_auto_compact`（`:3677`）在每轮回答之后判断
  `used_percent >= trigger_ratio × 100`（默认 90）才真压一次，摘要里标注 `trigger="auto"`，
  并把这一轮的 `context.compacted` 标成 `true`。
  压缩要额外花一次模型调用，所以默认关闭——用户没要求就不该静默发生。
- 本轮实现的开关**默认关闭**（与方案 §B4 的用户拍板一致）。

---

## 4. 测试与验收

| 用例 | 文件 | 钉住的行为 |
|---|---|---|
| 存储 CRUD / 排序 / 标题 | `tests/test_chat_session.py` | 新建即切换、id 单调、40 字截断、同秒按 id 排序 |
| 索引自愈四分支 | 同上 | 索引丢失/落后/超前/current 为空 |
| 迁移 | 同上 + `test_jsonl_backend.py::test_legacy_chat_session_json_is_migrated_when_the_backend_starts` | 只读旧文件、只导一次、删掉不复活；后者走真正的 `serve()` |
| 协议五方法 | `tests/test_jsonl_backend.py` | `list` 键集、`switch` 先落盘、`rename`/`delete` 形状、`create` 旧键 + `session` |
| 绑定随会话走 | 同上 | 切走切回、重启后 `current_run_id` 仍在 |
| 压缩边界 | 同上 | 整轮保留、预算 < 1 轮至少保 1 轮、短消息全保留、装得下不调模型 |
| 文件清单 | 同上 | 消息路径计数 + finding 文件 + URL 不入清单 |
| 摘要截断 | 同上 | 丢最旧、条数确定性标注 |
| 七键 `pressure` | 同上 + `tests/test_chat_contract_events.py` | 四档边界值与 `null` |

验证命令（TEMP/TMP 指向 `.pytest_claude`）：

```
python -m pytest -q --no-cov
```

---

## 5. 未决项与已知取舍

1. **空标题的新会话**：新建会话（还没有任何消息）的标题是空串——标题的默认值是"首条用户消息
   截断 40 字"，此刻没有用户消息可截。列表行的占位文案（如"新会话"）应由 TUI 决定，
   后端不编造内容。首次保存后标题会自动补上。
2. **坏会话文件与索引**：索引里记录的会话文件内容损坏时，列表仍会显示它（见 §1.3 的取舍），
   点进去是 `not_found`。彻底解决要给索引加校验和/mtime 校验，属于下一轮。
3. **`session.delete` 的 `deleted` 字段**：契约 v1 写的是**被删的 id**（`{deleted: id, next}`），
   而 TUI 侧 `protocol.ts` 的解析器当前只接受 boolean——两边需要对齐（后端按契约返回 id）。
4. **`/sessions` 不在后端 `/help` 里**：`tests/test_chat_commands.py` 把 `sessions` 列在
   `REMOVED_COMMANDS` 中，且后端确实不分发该命令（TUI 拦截后走 `session.list` 协议方法）。
   帮助文本里的会话入口归 TUI 的命令菜单负责。
5. **`tests/test_chat_contract_events.py` 不在本任务 `write_scope` 里**，但 prompt 明确要求
   "六键断言 → 七键"。已按 prompt 做最小改动（键集 + 两条压缩用例的夹具改为长消息）。
6. **prune（工具结果收缩）明确不做**：我们的 chat 没有"工具调用结果"这种大块内容
   （review 上下文每轮现算、不落盘），方案 §B7 已定。
7. **自动压缩的可见性**：自动压缩只写 stderr 日志并标在 `context.compacted` 上，没有单独的
   事件。若 TUI 想显式提示"刚刚自动压缩了"，需要新增事件——属于契约扩展，本轮不做。
8. **CLI 与 TUI 的会话从此是两份存储**：迁移之后 `pr-review chat`（`chat_session.json`）
   与 TUI（`sessions/`）不再共享历史。若要让 CLI 也走多会话存储，属于另一期工作。
9. **重复压缩会让清单里的路径"续命"**：旧摘要的正文与文件清单也会参与下一次压缩的清单统计
   （这是有意的——否则早期提过的文件会随压缩消失）。计数按"每条消息最多一次"，
   但多次压缩之间仍会累加。
