import { expect, test } from "bun:test"
import {
  codeFoldBadge,
  codeFoldStateKey,
  CODE_FOLD_LINE_THRESHOLD,
  compactPath,
  cursorFrame,
  foldableCodeBlocks,
  foldMarkdownCodeBlocks,
  formatChatHistoryLines,
  formatCompactFailure,
  formatCompactSummary,
  formatContextUsage,
  formatDurationSeconds,
  formatThinkLevel,
  formatThinkUnsupported,
  formatTokenCount,
  overBudgetTip,
  spinnerFrame,
  splitFoldableMarkdown,
  thinkingPlaceholder,
  truncateMiddle,
  workspaceRootLabel,
} from "./format"

test("compactPath keeps the tail of an over-long path", () => {
  expect(compactPath("C:\\short", 30)).toBe("C:\\short")
  const long = "C:\\Users\\21986\\Desktop\\ican\\AI-PR-Review-Assistant\\frontend\\tui"
  const compact = compactPath(long, 20)
  expect(compact.length).toBe(20)
  expect(compact.startsWith("…")).toBe(true)
  expect(compact.endsWith("frontend\\tui")).toBe(true)
})

test("truncateMiddle preserves both ends of a PR url", () => {
  const url = "https://github.com/JiangLai999/AI-PR-Review-Assistant/pull/138"
  expect(truncateMiddle(url, 70)).toBe(url)
  const cut = truncateMiddle(url, 30)
  expect(cut.length).toBe(30)
  // Exactly `max` columns: head + ellipsis + tail.
  expect(cut).toBe(`${url.slice(0, 15)}…${url.slice(url.length - 14)}`)
  expect(cut.startsWith("https://github.")).toBe(true)
  expect(cut.endsWith("/pull/138")).toBe(true)
})

test("workspaceRootLabel folds the home prefix and never exceeds the footer budget", () => {
  expect(workspaceRootLabel("C:\\Users\\21986\\Desktop\\ican", "C:\\Users\\21986")).toBe(
    "~\\Desktop\\ican",
  )
  expect(workspaceRootLabel("/home/me/projects/app", "/home/me")).toBe("~/projects/app")
  expect(workspaceRootLabel("/opt/other/app", "/home/me")).toBe("/opt/other/app")
  expect(workspaceRootLabel("")).toBe("")
  const long = workspaceRootLabel("C:\\Users\\21986\\Desktop\\ican\\AI-PR-Review-Assistant", "")
  expect(long.length).toBe(30)
  expect(long.startsWith("…")).toBe(true)
})

// ---------------------------------------------------------------------
// C4 · 耗时
// ---------------------------------------------------------------------

test("formatDurationSeconds renders C4 duration and hides missing values", () => {
  expect(formatDurationSeconds(3.2)).toBe("3.2s")
  expect(formatDurationSeconds(0.4)).toBe("0.4s")
  expect(formatDurationSeconds(45)).toBe("45s")
  expect(formatDurationSeconds(undefined)).toBe("")
  expect(formatDurationSeconds(Number.NaN)).toBe("")
})

// ---------------------------------------------------------------------
// A5 · token 缩写与上下文提示
// ---------------------------------------------------------------------

test("formatTokenCount abbreviates thousands with one decimal where needed", () => {
  expect(formatTokenCount(999)).toBe("999")
  expect(formatTokenCount(2400)).toBe("2.4k")
  expect(formatTokenCount(20000)).toBe("20k")
  expect(formatTokenCount(undefined)).toBe("")
})

test("formatContextUsage builds the A5 status line and hides without context", () => {
  expect(
    formatContextUsage({ used_tokens: 2400, budget_tokens: 20000, used_percent: 12 }),
  ).toBe("上下文 12% · 2.4k/20k")
  expect(
    formatContextUsage({ used_tokens: 2400, budget_tokens: 20000, used_percent: 12 }, "en-US"),
  ).toBe("context 12% · 2.4k/20k")
  expect(formatContextUsage(undefined)).toBe("")
  expect(formatContextUsage({})).toBe("")
})

// ---------------------------------------------------------------------
// A4 · over_budget tips
// ---------------------------------------------------------------------

test("overBudgetTip offers zh/en copy mentioning /compact and /new", () => {
  const zh = overBudgetTip()
  expect(zh).toContain("/compact")
  expect(zh).toContain("/new")
  expect(zh).toContain("上下文接近上限")
  const en = overBudgetTip("en-US")
  expect(en).toContain("/compact")
  expect(en).toContain("/new")
  expect(en.toLowerCase()).toContain("context")
})

