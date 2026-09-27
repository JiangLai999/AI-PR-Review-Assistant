/**
 * Chat Markdown 渲染的文本证据脚本（任务 mimo-chat-render-c / -c3）。
 *
 * 背景（用户实测反馈）：TUI 之前把 assistant 回复当**纯文本**渲染，于是
 * `##`、`**`、`| 表格 |` 全部原样显示，很影响观感。现在改用 OpenTUI 自带的
 * `<markdown>`（mimo-code 用的也是它），本脚本渲染一段真实形态的回复，断言：
 *
 *   A. `**粗体**` 与 `` `代码` `` 的标记符被隐藏（conceal 生效）；
 *   B. `## 标题` 不再出现裸 `##`；
 *   C. Markdown 表格被渲染成表格（出现边框字符），且不出现裸管道分隔行
 *      `|---|---|`；
 *   D. 渲染宽度受限于给定 width（120x30 下不溢出）。
 *
 * 追加（C1/C2，docs/mimo-chat-render-c.md）：
 *
 *   E. 【C1 表格分档】同一张 3 列表格在 120x30（窄档 <100 列 →
 *      content/cellPadding 0）与 209x51（宽档 ≥100 列 → full/cellPadding 0，
 *      见 mimo-chat-render-c3 紧凑化决策）都不溢出、也不过留白；
 *   F. 【C2 代码折叠】30 行代码块默认只渲染前 15 行 + `▸ 展开（共 30 行）`，
 *      不出现第 16 行内容；Alt+L 切开后全文可见并给出 `▾ 收起`；短块不变。
 *
 * 追加（C3 批次，docs/mimo-chat-render-c3.md）：
 *
 *   G. 【角标可点击】折叠角标是独立 `<text onMouseDown>` 元素（方案 A）；
 *      对 onMouseDown 处理函数做行为断言：调用后折叠态翻转、帧内容切换；
 *   H. 【用户消息样式】120×30 与 209×51 帧都出现 `›` 前缀 + 左色条 + 深色底；
 *   I. 【宽档表格紧凑】209×51 帧数据行相邻、行间无空行。
 *
 * 追加（mimo-message-metrics，docs/mimo-message-metrics.md）：
 *
 *   K. 【消息指标行】120×30 与 209×51 帧出现完整指标行
 *      `· deepseek-flash · 1.6s · 61 字 · 14:32`（MessageMetricsLine）；
 *   L. 【思考区可展开】header 绑 onMouseDown：行为断言点击展开/折叠；
 *      Alt+T 键盘循环切换；折叠态 `▸ 思考（N 行）` 行数标注正确。
 *
 * 追加（mimo-sessions-ui，docs/mimo-sessions-ui.md）：
 *
 *   N. 【会话 UI】会话弹窗 120×30 / 209×51、重命名态、空态、
 *      状态栏会话名（≥100 列显示 / <100 列隐藏）、pressure=high 黄段与提示。
 *
 * 运行（在 frontend/tui 下）：
 *
 *   bun --preload @opentui/solid/preload scripts/manual-chat-markdown-check.tsx
 */
