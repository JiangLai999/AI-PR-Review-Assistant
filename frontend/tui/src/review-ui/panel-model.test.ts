import { expect, test } from "bun:test"
import {
  actionBarView,
  clampLine,
  demoView,
  displayWidth,
  filterBarView,
  fitBorderedContent,
  hasClosingBorder,
  panelContentBudget,
  publishDialogView,
  PUBLISH_DIALOG_STATES,
  riskBadge,
  scrubCredentials,
  showcaseView,
  truncateCommentBody,
} from "./panel-model"
import type { PublishDialogState } from "./panel-model"
import type { ReviewFinding } from "./types"

// ---------------------------------------------------------------------------
// Single-line clamping (filter bar "never wrap / never exceed width")
// ---------------------------------------------------------------------------

test("displayWidth counts CJK as two columns", () => {
  expect(displayWidth("abc")).toBe(3)
  expect(displayWidth("审查进度")).toBe(8)
  expect(displayWidth("")).toBe(0)
  expect(displayWidth(undefined as unknown as string)).toBe(0)
})

test("clampLine never exceeds the budget and never emits a newline", () => {
  expect(clampLine("hello", 10)).toBe("hello")
  expect(clampLine("hello world", 8)).toBe("hello w…")
  expect(clampLine("line1\nline2", 20)).toBe("line1 line2")
  expect(clampLine("审查进度面板标题", 6)).toBe("审查…")
  expect(clampLine("x", 1)).toBe("x")
  expect(clampLine("xy", 1)).toBe("…")
  expect(clampLine("x", 0)).toBe("")
  expect(clampLine(undefined as unknown as string, 8)).toBe("")
  const clamped = clampLine("a".repeat(200), 30)
  expect(clamped).toHaveLength(30)
  expect(clamped.includes("\n")).toBe(false)
})

// ---------------------------------------------------------------------------
// FindingsFilterBar
// ---------------------------------------------------------------------------

test("filterBarView inactive is a hint-only row with shown/total", () => {
  const view = filterBarView({ active: false, shown: 3, total: 15, language: "en" })
  expect(view.hintOnly).toBe(true)
  expect(view.text).toContain("Ctrl+F to filter")
  expect(view.text).toContain("3/15")
  expect(view.text.includes("\n")).toBe(false)

  const zh = filterBarView({ active: false, shown: 0, total: 0 })
  expect(zh.hintOnly).toBe(true)
  expect(zh.text).toContain("Ctrl+F 过滤")
})

test("filterBarView active highlights filter tokens and shows counts", () => {
  const view = filterBarView({
    active: true,
    query: "auth",
    severity: "high",
    evidence: "valid",
    sort: "file",
    shown: 2,
    total: 9,
    language: "en",
  })
  expect(view.hintOnly).toBe(false)
  expect(view.text).toContain("q:auth")
  expect(view.text).toContain("sev:high")
  expect(view.text).toContain("ev:valid")
  expect(view.text).toContain("sort:file")
  expect(view.text).toContain("2/9")
  expect(view.tokens.some((token) => token.active)).toBe(true)
  expect(view.tokens[view.tokens.length - 1].active).toBe(false)
  expect(view.text.includes("\n")).toBe(false)
})

test("filterBarView survives undefined and malformed input", () => {
  expect(() => filterBarView(undefined)).not.toThrow()
  expect(() => filterBarView(null)).not.toThrow()
  const junk = filterBarView({
    active: true,
    query: undefined,
    severity: undefined,
    evidence: undefined,
    sort: undefined,
    shown: Number.NaN,
    total: -5,
    language: "en",
  })
  expect(junk.text).toContain("0/0")
  expect(junk.text.includes("\n")).toBe(false)

  const huge = filterBarView({
    active: true,
    query: "x".repeat(200),
    shown: 1,
    total: 1,
    language: "en",
  })
  expect(displayWidth(huge.text)).toBeLessThanOrEqual(78)
})

