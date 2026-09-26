# 上下文管理 A1-A3（任务 `claude-chat-context-a`）交付报告

**一句话结论**：注入的仓库文件不再一律从**文件头**截断——被本次 finding 点名的文件改取
`finding.line_start ± 80` 行的窗口并标注「（显示第 157-317 行，文件共 412 行）」，窗口超预算时
**先保住 finding 那一行**再向两侧补上下文；会话（role/content/timestamp）落盘到
`chat_session.json`，新建会话即恢复、`/new` 清空；对话历史窗口 40 → 80 条并在裁剪时**明确告知**，
`chat_context_budget`（默认 8000）可在配置文件里改。

- 任务类型：实现（write_scope：`src/ai_pr_review/backend/jsonl_server.py`、
  `src/ai_pr_review/chat_session.py`、`tests/test_jsonl_backend.py`、本文件）
- 验证：`TEMP`/`TMP` → `.pytest_claude` → `python -m pytest -q --no-cov`
  → **1036 passed, 1 skipped**（基线 1028 passed, 1 skipped；新增 8 条，无回归）
- 未做：未读/打印凭据（全部用 stub `PRFetcher` + stub provider，不联网）；未执行任何 git
  操作；未改 TUI/`frontend/**`；未改 `config.py` 与 `cli.py`（在 write_scope 之外，见 §6.1）；
  未落盘 review 上下文与注入的源码

## 1. A1 · 仓库文件按 finding 行号取窗口（根因修复）

**缺陷证据（用户实测）**：绑定 PR #31 后问 `website/index.html` 的 finding，模型把整轮输出
花在"数行号"上——因为 `_collect_repo_files` 从文件头截断 8000 字符，而该 finding 在**第 237 行**，
文件只给到 ~200 行，**要找的那一行根本不在注入内容里**。

改造后的分流（`_collect_repo_files`，`jsonl_server.py:1673`）：

| 文件 | 取哪一段 | 文件头标注 |
|---|---|---|
| 被本次 run 的 finding **点名** | `finding.line_start ± 80` 行窗口 | `（显示第 157-317 行，文件共 412 行）` |
| **未**被点名 | 头部截断（旧行为） | `（文件共 599 行，此处仅显示前 165 行）`；未截断则不标注 |
| 窗口内容超预算 | 窗口内再截断，**以 finding 行为锚点**向两侧收 | `（显示第 218-255 行，文件共 412 行；窗口 157-317 行已按预算截断）` |
| 窗口外还有 finding | 只给首个窗口 | 追加 `；另有 finding 在第 900 行` |

- **几何**（`_finding_window`，`:1751`）：多条 finding 时取**首个窗口**（方案 §A1 允许"覆盖并集
  或首个窗口"），与之重叠的 finding 并进来（`± 80` 后相接即合并）；行号先夹进文件范围，
  记录的行号越界时仍取到有效下标。
- **锚点截断**（`_fit_lines`，`:1805`）：这是本任务唯一一处"照抄方案会留坑"的地方——方案只说
  "超预算时窗口内再截断"，而按顺序从头切会让 `157→220` 行的截断把 **237 行的 finding 又切掉**，
  等于没修。所以窗口模式下先放 finding 行，再以"上下交替、少的一侧优先"补上下文，保证注入
  内容**连续且包含 finding 行**；未被点名的文件仍是从头顺次截断（旧行为不变）。
- **诚实标注**（`_excerpt_note`，`:1853`）：标注永远描述**真正注入的内容**——被预算截断时行范围
  随之收窄并写明"窗口已按预算截断"，不会出现"标注说给了 157-317 行、实际只到 220 行"。
- **预算不变**：单文件 8000 字符 / 多文件合计 12000 字符（`CHAT_REPO_FILE_MAX_CHARS` /
  `CHAT_REPO_FILES_TOTAL_CHARS` 原值），拉不到仍写 `(未能读取 X：原因)`，异常仍降级为空串。
- **注入段规则**新增第 4 条（`_repo_files_rules`，`:1873`）：文件头标注了行号范围的只给了那一段，
  直接按标注引用、**不要再自己数行号**，范围之外的代码不得臆测。
- 路径比较统一走 `_normalized_repo_path`（`:280`）：findings 存的是仓库相对路径，用户可能写
  `./website/index.html` 或反斜杠；不统一就会静默退化成头部截断。
- `_truncate_repo_file`（旧的字符截断助手）已被 `_repo_file_excerpt` 取代并删除，全仓无其它引用。

## 2. A2 · 会话落盘（重启可续）

