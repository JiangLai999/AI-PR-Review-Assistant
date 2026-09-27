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

/** `POST /api/publish` 的状态机：preview = 只渲染不联网，published = 本次新发，already_published = 之前发过但照发。 */
export type PublishStatus = 'preview' | 'published' | 'already_published'

export interface PublishResponse {
  status: PublishStatus
  /** 完整 Markdown 评论正文（预览与成功态都返回，可直接给用户看/复制）。 */
  comment_body: string
  comment_chars: number
  /** 服务端要求二次确认时出现；已发布分支可能省略，判定一律以 status 为准。 */
  requires_confirmation?: boolean
  /** 评论链接，仅 published / already_published 且上游返回时可非空。 */
  comment_url: string
  /** 评论 ID，可能为空串。 */
  comment_id: string
  /** 服务端给的人话状态/警告，可能为空串。 */
  message: string
}

/** 报告导出格式；markdown 与 CLI `export-run` 逐字节一致。 */
export type ReportExportFormat = 'markdown' | 'json'

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
  /** 结构化词条键；空串/缺失 → 前端回落 `label` 原文。 */
  label_key?: string
  detail_key?: string
  fix_hint_key?: string
  /** 上述 key 的插值参数（如 `{login}`）。 */
  params?: Record<string, string | number>
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

/** 下拉选项：值与展示名都来自后端（前端不硬编码词表），label 为中英双语。 */
export interface OptionItem {
  value: string
  label: string
}

/** 数值输入范围（`options.numeric_ranges`）；缺字段时前端退回本地默认 step。 */
export interface NumericRange {
  min?: number
  max?: number
  step?: number
}

/** 设置页可写的 6 个界面/审查偏好，与 CLI 助手的 `preferences` 是同一份。 */
export interface PreferenceView {
  ui_language?: string
  output_format?: string
  chat_layout?: string
  workbench_mode?: string
  repo_context?: string
  review_reasoning_effort?: string
}

/**
 * 下拉清单 + 数值范围。Phase 2 新增；**旧后端不返回这一块**，
 * 设置页据此把对应控件置为禁用（显示"当前后端不支持这一项"），而不是渲染空下拉。
 */
export interface ConfigOptions {
  ui_languages?: OptionItem[]
  output_formats?: OptionItem[]
  chat_layouts?: OptionItem[]
  workbench_modes?: OptionItem[]
  repo_contexts?: OptionItem[]
  review_efforts?: OptionItem[]
  numeric_ranges?: Record<string, NumericRange>
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
  /** 当前生效的偏好值（Phase 2）；旧后端没有这个键。 */
  preferences?: PreferenceView
  /** 可选项清单（Phase 2）；旧后端没有这个键 → 6 个下拉禁用。 */
  options?: ConfigOptions
  /** 运行档位（cloud / local / hybrid / custom…），只读展示，不接受提交。 */
  runtime_profile?: string
}

export interface SaveConfigResponse {
  ok: boolean
  changed: string[]
  message: string
  save_key_used: boolean
  config: ConfigView
  /** 结构化词条键；空串/缺失 → 前端回落 `message` 原文。 */
  message_key?: string
  message_params?: Record<string, string | number>
}

/**
 * `POST /api/config/import-cli` 的响应：把 CLI 侧实际生效的配置导入 Web 那份。
 *
 * 失败形状（以 `ApiError` 抛出，status 供调用点区分）：
 * - 400 未确认 —— `confirm` 不是字面 `true`；
 * - 404 无来源 —— CLI 侧没有任何配置文件，或 Web 配置名不带 `.web` 后缀（反推不出 CLI 路径）；
 * - 400 其它 —— 读取/写入源配置失败。
 * 成功后 `config` 已经是导入后的视图，调用点直接 hydrate，不必再拉一次 `GET /api/config`。
 */
export interface ImportCliConfigResponse {
  ok: boolean
  /** 实际导入来源（CLI 配置的绝对路径）。 */
  imported_from: string
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

/* ------------------------------ Phase 3：追问 ------------------------------ */

/**
 * `POST /api/chat` 的上下文元信息。
 *
 * `bound_run` 是服务端**实际**绑定的 run（请求没带 run_id、或该 run 的上下文取不到时为
 * null），前端据此判断这条回答是否真的读到了审查记录 —— 不要用请求里发出去的 run_id
 * 反推，两者在服务端降级时会不一致。
 */
export interface ChatContextMeta {
  bound_run: string | null
  /** 估算的上下文规模；服务端算不出时为 null，界面就不显示这一句。 */
  token_estimate: number | null
  /** 本次注入的上下文段落名（如 summary / findings / plan）；旧后端可能没有这一层。 */
  sections: string[]
  /** 上下文被裁剪过 → 界面在回答上方显示 note 警告条。 */
  truncated: boolean
  /** 服务端给用户看的提示语；truncated 时通常说明裁掉了什么。 */
  note: string
}

/** 模型用量统计；字段全部可选，服务端拿不到的就不出现。 */
export interface ChatUsage {
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
}

/** `POST /api/chat` 的成功响应（失败形状见 client.ts 的 ApiError.status）。 */
export interface ChatResponse {
  reply: string
  model: string
  /** 用量统计；服务端拿不到时为 null。前端只做展示，不参与任何判定。 */
  usage: ChatUsage | null
  context_meta: ChatContextMeta
  /** 本次模型调用的墙钟耗时（毫秒）。 */
  duration_ms: number
  /** 回答语言（`preferences.language`），与界面语言无关。 */
  language: string
  /** 请求绑定的 run；未绑定普通对话时为空串。 */
  run_id: string
  /** 这一轮是否已写入追问历史；false = 未绑定 run 或写库失败。 */
  persisted: boolean
  /** 以下三个只在 `persisted=true` 时出现。 */
  turn_id?: number
  question_turn_id?: number
  created_at?: string
}

/** `GET /api/chat/history` 的单条记录：user / assistant 各占一条，按 `turn_index` 升序。 */
export interface ChatTurn {
  turn_id: number
  turn_index: number
  role: 'user' | 'assistant'
  content: string
  model: string
  /** user 轮通常为 `{}`。 */
  usage: ChatUsage
  /** user 轮通常为 `{}`；assistant 轮可能是部分字段。 */
  context_meta: Partial<ChatContextMeta> | null
  duration_ms: number | null
  created_at: string
}

export interface ChatHistoryResponse {
  run_id: string
  count: number
  turns: ChatTurn[]
}

/** `POST /api/chat/history/clear` 的响应（幂等：没有记录时 `deleted: 0`）。 */
export interface ClearChatHistoryResponse {
  ok: boolean
  run_id: string
  deleted: number
}
