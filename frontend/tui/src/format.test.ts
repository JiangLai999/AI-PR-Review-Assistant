import { expect, test } from "bun:test"
import {
  compactPath,
  cursorFrame,
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