test("filterBarView active with no criteria still renders one clean row", () => {
  const view = filterBarView({ active: true, shown: 5, total: 5, language: "en" })
  expect(view.hintOnly).toBe(false)
  expect(view.text).toContain("5/5")
  expect(view.text.includes("\n")).toBe(false)
})

// ---------------------------------------------------------------------------
// PublishConfirmDialog
// ---------------------------------------------------------------------------

const previewFixture = {
  runId: "run-1",
  repository: "owner/repo",
  prNumber: 31,
  url: "https://github.com/owner/repo/pull/31",
  commentBody: Array.from({ length: 12 }, (_, i) => `comment line ${i + 1}`).join("\n"),
  findings: 15,
  alreadyPublished: false,
}

test("PUBLISH_DIALOG_STATES covers the five contract states", () => {
  expect(PUBLISH_DIALOG_STATES).toEqual([
    "preview",
    "publishing",
    "published",
    "failed",
    "cancelled",
  ])
})

test("publishDialogView preview shows target, findings, url and truncated body", () => {
  const view = publishDialogView({
    state: "preview",
    preview: previewFixture,
    maxBodyLines: 8,
    language: "en",
  })
  expect(view.success).toBe(false)
  expect(view.title).toBe("PUBLISH PREVIEW")
  const joined = view.lines.join("\n")
  expect(joined).toContain("owner/repo#31")
  expect(joined).toContain("15")
  expect(joined).toContain("https://github.com/owner/repo/pull/31")
  expect(joined).toContain("comment line 1")
  expect(joined).toContain("comment line 8")
  expect(joined).not.toContain("comment line 9")
  expect(joined).toMatch(/truncated/i)
  expect(joined).toContain("8/12")
})

test("publishDialogView honors a custom maxBodyLines", () => {
  const view = publishDialogView({
    state: "preview",
    preview: previewFixture,
    maxBodyLines: 3,
    language: "en",
  })
  const joined = view.lines.join("\n")
  expect(joined).toContain("comment line 3")
  expect(joined).not.toContain("comment line 4")
  expect(joined).toMatch(/3\/12/)
})

test("publishDialogView publishes success only in the published state", () => {
  const states: PublishDialogState[] = ["preview", "publishing", "failed", "cancelled"]
  for (const state of states) {
    const view = publishDialogView({
      state,
      preview: previewFixture,
      message: "boom",
      language: "en",
    })
    expect(view.success).toBe(false)
    expect(view.title).not.toBe("PUBLISHED")
    const joined = view.lines.join("\n")
    expect(joined).not.toMatch(/successfully/i)
    expect(joined).not.toMatch(/comment posted/i)
    expect(joined).not.toContain("已发布到")
    expect(joined).not.toContain("审查评论已发布")
  }

  const published = publishDialogView({
    state: "published",
    preview: previewFixture,
    language: "en",
  })
  expect(published.success).toBe(true)
  expect(published.title).toBe("PUBLISHED")
  expect(published.lines.join("\n")).toContain("owner/repo#31")
  expect(published.lines.join("\n")).toMatch(/posted/i)
})

test("publishDialogView failed shows the message verbatim", () => {
  const view = publishDialogView({
    state: "failed",
    preview: previewFixture,
    message: "GitHub API 502: upstream unavailable",
    language: "en",
  })
  expect(view.success).toBe(false)
  expect(view.title).toBe("PUBLISH FAILED")
  expect(view.lines).toEqual(["GitHub API 502: upstream unavailable"])
})

test("publishDialogView cancelled never claims a post", () => {
  const view = publishDialogView({
    state: "cancelled",
    preview: previewFixture,
    language: "en",
  })
  expect(view.success).toBe(false)
  expect(view.title).toBe("PUBLISH CANCELLED")
  const joined = view.lines.join("\n")
  expect(joined).toContain("owner/repo#31")
  expect(joined).toContain("No review comment was created")
  expect(joined).not.toMatch(/successfully/i)
  expect(joined).not.toMatch(/comment posted/i)
})

