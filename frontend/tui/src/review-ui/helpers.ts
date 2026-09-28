import type { EvidenceCounts, ReviewFinding, SeverityCounts } from "./types"

const SEVERITY_COLORS: Record<string, string> = {
  critical: "#ff6b6b",
  high: "#fb8147",
  medium: "#f3c742",
  low: "#7edc92",
  info: "#808080",
}

const SEVERITY_RANK: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
  info: 4,
}

const SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"] as const

const SEVERITY_GLYPH: Record<(typeof SEVERITY_ORDER)[number], string> = {
  critical: "█",
  high: "▓",
  medium: "▒",
  low: "░",
  info: "·",
}

const UNKNOWN_RANK = 5

export function isEnLanguage(language?: string): boolean {
  return String(language ?? "zh-CN").toLowerCase().startsWith("en")
}

const normalizeToken = (value: string | undefined | null): string =>
  String(value ?? "")
    .trim()
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .toLowerCase()
    .replace(/[\s-]+/g, "_")

export function severityColor(severity: string): string {
  return SEVERITY_COLORS[normalizeToken(severity)] ?? SEVERITY_COLORS.info
}

/**
 * Text badge for evidence health. Always words/glyphs — never color alone.
 * Accepts `needs_review` / `needs-review` / `needsReview` spellings.
 */
export function evidenceBadge(status: string, language?: string): string {
  const en = isEnLanguage(language)
  switch (normalizeToken(status)) {
    case "valid":
      // Vocabulary contract (docs/DEV_RECORD.md §1): the badge names
      // what the validator checked (location + snippet self-consistency),
      // never "the finding is true". The four terms must match the terminal
      // renderer and the GitHub comment.
      return en ? "✓ validated" : "✓ 校验通过"
    case "needs_review":
    case "review":
      return en ? "⚠ needs review" : "⚠ 待人工确认"
    case "invalid":
      return en ? "✗ invalid" : "✗ 校验不成立"
    default:
      return en ? "? unverified" : "? 未校验"
  }
}

export function evidenceColor(status: string): string {
  switch (normalizeToken(status)) {
    case "valid":
      return "#7edc92"
    case "needs_review":
    case "review":
      return "#f3c742"
    case "invalid":
      return "#ff6b6b"
    default:
      return "#808080"
  }
}

/** Format a duration in milliseconds. Missing / invalid input renders as `—`. */
export function formatDuration(ms?: number, language?: string): string {
  if (typeof ms !== "number" || !Number.isFinite(ms) || ms < 0) return "—"
  const en = isEnLanguage(language)
  if (ms < 1000) return `${Math.round(ms)}ms`
  const totalSeconds = ms / 1000
  if (totalSeconds < 60) return `${totalSeconds.toFixed(1)}s`
  const totalMinutes = Math.floor(totalSeconds / 60)
  const seconds = Math.floor(totalSeconds % 60)
  if (totalMinutes < 60) {
    return en
      ? `${totalMinutes}m ${String(seconds).padStart(2, "0")}s`
      : `${totalMinutes}分${String(seconds).padStart(2, "0")}秒`
  }
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  return en
    ? `${hours}h ${String(minutes).padStart(2, "0")}m`
    : `${hours}小时${String(minutes).padStart(2, "0")}分`
}

const clampCount = (value: number | undefined): number =>
  typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0

/**
 * Segmented severity distribution bar. Segments are proportional to counts
 * (largest-remainder allocation), not to the length of any label string.
 */
export function severityBar(counts: SeverityCounts, width = 20): string {
  const size = Number.isFinite(width) && width > 0 ? Math.floor(width) : 20
  const amounts = SEVERITY_ORDER.map((key) => clampCount(counts?.[key]))
  const total = amounts.reduce((sum, value) => sum + value, 0)
  if (total === 0) return "░".repeat(size)

  const exact = amounts.map((value) => (value / total) * size)
  const allocated = exact.map((value) => Math.floor(value))
  let leftover = size - allocated.reduce((sum, value) => sum + value, 0)
  const remainders = exact
    .map((value, index) => ({ index, rest: value - Math.floor(value) }))
    .sort((a, b) => b.rest - a.rest || a.index - b.index)
  for (let i = 0; leftover > 0; i = (i + 1) % remainders.length) {
    allocated[remainders[i].index] += 1
    leftover -= 1
  }
  return SEVERITY_ORDER.map((key, index) => SEVERITY_GLYPH[key].repeat(allocated[index])).join("")
}

/**
 * Share of findings rated critical or high, as a rounded 0–100 percentage.
 * Empty distributions return 0 (never a fake score).
 */
export function severityPercent(counts: SeverityCounts): number {
  const critical = clampCount(counts?.critical)
  const high = clampCount(counts?.high)
  const total = SEVERITY_ORDER.reduce((sum, key) => sum + clampCount(counts?.[key]), 0)
  if (total === 0) return 0
  return Math.round(((critical + high) / total) * 100)
}

