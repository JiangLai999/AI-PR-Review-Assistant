# 消息指标行 + 思考区可展开 + 状态栏思考强度（mimo-message-metrics）

> 任务：`.agent-bus/tasks/mimo-message-metrics.json`
> 数据侧前置：提交 983f2c7（`assistant.finished.model`）、2a8cc2b 一带
> （`config.snapshot.chat_reasoning_effort`）
> 写集（write_scope）：`frontend/tui/src/app.tsx`、`frontend/tui/src/format.ts`、
> `frontend/tui/src/format.test.ts`、`frontend/tui/src/protocol.ts`、
> `frontend/tui/src/protocol.test.ts`、`frontend/tui/scripts/manual-chat-markdown-check.tsx`、
> `frontend/tui/scripts/manual-route-wizard-check.tsx`、本文件

---

## 1. 状态栏思考强度

### 格式

`THINK max`（en）/ `思考 max`（zh），接在路由段之后：

```
cloud · 就绪 · deepseek-flash · 思考 max · ONLINE · 120×30
```

### 设计决策

- **文案选 `思考 max` / `THINK max` 而不是全中文档位名**：状态栏已有
  `CHAT x · REVIEW y` 的「英文槽位词 + 值」风格，思考强度同构（`THINK` + 契约档位
  原词 `off/low/high/max/auto`）；档位用契约原词，中英宽度一致可预测，不必维护
  第二套档位译名（`formatThinkLevel` 的全称译名继续服务 `/think` 回显）。
- **数据源**：`runtime.chat_reasoning_effort`（`config.snapshot` 顶层标量，
  与 `review_reasoning_effort` 同层级）。前端 `RuntimeSnapshot` 增加同名可选字段。
- **缺字段不显示**：旧后端没有该键时 `formatEffortBadge` 返回空串，状态栏整段省略
  （不显示占位符/`—`）。

### 窄终端降级策略

状态栏是单行 `<text>`，宽度紧张。**阈值 90 列**：`width < 90` 时省略思考强度段，
保路由模型、在线状态、尺寸这类运维刚需。理由：思考强度是「偏好回显」而非
「运行状态」，丢失代价最低；路由/在线状态缺了直接影响判断。降级只砍这一个段，
不动其它段的顺序与文案。

---

## 2. 思考区可展开

### 问题

`ThinkingBlock` 的 header 是纯 `<text>`，`onToggle` prop 从未被调用——用户点不开。

### 设计决策

| 路径 | 行为 |
|---|---|
| 鼠标点击 header | `onMouseDown={props.onToggle}`（与代码块角标 `FoldableMarkdownBlock` 同一模式；OpenTUI 对 `text` 的鼠标按下事件即走该 handler） |
| Alt+T（键盘） | 循环切换：游标 `thinkingCursor` 依次扫过所有带思考的消息，每按一次翻转一条（与 Alt+L 代码块 `toggleCodeFold` 的游标循环同语义） |
| 文案 | 保持 `▾ 思考`（展开）/ `▸ 思考（N 行）`（折叠），N = `text.split("\n").length` |

- 流式期间思考区默认展开（`onToggle` 为空操作，不给用户一个点不动的假控件）；
  落定后默认折叠（原有策略不变）。
- Alt+T 与 Alt+L（代码块）、Alt+W（工作台）不冲突（字母不同）。
- 鼠标悬停指针：OpenTUI 的 `text` 不暴露 cursor 样式切换，悬停指针可用性以实际
  渲染器能力为准；点击命中区域就是 header 文本行。

---

## 3. 消息指标行（DurationLine 升级版）

### 格式

```
· deepseek-flash · 1.6s · 61 字 · 14:32
```

顺序固定：**模型 → 耗时 → 输出长度 → 对话时间**，分隔符统一 ` · `（行首 `·`）。

### 各段取数与缺失策略

