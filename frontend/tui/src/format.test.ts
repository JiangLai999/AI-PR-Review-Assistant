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
  formatEffortBadge,
  formatMessageMetrics,
  formatOutputLength,
  formatReviewBudgetCapHint,
  formatReviewEffortCost,
  formatReviewEffortDisabled,
  formatThinkLevel,
  formatThinkTransparent,
  formatThinkUnsupported,
  formatTokenCount,
  overBudgetTip,
  REVIEW_BUDGET_CAP_MAX_OUTPUT,
  reviewEffortBilingualLabel,
  reviewSlotMaxOutput,
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
// 消息指标行（mimo-message-metrics）：模型 · 耗时 · 输出长度 · 对话时间
// ---------------------------------------------------------------------

test("formatMessageMetrics renders every segment when all fields are present", () => {
  expect(
    formatMessageMetrics(
      {
        model: "deepseek-flash",
        durationSeconds: 1.6,
        contentLength: 61,
        timestamp: "14:32",
      },
    ),
  ).toBe("· deepseek-flash · 1.6s · 61 字 · 14:32")
  expect(
    formatMessageMetrics(
      {
        model: "deepseek-flash",
        durationSeconds: 1.6,
        completionTokens: 300,
        timestamp: "14:32",
      },
      "en-US",
    ),
  ).toBe("· deepseek-flash · 1.6s · 300 tok · 14:32")
})

test("formatMessageMetrics prefers completion_tokens over content length", () => {
  expect(
    formatMessageMetrics({ completionTokens: 300, contentLength: 61 }).trim(),
  ).toBe("· 300 tok")
})

test("formatMessageMetrics omits missing model segment", () => {
  expect(
    formatMessageMetrics({ durationSeconds: 1.6, contentLength: 61, timestamp: "14:32" }),
  ).toBe("· 1.6s · 61 字 · 14:32")
})

test("formatMessageMetrics omits missing usage by falling back to chars", () => {
  expect(formatMessageMetrics({ model: "m", contentLength: 61 })).toBe("· m · 61 字")
  expect(formatMessageMetrics({ model: "m", contentLength: 61 }, "en-US")).toBe("· m · 61 chars")
})

test("formatMessageMetrics omits missing timestamp segment", () => {
  expect(
    formatMessageMetrics({ model: "m", durationSeconds: 2, completionTokens: 10 }),
  ).toBe("· m · 2.0s · 10 tok")
})

test("formatMessageMetrics hides zero-length output and non-finite fields", () => {
  // length 0 is a real value (empty completion) and should still render once present
  expect(formatMessageMetrics({ completionTokens: 0 })).toBe("· 0 tok")
  expect(
    formatMessageMetrics({
      model: "m",
      durationSeconds: Number.NaN,
      completionTokens: Number.POSITIVE_INFINITY,
      timestamp: "14:32",
    }),
  ).toBe("· m · 14:32")
})

test("formatMessageMetrics returns empty string when every field is missing", () => {
  expect(formatMessageMetrics({})).toBe("")
})

test("formatOutputLength labels zh/en char fallback and tok for real tokens", () => {
  expect(formatOutputLength({ completionTokens: 300, contentLength: 61 })).toBe("300 tok")
  expect(formatOutputLength({ contentLength: 61 })).toBe("61 字")
  expect(formatOutputLength({ contentLength: 61 }, "en-US")).toBe("61 chars")
  expect(formatOutputLength({})).toBe("")
})

