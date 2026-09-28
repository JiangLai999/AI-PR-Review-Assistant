/**
 * Shared types for the review workspace presentational components.
 * Props-only: components never talk to the backend.
 */

export type ReviewStageState = {
  id: string
  label: string
  status: "pending" | "active" | "done" | "failed" | "skipped"
  durationMs?: number
  detail?: string
}

export type ReviewFileState = {
  filename: string
  status: "pending" | "reviewed" | "skipped" | "failed"
  findingsCount?: number | null
  durationMs?: number
  reason?: string
  error?: string
}

export type ReviewModelRouting = {
  runtimeProfile?: string
  routerModel?: string
  deepModel?: string
  reason?: string
}

export type SeverityCounts = {
  critical: number
  high: number
  medium: number
  low: number
  info?: number
}

export type EvidenceCounts = {
  valid: number
  needsReview: number
  invalid: number
  unverified: number
}

export type ReviewFinding = {
  severity?: string
  category?: string
  title?: string
  file?: string
  line_start?: number
  line_end?: number
  problem?: string
  message?: string
  suggestion?: string
  confidence?: number
  code_snippet?: string
  sources?: string[]
  evidence_status?: string
  evidence_issues?: string[]
}