| 时机 | 行为 | 位置 |
|---|---|---|
| `session.create` | 从 `chat_session.json` 恢复历史后返回；并写回一次（幂等） | `:2609`、`_restore_session_messages` `:2084` |
| 每轮 chat 完成 | 落盘整个 transcript | `_chat` `:2036`、`_persist_session` `:2100` |
| `/new` | `clear_chat_session` 后建空会话（不立刻重建文件） | `:3079` |
| 读/写失败 | 只向 stderr 记一行 warning，聊天照常（磁盘问题不该让回答失败） | `:2084`、`:2100` |

- **格式**沿用既有：`{"role", "content", "timestamp"[, "duration_seconds"]}`（`HH:MM`，与 CLI
  `chat_runtime.send_once` 一致；`duration_seconds` 是**既有格式的一部分**，组 C 的 C4 要用）。
  `chat_session.json` 与 `pr-review chat` 共用，两个前端切换着用能看见彼此的历史。
- **不存 review 上下文**：system prompt（审查上下文 + 注入的源码）每轮现算，落盘只会让历史重复
  膨胀、重复计费。验收脚本 [D] 直接断言落盘字段集与"历史里不含 system prompt 文案"。
- **上线路的消息只带 role/content**（`:2010`）：timestamp/duration_seconds 是落盘字段，部分
  OpenAI 兼容端点对消息里的未知字段直接报错。CLI 侧历史上会把它们发上线路，这里不跟。
- **绑定不落盘**：`current_run_id` / `context_candidates` / `published_run_ids` 仍是内存态——
  "绑定"是一次会话内的上下文，重启后回到普通聊天（与 §9.2 A 的既有语义一致），脚本 [D] 有断言。

## 3. A3 · 历史窗口与预算

- `session.messages[-40:]` → `[-CHAT_HISTORY_MESSAGE_LIMIT:]` = **80 条**（`:235`、`_trim_history` `:2074`）。
- **裁剪必须明说**（旧实现静默丢弃，用户只看到模型"忘了"前面说过的话）：裁剪发生时在回答**之后**
  追加 `（对话历史超过 80 条，最旧的 N 条已不进入本轮上下文；/new 可开始新会话）`，同时向 stderr
  记一行。提示只进 `assistant.finished.text`（UI），**不进 transcript**——否则下一轮会把机器生成
  的句子当成对话内容再发一遍（绑定提示同理，它是**前缀**，裁剪提示是**后缀**）。
- `chat_context_budget` 默认 8000，可配置：读取顺序 = `preferences.chat_context_budget` 属性
  → 配置文件里该键的**字面量** → 构建器默认值（`_chat_context_budget` `:1438`、
  `_config_preference_literal` `:1460`）。非法值（非数字 / ≤0 / 缺字段）一律回退 8000。
  第 2 条是**临时通道**，原因见 §6.1。

## 4. 离线实测证据（不联网、不读凭据）

脚本 `.pytest_claude/verify_chat_context_a.py`（stub `PRFetcher` + stub provider，每个小节独立
配置目录与仓库缓存），`python .pytest_claude/verify_chat_context_a.py`：

```
[A] 窗口标注 = （显示第 157-317 行，文件共 412 行）      ← 412 行文件，finding 在第 237 行
[A] 覆盖 237 行 = True | 覆盖窗口首行 157 = True | 未从文件头截断（无第 1 行）= True
[B] 头部标注 = （文件共 599 行，此处仅显示前 165 行）    ← 未被 finding 点名的文件
[B] 含首行 = True | 含末行 = False
[C] 截断标注 = （显示第 218-255 行，文件共 412 行；窗口 157-317 行已按预算截断）
[C] finding 行仍在 = True                               ← 长行文件（每行 205 字符）也不丢 finding 行
[D] 落盘消息 = [('user', '第一个问题', ['content','role','timestamp']),
                ('assistant', 'stub', ['content','duration_seconds','role','timestamp'])]
[D] 上线路的消息字段 = ['content', 'role']
[D] 重启后恢复 = [('user', '第一个问题'), ('assistant', 'stub')]
[E] /new 后落盘文件存在 = False | 清空后重启消息数 = 0
[F] 消息数 = 80 | 第 40 轮有提示 = False | 第 41 轮有提示 = True | 在回答之后 = True
[F] 第 41 轮文案尾部 = （对话历史超过 80 条，最旧的 2 条已不进入本轮上下文；/new 可开始新会话）
[G] _chat_context_budget() = 1200 | /context token_budget = 1200 | 非法值回退 = 8000
```

## 5. 测试（`tests/test_jsonl_backend.py` 末尾新增 8 条）

