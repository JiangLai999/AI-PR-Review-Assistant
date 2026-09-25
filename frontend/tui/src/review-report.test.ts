import { expect, test } from "bun:test"
import {
  evidenceCountsFromFindings,
  reviewReportPanels,
  reviewWorkspaceFromReport,
  severityCountsFromFindings,
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
