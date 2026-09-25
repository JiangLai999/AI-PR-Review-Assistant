# 后端交付报告：审查上下文 · Review-Aware Chat（任务 `claude-review-context`）

**一句话结论**：聊天从"通用对话"变成"能解读本次审查"——新增 `services/review_context.py`
把一次已落库的审查渲染成 **L1 运行摘要 / L2 findings 清单 / L3 重点 finding 全文 / L4 被过滤计数**
的分层纯文本（4 字符 ≈ 1 token，裁剪顺序 L4 → L3 → L2，L1 永不裁剪），`Session` 新增
`current_run_id` 并在 **审查成功落库 / `/history <run_id>` / `/explain <run_id>`** 三处绑定，
`/context` 提供查看/切换/解绑三态，`_chat` 把上下文追加到 system prompt 的语言指令之后并附
诚实约束（只依据上下文、引用必须给「文件:行」+ 严重度、没有的内容说"需要查看源码"）；
构建失败/run 读不到时**降级为普通聊天并记 warning**，对话不中断。

- 任务类型：实现（写入范围：`src/ai_pr_review/services/review_context.py`（新建）、
  `src/ai_pr_review/backend/jsonl_server.py`、`tests/test_jsonl_backend.py`、本文件）
- 验证命令（**已运行**）：
  `New-Item -ItemType Directory -Force -Path .pytest_claude` → `TEMP`/`TMP` 指向它 →
  `python -m pytest tests/test_jsonl_backend.py -q --no-cov` 与 `python -m pytest -q --no-cov`
- 结果：**`tests/test_jsonl_backend.py` 123 passed**（改造前基线 111 passed，本任务 +12 个用例）；
  **全量 826 passed, 1 skipped**（上一轮改动中的全量为 825 passed → 新增最后一个用例后 826）。
- 未做：未读/打印任何凭据；未执行任何 git 操作；未改 `config.py`（`chat_context_budget` 用
  `getattr` 读取、缺省 8000，见 §5）；未改 `frontend/tui`（状态栏/完成提示/i18n 属 §9.3 P6）。

> 并发提示：本仓库多个 agent 共用一个工作树。本任务的改动只落在上表四个文件；若
> `jsonl_server.py` 在本报告之后被其它 agent 改动，请以实际文件为准重新核对
> `_chat_system_prompt` / `_bind_session_run` / `command == "context"` 三处。

## 1. 交付内容（含行号）

