# Chat 前端第二批：动画/耗时/思考区 + 上下文提示/超额 tips + 命令 UI

> 任务：`.agent-bus/tasks/mimo-chat-frontend-c1.json`
> 契约：v1（后端并行实现；前端先兼容"字段缺失"）
> 写集：`frontend/tui/src/{app.tsx,command-menu.ts,format.ts,protocol.ts,*.test.ts}`、
> `frontend/tui/scripts/{manual-chat-markdown-check.tsx,manual-route-wizard-check.tsx}`、本文件

---

## 1. 契约 v1 消费（protocol.ts）

后端字段可能后落地，解析层一律"缺失 → undefined → 不显示"，绝不崩溃。

| 来源 | 字段 | 解析函数 |
|---|---|---|
| `assistant.finished` | `duration_seconds` | `parseAssistantFinishMeta` |
| `assistant.finished` | `usage.{prompt,completion,total}_tokens` | 同上 |
| `assistant.finished` | `context.{used,budget}_tokens / used_percent / trimmed_messages / compacted` | 同上 |
| `assistant.finished` | `reasoning` | 同上 |
| `assistant.finished` | `warning: "over_budget"` | 同上（未知值丢弃） |
| `assistant.reasoning_delta` | `{text}` | `parseReasoningDelta` |
| 命令返回 | `kind: "think"` | `parseThinkCommandResult` |
| 命令返回 | `kind: "compact"` | `parseCompactCommandResult` |

## 2. C3 · 动画（无新依赖）

- **流式光标**：正文末尾 `▌ → ▍ → 空格` 2-3 帧循环（`cursorFrame(tick)`，180ms tick）。
- **等待首 token**：`spinnerFrame(tick)`（`⠋⠙⠹…`）+「思考中 / Thinking…」。
- **落定效果**：正文完成后进入 transcript（Markdown 重绘）即一次自然高亮；不另起动效依赖。
- **teardown**：`createEffect` 内 `setInterval`，依赖（streaming/active request）变化时 `onCleanup` 清定时器。

## 3. C4 · 耗时展示

- assistant 消息底部 `· 3.2s`（`formatDurationSeconds`：<10s 一位小数，≥10s 取整）。
- 取 `assistant.finished.duration_seconds`；缺失/非有限数 → 整段不渲染。
- 用户消息不显示。

## 4. C5 · 思考区

- `assistant.reasoning_delta` 累积到**独立** `streamingThinking`，绝不拼进正文。
- `assistant.finished.reasoning` 仅作兜底：流已给过则不重复。
- 思考文本挂在 `ChatMessage.thinking`，**不写入** `content`（消息历史正文）。
- UI：暗色底 + 左框线 + 斜体（`ThinkingBlock`）。
- **默认折叠**：落定后折叠、流式期间展开。理由：思考往往很长，落定后正文才是交付物；流式期间用户在等答案，想看到模型在做什么。`Alt+T` 切换最近一条的折叠态。

## 5. A5 · 上下文提示

- chat 头部行右侧：`上下文 12% · 2.4k/20k`（`ContextUsageLine` + `formatContextUsage`）。
- token 用 k 缩写（`formatTokenCount`：2.4k / 20k）。
- 无 `context` 字段（旧后端）→ 整行不渲染。
- `used_percent` 缺失时用 `used/budget` 推算。

## 6. A4 · 超额 tips

- `warning === "over_budget"` 时在回答尾部显示：
  - zh：`上下文接近上限：可用 /compact 压缩，或 /new 重新开始`
  - en：`Context near limit: run /compact to compress, or /new to start over`
- 用 warn 色 `#f3c742`，不用报警红。

## 7. 命令 UI

| 命令 | 行为 |
|---|---|
| `/think off\|low\|high\|max\|auto` | 经 `command.execute`；`kind:"think"` → `formatThinkLevel` 回显档位；`state=unsupported` → `formatThinkUnsupported`（后端 reason 优先） |
| `/compact [指令]` | `kind:"compact"` → `formatCompactSummary`（`12.4k → 3.1k · 保留 8 轮`）；失败 → `formatCompactFailure` 强调「原历史未变」 |
| `/history` | 对话消息列表：行首序号 + 角色 + 截断正文（`formatChatHistoryLines`），与审查列表视觉区分 |
| `/history --runs` | 原审查 Run 列表（HistoryDialog） |
| `/history <id>` | 原后端单条 Run 载入 |

`command-menu.ts` 补齐三条命令描述与参数补全，中英都有（`commandDescription` / `commandArgumentLabel`）。

## 8. 中英文

所有新增文案 zh/en 成对，沿用 `isEn(ui_language)` 机制；术语一致（compact=压缩上下文）。

## 9. 验证数字

| 命令 | 结果 |
|---|---|
| `cd frontend/tui && bun run typecheck` | exit 0 |
| `bun test src/format.test.ts src/protocol.test.ts src/command-menu.test.ts` | **全绿**（本批新增/扩展单测） |
| `bun test src` | 155 pass / 1 fail —— 失败项 `backend.test.ts`「unexpected backend exit…」，根因是并行后端 `src/ai_pr_review/backend/jsonl_server.py` 当前 `SyntaxError: 'continue' not properly in loop`（不在本任务写集，且约束禁止改 Python） |
| `frontend/tui/scripts/manual-chat-markdown-check.tsx` | **ALL PASS**（含 120×30 / 209×51 上下文帧、思考区折叠帧、tips 帧） |
| `frontend/tui/scripts/manual-route-wizard-check.tsx` | **ALL PASS** |

帧文件目录：`.pytest_mimo/ai-pr-review-chat-markdown/`、`.pytest_mimo/ai-pr-review-route-check/`。

关键帧：

- `frame-contract-120x30.txt` / `frame-contract-209x51.txt`：上下文 12% · 2.4k/20k + 思考区 + · 3.2s + tips
- `frame-thinking-collapsed.txt`：思考区折叠、正文可见
- `frame-over-budget-tip-en.txt`：en tips 文案

## 10. 未决

- 后端契约 v1 尚未落地时，`/think` `/compact` 返回无 `kind` 字段 → 走现有 `result.text` 路径，不崩溃。
- 思考区展开目前用 `Alt+T`（OpenTUI 文本节点无 onClick）；若后续渲染层支持鼠标可再挂点击。
- `backend.test.ts` 因并行后端 Python 语法错误而红（`jsonl_server.py: continue not properly in loop`），待后端修复后应恢复全绿。
