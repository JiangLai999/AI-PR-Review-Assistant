# Chat 渲染第三批：角标可点击 + 用户消息样式 + 宽屏表格紧凑化（mimo-chat-render-c3）

> 任务：`.agent-bus/tasks/mimo-chat-render-c3.json`
> 前置：`docs/mimo-chat-render-c.md`（C1 表格分档 + C2 代码折叠）、
> `docs/mimo-chat-frontend-c1.md`（C3-C5 流式动画/思考区/耗时/上下文）
> 写集（write_scope）：`frontend/tui/src/app.tsx`、`frontend/tui/src/format.ts`、
> `frontend/tui/src/format.test.ts`、`frontend/tui/scripts/manual-chat-markdown-check.tsx`、本文件

---

## 1. 角标可点击（方案 A）

### 问题

用户实测：折叠角标文案被塞进 markdown 内容字符串（`foldMarkdownCodeBlocks` 在代码围栏
内末尾插入 `▸ 展开（共 M 行）`），无法交互——"不是 Alt+L 快捷键，是角标"。

### 设计决策

采用**方案 A**：把可折叠代码块的角标从 markdown 内容中拆出，作为独立
`<text onMouseDown>` 元素渲染在对应块之后（视觉上仍是块尾角标）。

新增纯函数 `splitFoldableMarkdown(content, isExpanded)`（落在 `format.ts`）返回
「markdown 分段 + 角标位置」序列：

```ts
type MarkdownSegment =
  | { kind: "markdown"; content: string; foldable?: boolean }
  | { kind: "foldBadge"; blockIndex: number; lineCount: number; expanded: boolean }
```

- 可折叠长代码块（>15 行）自成一段 markdown（截断/展开，**不含**角标，`foldable: true`），
  其后紧跟一个 `foldBadge` 段；
- `foldable: true` 让 `renderNode` 把代码块 `marginBottom` 置 0，角标贴住块尾；
- 短块与其它内容留在 markdown 流里，不打断分段。

新组件 `FoldableMarkdownBlock`（`app.tsx` 导出）把分段渲染出来：markdown 段走
`<markdown>`，`foldBadge` 段走独立 `<text onMouseDown>`，文案仍为
`▸ 展开（共 M 行）` / `▾ 收起`（用户指定不变）。

### 交互

| 路径 | 行为 |
|---|---|
| 鼠标点击角标 | `onMouseDown → toggleCodeFoldAt(messageKey, blockIndex)`，直接翻转该块 |
| Alt+L（键盘无障碍） | 保留原 `toggleCodeFold` 游标循环语义，Composer 提示 `Alt+L 代码块` 不变 |

`toggleCodeFoldAt` 与 Alt+L 共用同一状态键 `codeFoldStateKey(messageKey, blockIndex)`。

### 视觉差异说明

角标从"代码围栏内末行"变为"块后独立 text 元素"：位置仍在块尾紧贴最后一行可见代码，
但不再继承代码块底色（`#141414`）。折行观感差异极小，且换来真正可点击的交互面。
未退到方案 B（块后独立角标行）。

---

## 2. 用户消息样式

用户反馈："用户输入和 AI 输出内容无法区分"。给 user 消息明确视觉身份：

| 元素 | 设计 | 说明 |
|---|---|---|
| 左侧色条 | `border=["left"]` + 橙色 `#fb8147` | 竖条，与 assistant 无边框区分 |
| 前缀 | `› `（橙色） | 用户独有；assistant 用 `●` 项目符号 |
| 底色 | `#1a1a1a` 深色 | assistant 正文无底色 |
| 正文色 | `#eeeeee` 亮灰 | 与 assistant 的 `muted` 正文区分 |

zh/en 均成立（`›` 与色条不依赖语言文案）。宽度预算从 `chatContentWidth()-10`
收为 `chatContentWidth()-12`，容纳 `› ` 前缀，不破坏既有布局。

---

## 3. 宽屏表格紧凑化

### 问题

209×51 帧显示宽档 `cellPadding=1` 在每行数据上下插入空行，表格行高膨胀（"太大"）。

### 调查结论

查 `@opentui/core` `TextTable` 实现（`index-ekbq0zm9.js`）：

```js
const cellY = (rowOffsets[rowIdx] ?? 0) + 1 + cellPadding
buffer.drawTextBuffer(cell.textBufferView, (colOffsets[colIdx] ?? 0) + 1 + cellPadding, cellY)
```

`cellPadding` 是**单一数字**，垂直/水平共用，无法只保留水平内边距。

### 决策

宽档 `cellPadding` 从 1 改为 **0**（保留 `widthMode: "full"` 铺满宽度）。
窄档不变（content / 0）。`chatTableOptions()` 注释里记录了该调查与决策依据。

---

## 4. 帧证据