| # | 位置 | 改动 |
|---|---|---|
| 1 | `services/review_context.py:33-54` | 常量：`CHARS_PER_TOKEN=4`、`DEFAULT_TOKEN_BUDGET=8000`、`L3_MAX_FINDINGS=3`、各段字符上限、`CONTEXT_RULES`（诚实约束文案）、`TRIM_HINT_COMMAND="/explain"` |
| 2 | `services/review_context.py:57-79` | `RunReader` Protocol（`get_run_summary`/`get_result`/`get_run_metadata`）与 `ReviewContext(text, tokens, budget, trimmed)` |
| 3 | `services/review_context.py:81-160` | `estimate_tokens()`、`build_review_context()`（任务要求的签名）、`build_review_context_meta()`（带 token 估算与裁剪元数据）、候选档选择循环 |
| 4 | `services/review_context.py:162-168` | `wrap_review_context(run_id, context)`：`<review_context run_id="...">` 包裹 + 三条规则 |
| 5 | `services/review_context.py:171-213` | `_budget_plans()`：从"含 L4 的最完整档"到"L1 + 仅 critical/high 的 L2"的候选序列；`_trim_note()`、`_normalize_budget()` |
| 6 | `services/review_context.py:223-352` | 分层渲染 `_render_l1/_render_l2/_render_l3_block/_l3_section/_render_l4` |
| 7 | `services/review_context.py:354-513` | 字段读取与格式化：`_field`（兼容 pydantic 与 dict）、`_sorted_findings`（与 `PostProcessor.sort_by_severity` 同键）、`_location`、`describe_run()` 等 |
| 8 | `jsonl_server.py:398-402` | `Session.current_run_id: str \| None = None` |
| 9 | `jsonl_server.py:1048-1054` | `_session_snapshot()` 新增 `current_run_id`（纯新增字段，TUI 可免二次查询） |
| 10 | `jsonl_server.py:1080-1087` | `_chat_context_budget()`：读 `preferences.chat_context_budget`，非法/缺失退回 8000 |
| 11 | `jsonl_server.py:1089-1132` | `_chat_system_prompt()`（语言指令 + 注入）、`_review_context_for_chat()`（构建 + 降级）、`_warn_context_unavailable()`（stderr warning） |
| 12 | `jsonl_server.py:1134-1146` | `_bind_session_run(session_id, run_id)`：只对已存在的会话生效 |
| 13 | `jsonl_server.py:1148-1225` | `_context_status()` / `_context_text()` / `_context_switch()`：`/context` 的查看、切换、读不到时的如实提示 |
| 14 | `jsonl_server.py:1245` | `_chat` 改用 `self._chat_system_prompt(session)` 作为 `system_prompt`（其余 chat 行为不变） |
| 15 | `jsonl_server.py:1770` | `/help` 新增 `/context [run_id\|off] 查看/切换/解除审查上下文绑定` |
| 16 | `jsonl_server.py:1847-1852` | `/history <run_id>` 成功（`run` 非空）后绑定 |
| 17 | `jsonl_server.py:1880-1885` | `/explain <run_id>` 成功后绑定（`not_found` 时不绑定） |
| 18 | `jsonl_server.py:1886-1908` | 新命令 `/context`：无参查看 / `<run_id>` 切换 / `off` 解绑；无会话时 `not_found`；未知 run 报 `not_found` 且不改动已有绑定 |
| 19 | `jsonl_server.py:2108-2111` | `/review` 的 `else` 分支（成功落库才走到）绑定该 run |
| 20 | `tests/test_jsonl_backend.py:3433-4008` | 新增 12 个用例 + 4 个测试辅助（见 §4） |

## 2. 分层格式（可冻结）

```
[L1 运行摘要]
Run: <run_id>
PR: example/repo #31 · Review workspace contract
作者: octocat
URL: https://github.com/example/repo/pull/31
时间: 2026-09-25 13:44:25
模型: deepseek-flash
耗时 42.3s · 成本 $0.0124
统计: 共 3 条 · critical 1 · high 1 · medium 1 · low 0 · info 0 · 文件: 审查 2 · 跳过 1（共 3）
证据校验: valid 1 · needs_review 1 · invalid 1
摘要: 审查完成，发现 3 个问题

[L2 FINDINGS 清单] 共 3 条（按严重度排序）
1. [critical] src/critical.py:12-20 · 置信度 90% · 证据 needs_review · critical 问题
…

[L3 重点 FINDING 全文] 前 3 条（按严重度排序）
#1 [critical] critical 问题
   位置: src/critical.py:12-20
   置信度 90% · 证据: needs_review
   原因: 问题描述
   建议: 修复建议
   代码:
     if x == 1:
         pass
   疑点: 行号与 diff 不一致

[L4 被过滤 FINDING] 门槛 0.70 · 低于门槛 2 条 · 去重 1 条
```

约定与依据：

- **L2 编号 = L3 的 `#N`**：同一份按严重度排序的清单，用户问"第 2 条"两处指向同一条
  （验收标准 §9.3-1 的"逐字一致"由此可核对）。
- **`文件:行`**：单行 finding 写 `src/medium.py:5`，多行写 `12-20`，与 GitHub 评论里的
  `文件:行` 口径一致（`report_renderer.py:828-830`）。
- **L4 复用 `report_filtered_section()`**：与 GitHub 评论、报告 `run.filtered`、历史详情同源，
  四处不会对同一次 run 给出不同的门槛/计数；**没有 `filtered_findings` 就整段省略**，
  不写"被过滤 0 条"。
