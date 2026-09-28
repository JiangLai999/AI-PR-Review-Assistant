/**
 * Both entry points that receive a report — a finished review and a run loaded
 * from history — must fill the summary and the findings list together. Filling
 * only one of them left the FINDINGS panel empty and made Ctrl+O a no-op,
 * because it refuses to open without findings.
 */
import type { ReviewFinding } from "./review-ui/types"

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

// ---------------------------------------------------------------------------
// P5 payloads: publish preview, offline demo, showcase script
// ---------------------------------------------------------------------------

/** `ShowcasePanel` props derived from the backend `showcase` payload. */
export type ShowcasePanelData = {
  title?: string
  offlineReady?: boolean
  realReviewReady?: boolean
  steps: { step: number | string; command: string; purpose?: string }[]
}

/** `DemoResultPanel` props derived from the backend `demo` payload. */
export type DemoPanelData = {
  caseKey?: string
  title?: string
  description?: string
  riskLevel?: string
  priorityFiles?: number
  findings: ReviewFinding[]
  evidence?: EvidenceCounts
  durationMs?: number
}

/** `PublishConfirmDialog` preview derived from the backend `publish` payload. */
export type PublishPreviewData = {
  runId?: string
  repository?: string
  prNumber?: number
  url?: string
  commentBody?: string
  findings?: number
  alreadyPublished?: boolean
}

export type PublishPayloadStatus = "preview" | "published" | "failed" | "publishing" | "cancelled"

const asText = (value: unknown): string | undefined =>
  typeof value === "string" && value.length > 0 ? value : undefined

/**
 * Credentials must never reach a dialog: the backend already refuses to echo
 * tokens, and this is the second line of defence for any future payload field.
 */
const REDACTION_PATTERNS: RegExp[] = [
  /\bgh[pousr]_[A-Za-z0-9]{16,}\b/g,
  /\bgithub_pat_[A-Za-z0-9_]{16,}\b/g,
  /\bsk-[A-Za-z0-9_-]{16,}\b/g,
  /\bBearer\s+[A-Za-z0-9._~+/=-]{12,}\b/gi,
]

export function redactCredentials(text: string): string {
  let output = text
  for (const pattern of REDACTION_PATTERNS) output = output.replace(pattern, "[redacted]")
  return output
}

export function showcasePanelFromPayload(payload: unknown): ShowcasePanelData | undefined {
  const record = asRecord(payload)
  const rawSteps = Array.isArray(record.steps) ? record.steps : []
  if (Object.keys(record).length === 0) return undefined
  return {
    title: asText(record.title),
    offlineReady: typeof record.offline_ready === "boolean" ? record.offline_ready : undefined,
    realReviewReady:
      typeof record.real_review_ready === "boolean" ? record.real_review_ready : undefined,
    steps: rawSteps.map((raw, index) => {
      const step = asRecord(raw)
      return {
        step: typeof step.step === "number" || typeof step.step === "string" ? step.step : index + 1,
        command: String(step.command ?? ""),
        purpose: asText(step.purpose),
      }
    }),
  }
}

export function demoPanelFromPayload(payload: unknown): DemoPanelData | undefined {
  const record = asRecord(payload)
  if (Object.keys(record).length === 0) return undefined
  const caseInfo = asRecord(record.case)
  const plan = asRecord(record.plan)
  const findings = Array.isArray(record.findings) ? (record.findings as ReviewFinding[]) : []
  const priorityFiles = Array.isArray(plan.priority_files) ? plan.priority_files.length : undefined
  return {
    caseKey: asText(caseInfo.key),
    title: asText(caseInfo.title),
    description: asText(caseInfo.description),
    riskLevel: asText(plan.risk_level),
    priorityFiles,
    findings,
    evidence: findings.length > 0 ? evidenceCountsFromFindings(findings) : undefined,
  }
}

export function publishPreviewFromPayload(payload: unknown): PublishPreviewData | undefined {
  const record = asRecord(payload)
  const body = asText(record.comment_body)
  const repository = asText(record.repository)
  if (!body && !repository) return undefined
  return {
    runId: asText(record.run_id),
    repository,
    prNumber: typeof record.pr_number === "number" ? record.pr_number : undefined,
    url: asText(record.url),
    commentBody: body ? redactCredentials(body) : undefined,
    findings: typeof record.findings === "number" ? record.findings : undefined,
    alreadyPublished:
      typeof record.already_published === "boolean" ? record.already_published : undefined,
  }
}