帧目录：`.pytest_mimo/ai-pr-review-chat-markdown/`

### 折叠角标（`frame-code-fold-collapsed.txt` / `frame-code-fold-expanded.txt`）

```
●折叠演示
  // line 01 of thirty
  ...
  // line 15 of thirty
  ▸ 展开（共 30 行）        ← 独立 onMouseDown 元素，贴住块尾
  完。
```

Alt+L 展开后 `line 16-30` 可见 + `▾ 收起`。

### 用户消息（`frame-user-message-120x30.txt` / `frame-user-message-209x51.txt`）

```
│ › 帮我看看这个 PR 的 innerHTML
 ● 已定位两处 innerHTML 注入点。
```

左色条 `│` + 橙色 `›` 前缀 + 深色底；assistant 行是 `●` 无底色。

### 宽档表格（`frame-table-209x51.txt`）

```
┌───┬───┬───┐
│1  │website/index.html:237 │critical│
├───┼───┼───┤
│2  │website/js/main.js:86  │high    │
├───┼───┼───┤
│3  │website/css/main.css:12│medium  │
└───┴───┴───┘
```

数据行相邻：行间距仅夹一条分隔线（`├─┼─┤`），不再出现空行。

---

## 5. 测试与验证命令（TEMP/TMP → `.pytest_mimo`）

### 纯函数用例（`format.test.ts`）

新增 8 个用例覆盖 `codeFoldBadge` / `codeFoldStateKey` / `foldableCodeBlocks` /
`foldMarkdownCodeBlocks` / `splitFoldableMarkdown`（分段结构、展开翻转、短块单段、
前置/连续折叠块）。

### 手动帧断言（`manual-chat-markdown-check.tsx`）

| 组 | 断言数 | 要点 |
|---|---|---|
| A–D 既有 | 14 | conceal / 表格边框 / 宽度不溢出 / 用户 `›` 前缀（+1） |
| E 表格分档 | 12 | 72→content/0、132→full/**0**（c3 改）；tableWidth 断言不变 |
| I 宽档紧凑 | 3 | 数据行 ≥3 条、maxGap≤2、行间无空行 |
| F 代码折叠 | 13 | 折叠态 5 条 + Alt+L 展开 5 条 + 短块 2 条 + 分段短块 1 条 |
| G 角标可点击 | 7 | foldBadge 段状态、badge 文案、onMouseDown 翻转、二次调用收回、块段全文、复位 |
| H 用户消息样式 | 9 | 120×30 ×5 + 209×51 ×4（`›` 前缀、内容、`●` 对比、色条、不溢出） |
| J 契约 v1 | 15 | 上下文/思考/耗时/tips（既有保持） |

### 验证数字

```
cd frontend/tui
bun run typecheck                          # exit 0
bun test src                               # 164 pass / 0 fail（796 expects，13 files）
bun --preload @opentui/solid/preload \
  scripts/manual-chat-markdown-check.tsx   # PASS=75 FAIL=0 → ALL PASS
bun --preload @opentui/solid/preload \
  scripts/manual-route-wizard-check.tsx    # PASS=64 FAIL=0 → ALL PASS
```

关键帧路径：

- `.pytest_mimo/ai-pr-review-chat-markdown/frame-code-fold-collapsed.txt`
- `.pytest_mimo/ai-pr-review-chat-markdown/frame-code-fold-expanded.txt`
- `.pytest_mimo/ai-pr-review-chat-markdown/frame-user-message-120x30.txt`
- `.pytest_mimo/ai-pr-review-chat-markdown/frame-user-message-209x51.txt`
- `.pytest_mimo/ai-pr-review-chat-markdown/frame-table-209x51.txt`

---

## 6. 未决项

1. **角标不继承代码块底色**（方案 A 的视觉差异）：角标从围栏内末行变为块后独立
   text，不再带 `#141414` 底。若用户希望底色一致，可在 `FoldableMarkdownBlock`
   的 badge text 上加 `bg="#141414"`（需验证 OpenTUI text 的 bg setter 行为）。
2. **鼠标命中区**：`onMouseDown` 挂在角标 text 元素上，命中区即角标文案宽度；
   手动脚本对 handler 做行为断言（直接调用 toggle 语义），未走 mockMouse.click
   的坐标命中路径（帧布局下角标 y 坐标随内容动态变化，坐标断言易碎）。
3. **`gap` 在 row box 上未生效**：`●` 与 markdown 之间、分段 markdown 与占位符
   之间的 `gap={1}` 在实测帧里未产生间隔（`●折叠演示` 紧贴）。属 OpenTUI box gap
   的既有表现，与本批次改动无关；badge 的 `paddingLeft=2` 已按实际无-gap 布局对齐。
4. **折叠仅对围栏代码块**：缩进式代码块（4 空格）不在折叠范围（沿用 C2 决策）。