| 段 | 主源 | 回退 | 全缺时 |
|---|---|---|---|
| 模型 | `assistant.finished.model`（按轮下发） | `runtime.model` | 省略该段 |
| 耗时 | `durationSeconds`（`duration_seconds`） | 无 | 省略该段 |
| 输出长度 | `usage.completion_tokens` → `300 tok` | `content.length` → zh `61 字` / en `61 chars` | 省略该段 |
| 对话时间 | 消息落定本地 `HH:MM`（frontend 侧写入 `ChatMessage.timestamp`） | 无 | 省略该段 |

- **逐项省略，不显示占位符/0**：`formatMessageMetrics` 只拼实际存在的段；全缺返回
  空串，调用方整行不渲染。
- **token 用 `tok` 缩写**（中英一致）：真实 token 数与字符数是两种量纲，用不同单位
  后缀（`tok` vs `字`/`chars`）区分来源；`tok` 比 `tokens` 省宽度。
- **用户消息也给时间**：理由——回看对话节奏、定位「哪一轮问的」比只看 assistant
  耗时更有用；用户气泡下渲染 `· HH:MM`（muted，`paddingLeft=2`）。
- **时间来源**：`appendMessage` 落定时取本地 `Date` 格式化为 `HH:MM`（非服务端时间，
  与用户体感一致）。

### 实现落点

- `format.ts`：`formatMessageMetrics` / `formatOutputLength` / `formatEffortBadge`（纯函数，单测覆盖）；
- `protocol.ts`：`AssistantFinishMeta.model` + `parseAssistantFinishMeta` 解析 `event.model`；
- `app.tsx`：`ChatMessage` 增 `model/completionTokens/timestamp`；`MessageMetricsLine`
  组件替换 `DurationLine`；`assistant.finished` 事件写入 model/completionTokens；
  `appendMessage` 统一打时间戳。

---

## 4. 中英文案

沿用 `ui_language`：`isEn()` 判定；指标行的 `字`/`chars`、状态栏 `THINK`/`思考`
随语言切换。指标行的模型名、token 数、时间是语言无关数据，不翻译。

---

## 5. 帧路径与验证数字

### 帧路径（TEMP 指向 `.pytest_mimo`）

- `…\.pytest_mimo\ai-pr-review-chat-markdown\frame-contract-120x30.txt`
- `…\.pytest_mimo\ai-pr-review-chat-markdown\frame-contract-209x51.txt`
- `…\.pytest_mimo\ai-pr-review-chat-markdown\frame-thinking-header-collapsed.txt`
- `…\.pytest_mimo\ai-pr-review-chat-markdown\frame-thinking-header-expanded.txt`
- `…\.pytest_mimo\ai-pr-review-chat-markdown\frame-thinking-alt-t-collapsed.txt`
- `…\.pytest_mimo\ai-pr-review-route-check\frame-status-*.txt`（思考强度段 4 例 + 窄终端降级）

### 验证数字（2026-09-26）

| 命令 | 结果 |
|---|---|
| `cd frontend/tui && bun run typecheck` | exit 0 |
| `bun test src` | **200 pass / 0 fail**（956 expect） |
| `scripts/manual-chat-markdown-check.tsx` | **PASS 87 / FAIL 0**（ALL PASS） |
| `scripts/manual-route-wizard-check.tsx` | **PASS 140 / FAIL 0**（ALL PASS） |

### 新增断言覆盖

- 单测（`format.test.ts`）：指标行全字段 / 缺 model / 缺 usage 回退 chars / 缺时间 /
  token 优先于字符 / 非有限数丢弃 / 全缺空串；`formatEffortBadge` 缺字段空串；
- 单测（`protocol.test.ts`）：`finished.model` 解析 + 旧后端缺失；
- manual（chat）：120×30 与 209×51 完整指标行 `· deepseek-flash · 1.6s · 61 字 · 14:32`；
  header `onMouseDown` 行为断言（false→true 展开）；Alt+T 切换与再切回；
  折叠态 `▸ 思考（3 行）` 行数标注；用户消息时间 `· 14:28`；
- manual（route）：`思考 max`（zh）/ `THINK high`（en）/ 缺字段不显示 / 80 列窄终端省略。
