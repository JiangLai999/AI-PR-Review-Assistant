# Chat 渲染组 C：表格分档 + 代码块折叠（mimo-chat-render-c）

> 任务：`.agent-bus/tasks/mimo-chat-render-c.json`（C1-C2）
> 方案来源：`docs/chat-experience-plan.md` 组 C（用户已确认：15 行阈值 + 小角标展开）
> 写集（write_scope）：`frontend/tui/src/app.tsx`、`frontend/tui/scripts/manual-chat-markdown-check.tsx`、本文件
>
> 注：prompt 正文写的文档名 mimo-chat-render.md（无 -c 后缀）在仓库中从未创建，实际落点是
> `docs/mimo-chat-render-c.md`（即 write_scope 指定名）。按约束"只写 write_scope"，文档落在本文件。

---

## 1. C1 · 表格按宽度分档

### 分档规则

分档宽度取 **markdown 实际渲染宽度** `Math.max(24, chatContentWidth() - 6)`
（由现有的 `useTerminalDimensions()` → `chatContentWidth()` 派生，不新增尺寸来源）：

| 档位 | 条件 | tableOptions |
|---|---|---|
| 窄 | 渲染宽 **< 100 列** | `{ widthMode: "content", cellPadding: 0, wrapMode: "word", borders: true }` |
| 宽 | 渲染宽 **≥ 100 列** | `{ widthMode: "full", cellPadding: 1, wrapMode: "word", borders: true }` |

- 窄档贴内容宽度（content），去掉 cell 内边距，避免小表在窄列里被撑松/挤字；
- 宽档铺满可用宽度（full），保留 1 格内边距，避免宽终端上 3 列小表右侧大片留白。

实现：`frontend/tui/src/app.tsx` 导出 `chatTableOptions(renderWidth)`、
`CHAT_TABLE_WIDE_BREAKPOINT = 100`；App 内 `chatMarkdownTableOptions()` 用
`chatContentWidth()` 派生渲染宽后代入，历史消息 markdown 与流式 markdown 两处
`tableOptions` 都改走该函数（替换原先写死的 full/padding 1）。

### 验证数字（同一张 3 列表格）

| 尺寸 | 渲染宽 | 档位 | 实测 tableWidth（去尾随空格后的边框行宽） | 结论 |
|---|---|---|---|---|
| 120×30 | 72 | 窄（content / padding 0） | **36** | 不溢出（36 ≤ 72），贴内容不铺满 |
| 209×51 | 132 | 宽（full / padding 1） | **132** | 不溢出（132 ≤ 132），铺满无大片留白 |

两档的 `wrapMode: "word" / borders: true` 不变。

---

## 2. C2 · 长代码块折叠

### 折叠规则

- 阈值：**> 15 行** 的围栏代码块（`CODE_FOLD_LINE_THRESHOLD = 15`）。
- 默认只渲染**前 15 行**，块内末尾给小角标 **`▸ 展开（共 M 行）`**（M = 块体总行数）。
- 展开后渲染全文，块内末尾改给 **`▾ 收起`**。
- 短块（≤ 15 行）行为不变（内容原样，无角标）。
- 实现：`foldMarkdownCodeBlocks(content, isExpanded)` 在传给 `<markdown content>` 前
  按展开状态重写块体；`foldableCodeBlocks(content)` 枚举可折叠块。

### 折叠交互

- **快捷键 `Alt+L`**（与 `Alt+E` 解释、`Ctrl+L` 历史不冲突；方案 §5.5 推荐键位）。
- 角标可操作语义：`Alt+L` 切换**当前**代码块的折叠态（收起 ⇄ 展开），切换后跳到
  消息内下一个可折叠块（循环）。有可折叠块时 Composer 底栏显示 `Alt+L 代码块` 提示。
- **状态键 = 消息 id + 代码块序号**（`codeFoldStateKey(messageId, blockIndex)` →
  `"msg-3#0"` 这类字符串），由 TUI 侧 `createSignal<Record<string, boolean>>` 维护；
  切换后该消息以新的折叠内容重渲染（Solid 响应式，`content` 随信号变化）。
- 消息 id：`appendMessage` 为每条消息分配 `msg-N`（`ChatMessage.id`），流式内容用
  固定键 `streaming`。

实现位置（`frontend/tui/src/app.tsx`）：

- 折叠渲染导出：`CODE_FOLD_LINE_THRESHOLD`、`codeFoldBadge`、`codeFoldStateKey`、
  `foldableCodeBlocks`、`foldMarkdownCodeBlocks`
- App 状态/切换：`codeFoldExpanded`、`codeFoldCursor`、`toggleCodeFold`
- Composer 绑定：`onToggleCodeFold` + `key.meta === "l"` 分支 + 底栏提示 `codeFoldActive`

### 渲染证据（30 行代码块）

折叠态（`frame-code-fold-collapsed.txt`）：

```
// line 01 of thirty
...
// line 15 of thirty
▸ 展开（共 30 行）
```

展开态（`Alt+L` 后，`frame-code-fold-expanded.txt`）：

```
// line 01 of thirty
...
// line 30 of thirty
▾ 收起
```

---

## 3. 测试与证据

扩展 `frontend/tui/scripts/manual-chat-markdown-check.tsx`（既有断言全保留）：

| 组 | 断言数 | 要点 |
|---|---|---|
| 既有 A–D | 13 | conceal/表格边框/宽度不溢出（全绿保持） |
| C1 分档 | 12 | 72→content/0、132→full/1；120×30 tableWidth=36 不溢出不铺满；209×51 tableWidth=132 铺满不溢出 |
| C2 折叠 | 11 | 30 行默认折叠：line01/15 可见、line16/30 不出现、`▸ 展开（共 30 行）`；Alt+L 展开后 line16/30 可见、`▾ 收起`；短块不变 |

### 验证命令与真实数字（TEMP/TMP → `.pytest_mimo`）

```
cd frontend/tui
bun run typecheck                          # exit 0
bun test src                               # 137 pass / 0 fail（665 expects，13 files）
bun --preload @opentui/solid/preload \
  scripts/manual-chat-markdown-check.tsx   # PASS=36 FAIL=0 → ALL PASS
bun --preload @opentui/solid/preload \
  scripts/manual-route-wizard-check.tsx    # PASS=64 FAIL=0 → ALL PASS
```

帧证据目录：`.pytest_mimo/ai-pr-review-chat-markdown/`（`frame-chat-markdown.txt`、
`frame-table-120x30.txt`、`frame-table-209x51.txt`、`frame-code-fold-collapsed.txt`、
`frame-code-fold-expanded.txt`）。

---

## 4. 未决项

1. **文档路径分歧**：prompt 正文写的文档名 mimo-chat-render.md（无 -c 后缀）从未创建，
   write_scope 写的是 `docs/mimo-chat-render-c.md`（即本文件）；按约束只写后者。若调度方要合并到
   mimo-chat-render.md 需另开任务（本任务不得越写集）。
2. **角标交互粒度**：当前 `Alt+L` 是"切换当前块 + 游标后移"的循环语义；若用户希望
   逐块聚焦（Tab 移动焦点 + Enter 切换）或首块常驻，可后续加 Tab 游标而不改状态键。
3. **折叠仅对围栏代码块**：缩进式代码块（4 空格）不在折叠范围；方案未要求，暂不处理。
4. **C3–C6**（动画 / 耗时 / 思考分离 / 思考强度）属组 C 后续批次，不在本任务范围。
