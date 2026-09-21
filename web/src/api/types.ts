/** 后端 API 的数据契约，与 ai_pr_review/web_server.py 的响应保持一致。 */

export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'info'
export type EvidenceStatus = 'valid' | 'needs_review' | 'invalid' | 'unverified'
export type FeedbackStatus = 'accepted' | 'rejected' | 'fixed' | 'needs_review'

export interface Evidence {
  file: string
  line_start: number
  line_end: number
  changed_line?: boolean
  code_snippet?: string
  source?: string
  validation_status?: EvidenceStatus
  validation_messages?: string[]
}

export interface Finding {
  severity: Severity
  category: string
  file: string
  line_start: number
  line_end: number
  title: string
  problem: string
  suggestion: string
  confidence: number
  code_snippet?: string
  finding_id?: string
  sources?: string[]
  evidence?: Evidence[]
  evidence_status?: EvidenceStatus
  evidence_issues?: string[]
}

export interface ReviewResult {
  summary: string
  findings: Finding[]
}

export interface ReviewPlan {
  intent: string
  risk_level: string
  risk_categories: string[]
  priority_files: string[]
  skipped_files: string[]
  strategies: string[]
  requires_cross_file_analysis: boolean
  estimated_file_reviews: number
  rationale: string[]
}

export interface InterfaceImpact {
  symbol: string
  kind: string
  file: string
  line: number
  change: string
  label: string
  before: string
  after: string
  affected_files: string[]
  references: { file: string; line: number }[]
  is_breaking: boolean
}

export interface FilterReason {
  code: string
  action: string
  message: string
  details?: Record<string, unknown>
}

export interface FilterEntry {
  filename: string
  included: boolean
  reasons?: FilterReason[]
}

export interface FilterResult {
  total_files: number
  included_count: number
  excluded_count: number
  excluded_reason_counts: Record<string, number>
  results: FilterEntry[]
}

export interface PRInfo {
  pr_number?: number
  title?: string
  url?: string
  repository?: string
  files_changed?: number
  files_reviewed?: number
  files_skipped?: number
  author?: string
  head_sha?: string
}

export interface RunInfo {
  id?: string | null
  duration_seconds?: number
  total_cost?: number
  dry_run?: boolean
}

export interface ReviewResponse {
  pr: PRInfo
  filter: FilterResult
  plan: ReviewPlan | null
  validation: Record<string, number>
  review?: ReviewResult
  cross_file_impacts: unknown[]
  interface_impacts: InterfaceImpact[]
  run: RunInfo
}

export interface HistoryRun {
  id: string
  pr_url: string
  pr_number?: number
  repo_owner?: string
  repo_name?: string
  total_findings?: number
  critical_findings?: number
  high_findings?: number
  total_cost?: number
  duration_seconds?: number
  model?: string
  created_at: string
}

export interface HistoryResponse {
  runs: HistoryRun[]
  statistics: Record<string, string | number>
}

export interface ReportResponse {
  run_id: string
  run: Partial<HistoryRun>
  review: ReviewResult
  plan: ReviewPlan | null
  validation: Record<string, number>
  cross_file_impacts: unknown[]
  interface_impacts: InterfaceImpact[]
  feedback: { run_id: string; finding_id: string; status: string; note: string; created_at: string }[]
}

export interface BenchmarkCaseOutcome {
  case_id: string
  true_positives: number
  false_positives: number
  false_negatives: number
  precision: number
  recall: number
  f1: number
  line_accuracy: number
}

export interface CredentialItem {
  key: string
  label: string
  ok: boolean
  detail: string
  fix_hint: string
  configured: boolean
}

export interface CredentialReport {
  ok: boolean
  items: CredentialItem[]
}

export interface ProviderPreset {
  name: string
  display_name: string
  base_url: string
  api_format: string
  default_model: string
}

export interface ConfigView {
  config_path: string
  github_token_set: boolean
  github_token_masked: string
  provider_name: string
  base_url: string
  model: string
  api_format: string
  api_key_set: boolean
  api_key_masked: string
  settings: Record<string, string | number | boolean>
  available_providers: ProviderPreset[]
}

export interface SaveConfigResponse {
  ok: boolean
  changed: string[]
  message: string
  save_key_used: boolean
  config: ConfigView
}

export type JobStatus = 'queued' | 'running' | 'cancelling' | 'done' | 'failed' | 'cancelled'

export interface JobSnapshot {
  job_id: string
  pr_url: string
  status: JobStatus
  total_files: number
  completed_files: number
  current_file: string
  progress: number
  error: string
  elapsed_seconds: number
  run_id: string | null
  result?: ReviewResponse
}

export interface JobEvent extends JobSnapshot {
  event: string
  filename?: string
  stage?: string
  message?: string
}

export interface MetaResponse {
  rule_count: number
  provider_count: number
  tree_sitter_available: boolean
  cross_file_review_enabled: boolean
  static_analysis_enabled: boolean
  model: string
}

export interface BenchmarkReport {
  strategy: string
  case_count: number
  true_positives: number
  false_positives: number
  false_negatives: number
  precision: number
  recall: number
  f1: number
  false_positive_rate: number
  line_accuracy: number
  cases: BenchmarkCaseOutcome[]
}

export interface DemoCaseSummary { key: string; title: string; description: string }
export interface DemoCasesResponse { cases: DemoCaseSummary[] }
export interface DemoResult {
  case: DemoCaseSummary
  pr: PRInfo
  filter: FilterResult
  plan: ReviewPlan
  findings: Finding[]
  summary: { risk_level: string; finding_count: number; evidence_validated: number; cost: number }
}