/** Stable rank: critical → high → medium → low → info → unknown. Does not mutate input. */
export function rankFindings(findings: ReviewFinding[]): ReviewFinding[] {
  if (!Array.isArray(findings)) return []
  return findings
    .map((finding, index) => ({ finding, index }))
    .sort((a, b) => {
      const rankA = SEVERITY_RANK[normalizeToken(a.finding?.severity)] ?? UNKNOWN_RANK
      const rankB = SEVERITY_RANK[normalizeToken(b.finding?.severity)] ?? UNKNOWN_RANK
      return rankA - rankB || a.index - b.index
    })
    .map((entry) => entry.finding)
}

/** Progress track derived from the numeric percent, never from string length. */
export function progressBar(percent: number, width = 20): string {
  const size = Number.isFinite(width) && width > 0 ? Math.floor(width) : 20
  const clamped =
    typeof percent === "number" && Number.isFinite(percent) ? Math.min(100, Math.max(0, percent)) : 0
  const filled = Math.round((clamped / 100) * size)
  return `${"█".repeat(filled)}${"░".repeat(size - filled)}`
}

export function formatCost(cost?: number): string {
  if (typeof cost !== "number" || !Number.isFinite(cost)) return "—"
  return `$${cost.toFixed(4)}`
}

export function formatConfidence(confidence?: number): string {
  if (typeof confidence !== "number" || !Number.isFinite(confidence)) return ""
  return `${Math.round(confidence * 100)}%`
}

export function severityTotals(counts: SeverityCounts): number {
  return SEVERITY_ORDER.reduce((sum, key) => sum + clampCount(counts?.[key]), 0)
}

export function evidenceTotals(counts: EvidenceCounts): number {
  return clampCount(counts?.valid) + clampCount(counts?.needsReview) + clampCount(counts?.invalid) + clampCount(counts?.unverified)
}

export type FindingsFilter = {
  severity?: string
  evidence?: string
  query?: string
}

export type FindingsSortKey = "severity" | "file" | "confidence"

const isFindingObject = (value: unknown): value is ReviewFinding =>
  typeof value === "object" && value !== null

const searchableText = (finding: ReviewFinding): string =>
  [finding.title, finding.message, finding.problem, finding.file, finding.category, finding.suggestion]
    .map((part) => String(part ?? ""))
    .join(" ")
    .toLowerCase()

/**
 * Filter findings by severity, evidence health, and free-text query.
 * Criteria are AND-ed; blank criteria are ignored. Never throws.
 */
export function filterFindings(
  findings: ReviewFinding[] | null | undefined,
  filter?: FindingsFilter | null,
): ReviewFinding[] {
  const list = Array.isArray(findings) ? findings : []
  const severity = normalizeToken((filter?.severity ?? "") as string)
  const evidence = normalizeToken((filter?.evidence ?? "") as string)
  const query = String(filter?.query ?? "")
    .trim()
    .toLowerCase()

  return list.filter((finding) => {
    if (!isFindingObject(finding)) return false
    if (severity && normalizeToken(finding.severity) !== severity) return false
    if (evidence && normalizeToken(finding.evidence_status) !== evidence) return false
    if (query && !searchableText(finding).includes(query)) return false
    return true
  })
}

const compareIndex = (
  a: { index: number },
  b: { index: number },
): number => a.index - b.index

const confidenceValue = (finding: ReviewFinding): number | undefined => {
  const value = finding?.confidence
  return typeof value === "number" && Number.isFinite(value) ? value : undefined
}

/**
 * Stable sort of findings by severity (critical first), file path, or
 * confidence (highest first). Missing values sink to the end. Never throws
 * and never mutates the input array.
 */
export function sortFindings(
  findings: ReviewFinding[] | null | undefined,
  key: FindingsSortKey = "severity",
): ReviewFinding[] {
  const list = Array.isArray(findings) ? findings : []
  const entries = list.map((finding, index) => ({ finding, index }))

  entries.sort((a, b) => {
    if (key === "file") {
      const fileA = String(a.finding?.file ?? "")
      const fileB = String(b.finding?.file ?? "")
      if (!fileA && !fileB) return compareIndex(a, b)
      if (!fileA) return 1
      if (!fileB) return -1
      return fileA.localeCompare(fileB) || compareIndex(a, b)
    }

    if (key === "confidence") {
      const confA = confidenceValue(a.finding)
      const confB = confidenceValue(b.finding)
      if (confA === undefined && confB === undefined) return compareIndex(a, b)
      if (confA === undefined) return 1
      if (confB === undefined) return -1
      return confB - confA || compareIndex(a, b)
    }

    const rankA = SEVERITY_RANK[normalizeToken(a.finding?.severity)] ?? UNKNOWN_RANK
    const rankB = SEVERITY_RANK[normalizeToken(b.finding?.severity)] ?? UNKNOWN_RANK
    return rankA - rankB || compareIndex(a, b)
  })

  return entries.map((entry) => entry.finding)
}