// ---------------------------------------------------------------------
// C3 · 动画帧
// ---------------------------------------------------------------------

test("cursor and spinner frames cycle without new dependencies", () => {
  expect(cursorFrame(0)).toBe("▌")
  expect(cursorFrame(1)).toBe("▍")
  expect(cursorFrame(2)).toBe(" ")
  expect(cursorFrame(3)).toBe("▌")
  expect(spinnerFrame(0)).toBe("⠋")
  expect(spinnerFrame(10)).toBe(spinnerFrame(0))
  expect(thinkingPlaceholder(0, "en-US")).toContain("Thinking")
  expect(thinkingPlaceholder(0)).toContain("思考中")
})

// ---------------------------------------------------------------------
// 命令展示文案
// ---------------------------------------------------------------------

test("formatThinkLevel echoes the level in zh and en", () => {
  expect(formatThinkLevel("high")).toBe("思考档位：高")
  expect(formatThinkLevel("high", "en-US")).toBe("Thinking level: high")
  expect(formatThinkLevel(undefined)).toContain("—")
})

test("formatThinkUnsupported prefers the backend reason", () => {
  expect(formatThinkUnsupported("model has no reasoning control")).toBe(
    "model has no reasoning control",
  )
  expect(formatThinkUnsupported(undefined)).toContain("不支持")
  expect(formatThinkUnsupported(undefined, "en-US")).toContain("does not support")
})

test("formatCompactSummary shows before→after tokens and kept turns", () => {
  expect(
    formatCompactSummary({ before_tokens: 12400, after_tokens: 3100, kept_turns: 8 }),
  ).toBe("12.4k → 3.1k · 保留 8 轮")
  expect(
    formatCompactSummary({ before_tokens: 12400, after_tokens: 3100, kept_turns: 8 }, "en-US"),
  ).toBe("12.4k → 3.1k · kept 8 turns")
  expect(
    formatCompactSummary({
      before_tokens: 12400,
      after_tokens: 3100,
      kept_turns: 8,
      replaced_messages: 22,
    }),
  ).toBe("12.4k → 3.1k · 保留 8 轮 · 已压缩 22 条")
  expect(
    formatCompactSummary(
      { kept_turns: 8, replaced_messages: 22 },
      "en-US",
    ),
  ).toBe("kept 8 turns · 22 messages summarized")
  // replaced_messages=0 不显示（没有旧消息被压缩）。
  expect(formatCompactSummary({ kept_turns: 8, replaced_messages: 0 })).toBe("保留 8 轮")
  expect(formatCompactSummary({})).toBe("上下文已压缩")
})

test("formatCompactFailure emphasizes that original history is unchanged", () => {
  const zh = formatCompactFailure("store locked")
  expect(zh).toContain("store locked")
  expect(zh).toContain("原历史未变")
  const en = formatCompactFailure(undefined, "en-US")
  expect(en).toContain("original history is unchanged")
})

test("formatChatHistoryLines numbers messages and truncates long bodies", () => {
  const lines = formatChatHistoryLines(
    [
      { role: "user", content: "帮我看看这个 PR" },
      { role: "assistant", content: "A".repeat(80) },
    ],
    { contentWidth: 20, language: "en-US" },
  )
  expect(lines[0]).toContain("1")
  expect(lines[0]).toContain("user")
  expect(lines[0]).toContain("帮我看看这个 PR")
  expect(lines[1]).toContain("2")
  expect(lines[1]).toContain("assistant")
  expect(lines[1]).toContain("…")
  expect(lines[1].length).toBeLessThan(80)
})

// ---------------------------------------------------------------------
// C2/C3 · 代码折叠纯函数 + 角标分段（mimo-chat-render-c3）
// ---------------------------------------------------------------------

test("codeFoldBadge keeps the user-facing copy", () => {
  expect(codeFoldBadge(30, false)).toBe("▸ 展开（共 30 行）")
  expect(codeFoldBadge(30, true)).toBe("▾ 收起")
  expect(CODE_FOLD_LINE_THRESHOLD).toBe(15)
})

test("codeFoldStateKey joins message id and block index", () => {
  expect(codeFoldStateKey("msg-3", 0)).toBe("msg-3#0")
  expect(codeFoldStateKey("streaming", 2)).toBe("streaming#2")
})