| 用例 | 钉住的行为 |
|---|---|
| `test_chat_injects_a_line_window_around_the_finding_line` | finding 在 237 行 → 窗口覆盖该行、标注 `（显示第 157-317 行，文件共 412 行）`、不含第 1/412 行 |
| `test_chat_head_truncates_a_file_no_finding_names_and_says_so` | 未被点名的文件 → 头部截断 + `（文件共 599 行，此处仅显示前 M 行）`，M 真在 (0, 599) 内 |
| `test_chat_names_the_findings_that_fall_outside_the_window` | 237/900 两条 finding → 取首个窗口 + `另有 finding 在第 900 行`，窗口外内容不注入 |
| `test_chat_keeps_the_finding_line_when_the_window_overflows_the_budget` | 每行 205 字符 → 标注收窄为"窗口已按预算截断"，且 finding 行仍在 |
| `test_chat_session_is_persisted_and_restored_by_a_new_backend` | 落盘字段集 ⊆ {role,content,timestamp,duration_seconds}、无 system prompt；新实例恢复同样消息、绑定不恢复 |
| `test_new_command_clears_the_persisted_session` | `/new` → 文件消失、新实例消息数为 0 |
| `test_chat_history_window_is_80_messages_and_the_trim_is_announced` | 40 轮无提示、第 41 轮提示为**后缀**、消息数 80、落盘 transcript 不含提示 |
| `test_chat_context_budget_can_be_set_in_the_config_file` | 配置文件写 1200 → `_chat_context_budget()` 与 `/context token_budget` 均为 1200；0/-5/"abc"/null/数组 → 8000；配置文件缺失 → 8000 |

数字：`tests/test_jsonl_backend.py` **186 passed**；全量 `python -m pytest -q --no-cov`
→ **1036 passed, 1 skipped in 81.96s**（基线 **1028 passed, 1 skipped**）。

### 变异检查（`.pytest_claude/a1_mutation.py`，用 pytest 插件注入，不改源文件）

| 变异 | 结果 |
|---|---|
| `CHAT_REPO_FINDING_WINDOW_LINES = 0`（窗口退化） | 3 failed（三条窗口用例） |
| `_finding_line_spans → {}`（回到头部截断） | 3 failed |
| `_persist_session → no-op`（不落盘） | 3 failed（含 `/new` 与历史窗口用例） |
| `_fit_lines` 忽略 anchor（按顺序从头切） | 1 failed（超预算那条，其余三条仍绿） |
| `_trim_history` 回到 40 条且不返回丢弃数 | 1 failed（历史窗口用例） |

## 6. 未决与边界

1. **`chat_context_budget` 还没进 `PreferencesConfig`**（`config.py` 不在本任务 write_scope，
   且组 B/Codex 正在并行改它）。因此"可配"目前是：属性优先、配置文件字面量兜底
   （`_config_preference_literal`）。字段进配置层后第 1 条自动接管、兜底通道变成死代码，
   无需迁移。**待办**：由配置层加 `chat_context_budget`（默认 8000）+ 配置助手/CLI 写入口；
   在那之前 `config.save()` 会把该键写掉（`asdict` 只序列化 dataclass 字段），所以**只改文件、
   不走保存流程**才有效——这点必须让用户知道，否则会出现"配了又没了"。写入口留给配置层。
2. **只给首个窗口**：同一文件里相隔很远的第二条 finding 只标注行号（`另有 finding 在第 N 行`），
   不注入其上下文。要"多窗口"就得改注入段的文件内结构（多个代码块 + 各自标注），留给后续增量。
3. **`mention` 与 `finding` 的路径匹配是精确匹配**（规范化后）：用户写裸名 `index.html` 时，
   finding 记的是 `website/index.html`，匹配不上 → 该文件走头部截断。这与现有"裸名按仓库根解析"
   的取舍一致（读不到会如实说明），不额外做 basename 猜测。
4. **`timestamp` 是 `HH:MM`**（沿用 CLI），跨天会话无法区分日期。改成 ISO 需要同时改 CLI 的渲染，
   留给后续统一。
5. **恢复点选在 `session.create`**（不是 `__init__`）：没有会话就没有历史可以挂载，启动即读盘
   只会在内存里放一份无人认领的消息。TUI 启动后第一次 `session.create` 就是"恢复"。
6. **`/new` 不做备份**：CLI 的 `/new` 会先 `save_session` 以便 `/restore`，后端没有 `/restore`
   命令，清空就是清空（脚本 [E] 断言文件消失）。
7. **A4/A5 未做**（本批只 A1-A3）：超预算的"L1→L2→L3 裁剪"提示、状态栏 `上下文 12% · 2.4k/20k`
   仍是下一批；本轮只保证**对话历史**的裁剪有明确告知。