test("publishDialogView warns when already_published", () => {
  const view = publishDialogView({
    state: "preview",
    preview: { ...previewFixture, alreadyPublished: true },
    language: "en",
  })
  expect(view.lines.join("\n").toLowerCase()).toContain("already published")
})

test("publishDialogView never renders credential-looking strings", () => {
  const secretBody = [
    "header",
    "token ghp_abcdefghijklmnopqrstuvwxyz012345",
    "Authorization: Bearer abcdefghijklmnop",
    "api_key=sk-abcdefghijklmnopqrstuv",
  ].join("\n")
  const view = publishDialogView({
    state: "preview",
    preview: { ...previewFixture, commentBody: secretBody },
    language: "en",
  })
  const joined = view.lines.join("\n")
  expect(joined).not.toContain("ghp_abcdefghijklmnopqrstuvwxyz012345")
  expect(joined).not.toContain("abcdefghijklmnop")
  expect(joined).not.toContain("sk-abcdefghijklmnopqrstuv")
  expect(joined).toContain("[redacted]")

  const failed = publishDialogView({
    state: "failed",
    message: "bad token ghp_abcdefghijklmnopqrstuvwxyz012345",
    language: "en",
  })
  expect(failed.lines.join("\n")).not.toContain("ghp_abcdefghijklmnopqrstuvwxyz012345")
})

test("publishDialogView is empty-safe and state-safe", () => {
  const empty = publishDialogView({ state: "preview", language: "en" })
  expect(empty.success).toBe(false)
  expect(empty.lines.join("\n")).toContain("unknown target")

  const unknown = publishDialogView({
    state: "nope" as PublishDialogState,
    preview: previewFixture,
    language: "en",
  })
  expect(unknown.state).toBe("preview")

  expect(() => publishDialogView(undefined)).not.toThrow()
  expect(() =>
    publishDialogView({
      state: "preview",
      preview: {
        repository: undefined,
        prNumber: Number.NaN,
        url: undefined,
        commentBody: undefined,
        findings: Number.POSITIVE_INFINITY,
      },
    }),
  ).not.toThrow()
})

test("truncateCommentBody defaults to 8 lines and marks truncation", () => {
  const body = Array.from({ length: 10 }, (_, i) => `L${i}`).join("\n")
  const cut = truncateCommentBody(body)
  expect(cut.lines).toHaveLength(8)
  expect(cut.truncated).toBe(true)
  expect(cut.totalLines).toBe(10)

  const short = truncateCommentBody("only")
  expect(short.lines).toEqual(["only"])
  expect(short.truncated).toBe(false)

  const empty = truncateCommentBody(undefined)
  expect(empty.lines).toEqual([])
  expect(empty.truncated).toBe(false)
  expect(empty.totalLines).toBe(0)
})

test("scrubCredentials redacts common token shapes", () => {
  expect(scrubCredentials("ghp_0123456789abcdefghijklmnop")).toContain("[redacted]")
  expect(scrubCredentials("github_pat_0123456789_abcdef")).toContain("[redacted]")
  expect(scrubCredentials("Bearer 0123456789abcdef")).toContain("[redacted]")
  expect(scrubCredentials("password=hunter2")).toContain("[redacted]")
  expect(scrubCredentials("plain prose")).toBe("plain prose")
  expect(scrubCredentials(undefined as unknown as string)).toBe("")
})

// ---------------------------------------------------------------------------
// ShowcasePanel
// ---------------------------------------------------------------------------

test("showcaseView numbers steps and reports readiness as text plus color", () => {
  const view = showcaseView({
    title: "Showcase",
    offlineReady: true,
    realReviewReady: false,
    steps: [
      { step: 1, command: "pr-review demo", purpose: "offline demo" },
      { step: 2, command: "pr-review plan <url>" },
      { step: "B", command: "pr-review review <url>", purpose: "real review" },
    ],
    language: "en",
  })
  expect(view.title).toBe("Showcase")
  expect(view.steps).toHaveLength(3)
  expect(view.steps[0].line).toBe("1. pr-review demo")
  expect(view.steps[1].line).toBe("2. pr-review plan <url>")
  expect(view.steps[2].line).toBe("B. pr-review review <url>")

  expect(view.readiness[0].ready).toBe(true)
  expect(view.readiness[0].color).toBe("#7edc92")
  expect(view.readiness[0].text).toContain("Offline")
  expect(view.readiness[1].ready).toBe(false)
  expect(view.readiness[1].color).toBe("#f3c742")
  expect(view.readiness[1].text).toContain("pending")
})