- **缺什么少哪行**：没有 `pr_title`/`pr_author`/`validation_summary` 就没有对应行；
  L2 里"共 0 条"只在 `result.findings` 真的为空时出现（实测的 0，不是猜的 0）。
- **裁剪提示**：发生裁剪时在末尾附
  `（注：本上下文超出 8000 token 预算，已按 L4 → L3 → L2 顺序裁剪 …；完整内容可用 /explain <run_id> 查看。）`
  ——让模型知道清单不完整，不会把裁剪当成"审查只有这些"。

### 2.1 预算与裁剪（`token_budget`，默认 8000）

裁剪档位从完整到最简：`[L1,L2,L3(N),L4]` → `[L1,L2,L3(N)]` → `[L1,L2,L3(N-1)]` → … →
`[L1,L2]` → `[L1,L2(仅 critical/high)]`，取第一个装得下的档；**全都装不下时保留最简档**
（L1 + 仅 critical/high 的 L2），而不是输出空上下文。

两处刻意的取舍（都写进了模块 docstring）：

1. **预算只衡量分层内容**：裁剪提示是元信息（约 30 token），不参与档位取舍。若把它计入，
   它会先挤掉 L4 之外的一层，让"L4 先消失"的既定顺序失真。
2. **L1/L2 是地板**：`L1 永不裁剪` + `L2 最少保留 critical/high` 意味着极端预算或
   超大 run 下最终文本可能仍超预算——这是规范要求的行为，不是漏算。
3. **L2 收窄到 critical/high 且结果为空时**（例如全是 medium 的 run），文案是
   `（预算受限：该 Run 没有 critical/high 的 Finding；完整清单可用 /explain 查看）`，
   **不会**写成"该 Run 没有记录任何 Finding"——那会把"有 finding 但被裁"说成"什么都没发现"。

## 3. 会话绑定与注入契约

### 3.1 绑定时机（§9.2 A）

| 触发 | 行为 | 行号 |
|---|---|---|
| `/review` 完成且成功落库 | 绑定该 run | `jsonl_server.py:2108` |
| `/review` 失败 / 取消 / 超时 | **不绑定**（保留上一次的成功绑定） | 同上（异常分支天然绕过） |
| `/history <run_id>` 找到该 run | 绑定 | `jsonl_server.py:1847` |
| `/explain <run_id>` 成功 | 绑定 | `jsonl_server.py:1880` |
| `/history`（列表）/ 未找到的 run | 不绑定，也不清除已有绑定 | 同上 |

绑定只发生在**已存在**的会话上（`_bind_session_run` 对未知 session_id 返回 False）：
没有会话就没有"当前绑定的审查"，凭空造会话只会报出一个用户看不见的状态。

### 3.2 `/context` 三态

| 输入 | 返回（`result`） |
|---|---|
| `/context` | `{text, bound, run_id, token_estimate, token_budget, trimmed, [pr]}`；未绑定时 `bound=False`、`token_estimate=null`，文案给出绑定方法 |
| `/context <run_id>` | 先确认 run 可读（`get_run_summary`），再绑定；未知 run → `not_found`，**不改动**原绑定 |
| `/context off` | 解绑，`bound=False`；无会话时切换/解绑返回 `not_found` |
| 已绑定但 run 读不到 | `bound=True`、`token_estimate=null`，文案："该 Run 当前无法读取（可能已被清理）；对话会降级为普通聊天。"——绑定不会因为 run 被清理就悄悄变回"未绑定" |

### 3.3 注入（§9.2 C）

```
<语言指令>

你正在协助分析一次 PR 审查结果。以下是本次会话绑定的审查上下文：
<review_context run_id="…">
…L1..L4…
</review_context>
规则：
1. 只依据上面的审查上下文回答，不要引入上下文之外的信息；
2. 引用 finding 时必须给出「文件:行」与严重度；
3. 上下文未包含的内容（例如未展示的完整源码）必须明确说明"需要查看源码"，不得臆测。
```

