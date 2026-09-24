import { expect, test } from "bun:test"
import { reviewReportPanels } from "./review-report"

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