test("formatEffortBadge shows level only when present", () => {
  expect(formatEffortBadge("max")).toBe("思考 max")
  expect(formatEffortBadge("max", "en-US")).toBe("THINK max")
  expect(formatEffortBadge("off")).toBe("思考 off")
  expect(formatEffortBadge(undefined)).toBe("")
  expect(formatEffortBadge("")).toBe("")
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

test("formatThinkTransparent shows the level plus an upstream caveat", () => {
  // 中转/自定义端点：档位已写入请求，但生效与否取决于上游——必须说清楚。
  expect(formatThinkTransparent("high", undefined)).toBe(
    "思考档位：高 · 是否生效取决于上游服务",
  )
  expect(formatThinkTransparent("high", "depends on api2d upstream")).toBe(
    "思考档位：高 · depends on api2d upstream",
  )
  expect(formatThinkTransparent("high", undefined, "en-US")).toBe(
    "Thinking level: high · Whether it takes effect depends on the upstream provider",
  )
  expect(formatThinkTransparent(undefined, undefined, "en-US")).toContain("—")
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

// ---------------------------------------------------------------------
// review 思考档位（docs/mimo-review-effort-ui.md）
// ---------------------------------------------------------------------

test("review effort cost hint shows baseline for off and measured multiplier for thinking levels", () => {
  expect(formatReviewEffortCost("off", "zh-CN")).toContain("与现状相同")
  expect(formatReviewEffortCost("off", "en-US")).toContain("baseline")
  expect(formatReviewEffortCost("low", "zh-CN")).toContain("×3.6")
  expect(formatReviewEffortCost("high", "zh-CN")).toContain("×2.9")
  expect(formatReviewEffortCost("max", "zh-CN")).toContain("max 档")
  expect(formatReviewEffortCost("max", "en-US")).toContain("×3.6")
  expect(formatReviewEffortCost("auto", "zh-CN")).toContain("供应商默认")
  expect(formatReviewEffortCost("auto", "en-US")).toContain("provider default")
})

test("review effort disabled reason prefers the backend reason", () => {
  expect(formatReviewEffortDisabled("本地模型固定使用快速模式", "zh-CN")).toBe(
    "本地模型固定使用快速模式",
  )
  expect(formatReviewEffortDisabled(undefined, "zh-CN")).toContain("不接受思考参数")
  expect(formatReviewEffortDisabled(undefined, "en-US")).toContain("will not take effect")
})

test("review effort bilingual label splits on the backend's zh / en separator", () => {
  expect(reviewEffortBilingualLabel("关闭 / Off（不思考，默认）", "zh-CN")).toBe("关闭")
  expect(reviewEffortBilingualLabel("关闭 / Off（不思考，默认）", "en-US")).toBe("Off（不思考，默认）")
  expect(reviewEffortBilingualLabel("NoSeparator", "zh-CN")).toBe("NoSeparator")
  expect(reviewEffortBilingualLabel("", "zh-CN")).toBe("")
})

// ---------------------------------------------------------------------
// 小 max_output × high/max 封顶提示（docs/mimo-review-budget-hint.md）
// ---------------------------------------------------------------------

test("review budget cap hint triggers only on high/max with a small max_output", () => {
  // 阈值内 + high/max → 有提示
  expect(formatReviewBudgetCapHint(8192, "high", "zh-CN")).toContain("封顶")
  expect(formatReviewBudgetCapHint(8192, "max", "zh-CN")).toContain("封顶")
  expect(formatReviewBudgetCapHint(4096, "high", "zh-CN")).toContain("4096")
  expect(formatReviewBudgetCapHint(REVIEW_BUDGET_CAP_MAX_OUTPUT, "max", "zh-CN")).toContain("封顶")
  // 阈值外 → 无提示
  expect(formatReviewBudgetCapHint(384000, "max", "zh-CN")).toBe("")
  expect(formatReviewBudgetCapHint(32768, "high", "zh-CN")).toBe("")
  expect(formatReviewBudgetCapHint(REVIEW_BUDGET_CAP_MAX_OUTPUT + 1, "max", "zh-CN")).toBe("")
})

test("review budget cap hint is silent for off/low/auto and missing max_output", () => {
  expect(formatReviewBudgetCapHint(8192, "off", "zh-CN")).toBe("")
  expect(formatReviewBudgetCapHint(8192, "low", "zh-CN")).toBe("")
  expect(formatReviewBudgetCapHint(8192, "auto", "zh-CN")).toBe("")
  expect(formatReviewBudgetCapHint(8192, undefined, "zh-CN")).toBe("")
  expect(formatReviewBudgetCapHint(8192, "", "zh-CN")).toBe("")
  expect(formatReviewBudgetCapHint(undefined, "high", "zh-CN")).toBe("")
  expect(formatReviewBudgetCapHint(undefined, "max", "zh-CN")).toBe("")
  expect(formatReviewBudgetCapHint(NaN, "high", "zh-CN")).toBe("")
  expect(formatReviewBudgetCapHint(Infinity, "max", "zh-CN")).toBe("")
})

test("review budget cap hint copy is bilingual and names the actual limit", () => {
  const zh = formatReviewBudgetCapHint(8192, "high", "zh-CN")
  expect(zh).toContain("8192")
  expect(zh).toContain("封顶")
  expect(zh).toContain("low")
  const en = formatReviewBudgetCapHint(4096, "max", "en-US")
  expect(en).toContain("4096")
  expect(en).toContain("capped")
  expect(en).toContain("low")
  // 默认语言 = 中文
  expect(formatReviewBudgetCapHint(8192, "max")).toContain("封顶")
})

test("reviewSlotMaxOutput reads the review slot's max_output from model spec slots", () => {
  const spec = {
    max_output: 384000,
    slots: {
      remote: { max_output: 8192 },
      local: { max_output: 4096 },
    },
  }
  expect(reviewSlotMaxOutput("remote", spec)).toBe(8192)
  expect(reviewSlotMaxOutput("local", spec)).toBe(4096)
  expect(reviewSlotMaxOutput("REMOTE", spec)).toBe(8192)
  // hybrid / 未知 / 缺槽 → undefined（不显示提示）
  expect(reviewSlotMaxOutput("hybrid", spec)).toBeUndefined()
  expect(reviewSlotMaxOutput("unknown", spec)).toBeUndefined()
  expect(reviewSlotMaxOutput(undefined, spec)).toBeUndefined()
  expect(reviewSlotMaxOutput("", spec)).toBeUndefined()
  // 缺 slots（旧后端）→ undefined，绝不回落到顶层 max_output
  expect(reviewSlotMaxOutput("remote", { max_output: 384000 })).toBeUndefined()
  expect(reviewSlotMaxOutput("local", { max_output: 384000 })).toBeUndefined()
  expect(reviewSlotMaxOutput("remote", undefined)).toBeUndefined()
  // 槽块缺 max_output 字段 → undefined
  expect(reviewSlotMaxOutput("remote", { slots: { remote: {} } })).toBeUndefined()
})