- **只进 system prompt，不写 `session.messages`**：历史不会随每轮对话重复膨胀/重复计费
  （测试断言历史里只有 `user`/`assistant` 轮次且不含 `<review_context`）。
- **降级**：`build_review_context` 抛异常或返回 `None`（run 不存在/已被清理/库读失败）时，
  system prompt 退回只有语言指令，并往 stderr 打一条
  `review context unavailable for run <id> (原因); falling back to plain chat`；
  对话照常成功（测试用 capsys 断言 warning 出现 3 次）。
- 上下文不含图片/工具调用，兼容本地 Ollama 槽（纯文本注入，不依赖 function calling）。

## 4. 测试（`tests/test_jsonl_backend.py:3433-4008`）

| 用例（行号） | 冻结的契约 |
|---|---|
| `test_review_context_renders_l1_to_l4_with_stable_format` (3559) | L1-L4 逐字格式：PR/作者/URL/模型/成本/统计/证据校验；L2 排序与 `文件:行`/置信度/证据状态；L3 编号与 L2 对齐、代码片段缩进、疑点；L4 门槛 0.70 与两条计数 |
| `test_review_context_never_invents_unrecorded_layers` (3604) | 无 `filtered_findings` → 无 L4、无"被过滤"字样；无 finding → L2 明说"没有记录"；无标题/作者/校验 → 无对应行 |
| `test_review_context_budget_drops_l4_then_l3_then_l2_but_keeps_l1` (3626) | 预算 = 全量 − 1 时 `trimmed == ("L4",)` 且 L2/L3 完整；再收紧 L3 减条目（`1 ≤ 块数 < 3`）；1 token 时 `("L4","L3","L2")` 且 L1 逐字等于未裁剪版；裁剪提示点名层并给出 `/explain` |
| `test_review_context_budget_trim_never_claims_an_empty_run` (3979) | 全是 medium 的 run 被收到最简档时，说的是"预算受限…没有 critical/high"，不是"没有记录任何 Finding" |
| `test_review_context_returns_none_when_the_run_or_store_is_unreadable` (3681) | store 抛 `sqlite3.OperationalError` / `result` 缺失 / 未知 run / 空 run_id → 一律 `None`，不抛异常 |
| `test_review_completion_binds_the_session_but_failure_and_cancel_do_not` (3711) | 成功 `/review` 绑定 `run-31`；`RuntimeError` 失败与 `ReviewCancelled` 取消都不绑定 |
| `test_context_command_reports_switches_and_clears_the_binding` (3757) | 三态 + `session.get` 里的 `current_run_id` + 未知 run `not_found` 且不改绑定 + 无会话时切换/解绑 `not_found` |
| `test_history_and_explain_bind_the_run_only_on_success` (3819) | `/history <id>`、`/explain <id>` 绑定；列表、未找到的 run 都不绑定；已有绑定不被列表清掉 |
| `test_chat_injects_the_bound_review_context_into_the_system_prompt` (3849) | 未绑定只有语言指令；绑定后 `<review_context run_id>`、L1/L2/L3/L4 内容、三条诚实约束都在，且**位置在语言指令之后**；历史不含上下文；预算=1 时注入被裁剪且带裁剪提示 |
| `test_chat_degrades_to_plain_chat_when_context_cannot_be_built` (3909) | run 被清理 / 构建器抛异常 / 构建器返回 None 三种情况下对话仍成功、无 `<review_context`、`/context` 如实报"无法读取"；stderr 恰好 3 条 warning |
| `test_chat_context_budget_preference_is_read_defensively` (3967) | 1200 → 1200；0 与非数值 → 8000 |
| `test_help_lists_the_context_command` (4005) | `/help` 文案含 `/context` |

辅助：`_execute_async` / `_new_session_async`（3433/3447，协程版，避免在事件循环里嵌套
`asyncio.run`）、`_context_finding` / `_store_context_run` / `_context_store`（3453-3545）、
`_review_request_for`（3547）。

