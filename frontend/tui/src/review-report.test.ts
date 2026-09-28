import { expect, test } from "bun:test"
import {
  demoPanelFromPayload,
  evidenceCountsFromFindings,
  publishPreviewFromPayload,
  redactCredentials,
  reviewReportPanels,
  reviewWorkspaceFromReport,
  severityCountsFromFindings,
  showcasePanelFromPayload,
} from "./review-report"

test("a report fills both the summary and the findings list", () => {
  const panels = reviewReportPanels({
    summary: "审查完成，发现 9 个问题",
    findings: [{ title: "a" }, { title: "b" }],
  })
  expect(panels.summary).toBe("审查完成，发现 9 个问题")
  expect(panels.findings).toHaveLength(2)
})

test("a report without findings still yields a usable, empty list", () => {
  const panels = reviewReportPanels({ summary: "clean" })
  expect(panels.summary).toBe("clean")
  expect(panels.findings).toEqual([])
})

test("a malformed or missing report never throws", () => {
  expect(reviewReportPanels(undefined)).toEqual({ summary: "", findings: [] })
  expect(reviewReportPanels({ summary: 42, findings: "nope" })).toEqual({
    summary: "",
    findings: [],
  })
})

test("severity and evidence counts normalize finding fields", () => {
  const findings = [
    { severity: "critical", evidence_status: "valid" },
    { severity: "HIGH", evidence_status: "needs_review" },
    { severity: "medium", evidence_status: "invalid" },
    { severity: "low" },
    { severity: "unknown", evidence_status: "needs-review" },
  ]

  expect(severityCountsFromFindings(findings)).toEqual({
    critical: 1,
    high: 1,
    medium: 1,
    low: 1,
    info: 1,
  })
  expect(evidenceCountsFromFindings(findings)).toEqual({
    valid: 1,
    needsReview: 2,
    invalid: 1,
    unverified: 1,
  })
})

test("workspace data uses report counts when present", () => {
  const workspace = reviewWorkspaceFromReport({
    summary: "review summary",
    counts: { total_findings: 9, by_severity: { critical: 2, high: 7 } },
    findings: [{ severity: "low" }],
    pr: {
      repository: "owner/repo",
      number: 31,
      title: "Fix auth",
      files_reviewed: 18,
      files_skipped: 4,
    },
    run: {
      id: "run-1",
      duration_seconds: 42.3,
      total_cost: 0.0124,
      validation: { valid: 8, needs_review: 1 },
    },
  })

  expect(workspace.severity).toEqual({
    critical: 2,
    high: 7,
    medium: 0,
    low: 0,
    info: 0,
  })
  expect(workspace.evidence).toEqual({
    valid: 8,
    needsReview: 1,
    invalid: 0,
    unverified: 0,
  })
  expect(workspace.filesReviewed).toBe(18)
  expect(workspace.filesSkipped).toBe(4)
  expect(workspace.runId).toBe("run-1")
  expect(workspace.repository).toBe("owner/repo")
  expect(workspace.prNumber).toBe(31)
})
test("showcase payload maps into ShowcasePanel props", () => {
  const data = showcasePanelFromPayload({
    title: "AI PR Review Assistant · Competition Showcase",
    offline_ready: true,
    real_review_ready: false,
    steps: [
      { step: 1, command: "pr-review doctor", purpose: "检查环境" },
      { command: "pr-review demo --case sql-injection" },
    ],
  })
  expect(data?.title).toContain("Showcase")
  expect(data?.offlineReady).toBe(true)
  expect(data?.realReviewReady).toBe(false)
  expect(data?.steps.length).toBe(2)
  // A step without a number falls back to its 1-based position.
  expect(data?.steps[1].step).toBe(2)
  expect(showcasePanelFromPayload({})).toBeUndefined()
  expect(showcasePanelFromPayload(null)).toBeUndefined()
})

test("demo payload maps into DemoResultPanel props with evidence counts", () => {
  const data = demoPanelFromPayload({
    case: { key: "sql-injection", title: "SQL 注入", description: "参数拼接" },
    plan: { risk_level: "high", priority_files: ["a.py", "b.py"] },
    findings: [
      { severity: "critical", title: "SQL injection", file: "a.py", evidence_status: "valid" },
      { severity: "medium", title: "Weak hash", file: "b.py", evidence_status: "needs_review" },
    ],
  })
  expect(data?.caseKey).toBe("sql-injection")
  expect(data?.riskLevel).toBe("high")
  expect(data?.priorityFiles).toBe(2)
  expect(data?.findings.length).toBe(2)
  expect(data?.evidence).toEqual({ valid: 1, needsReview: 1, invalid: 0, unverified: 0 })
  // An entirely empty payload has nothing to show; a partial one still renders.
  expect(demoPanelFromPayload({})).toBeUndefined()
  expect(demoPanelFromPayload({ case: { key: "clean-change" } })?.findings).toEqual([])
})

test("publish preview maps and redacts credential-shaped text", () => {
  const data = publishPreviewFromPayload({
    status: "preview",
    run_id: "run-1",
    repository: "example/repo",
    pr_number: 7,
    url: "https://github.com/example/repo/pull/7",
    comment_body: "## Review\ntoken: ghp_abcdefghijklmnopqrstuvwx",
    findings: 3,
    already_published: false,
  })
  expect(data?.runId).toBe("run-1")
  expect(data?.prNumber).toBe(7)
  expect(data?.findings).toBe(3)
  expect(data?.alreadyPublished).toBe(false)
  expect(data?.commentBody).toContain("[redacted]")
  expect(data?.commentBody).not.toContain("ghp_abcdefghijklmnopqrstuvwx")
  expect(publishPreviewFromPayload({})).toBeUndefined()
})

test("credential redaction covers the known key shapes", () => {
  expect(redactCredentials("sk-abcdefghijklmnopqrstuvwx")).toBe("[redacted]")
  expect(redactCredentials("ghp_abcdefghijklmnopqrstuvwx")).toBe("[redacted]")
  expect(redactCredentials("Bearer abcdefghijklmnop")).toBe("[redacted]")
  expect(redactCredentials("no secrets here")).toBe("no secrets here")
})
