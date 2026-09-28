import { expect, test } from "bun:test"
import {
  EVIDENCE_FILTERS,
  SEVERITY_FILTERS,
  SORT_KEYS,
  applyFindingsFilter,
  cycleEvidence,
  cycleSeverity,
  cycleSort,
  cycleValue,
  describeFilter,
  emptyFindingsFilter,
  filterCounts,
  hasActiveCriteria,
  normalizeSort,
  type FindingsFilterState,
} from "./findings-filter"
import type { ReviewFinding } from "./review-ui/types"

const findings: ReviewFinding[] = [
  {
    severity: "low",
    title: "Minor style issue",
    file: "src/b.py",
    confidence: 0.4,
    evidence_status: "needs_review",
  },
  {
    severity: "critical",
    title: "SQL injection",
    file: "src/a.py",
    confidence: 0.95,
    evidence_status: "valid",
  },
  {
    severity: "high",
    title: "Missing TLS verify",
    file: "src/c.py",
    confidence: 0.8,
    evidence_status: "valid",
  },
]

test("every cycle starts at its head and wraps around", () => {
  expect(cycleValue(SEVERITY_FILTERS, undefined)).toBe("all")
  expect(cycleValue(SEVERITY_FILTERS, "info")).toBe("all")
  expect(cycleValue(SORT_KEYS, "confidence")).toBe("severity")
  expect(cycleValue(EVIDENCE_FILTERS, "all")).toBe("valid")
})

test("unknown cycle input falls back to the head instead of throwing", () => {
  expect(cycleValue(SEVERITY_FILTERS, "nonsense" as never)).toBe("all")
})

test("cycling keeps every other field intact", () => {
  const start: FindingsFilterState = {
    ...emptyFindingsFilter(),
    query: "sql",
    severity: "high",
    evidence: "valid",
  }
  expect(cycleSeverity(start)).toEqual({ ...start, severity: "medium" })
  expect(cycleEvidence(start)).toEqual({ ...start, evidence: "needs_review" })
  expect(cycleSort(start)).toEqual({ ...start, sort: "file" })
})

test("only narrowing criteria count as active", () => {
  expect(hasActiveCriteria(undefined)).toBe(false)
  expect(hasActiveCriteria(emptyFindingsFilter())).toBe(false)
  expect(hasActiveCriteria({ ...emptyFindingsFilter(), sort: "confidence" })).toBe(false)
  expect(hasActiveCriteria({ ...emptyFindingsFilter(), query: "   " })).toBe(false)
  expect(hasActiveCriteria({ ...emptyFindingsFilter(), query: "sql" })).toBe(true)
  expect(hasActiveCriteria({ ...emptyFindingsFilter(), severity: "critical" })).toBe(true)
  expect(hasActiveCriteria({ ...emptyFindingsFilter(), evidence: "invalid" })).toBe(true)
})

test("no criteria keeps every finding, sorted by severity by default", () => {
  const result = applyFindingsFilter(findings, emptyFindingsFilter())
  expect(result.map((finding) => finding.severity)).toEqual(["critical", "high", "low"])
})

test("severity, evidence and query criteria are AND-ed", () => {
  const severityOnly = applyFindingsFilter(findings, {
    ...emptyFindingsFilter(),
    severity: "high",
  })
  expect(severityOnly.map((finding) => finding.title)).toEqual(["Missing TLS verify"])

  const both = applyFindingsFilter(findings, {
    ...emptyFindingsFilter(),
    severity: "high",
    evidence: "needs_review",
  })
  expect(both).toEqual([])

  const query = applyFindingsFilter(findings, {
    ...emptyFindingsFilter(),
    query: "SQL",
  })
  expect(query.map((finding) => finding.title)).toEqual(["SQL injection"])
})

test("sort keys reorder the filtered list", () => {
  const byFile = applyFindingsFilter(findings, { ...emptyFindingsFilter(), sort: "file" })
  expect(byFile.map((finding) => finding.file)).toEqual(["src/a.py", "src/b.py", "src/c.py"])

  const byConfidence = applyFindingsFilter(findings, {
    ...emptyFindingsFilter(),
    sort: "confidence",
  })
  expect(byConfidence.map((finding) => finding.confidence)).toEqual([0.95, 0.8, 0.4])
})

test("an unknown sort key falls back to severity", () => {
  expect(normalizeSort("nope")).toBe("severity")
  expect(normalizeSort(undefined)).toBe("severity")
  const result = applyFindingsFilter(findings, {
    ...emptyFindingsFilter(),
    sort: "nope" as never,
  })
  expect(result.map((finding) => finding.severity)).toEqual(["critical", "high", "low"])
})

test("malformed input never throws", () => {
  expect(applyFindingsFilter(undefined, emptyFindingsFilter())).toEqual([])
  expect(applyFindingsFilter(null, undefined)).toEqual([])
  expect(applyFindingsFilter([{} as ReviewFinding], emptyFindingsFilter()).length).toBe(1)
  expect(filterCounts(undefined, emptyFindingsFilter())).toEqual({ shown: 0, total: 0 })
})

test("counts report the filtered size against the full size", () => {
  expect(filterCounts(findings, emptyFindingsFilter())).toEqual({ shown: 3, total: 3 })
  expect(filterCounts(findings, { ...emptyFindingsFilter(), severity: "critical" })).toEqual({
    shown: 1,
    total: 3,
  })
})

test("the transcript summary names every active criterion", () => {
  expect(
    describeFilter({ ...emptyFindingsFilter(), query: " sql ", severity: "high", evidence: "valid" }),
  ).toBe('query="sql" · severity=high · evidence=valid · sort=severity')
  expect(describeFilter(emptyFindingsFilter())).toBe("sort=severity")
})