test("foldableCodeBlocks lists only long fenced blocks with stable indexes", () => {
  const long = ["```js", ...Array.from({ length: 20 }, (_, i) => `l${i}`), "```"].join("\n")
  const short = ["```js", "one", "```"].join("\n")
  const blocks = foldableCodeBlocks(`${short}\n\n${long}\n\n${short}`)
  expect(blocks).toHaveLength(1)
  expect(blocks[0].index).toBe(1) // 短块占 index 0
  expect(blocks[0].lineCount).toBe(20)
})

test("foldMarkdownCodeBlocks truncates long blocks and leaves short blocks alone", () => {
  const long = ["```js", ...Array.from({ length: 20 }, (_, i) => `l${i}`), "```"].join("\n")
  const folded = foldMarkdownCodeBlocks(long, () => false)
  expect(folded).toContain("l0")
  expect(folded).toContain("l14")
  expect(folded).not.toContain("l15")
  expect(folded).toContain("▸ 展开（共 20 行）")
  const expanded = foldMarkdownCodeBlocks(long, () => true)
  expect(expanded).toContain("l19")
  expect(expanded).toContain("▾ 收起")
  const short = ["```js", "one", "```"].join("\n")
  expect(foldMarkdownCodeBlocks(short, () => false)).toBe(short)
})

test("splitFoldableMarkdown emits markdown segments plus foldBadge slots", () => {
  const long = ["```js", ...Array.from({ length: 20 }, (_, i) => `l${i}`), "```"].join("\n")
  const content = `prose before\n\n${long}\n\nprose after`
  const segments = splitFoldableMarkdown(content, () => false)
  // 段序：prose-before(markdown) + 折叠代码块(markdown, foldable) + 角标 + prose-after(markdown)
  expect(segments.map((s) => s.kind)).toEqual([
    "markdown",
    "markdown",
    "foldBadge",
    "markdown",
  ])
  const [before, block, badge, after] = segments
  expect(before.kind === "markdown" && before.content).toContain("prose before")
  expect(block.kind === "markdown" && block.foldable).toBe(true)
  expect(block.kind === "markdown" && block.content).toContain("l0")
  expect(block.kind === "markdown" && block.content).not.toContain("▸ 展开")
  expect(badge.kind === "foldBadge" && badge.blockIndex).toBe(0)
  expect(badge.kind === "foldBadge" && badge.lineCount).toBe(20)
  expect(badge.kind === "foldBadge" && badge.expanded).toBe(false)
  expect(after.kind === "markdown" && after.content).toContain("prose after")
})

test("splitFoldableMarkdown flips the badge expanded flag and grows the block segment", () => {
  const long = ["```js", ...Array.from({ length: 20 }, (_, i) => `l${i}`), "```"].join("\n")
  const collapsed = splitFoldableMarkdown(long, () => false)
  const expanded = splitFoldableMarkdown(long, () => true)
  const collapsedBlock = collapsed.find((s) => s.kind === "markdown")
  const expandedBlock = expanded.find((s) => s.kind === "markdown")
  expect(collapsedBlock?.kind === "markdown" && collapsedBlock.content).not.toContain("l19")
  expect(expandedBlock?.kind === "markdown" && expandedBlock.content).toContain("l19")
  const collapsedBadge = collapsed.find((s) => s.kind === "foldBadge")
  const expandedBadge = expanded.find((s) => s.kind === "foldBadge")
  expect(collapsedBadge?.kind === "foldBadge" && collapsedBadge.expanded).toBe(false)
  expect(expandedBadge?.kind === "foldBadge" && expandedBadge.expanded).toBe(true)
})

test("splitFoldableMarkdown leaves short-block content in a single markdown segment", () => {
  const short = ["```js", "one", "```"].join("\n")
  const segments = splitFoldableMarkdown(`${short}\n\nafter`, () => false)
  expect(segments).toHaveLength(1)
  expect(segments[0].kind).toBe("markdown")
  expect(segments[0].kind === "markdown" && segments[0].content).toBe(`${short}\n\nafter`)
})

test("splitFoldableMarkdown handles leading and consecutive foldable blocks", () => {
  const long = ["```js", ...Array.from({ length: 20 }, (_, i) => `l${i}`), "```"].join("\n")
  const leading = splitFoldableMarkdown(long, () => false)
  expect(leading[0].kind).toBe("markdown")
  expect(leading[1].kind).toBe("foldBadge")
  const double = splitFoldableMarkdown(`${long}\n${long}`, () => false)
  const kinds = double.map((s) => s.kind)
  expect(kinds).toEqual(["markdown", "foldBadge", "markdown", "foldBadge"])
  expect(double.filter((s) => s.kind === "foldBadge").map((s) => (s.kind === "foldBadge" ? s.blockIndex : -1))).toEqual([0, 1])
})