## 5. 未决 / 留给后续任务

1. **P6 展示层（不在本任务范围）**：状态栏 `CTX #29 (2 findings)`、审查完成后 chat 区
   "已绑定本次审查，可直接提问（例：解释第 2 条）" 提示、`frontend/tui/src/command-menu.ts`
   的 `/context` 词条、中英 i18n。后端已经把 `current_run_id` 放进 `session.create` /
   `session.get` 的返回体、把 `bound/run_id/token_estimate/trimmed` 放进 `/context` 返回体，
   前端不需要再推导任何东西。
2. **`preferences.chat_context_budget` 尚未落进 `config.py`**（本任务写入范围不含 config.py）。
   现在按 `getattr(..., 8000)` 读取，配置助手/`config.snapshot` 要暴露它需要另一个任务；
   在此之前 `/context` 显示的预算是 8000。
3. **超长 run 的地板**：findings 极多时"L1 + 仅 critical/high 的 L2"仍可能超预算
   （规范要求 L1 永不裁剪）。若要在真实大 PR 上收紧，需要先定义"critical/high 也放不下时
   丢哪一条"，属于新的决策点。
4. **提示注入面**：PR 标题/代码片段/finding 文本都是仓库作者可写的内容，会进 system prompt。
   当前缓解是把它包在 `<review_context>` 里 + 规则写在 system 消息中；更强的隔离
   （例如只保留结构化字段、剥离代码片段里的指令）留给安全任务评估。
5. **token 估算口径**是 4 字符 ≈ 1 token（§9.D），不是真实分词器；对中文/代码混排会偏乐观，
   真实成本仍以 provider 计费为准。

## 6. 离线端到端样例（真实 ResultStore + stub provider，不联网）

在临时目录建配置与历史库，落库一次真实 run（critical/security，`needs_review`），
`/context <run_id>` 绑定后发起一轮 chat，打印实际注入的 system prompt：

```
未绑定 /context： 审查上下文：未绑定
完成一次 /review，或用 /context <run_id> 绑定历史 Run，聊天即可解读该次审查结果。

切换后 /context：
已切换审查上下文：83e6e67b-…
审查上下文：已绑定
Run: 83e6e67b-…
PR: example/repo #77 · 修复登录流程
token 估算: 约 183 tokens（预算 8000）
用法：/context <run_id> 切换 · /context off 解绑

实际注入的 system prompt：
请默认使用中文回答，除非用户明确要求使用其他语言。

你正在协助分析一次 PR 审查结果。以下是本次会话绑定的审查上下文：
<review_context run_id="83e6e67b-…">
[L1 运行摘要]
…（PR/作者/URL/模型/耗时/成本/统计/证据校验/摘要）
[L2 FINDINGS 清单] 共 1 条（按严重度排序）
1. [critical] src/auth.py:42-48 · 置信度 93% · 证据 needs_review · 令牌未校验过期时间
[L3 重点 FINDING 全文] 前 1 条（按严重度排序）
#1 [critical] 令牌未校验过期时间
   位置: src/auth.py:42-48
   置信度 93% · 证据: needs_review
   原因: verify 只检查签名，未检查 exp
   建议: 校验 exp 并拒绝过期令牌
   代码:
     claims = jwt.decode(token)
     return claims
   疑点: 行号与 diff 不一致
[L4 被过滤 FINDING] 门槛 0.70 · 低于门槛 2 条 · 去重 0 条
</review_context>
规则：
1. 只依据上面的审查上下文回答，不要引入上下文之外的信息；
2. 引用 finding 时必须给出「文件:行」与严重度；
3. 上下文未包含的内容（例如未展示的完整源码）必须明确说明"需要查看源码"，不得臆测。

会话历史角色： ['user', 'assistant']      ← 上下文没有写进对话历史
```

（`去重 0 条` 是这一次 run 实测记录的 0；没有 `filtered_findings` 的 run 连整段 L4 都不会出现。）
