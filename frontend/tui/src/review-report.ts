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

export function reviewReportPanels(report: unknown): ReviewReportPanels {
  const record = (report ?? {}) as { summary?: unknown; findings?: unknown }
  return {
    summary: typeof record.summary === "string" ? record.summary : "",
    findings: Array.isArray(record.findings) ? record.findings : [],
  }
}
