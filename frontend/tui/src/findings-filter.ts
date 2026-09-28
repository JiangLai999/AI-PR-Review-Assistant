/**
 * Findings filter state shared by the Chat shell and the review workspace.
 *
 * The cycling helpers exist so the keyboard-only filter overlay can be tested
 * without a renderer: `Tab` cycles severity, `Shift+Tab` cycles evidence
 * health, `Ctrl+S` cycles the sort key. Filtering itself is delegated to the
 * review-ui helpers so the workspace list and any other caller agree.
 */

// Import the helpers module directly: the `review-ui` barrel also re-exports
// `.tsx` components, which plain `bun test` cannot load (JSX runtime).
import { filterFindings, sortFindings } from "./review-ui/helpers"
import type { ReviewFinding } from "./review-ui/types"

export const SEVERITY_FILTERS = ["all", "critical", "high", "medium", "low", "info"] as const
export const EVIDENCE_FILTERS = [
  "all",
  "valid",
  "needs_review",
  "invalid",
  "unverified",
] as const
export const SORT_KEYS = ["severity", "file", "confidence"] as const

export type SeverityFilter = (typeof SEVERITY_FILTERS)[number]
export type EvidenceFilter = (typeof EVIDENCE_FILTERS)[number]
export type FindingsSort = (typeof SORT_KEYS)[number]

export type FindingsFilterState = {
  /** Whether the filter row is shown at all. */
  active: boolean
  query: string
  severity: SeverityFilter
  evidence: EvidenceFilter
  sort: FindingsSort
}

export const emptyFindingsFilter = (): FindingsFilterState => ({
  active: false,
  query: "",
  severity: "all",
  evidence: "all",
  sort: "severity",
})

/** Next entry of a cycle, wrapping around; unknown input starts at the head. */
export function cycleValue<T extends string>(cycle: readonly T[], current: T | undefined): T {
  const index = cycle.indexOf(current as T)
  if (index < 0) return cycle[0]
  return cycle[(index + 1) % cycle.length]
}

export function cycleSeverity(state: FindingsFilterState): FindingsFilterState {
  return { ...state, severity: cycleValue(SEVERITY_FILTERS, state.severity) }
}

export function cycleEvidence(state: FindingsFilterState): FindingsFilterState {
  return { ...state, evidence: cycleValue(EVIDENCE_FILTERS, state.evidence) }
}

export function cycleSort(state: FindingsFilterState): FindingsFilterState {
  return { ...state, sort: cycleValue(SORT_KEYS, state.sort) }
}

export function normalizeSort(key: string | undefined): FindingsSort {
  return SORT_KEYS.includes(key as FindingsSort) ? (key as FindingsSort) : "severity"
}

/** True when any criterion narrows the list (the sort key alone does not). */
export function hasActiveCriteria(state: FindingsFilterState | undefined): boolean {
  if (!state) return false
  if (String(state.query ?? "").trim()) return true
  return String(state.severity ?? "all") !== "all" || String(state.evidence ?? "all") !== "all"
}

/**
 * Apply the filter state to a findings list. Malformed input yields an empty
 * list rather than an exception, matching the review-ui helpers.
 */
export function applyFindingsFilter(
  findings: ReviewFinding[] | null | undefined,
  state: FindingsFilterState | undefined,
): ReviewFinding[] {
  const list = Array.isArray(findings) ? findings : []
  const severity = state?.severity && state.severity !== "all" ? state.severity : ""
  const evidence = state?.evidence && state.evidence !== "all" ? state.evidence : ""
  const filtered = filterFindings(list, {
    severity,
    evidence,
    query: String(state?.query ?? ""),
  })
  return sortFindings(filtered, normalizeSort(state?.sort))
}

export function filterCounts(
  findings: ReviewFinding[] | null | undefined,
  state: FindingsFilterState | undefined,
): { shown: number; total: number } {
  const total = Array.isArray(findings) ? findings.length : 0
  return { shown: applyFindingsFilter(findings, state).length, total }
}

/** Short human-readable summary used for the transcript message. */
export function describeFilter(state: FindingsFilterState): string {
  const parts: string[] = []
  if (String(state.query ?? "").trim()) parts.push(`query="${state.query.trim()}"`)
  if (state.severity !== "all") parts.push(`severity=${state.severity}`)
  if (state.evidence !== "all") parts.push(`evidence=${state.evidence}`)
  parts.push(`sort=${normalizeSort(state.sort)}`)
  return parts.join(" · ")
}