test("showcaseView handles empty and missing input", () => {
  expect(() => showcaseView(undefined)).not.toThrow()
  expect(() => showcaseView({ steps: null })).not.toThrow()
  const empty = showcaseView({ steps: [], language: "en" })
  expect(empty.steps).toEqual([])
  expect(empty.readiness).toHaveLength(2)
  expect(empty.readiness.every((item) => item.ready === false)).toBe(true)

  const auto = showcaseView({ steps: [{ step: 1 as number | string, command: "x" }] })
  expect(auto.steps[0].line).toContain("1.")
})

// ---------------------------------------------------------------------------
// DemoResultPanel
// ---------------------------------------------------------------------------

const demoFindings: ReviewFinding[] = [
  { severity: "low", title: "log gap", file: "a.py", line_start: 3, evidence_status: "unverified" },
  {
    severity: "critical",
    title: "auth bypass",
    file: "b.py",
    line_start: 12,
    confidence: 0.9,
    evidence_status: "needs_review",
  },
  { severity: "high", title: "sql inject", file: "c.py", evidence_status: "valid" },
]

test("demoView ranks findings and surfaces risk, priority files and evidence", () => {
  const view = demoView({
    caseKey: "sql-injection",
    title: "SQL injection demo",
    description: "seeded case",
    riskLevel: "high",
    priorityFiles: 3,
    findings: demoFindings,
    evidence: { valid: 2, needsReview: 1, invalid: 0, unverified: 1 },
    durationMs: 1500,
    language: "en",
  })
  expect(view.caseKey).toBe("sql-injection")
  expect(view.risk.text).toContain("high")
  expect(view.risk.color).toBe("#fb8147")
  expect(view.priorityFiles).toBe(3)
  expect(view.findings.map((item) => item.title)).toEqual(["auth bypass", "sql inject", "log gap"])
  expect(view.findings[0].severityColor).toBe("#ff6b6b")
  expect(view.findings[0].evidenceText).toContain("Needs review")
  expect(view.evidenceLine).toContain("2")
  expect(view.durationLine).toContain("1.5s")
  expect(view.empty).toBe(false)
})

test("demoView empty and missing fields render neutrally", () => {
  expect(() => demoView(undefined)).not.toThrow()
  expect(() => demoView({ findings: null })).not.toThrow()

  const empty = demoView({ findings: [], language: "en" })
  expect(empty.empty).toBe(true)
  expect(empty.findings).toEqual([])
  expect(empty.priorityFiles).toBe(0)
  expect(empty.risk.text).toContain("unknown")
  expect(empty.durationLine).toBeUndefined()

  const sparse = demoView({
    findings: [{}, { severity: "weird", title: "t" }],
    language: "en",
  })
  expect(sparse.findings).toHaveLength(2)
  expect(sparse.findings[0].location).toBe("—")
  expect(sparse.findings[1].severityColor).toBe("#808080")
})

test("riskBadge maps known levels and degrades safely", () => {
  expect(riskBadge("critical", "en").color).toBe("#ff6b6b")
  expect(riskBadge("HIGH", "en").color).toBe("#fb8147")
  expect(riskBadge("", "en").color).toBe("#808080")
  expect(riskBadge(undefined, "en").text).toContain("unknown")
  expect(riskBadge("nonsense", "en").color).toBe("#808080")
})

// ---------------------------------------------------------------------------
// ReviewActionBar
// ---------------------------------------------------------------------------

