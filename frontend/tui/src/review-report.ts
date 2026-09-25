/**
 * Both entry points that receive a report — a finished review and a run loaded
 * from history — must fill the summary and the findings list together. Filling
 * only one of them left the FINDINGS panel empty and made Ctrl+O a no-op,
 * because it refuses to open without findings.
 */
export type ReviewReportPanels = {
  summary: string
  findings: unknown[]
}

export type SeverityCounts = {
  critical: number
  high: number
  medium: number
  low: number
  info: number
}

export type EvidenceCounts = {
  valid: number
  needsReview: number
  invalid: number
  unverified: number
}

export type ReviewWorkspaceData = {
  summary: string
  findings: unknown[]
  severity: SeverityCounts
  evidence: EvidenceCounts
  filesReviewed: number
  filesSkipped: number
  durationSeconds?: number
  cost?: number
  runId?: string
  repository?: string
  prNumber?: number
  title?: string
}

type RecordLike = Record<string, unknown>

const asRecord = (value: unknown): RecordLike =>
  value && typeof value === "object" ? (value as RecordLike) : {}

const asNumber = (value: unknown, fallback = 0): number =>
  typeof value === "number" && Number.isFinite(value) ? value : fallback

const normalizeSeverity = (value: unknown): keyof SeverityCounts => {
  const severity = String(value ?? "").trim().toLowerCase()
  if (severity === "critical" || severity === "high" || severity === "medium" || severity === "low") {
    return severity
  }
  return "info"
}

export function reviewReportPanels(report: unknown): ReviewReportPanels {
  const record = asRecord(report)
  return {
    summary: typeof record.summary === "string" ? record.summary : "",
    findings: Array.isArray(record.findings) ? record.findings : [],
  }
}

export function severityCountsFromFindings(findings: unknown[]): SeverityCounts {
  const counts: SeverityCounts = { critical: 0, high: 0, medium: 0, low: 0, info: 0 }
  for (const finding of findings) {
    counts[normalizeSeverity(asRecord(finding).severity)] += 1
  }
  return counts
}

export function evidenceCountsFromFindings(findings: unknown[]): EvidenceCounts {
  const counts: EvidenceCounts = { valid: 0, needsReview: 0, invalid: 0, unverified: 0 }
  for (const finding of findings) {
    const status = String(asRecord(finding).evidence_status ?? "unverified").trim().toLowerCase()
    if (status === "valid") counts.valid += 1
    else if (status === "needs_review" || status === "needs-review" || status === "review") {
      counts.needsReview += 1
    } else if (status === "invalid") counts.invalid += 1
    else counts.unverified += 1
  }
  return counts
}

const severityFromReport = (report: RecordLike, findings: unknown[]): SeverityCounts => {
  const counts = asRecord(asRecord(report.counts).by_severity)
  if (Object.keys(counts).length > 0) {
    return {
      critical: asNumber(counts.critical),
      high: asNumber(counts.high),
      medium: asNumber(counts.medium),
      low: asNumber(counts.low),
      info: asNumber(counts.info),
    }
  }
  return severityCountsFromFindings(findings)
}

const evidenceFromReport = (report: RecordLike, findings: unknown[]): EvidenceCounts => {
  const validation = asRecord(asRecord(report.run).validation)
  if (Object.keys(validation).length > 0) {
    return {
      valid: asNumber(validation.valid),
      needsReview: asNumber(validation.needs_review ?? validation.needsReview),
      invalid: asNumber(validation.invalid),
      unverified: asNumber(validation.unverified),
    }
  }
  return evidenceCountsFromFindings(findings)
}

export function reviewWorkspaceFromReport(report: unknown): ReviewWorkspaceData {
  const record = asRecord(report)
  const findings = Array.isArray(record.findings) ? record.findings : []
  const pr = asRecord(record.pr)
  const run = asRecord(record.run)
  return {
    summary: typeof record.summary === "string" ? record.summary : "",
    findings,
    severity: severityFromReport(record, findings),
    evidence: evidenceFromReport(record, findings),
    filesReviewed: asNumber(pr.files_reviewed),
    filesSkipped: asNumber(pr.files_skipped),
    durationSeconds:
      typeof run.duration_seconds === "number" ? run.duration_seconds : undefined,
    cost: typeof run.total_cost === "number" ? run.total_cost : undefined,
    runId: typeof run.id === "string" ? run.id : undefined,
    repository: typeof pr.repository === "string" ? pr.repository : undefined,
    prNumber: typeof pr.number === "number" ? pr.number : undefined,
    title: typeof pr.title === "string" ? pr.title : undefined,
  }
}