import { testRender, useKeyboard } from "@opentui/solid"
import { createSignal } from "solid-js"
import { mkdirSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import {
  chatMarkdownStyle,
  chatTableOptions,
  codeFoldBadge,
  codeFoldStateKey,
  ContextUsageLine,
  FoldableMarkdownBlock,
  foldMarkdownCodeBlocks,
  MessageMetricsLine,
  OverBudgetTip,
  RuntimeStatusLine,
  SessionsDialog,
  splitFoldableMarkdown,
  ThinkingBlock,
} from "../src/app"

const outDir = join(tmpdir(), "ai-pr-review-chat-markdown")
mkdirSync(outDir, { recursive: true })

const failures: string[] = []
function check(condition: boolean, label: string, detail = "") {
  if (condition) {
    console.log(`  PASS  ${label}`)
  } else {
    failures.push(label)
    console.log(`  FAIL  ${label}${detail ? ` :: ${detail}` : ""}`)
  }
}

function dumpFrame(frame: string, label: string) {
  writeFileSync(join(outDir, `frame-${label}.txt`), frame, "utf8")
}

/** Settle helper: layout needs several frames (tables land in batches). */
async function settle(view: { renderOnce: () => Promise<void> }, rounds = 20) {
  for (let i = 0; i < rounds; i += 1) {
    await view.renderOnce()
    await new Promise((resolve) => setTimeout(resolve, 10))
  }
}

/** Settle until `pattern` shows up in the frame (markdown blocks land in batches). */
async function settleUntil(
  view: { renderOnce: () => Promise<void>; captureCharFrame: () => string },
  pattern: RegExp,
  rounds = 30,
) {
  for (let i = 0; i < rounds; i += 1) {
    await view.renderOnce()
    if (pattern.test(view.captureCharFrame())) return
    await new Promise((resolve) => setTimeout(resolve, 10))
  }
}

const SAMPLE = [
  "## 审查结果概览",
  "",
  "本次共 **4 条** findings，其中 `website/index.html` 有 2 条 critical。",
  "",
  "| # | 位置 | 严重度 |",
  "|---|---|---|",
  "| 1 | website/index.html:237 | critical |",
  "| 2 | website/js/main.js:86 | high |",
  "",
  "建议这样改：",
  "",
  "```js",
  "docsPanelBody.textContent = tab.html;",
  "```",
  "",
  "- 建议先修 `innerHTML` 那两处",
  "- 再核对占位符",
  "",
  "> 证据校验：valid 9 · needs_review 1",
].join("\n")

const WIDTH = 78

const view = await testRender(
  () => (
    <box width={WIDTH} flexDirection="column">
      {/* 用户输入：`›` 前缀 + 底色 + 橙色左框线（与 assistant 的纯文本回复区分） */}
      <box
        flexDirection="row"
        marginBottom={1}
        paddingLeft={1}
        paddingRight={1}
        backgroundColor="#1a1a1a"
        border={["left"]}
        borderColor="#fb8147"
      >
        <text fg="#fb8147">› </text>
        <text width={WIDTH - 12} fg="#eeeeee">
          对应仓库代码
        </text>
      </box>
      <markdown
        width={WIDTH}
        content={SAMPLE}
        syntaxStyle={chatMarkdownStyle()}
        fg="#808080"
        conceal={true}
        renderNode={(token, ctx) => {
          if (token.type !== "code") return undefined
          const code = ctx.defaultRender()
          if (code) {
            const styled = code as { bg?: string; paddingLeft?: number; marginBottom?: number }
            styled.bg = "#141414"
            styled.paddingLeft = 1
            styled.marginBottom = 1
          }
          return code
        }}
        tableOptions={chatTableOptions(WIDTH)}
      />
    </box>
  ),
  { width: WIDTH, height: 30 },
)

// 布局需要多帧才能稳定（表格与后面的块会分批落地）——沿用其它 manual 脚本的
// settle 模式：单次 renderOnce 只能拿到第一帧。等标题出现再抓帧，避免
// 首帧只画出部分 markdown 块导致断言抖动。
await settleUntil(view, /审查结果概览/)
await settle(view)
const frame = view.captureCharFrame()
dumpFrame(frame, "chat-markdown")

console.log("---- rendered frame ----")
console.log(frame)
console.log("------------------------")

// captureCharFrame 会带一个尾随换行，别把它算成一行。
const lines = frame.replace(/\n+$/, "").split("\n")

check(!frame.includes("**"), "粗体标记 `**` 被隐藏")
check(!frame.includes("`"), "行内代码反引号被隐藏")
check(!/\|\s*-{3,}/.test(frame), "表格分隔行 `|---|` 不再原样显示")
check(!/^##\s/m.test(frame), "标题不再带裸 `##`")
check(frame.includes("审查结果概览"), "标题文字仍然可见")
check(frame.includes("4 条"), "粗体文字内容仍然可见")
check(frame.includes("website/index.html"), "表格单元格内容仍然可见")
check(/[│┌┐└┘├┤┬┴┼─]/.test(frame), "表格渲染出边框字符")
check(frame.includes("│") && frame.includes("对应仓库代码"), "用户输入框有左框线且内容可见")
check(frame.includes("›") && frame.includes("对应仓库代码"), "用户输入框有 `›` 前缀且内容可见")
check(frame.includes("textContent = tab.html"), "代码块内容可见")
check(!frame.includes("```"), "代码块围栏 ``` 被隐藏")
check(
  lines.length <= 30,
  `渲染行数不超过 30（实际 ${lines.length}）`,
)
const overflow = lines.filter((line) => [...line].length > WIDTH + 2)
check(overflow.length === 0, `无行宽溢出（宽度 ${WIDTH}）`, overflow[0]?.slice(0, 60) ?? "")

// ---------------------------------------------------------------------
// E. 【C1 表格分档】120x30 窄档 vs 209x51 宽档
//
// markdown 渲染宽度按 app.tsx 的 `Math.max(24, chatContentWidth()-6)` 推导：
// 120x30 两栏工作台 → chatContentWidth 78 → 渲染宽 72（<100，窄档）；
// 209x51 两栏工作台 → chatContentWidth 138 → 渲染宽 132（≥100，宽档）。
// ---------------------------------------------------------------------

const TABLE3 = [
  "| # | 位置 | 严重度 |",
  "|---|---|---|",
  "| 1 | website/index.html:237 | critical |",
  "| 2 | website/js/main.js:86 | high |",
  "| 3 | website/css/main.css:12 | medium |",
].join("\n")

const tierOptions = chatTableOptions(72)
check(
  tierOptions.widthMode === "content" && tierOptions.cellPadding === 0,
  `窄档（72 列）→ content + cellPadding 0（实际 ${tierOptions.widthMode}/${tierOptions.cellPadding}）`,
)
const wideOptions = chatTableOptions(132)
check(
  wideOptions.widthMode === "full" && wideOptions.cellPadding === 0,
  `宽档（132 列）→ full + cellPadding 0（实际 ${wideOptions.widthMode}/${wideOptions.cellPadding}）`,
)

async function renderTableFrame(label: string, width: number, height: number) {
  const tableOptions = chatTableOptions(width)
  const tableView = await testRender(
    () => (
      <box width={width} flexDirection="column">
        <markdown
          width={width}
          content={TABLE3}
          syntaxStyle={chatMarkdownStyle()}
          fg="#808080"
          conceal={true}
          tableOptions={tableOptions}
        />
      </box>
    ),
    { width, height },
  )
  await settle(tableView)
  const captured = tableView.captureCharFrame()
  dumpFrame(captured, label)
  const capturedLines = captured.replace(/\n+$/, "").split("\n")
  // 表格实体宽度：含边框字符的最长行（captureCharFrame 会把行垫满帧宽，
  // 量宽度前先去掉尾随空格，否则量到的是帧宽而不是表格宽）。
  const tableWidth = capturedLines.reduce((max, line) => {
    const trimmed = line.replace(/\s+$/, "")
    return /[│┌┐└┘├┤┬┴┼─]/.test(trimmed) ? Math.max(max, [...trimmed].length) : max
  }, 0)
  return { frame: captured, lines: capturedLines, tableWidth, tableOptions }
}

const narrow = await renderTableFrame("table-120x30", 72, 30)
console.log(`\n---- 120x30 窄档 table frame (tableWidth=${narrow.tableWidth}) ----`)
console.log(narrow.frame)
check(
  narrow.lines.every((line) => [...line].length <= 72 + 2),
  "120x30：表格不溢出渲染宽度 72",
)
check(/[│┌┐└┘]/.test(narrow.frame), "120x30：表格渲染出边框字符")
check(narrow.frame.includes("website/js/main.js:86"), "120x30：单元格内容可见")
check(
  narrow.tableWidth > 0 && narrow.tableWidth < 72,
  `120x30：窄档贴内容不铺满（tableWidth=${narrow.tableWidth} < 72）`,
)
check(narrow.tableOptions.cellPadding === 0, "120x30：cellPadding 0（窄档不挤）")

const wide = await renderTableFrame("table-209x51", 132, 51)
console.log(`\n---- 209x51 宽档 table frame (tableWidth=${wide.tableWidth}) ----`)
console.log(wide.frame)
check(
  wide.lines.every((line) => [...line].length <= 132 + 2),
  "209x51：表格不溢出渲染宽度 132",
)
check(/[│┌┐└┘]/.test(wide.frame), "209x51：表格渲染出边框字符")
check(wide.frame.includes("website/css/main.css:12"), "209x51：单元格内容可见")
check(
  wide.tableWidth >= 130,
  `209x51：宽档铺满渲染宽度（tableWidth=${wide.tableWidth} ≈ 132）`,
)
check(wide.tableOptions.cellPadding === 0, "209x51：cellPadding 0（宽档不膨胀行高）")
// I. 【宽档表格紧凑】数据行相邻：找出数据行（含 website/ 的行），断言它们在
// 帧里连续出现（之间没有空行）。cellPadding 1 时每行上下各插一行空行导致
// 行高膨胀；cellPadding 0 后数据行应紧贴。
{
  const dataRowIndexes = wide.lines
    .map((line, index) => (line.includes("website/") ? index : -1))
    .filter((index) => index >= 0)
  check(dataRowIndexes.length >= 3, `209x51：找到 ${dataRowIndexes.length} 条数据行`)
  const gaps: number[] = []
  for (let k = 1; k < dataRowIndexes.length; k += 1) {
    gaps.push(dataRowIndexes[k] - dataRowIndexes[k - 1])
  }
  // 相邻数据行之间不应隔出空行（间距 1 = 紧贴，间距 2 = 中间夹一行边框/空行）。
  // 允许 ≤2：一条分隔线行（├─┼─┤）可以夹在两数据行之间；>2 说明有空行膨胀。
  const maxGap = gaps.length > 0 ? Math.max(...gaps) : 0
  check(
    dataRowIndexes.length < 2 || maxGap <= 2,
    `209x51：数据行相邻无空行（maxGap=${maxGap} ≤ 2）`,
    gaps.join(","),
  )
  const blankBetweenData = dataRowIndexes.some((rowIndex, k) => {
    if (k === 0) return false
    for (let r = dataRowIndexes[k - 1] + 1; r < rowIndex; r += 1) {
      if (wide.lines[r].trim() === "") return true
    }
    return false
  })
  check(!blankBetweenData, "209x51：数据行之间不出现空行")
}

// ---------------------------------------------------------------------
// F. 【C2 代码折叠】30 行代码块：默认折叠 → Alt+L / 鼠标点击角标展开
//    C3 批次改用 FoldableMarkdownBlock（角标是独立 onMouseDown 元素）。
// ---------------------------------------------------------------------

const CODE_LINES = Array.from(
  { length: 30 },
  (_, index) => `// line ${String(index + 1).padStart(2, "0")} of thirty`,
)
const LONG_CODE = ["```js", ...CODE_LINES, "```"].join("\n")
const FOLD_SAMPLE = ["## 折叠演示", "", LONG_CODE, "", "完。"].join("\n")

// 与 app.tsx 相同的状态键与折叠渲染：消息 id + 代码块序号。
const messageId = "manual-msg-1"
const [codeFoldExpanded, setCodeFoldExpanded] = createSignal<Record<string, boolean>>({})
const isExpanded = (blockIndex: number) =>
  codeFoldExpanded()[codeFoldStateKey(messageId, blockIndex)] === true
const toggleFold = () => {
  const key = codeFoldStateKey(messageId, 0)
  setCodeFoldExpanded((prev) => ({ ...prev, [key]: prev[key] !== true }))
}
/** 与 app.tsx 的 toggleCodeFoldAt 同语义：直接切换指定块。 */
const toggleFoldAt = (_messageKey: string, blockIndex: number) => {
  const key = codeFoldStateKey(messageId, blockIndex)
  setCodeFoldExpanded((prev) => ({ ...prev, [key]: prev[key] !== true }))
}

const FOLD_WIDTH = 72

/** Alt+L 与 app.tsx Composer 的绑定一致；角标 onMouseDown 走 toggleFoldAt。 */
function FoldHarness() {
  useKeyboard((key: { name: string; meta?: boolean }) => {
    if (key.meta === true && key.name === "l") {
      toggleFold()
      key.stopPropagation?.()
    }
  })
  return (
    <box width={FOLD_WIDTH} flexDirection="column">
      <FoldableMarkdownBlock
        content={FOLD_SAMPLE}
        messageKey={messageId}
        isExpanded={isExpanded}
        onToggleAt={toggleFoldAt}
        width={FOLD_WIDTH}
        syntaxStyle={chatMarkdownStyle()}
        fg="#808080"
        bulletFg="#eeeeee"
        tableOptions={chatTableOptions(FOLD_WIDTH)}
      />
    </box>
  )
}

const foldView = await testRender(
  () => <FoldHarness />,
  { width: FOLD_WIDTH, height: 48, kittyKeyboard: true },
)
await settle(foldView)

const foldedFrame = foldView.captureCharFrame()
dumpFrame(foldedFrame, "code-fold-collapsed")
console.log("\n---- code block folded (30 lines) ----")
console.log(foldedFrame)

check(foldedFrame.includes("line 01 of thirty"), "折叠态：第 1 行可见")
check(foldedFrame.includes("line 15 of thirty"), "折叠态：第 15 行可见")
check(!foldedFrame.includes("line 16 of thirty"), "折叠态：第 16 行不出现")
check(!foldedFrame.includes("line 30 of thirty"), "折叠态：第 30 行不出现")
check(foldedFrame.includes("▸ 展开（共 30 行）"), "折叠态：角标文案 `▸ 展开（共 30 行）`")

// G. 【角标可点击】onMouseDown 处理函数行为断言：直接调用 handler（OpenTUI
// 在鼠标按下时调用的就是它），折叠态应翻转、帧内容应切换。
const segmentsBeforeClick = splitFoldableMarkdown(FOLD_SAMPLE, isExpanded)
const badgeBefore = segmentsBeforeClick.find((s) => s.kind === "foldBadge")
check(
  badgeBefore !== undefined && badgeBefore.kind === "foldBadge" && badgeBefore.expanded === false,
  "角标点击前：foldBadge 段处于折叠态",
)
check(
  badgeBefore !== undefined && badgeBefore.kind === "foldBadge" && codeFoldBadge(badgeBefore.lineCount, badgeBefore.expanded) === "▸ 展开（共 30 行）",
  "角标点击前：badge 文案为 `▸ 展开（共 30 行）`",
)

// 行为断言：调用 onMouseDown 绑定的 toggleFoldAt（messageKey, blockIndex）。
const beforeClickState = isExpanded(0)
toggleFoldAt(messageId, 0)
const afterClickState = isExpanded(0)
check(
  beforeClickState === false && afterClickState === true,
  `onMouseDown 处理函数：折叠态翻转（${beforeClickState} → ${afterClickState}）`,
)
// 翻转后分段结果里 foldBadge 应为 expanded，且块段含全文。
const segmentsAfterClick = splitFoldableMarkdown(FOLD_SAMPLE, isExpanded)
const badgeAfter = segmentsAfterClick.find((s) => s.kind === "foldBadge")
check(
  badgeAfter !== undefined && badgeAfter.kind === "foldBadge" && badgeAfter.expanded === true,
  "onMouseDown 处理函数：foldBadge 段变为展开态",
)
const blockAfter = segmentsAfterClick.find((s) => s.kind === "markdown" && s.foldable)
check(
  blockAfter !== undefined && blockAfter.kind === "markdown" && blockAfter.content.includes("line 30 of thirty"),
  "onMouseDown 处理函数：块段渲染全文（line 30 可见）",
)

// 再次调用应回到折叠态（toggle 语义）。
toggleFoldAt(messageId, 0)
check(isExpanded(0) === false, "onMouseDown 处理函数：再次调用回到折叠态")
// 显式复位，保证后续 Alt+L 断言从确定的折叠态出发。
setCodeFoldExpanded({})
await settle(foldView)
const refoldedFrame = foldView.captureCharFrame()
check(refoldedFrame.includes("▸ 展开（共 30 行）"), "行为断言后复位：角标回到折叠态")

// Alt+L 展开（键盘无障碍路径保留）。
foldView.mockInput.pressKey("l", { meta: true })
await settle(foldView)
const expandedFrame = foldView.captureCharFrame()
dumpFrame(expandedFrame, "code-fold-expanded")
console.log("\n---- code block expanded via Alt+L ----")
console.log(expandedFrame)

check(expandedFrame.includes("line 01 of thirty"), "展开态：第 1 行可见")
check(expandedFrame.includes("line 16 of thirty"), "展开态：第 16 行可见")
check(expandedFrame.includes("line 30 of thirty"), "展开态：第 30 行（全文末行）可见")
check(expandedFrame.includes("▾ 收起"), "展开态：角标文案 `▾ 收起`")
check(!expandedFrame.includes("▸ 展开（共 30 行）"), "展开态：折叠角标消失")

// 短块（≤15 行）不受折叠影响。
const SHORT_CODE = ["```js", "docsPanelBody.textContent = tab.html;", "```"].join("\n")
const shortFolded = foldMarkdownCodeBlocks(SHORT_CODE, () => false)
check(
  shortFolded === SHORT_CODE,
  "短块（1 行）折叠前后内容不变",
  shortFolded.slice(0, 80),
)
const shortSegments = splitFoldableMarkdown(SHORT_CODE, () => false)
check(
  shortSegments.length === 1 && shortSegments[0].kind === "markdown",
  "短块：splitFoldableMarkdown 不产生 foldBadge 段",
)

// ---------------------------------------------------------------------
// H. 【用户消息样式】120×30 与 209×51 帧：`›` 前缀 + 左色条 + 深色底
// ---------------------------------------------------------------------

async function renderUserMessageFrame(label: string, width: number, height: number) {
  const view = await testRender(
    () => (
      <box width={width} height={height} flexDirection="column" paddingLeft={1}>
        <box flexDirection="column" marginBottom={1}>
          <box
            flexDirection="row"
            paddingLeft={1}
            paddingRight={1}
            backgroundColor="#1a1a1a"
            border={["left"]}
            borderColor="#fb8147"
          >
            <text fg="#fb8147">› </text>
            <text width={Math.max(24, width - 12)} fg="#eeeeee">
              帮我看看这个 PR 的 innerHTML
            </text>
          </box>
          <box flexDirection="row" paddingLeft={2}>
            <text fg="#808080">· 14:28</text>
          </box>
        </box>
        <box flexDirection="row" gap={1}>
          <text fg="#eeeeee">●</text>
          <text fg="#808080">已定位两处 innerHTML 注入点。</text>
        </box>
      </box>
    ),
    { width, height },
  )
  await settle(view)
  const frame = view.captureCharFrame()
  dumpFrame(frame, label)
  return { frame, lines: frame.replace(/\n+$/, "").split("\n") }
}

const user120 = await renderUserMessageFrame("user-message-120x30", 120, 30)
console.log("\n---- 120x30 user message style frame ----")
console.log(user120.frame)
check(user120.frame.includes("›"), "120x30 用户消息：`›` 前缀可见")
check(user120.frame.includes("帮我看看这个 PR"), "120x30 用户消息：内容可见")
check(user120.frame.includes("· 14:28"), "120x30 用户消息：落定时间可见")
check(user120.frame.includes("●"), "120x30 用户消息：assistant 行有 `●` 前缀（角色对比）")
check(user120.frame.includes("│") || user120.frame.includes("▌") || user120.frame.includes("▎"), "120x30 用户消息：左侧色条可见")
check(user120.lines.every((line) => [...line].length <= 120), "120x30 用户消息：无行宽溢出")

const user209 = await renderUserMessageFrame("user-message-209x51", 209, 51)
console.log("\n---- 209x51 user message style frame ----")
console.log(user209.frame)
check(user209.frame.includes("›"), "209x51 用户消息：`›` 前缀可见")
check(user209.frame.includes("帮我看看这个 PR"), "209x51 用户消息：内容可见")
check(user209.frame.includes("●"), "209x51 用户消息：assistant 行有 `●` 前缀（角色对比）")
check(user209.lines.every((line) => [...line].length <= 209), "209x51 用户消息：无行宽溢出")

// ---------------------------------------------------------------------
// J. 【C3/C4/C5 + A4/A5】契约 v1 帧：上下文提示、思考区分离、tips
// ---------------------------------------------------------------------

const CONTEXT_FIXTURE = { used_tokens: 2400, budget_tokens: 20000, used_percent: 12 }

/** 含上下文提示的完整 chat 头部 + 回答 + 指标行 + tips（120×30 与 209×51 各一张）。 */
async function renderContractFrame(label: string, width: number, height: number) {
  const view = await testRender(
    () => (
      <box width={width} height={height} flexDirection="column" paddingLeft={1}>
        <box width={width - 2} flexDirection="row" justifyContent="space-between">
          <text fg="#fb8147">PR REVIEW / CHAT</text>
          <text fg="#808080">deepseek · deepseek-flash</text>
        </box>
        <box width={width - 2} flexDirection="row" justifyContent="flex-end">
          <ContextUsageLine context={CONTEXT_FIXTURE} />
        </box>
        <box width={width - 2} marginTop={1} flexDirection="column">
          <ThinkingBlock
            text={"先定位 innerHTML 再核对占位符。\n证据在 website/index.html:237。"}
            expanded
            onToggle={() => {}}
            width={Math.max(24, width - 8)}
          />
          <box flexDirection="row" gap={1}>
            <text fg="#eeeeee">●</text>
            <markdown
              width={Math.max(24, width - 8)}
              content={"已修复 `innerHTML` 两处，并核对占位符。"}
              syntaxStyle={chatMarkdownStyle()}
              fg="#808080"
              conceal={true}
              tableOptions={chatTableOptions(Math.max(24, width - 8))}
            />
          </box>
          <box flexDirection="row" paddingLeft={2}>
            <MessageMetricsLine
              model="deepseek-flash"
              seconds={1.6}
              contentLength={61}
              timestamp="14:32"
            />
          </box>
          <OverBudgetTip width={Math.max(24, width - 8)} />
        </box>
      </box>
    ),
    { width, height },
  )
  await settle(view)
  const frame = view.captureCharFrame()
  dumpFrame(frame, label)
  const lines = frame.replace(/\n+$/, "").split("\n")
  return { frame, lines }
}

const contract120 = await renderContractFrame("contract-120x30", 120, 30)
console.log("\n---- 120x30 contract frame (context + thinking + metrics) ----")
console.log(contract120.frame)
check(contract120.frame.includes("上下文 12%"), "120x30：上下文提示可见（12%）")
check(contract120.frame.includes("2.4k/20k"), "120x30：上下文 token 缩写可见")
check(contract120.frame.includes("思考"), "120x30：思考区头部可见")
check(contract120.frame.includes("先定位 innerHTML"), "120x30：思考区正文与回答分离（思考文本可见）")
check(
  contract120.frame.includes("· deepseek-flash · 1.6s · 61 字 · 14:32"),
  "120x30：K 完整指标行可见（模型·耗时·字数·时间）",
)
check(contract120.frame.includes("上下文接近上限"), "120x30：A4 tips 可见")
check(
  contract120.lines.every((line) => [...line].length <= 120),
  "120x30：无行宽溢出",
)

const contract209 = await renderContractFrame("contract-209x51", 209, 51)
console.log("\n---- 209x51 contract frame (context + thinking + metrics) ----")
console.log(contract209.frame)
check(contract209.frame.includes("上下文 12%"), "209x51：上下文提示可见（12%）")
check(contract209.frame.includes("2.4k/20k"), "209x51：上下文 token 缩写可见")
check(
  contract209.frame.includes("· deepseek-flash · 1.6s · 61 字 · 14:32"),
  "209x51：K 完整指标行可见（模型·耗时·字数·时间）",
)
check(contract209.frame.includes("上下文接近上限"), "209x51：A4 tips 可见")
check(
  contract209.lines.every((line) => [...line].length <= 209),
  "209x51：无行宽溢出",
)

// 思考区折叠态：正文可见、思考正文隐藏（默认落定后折叠）。
const foldThinkingView = await testRender(
  () => (
    <box width={72} flexDirection="column">
      <ThinkingBlock
        text={"很长的思考过程\n不该默认刷屏。"}
        expanded={false}
        onToggle={() => {}}
        width={64}
      />
      <text fg="#eeeeee">回答正文在这里。</text>
    </box>
  ),
  { width: 72, height: 12 },
)
await settle(foldThinkingView)
const foldedThinking = foldThinkingView.captureCharFrame()
dumpFrame(foldedThinking, "thinking-collapsed")
console.log("\n---- thinking collapsed frame ----")
console.log(foldedThinking)
check(foldedThinking.includes("▸ 思考"), "思考区折叠态：角标可见")
check(foldedThinking.includes("▸ 思考（2 行）"), "L 折叠态行数标注正确（2 行）")
check(!foldedThinking.includes("很长的思考过程"), "思考区折叠态：思考正文隐藏")
check(foldedThinking.includes("回答正文在这里。"), "思考区折叠态：回答正文不受影响")

// ---------------------------------------------------------------------
// L. 【思考区可展开】header onMouseDown 行为断言 + Alt+T 键盘循环切换
// ---------------------------------------------------------------------

const THINKING_TEXT = "先定位 innerHTML\n再核对占位符\n证据在 index.html:237"
const [thinkingExpanded, setThinkingExpanded] = createSignal(false)
const toggleThinkingHeader = () => setThinkingExpanded((prev) => !prev)
/** Alt+T 与 app.tsx Composer 的绑定一致（循环切换思考区折叠态）。 */
function ThinkingHarness() {
  useKeyboard((key: { name: string; meta?: boolean }) => {
    if (key.meta === true && key.name === "t") {
      toggleThinkingHeader()
      key.stopPropagation?.()
    }
  })
  return (
    <box width={64} flexDirection="column">
      <ThinkingBlock
        text={THINKING_TEXT}
        expanded={thinkingExpanded()}
        onToggle={toggleThinkingHeader}
        width={56}
      />
      <text fg="#eeeeee">回答正文。</text>
    </box>
  )
}

const thinkingView = await testRender(() => <ThinkingHarness />, {
  width: 64,
  height: 14,
  kittyKeyboard: true,
})
await settle(thinkingView)
const thinkingCollapsedFrame = thinkingView.captureCharFrame()
dumpFrame(thinkingCollapsedFrame, "thinking-header-collapsed")
console.log("\n---- thinking header collapsed ----")
console.log(thinkingCollapsedFrame)
check(thinkingCollapsedFrame.includes("▸ 思考（3 行）"), "L 初始折叠：`▸ 思考（3 行）` 行数标注正确")
check(!thinkingCollapsedFrame.includes("先定位 innerHTML"), "L 初始折叠：思考正文隐藏")

// 行为断言：ThinkingBlock header 的 onMouseDown 绑定 onToggle，调用后展开。
const beforeHeaderClick = thinkingExpanded()
toggleThinkingHeader()
const afterHeaderClick = thinkingExpanded()
check(
  beforeHeaderClick === false && afterHeaderClick === true,
  `L onMouseDown 处理函数：点击 header 展开（${beforeHeaderClick} → ${afterHeaderClick}）`,
)
await settle(thinkingView)
const thinkingExpandedFrame = thinkingView.captureCharFrame()
dumpFrame(thinkingExpandedFrame, "thinking-header-expanded")
console.log("\n---- thinking header expanded ----")
console.log(thinkingExpandedFrame)
check(thinkingExpandedFrame.includes("▾ 思考"), "L 展开态：`▾ 思考` 文案保持")
check(thinkingExpandedFrame.includes("先定位 innerHTML"), "L 展开态：思考正文可见")
check(thinkingExpandedFrame.includes("证据在 index.html:237"), "L 展开态：思考末行可见")

// Alt+T 键盘快捷键：切换折叠态。
thinkingView.mockInput.pressKey("t", { meta: true })
await settle(thinkingView)
const afterAltT = thinkingView.captureCharFrame()
dumpFrame(afterAltT, "thinking-alt-t-collapsed")
console.log("\n---- thinking collapsed via Alt+T ----")
console.log(afterAltT)
check(thinkingExpanded() === false, "L Alt+T：快捷键切换折叠态（展开 → 折叠）")
check(afterAltT.includes("▸ 思考（3 行）"), "L Alt+T 后：回到折叠态行数标注")
check(!afterAltT.includes("先定位 innerHTML"), "L Alt+T 后：思考正文隐藏")

// 再按一次 Alt+T 应重新展开（循环切换语义）。
thinkingView.mockInput.pressKey("t", { meta: true })
await settle(thinkingView)
check(thinkingExpanded() === true, "L Alt+T：再次按下重新展开（循环切换）")

// A4 tips 独立帧：en 文案也走同一组件（language 缺省为 zh）。
const tipsView = await testRender(
  () => (
    <box width={72} flexDirection="column">
      <OverBudgetTip width={64} language="en-US" />
    </box>
  ),
  { width: 72, height: 6 },
)
await settle(tipsView)
const tipsFrame = tipsView.captureCharFrame()
dumpFrame(tipsFrame, "over-budget-tip-en")
console.log("\n---- over-budget tips (en) frame ----")
console.log(tipsFrame)
check(tipsFrame.includes("/compact"), "A4 tips：提到 /compact")
check(tipsFrame.includes("/new"), "A4 tips：提到 /new")
check(tipsFrame.toLowerCase().includes("context near limit"), "A4 tips：en 文案可见")

// ---------------------------------------------------------------------
// N. 【会话 UI · docs/mimo-sessions-ui.md】会话弹窗 / 重命名态 / 空态 /
//    状态栏会话名 / pressure=high 黄段与提示
// ---------------------------------------------------------------------

// 时间戳相对「现在」生成：formatRelativeTime 的分档断言（5 分钟前 / 3 小时前）
// 依赖真实时钟，固定字面量会在不同时刻落到别的桶里。
const SESSIONS_NOW = new Date()
const minutesAgo = (n: number) => new Date(SESSIONS_NOW.getTime() - n * 60_000).toISOString()
const SESSIONS_FIXTURE = [
  { id: "s2", title: "修复 XSS 与 CSRF", updated_at: minutesAgo(5), message_count: 12, current: true },
  { id: "s1", title: "PR #31 审查", updated_at: minutesAgo(3 * 60), message_count: 3 },
  {
    id: "s0",
    title: "一个非常非常长的会话标题需要被截断以适配列表宽度和状态栏宽度限制",
    updated_at: minutesAgo(2 * 24 * 60),
    message_count: 40,
  },
]

async function renderSessionsFrame(label: string, width: number, height: number) {
  const view = await testRender(
    () => (
      <box width={width} height={height} flexDirection="column">
        <SessionsDialog
          sessions={SESSIONS_FIXTURE}
          currentId="s2"
          supported
          onSwitch={() => {}}
          onRename={() => {}}
          onDelete={() => {}}
          onClose={() => {}}
        />
      </box>
    ),
    { width, height },
  )
  await settle(view)
  const frame = view.captureCharFrame()
  dumpFrame(frame, label)
  return { frame, lines: frame.replace(/\n+$/, "").split("\n") }
}

const sessions120 = await renderSessionsFrame("sessions-120x30", 120, 30)
console.log("\n---- 120x30 sessions dialog frame ----")
console.log(sessions120.frame)
check(sessions120.frame.includes("SESSIONS"), "120x30 会话弹窗：标题可见")
check(sessions120.frame.includes("●"), "120x30 会话弹窗：当前会话 `●` 标记")
check(sessions120.frame.includes("修复 XSS 与 CSRF"), "120x30 会话弹窗：当前会话标题可见")
check(sessions120.frame.includes("▸ PR #31 审查"), "120x30 会话弹窗：非当前项 `▸` 前缀")
check(sessions120.frame.includes("12 条"), "120x30 会话弹窗：消息条数可见")
check(sessions120.frame.includes("5 分钟前"), "120x30 会话弹窗：相对时间可见")
check(sessions120.frame.includes("↑↓ 选择 · Enter 切换 · r 重命名 · d 删除 · Esc 关闭"), "120x30 会话弹窗：中英页脚键位")
check(sessions120.frame.includes("…"), "120x30 会话弹窗：超长标题被截断")
check(
  sessions120.lines.every((line) => [...line].length <= 120),
  "120x30 会话弹窗：无行宽溢出",
)

const sessions209 = await renderSessionsFrame("sessions-209x51", 209, 51)
console.log("\n---- 209x51 sessions dialog frame ----")
console.log(sessions209.frame)
check(sessions209.frame.includes("SESSIONS"), "209x51 会话弹窗：标题可见")
check(sessions209.frame.includes("●"), "209x51 会话弹窗：当前会话 `●` 标记")
check(sessions209.frame.includes("↑↓ 选择 · Enter 切换"), "209x51 会话弹窗：页脚键位")
check(
  sessions209.lines.every((line) => [...line].length <= 209),
  "209x51 会话弹窗：无行宽溢出",
)

// 重命名态：内联输入 + Enter/Esc 提示（行为：模式状态机 list → rename）。
const renameView = await testRender(
  () => (
    <box width={96} height={24} flexDirection="column">
      <SessionsDialog
        sessions={SESSIONS_FIXTURE}
        currentId="s2"
        supported
        onSwitch={() => {}}
        onRename={() => {}}
        onDelete={() => {}}
        onClose={() => {}}
      />
    </box>
  ),
  { width: 96, height: 24 },
)
await settle(renameView)
// `r` 进入重命名态（与 SessionsDialog useKeyboard 的 key.name === "r" 一致）。
renameView.mockInput.pressKey("r")
await settle(renameView)
const renameFrame = renameView.captureCharFrame()
dumpFrame(renameFrame, "sessions-rename")
console.log("\n---- sessions rename frame ----")
console.log(renameFrame)
check(renameFrame.includes("重命名会话"), "重命名态：提示行可见")
check(renameFrame.includes("Enter 保存 · Esc 取消"), "重命名态：Enter/Esc 提示可见")
check(renameFrame.includes("修复 XSS 与 CSRF"), "重命名态：输入框预填当前标题")

// 空态：session.list 不存在/失败（旧后端）→ 空态文案，不崩溃。
const emptyView = await testRender(
  () => (
    <box width={96} height={20} flexDirection="column">
      <SessionsDialog
        sessions={[]}
        supported={false}
        onSwitch={() => {}}
        onRename={() => {}}
        onDelete={() => {}}
        onClose={() => {}}
      />
    </box>
  ),
  { width: 96, height: 20 },
)
await settle(emptyView)
const emptyFrame = emptyView.captureCharFrame()
dumpFrame(emptyFrame, "sessions-empty")
console.log("\n---- sessions empty frame ----")
console.log(emptyFrame)
check(emptyFrame.includes("当前后端不支持会话列表"), "空态：「当前后端不支持会话列表」文案可见")
check(emptyFrame.includes("Esc"), "空态：仍可 Esc 关闭")

// 状态栏会话名（A-P3）：120 列显示、80 列（<100）隐藏。
const statusRuntime = {
  runtime_profile: "CLOUD",
  model: "deepseek-flash",
  ui_language: "zh-CN",
  available: true,
  chat_reasoning_effort: "high",
}
const statusWide = await testRender(
  () => (
    <box width={120} height={4} flexDirection="column">
      <RuntimeStatusLine
        runtime={statusRuntime}
        status="READY"
        width={120}
        height={30}
        sessionTitle="修复 XSS 与 CSRF"
      />
    </box>
  ),
  { width: 120, height: 4 },
)
await settle(statusWide)
const statusWideFrame = statusWide.captureCharFrame()
dumpFrame(statusWideFrame, "status-session-120")
console.log("\n---- status bar session name (120 cols) ----")
console.log(statusWideFrame)
check(statusWideFrame.includes("会话《"), "状态栏 120 列：会话名段可见")
check(statusWideFrame.includes("修复 XSS 与 CSRF"), "状态栏 120 列：会话标题内容可见")

const statusNarrow = await testRender(
  () => (
    <box width={80} height={4} flexDirection="column">
      <RuntimeStatusLine
        runtime={statusRuntime}
        status="READY"
        width={80}
        height={24}
        sessionTitle="修复 XSS 与 CSRF"
      />
    </box>
  ),
  { width: 80, height: 4 },
)
await settle(statusNarrow)
const statusNarrowFrame = statusNarrow.captureCharFrame()
dumpFrame(statusNarrowFrame, "status-session-80")
console.log("\n---- status bar session name hidden (80 cols) ----")
console.log(statusNarrowFrame)
check(!statusNarrowFrame.includes("会话《"), "状态栏 80 列：<100 列隐藏会话名段")
check(statusNarrowFrame.includes("CLOUD"), "状态栏 80 列：其余段保留")

// pressure=high：上下文段黄 + 尾部提示「上下文接近上限：可用 /compact 压缩」。
const pressureView = await testRender(
  () => (
    <box width={96} height={8} flexDirection="column">
      <ContextUsageLine
        context={{ used_tokens: 18000, budget_tokens: 20000, used_percent: 92, pressure: "high" }}
        language="zh-CN"
      />
    </box>
  ),
  { width: 96, height: 8 },
)
await settle(pressureView)
const pressureFrame = pressureView.captureCharFrame()
dumpFrame(pressureFrame, "pressure-high")
console.log("\n---- pressure=high frame ----")
console.log(pressureFrame)
check(pressureFrame.includes("上下文 92%"), "pressure=high：上下文段可见")
check(pressureFrame.includes("上下文接近上限"), "pressure=high：尾部提示可见")
check(pressureFrame.includes("/compact"), "pressure=high：提示提到 /compact")

// pressure=low/null：不提示、不改色（现状不变）。
const pressureCalm = await testRender(
  () => (
    <box width={96} height={6} flexDirection="column">
      <ContextUsageLine
        context={{ used_tokens: 2400, budget_tokens: 20000, used_percent: 12, pressure: "low" }}
        language="zh-CN"
      />
    </box>
  ),
  { width: 96, height: 6 },
)
await settle(pressureCalm)
const pressureCalmFrame = pressureCalm.captureCharFrame()
dumpFrame(pressureCalmFrame, "pressure-low")
check(pressureCalmFrame.includes("上下文 12%"), "pressure=low：上下文段可见")
check(!pressureCalmFrame.includes("上下文接近上限"), "pressure=low：无压力提示")

console.log(failures.length === 0 ? `\nALL PASS · frames: ${outDir}` : `\nFAILURES: ${failures.length}`)
process.exit(failures.length === 0 ? 0 : 1)