test("actionBarView shows publish/filter only when those callbacks are provided", () => {
  const withBoth = actionBarView({
    onPublish: () => {},
    onFilter: () => {},
    language: "en",
  })
  const publish = withBoth.actions.find((action) => action.id === "publish")
  const filter = withBoth.actions.find((action) => action.id === "filter")
  expect(publish).toBeDefined()
  expect(publish?.keyHint).toBe("Alt+P")
  expect(publish?.label).toBe("Publish comment")
  expect(filter).toBeDefined()
  expect(filter?.keyHint).toBe("Ctrl+F")
  expect(filter?.label).toBe("Filter findings")

  const without = actionBarView({ language: "en" })
  expect(without.actions.some((action) => action.id === "publish")).toBe(false)
  expect(without.actions.some((action) => action.id === "filter")).toBe(false)

  const partial = actionBarView({ onFilter: () => {}, language: "en" })
  expect(partial.actions.map((action) => action.id)).toEqual(["filter"])
})

test("actionBarView labels publish/filter in Chinese by default", () => {
  const zh = actionBarView({ onPublish: () => {}, onFilter: () => {} })
  expect(zh.actions.find((action) => action.id === "publish")?.label).toBe("发布评论到 GitHub")
  expect(zh.actions.find((action) => action.id === "filter")?.label).toBe("筛选问题")
  expect(zh.title).toBe("操作")
})

test("actionBarView keeps findings/explain/feedback/export behavior unchanged", () => {
  const en = actionBarView({
    onOpenFindings: () => {},
    onExplain: () => {},
    onFeedback: () => {},
    onExport: () => {},
    language: "en",
  })
  expect(en.actions.map((action) => action.id)).toEqual([
    "findings",
    "explain",
    "feedback",
    "export",
  ])
  expect(en.actions.map((action) => action.keyHint)).toEqual([
    "Ctrl+O",
    "Alt+E",
    "Alt+F",
    "Alt+X",
  ])
  expect(en.title).toBe("ACTIONS")

  const empty = actionBarView({ language: "en" })
  expect(empty.actions).toEqual([])
  expect(empty.emptyText).toBe("No actions available.")
})

// ---------------------------------------------------------------------------
// Overflow budget — closing border survives a short parent
// ---------------------------------------------------------------------------

test("panelContentBudget always reserves the two border rows", () => {
  expect(panelContentBudget(10)).toBe(8)
  expect(panelContentBudget(2)).toBe(0)
  expect(panelContentBudget(1)).toBe(0)
  expect(panelContentBudget(0)).toBe(0)
  expect(panelContentBudget(Number.NaN)).toBe(0)
  expect(panelContentBudget(-5)).toBe(0)
})

test("fitBorderedContent clips over-long content and keeps a bottom border row", () => {
  const lines = Array.from({ length: 20 }, (_, i) => `row ${i + 1}`)
  const fit = fitBorderedContent(lines, 12)
  expect(fit.visible).toHaveLength(10)
  expect(fit.clipped).toBe(true)
  expect(hasClosingBorder(fit.bottomBorderRow)).toBe(true)

  const short = fitBorderedContent(["a", "b"], 24)
  expect(short.visible).toEqual(["a", "b"])
  expect(short.clipped).toBe(false)
  expect(hasClosingBorder(short.bottomBorderRow)).toBe(true)
})

test("fitBorderedContent tolerates junk input", () => {
  expect(() => fitBorderedContent(undefined as unknown as string[], 10)).not.toThrow()
  const junk = fitBorderedContent([null, undefined, "ok"], 10)
  expect(junk.visible).toEqual(["", "", "ok"])
  expect(hasClosingBorder("└──────┘")).toBe(true)
  expect(hasClosingBorder("not a border")).toBe(false)
  expect(hasClosingBorder("")).toBe(false)
})

test("hasClosingBorder rejects content-overwritten border rows", () => {
  // The pre-fix defect painted content over the closing glyph.
  expect(hasClosingBorder("└─✓─Stage─2─label───1.0s─┘")).toBe(false)
  expect(hasClosingBorder("└──────────────────────────────────────┘")).toBe(true)
})
