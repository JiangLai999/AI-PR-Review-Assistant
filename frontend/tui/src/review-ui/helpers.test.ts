import { expect, test } from "bun:test"
import {
  evidenceBadge,
  evidenceColor,
  formatConfidence,
  formatCost,
  formatDuration,
  progressBar,
  rankFindings,
  severityBar,
  severityColor,
  severityPercent,
  severityTotals,
} from "./helpers"
import type { ReviewFinding, SeverityCounts } from "./types"

test("severityColor maps known severities and never throws on junk", () => {
  expect(severityColor("critical")).toBe("#ff6b6b")
  expect(severityColor("HIGH")).toBe("#fb8147")
  expect(severityColor("medium")).toBe("#f3c742")
  expect(severityColor("low")).toBe("#7edc92")
  expect(severityColor("info")).toBe("#808080")
  expect(severityColor("")).toBe("#808080")
  expect(severityColor("nope")).toBe("#808080")
  expect(severityColor(undefined as unknown as string)).toBe("#808080")
})

test("evidenceBadge is text-first and accepts alternate spellings", () => {
  expect(evidenceBadge("valid", "en")).toBe("✓ Valid")
  expect(evidenceBadge("needs_review", "en")).toBe("⚠ Needs review")
  expect(evidenceBadge("needs-review", "en")).toBe("⚠ Needs review")
  expect(evidenceBadge("needsReview", "en")).toBe("⚠ Needs review")
  expect(evidenceBadge("invalid", "en")).toBe("✗ Invalid")
  expect(evidenceBadge("unverified", "en")).toBe("? Unverified")
  expect(evidenceBadge("valid")).toBe("✓ 有效")
  expect(evidenceBadge("needs_review")).toBe("⚠ 待复核")
  expect(evidenceBadge("")).toBe("? 未验证")
  expect(evidenceBadge(undefined as unknown as string)).toBe("? 未验证")
})

test("evidenceColor covers the four health states", () => {
  expect(evidenceColor("valid")).toBe("#7edc92")
  expect(evidenceColor("needs_review")).toBe("#f3c742")
  expect(evidenceColor("invalid")).toBe("#ff6b6b")
  expect(evidenceColor("unverified")).toBe("#808080")
})

test("formatDuration renders missing values as an em dash", () => {
  expect(formatDuration()).toBe("—")
  expect(formatDuration(undefined, "en")).toBe("—")
  expect(formatDuration(Number.NaN)).toBe("—")
  expect(formatDuration(Number.POSITIVE_INFINITY)).toBe("—")
  expect(formatDuration(-5)).toBe("—")
})

test("formatDuration scales from milliseconds to hours", () => {
  expect(formatDuration(0)).toBe("0ms")
  expect(formatDuration(420)).toBe("420ms")
  expect(formatDuration(1200, "en")).toBe("1.2s")
  expect(formatDuration(25_800, "en")).toBe("25.8s")
  expect(formatDuration(125_000, "en")).toBe("2m 05s")
  expect(formatDuration(125_000)).toBe("2分05秒")
  expect(formatDuration(3_725_000, "en")).toBe("1h 02m")
  expect(formatDuration(3_725_000)).toBe("1小时02分")
})

test("severityBar is empty-safe and proportional to counts", () => {
  const empty: SeverityCounts = { critical: 0, high: 0, medium: 0, low: 0, info: 0 }
  expect(severityBar(empty, 8)).toBe("░░░░░░░░")
  expect(severityBar(empty)).toHaveLength(20)
  expect(severityBar({} as SeverityCounts, 4)).toBe("░░░░")

  const onlyCritical: SeverityCounts = { critical: 4, high: 0, medium: 0, low: 0 }
  expect(severityBar(onlyCritical, 4)).toBe("████")

  // 1 critical + 1 low over width 4 → one of each glyph, then remainder to critical.
  const mixed = severityBar({ critical: 1, high: 0, medium: 0, low: 1, info: 0 }, 4)
  expect(mixed).toHaveLength(4)
  expect(mixed.split("█").length - 1).toBe(2)
  expect(mixed.split("░").length - 1).toBe(2)
})

test("severityBar survives missing fields and odd widths", () => {
  const partial = severityBar({ critical: 2 } as SeverityCounts, 10)
  expect(partial).toBe("██████████")
  expect(severityBar({ critical: 1, high: 1, medium: 1, low: 1 }, 0)).toHaveLength(20)
  expect(severityBar({ critical: 1, high: 1, medium: 1, low: 1 }, -3)).toHaveLength(20)
})

test("severityPercent is the critical+high share and never invents a score", () => {
  const empty: SeverityCounts = { critical: 0, high: 0, medium: 0, low: 0 }
  expect(severityPercent(empty)).toBe(0)
  expect(severityPercent({} as SeverityCounts)).toBe(0)
  expect(severityPercent({ critical: 1, high: 0, medium: 0, low: 0 })).toBe(100)
  expect(severityPercent({ critical: 0, high: 0, medium: 2, low: 2 })).toBe(0)
  expect(severityPercent({ critical: 1, high: 2, medium: 1, low: 0 })).toBe(75)
  expect(severityPercent({ critical: 1, high: 1, medium: 1, low: 1, info: 0 })).toBe(50)
})

test("severityTotals ignores non-finite noise", () => {
  expect(severityTotals({ critical: 1, high: 2, medium: 3, low: 4, info: 5 })).toBe(15)
  expect(severityTotals({ critical: Number.NaN, high: -1, medium: 0, low: 2 } as SeverityCounts)).toBe(2)
})

test("rankFindings orders by severity and keeps relative stability", () => {
  const findings: ReviewFinding[] = [
    { title: "low-a", severity: "low" },
    { title: "critical-a", severity: "critical" },
    { title: "unknown", severity: "weird" },
    { title: "high-a", severity: "high" },
    { title: "critical-b", severity: "CRITICAL" },
    { title: "missing" },
  ]
  const ranked = rankFindings(findings)
  expect(ranked.map((item) => item.title)).toEqual([
    "critical-a",
    "critical-b",
    "high-a",
    "low-a",
    "unknown",
    "missing",
  ])
  // input untouched
  expect(findings[0].title).toBe("low-a")
})

test("rankFindings tolerates empty and malformed lists", () => {
  expect(rankFindings([])).toEqual([])
  expect(rankFindings(undefined as unknown as ReviewFinding[])).toEqual([])
  expect(rankFindings(null as unknown as ReviewFinding[])).toEqual([])
  const single = [{ title: "only" }]
  expect(rankFindings(single)).toEqual(single)
})

test("formatCost and formatConfidence handle missing values", () => {
  expect(formatCost()).toBe("—")
  expect(formatCost(0.0124)).toBe("$0.0124")
  expect(formatCost(Number.NaN)).toBe("—")
  expect(formatConfidence()).toBe("")
  expect(formatConfidence(0.95)).toBe("95%")
  expect(formatConfidence(0)).toBe("0%")
  expect(formatConfidence(0.5)).toBe("50%")
})

test("progressBar is driven by the numeric percent, not label length", () => {
  expect(progressBar(0, 10)).toBe("░░░░░░░░░░")
  expect(progressBar(50, 10)).toBe("█████░░░░░")
  expect(progressBar(100, 10)).toBe("██████████")
  expect(progressBar(-20, 4)).toBe("░░░░")
  expect(progressBar(250, 4)).toBe("████")
  expect(progressBar(Number.NaN, 4)).toBe("░░░░")
  expect(progressBar(50)).toHaveLength(20)
})
