/**
 * Pure presentation models for the Phase 5 panels.
 *
 * Components stay props-only; every string / truncation / state decision lives
 * here so `bun test src` (no JSX) can cover filter bar, publish dialog,
 * showcase, demo and the overflow budget.
 */
import {
  evidenceBadge,
  evidenceColor,
  formatDuration,
  isEnLanguage,
  rankFindings,
  severityColor,
} from "./helpers"
import type { EvidenceCounts, ReviewFinding } from "./types"

// ---------------------------------------------------------------------------
// Width-safe single-line text
// ---------------------------------------------------------------------------

/** Display width with CJK / fullwidth counted as 2 columns. */
export function displayWidth(value: string): number {
  let width = 0
  for (const char of String(value ?? "")) {
    const code = char.codePointAt(0) ?? 0
    width +=
      (code >= 0x1100 && code <= 0x115f) ||
      (code >= 0x2e80 && code <= 0xa4cf) ||
      (code >= 0xac00 && code <= 0xd7a3) ||
      (code >= 0xf900 && code <= 0xfaff) ||
      (code >= 0xfe30 && code <= 0xfe6f) ||
      (code >= 0xff00 && code <= 0xff60) ||
      (code >= 0xffe0 && code <= 0xffe6)
        ? 2
        : 1
  }
  return width
}

/** Hard-clip a single line to `max` columns, appending `…` when cut. */
export function clampLine(value: string, max: number): string {
  const text = String(value ?? "").replace(/[\r\n]+/g, " ")
  const limit = Number.isFinite(max) && max > 0 ? Math.floor(max) : 0
  if (limit === 0) return ""
  if (displayWidth(text) <= limit) return text
  if (limit === 1) return "…"
  const budget = limit - 1
  let out = ""
  let used = 0
  for (const char of text) {
    const w = displayWidth(char)
    if (used + w > budget) break
    out += char
    used += w
  }
  return `${out}…`
}

// ---------------------------------------------------------------------------
// FindingsFilterBar
// ---------------------------------------------------------------------------

export type FilterBarToken = {
  text: string
  active: boolean
}

export type FilterBarModel = {
  active: boolean
  query?: string
  severity?: string
  evidence?: string
  sort?: "severity" | "file" | "confidence"
  shown: number
  total: number
  language?: string
}

export type FilterBarView = {
  /** Single row — never contains a newline. */
  text: string
  tokens: FilterBarToken[]
  hintOnly: boolean
}

function safeCount(value: number | undefined): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? Math.floor(value) : 0
}

/**
 * One-row filter bar model. Inactive renders a `/` hint only; active renders
 * highlighted filter chips plus `shown/total`. Never wraps and never throws on
 * undefined / malformed input.
 */
export function filterBarView(model?: FilterBarModel | null): FilterBarView {
  const en = isEnLanguage(model?.language)
  const shown = safeCount(model?.shown)
  const total = safeCount(model?.total)
  const countText = `${shown}/${total}`
  const active = model?.active === true

  if (!active) {
    // Codex integration edit: the Chat composer owns `/` for slash commands,
    // so the real binding advertised here is `Ctrl+F`.
    const hint = en ? "Ctrl+F to filter" : "Ctrl+F 过滤"
    return {
      text: `${hint} · ${countText}`,
      tokens: [
        { text: hint, active: false },
        { text: `· ${countText}`, active: false },
      ],
      hintOnly: true,
    }
  }

  const tokens: FilterBarToken[] = []
  const query = String(model?.query ?? "").trim()
  const severity = String(model?.severity ?? "").trim()
  const evidence = String(model?.evidence ?? "").trim()
  const sort = model?.sort

  if (query) {
    const label = en ? "q:" : "搜:"
    tokens.push({ text: `${label}${clampLine(query, 24)}`, active: true })
  }
  if (severity) {
    const label = en ? "sev:" : "级:"
    tokens.push({ text: `${label}${clampLine(severity, 12)}`, active: true })
  }
  if (evidence) {
    const label = en ? "ev:" : "证:"
    tokens.push({ text: `${label}${clampLine(evidence, 12)}`, active: true })
  }
  if (sort) {
    const label = en ? "sort:" : "序:"
    tokens.push({ text: `${label}${sort}`, active: true })
  }
  if (tokens.length === 0) {
    tokens.push({ text: en ? "filter on" : "筛选开启", active: true })
  }

  const countToken = { text: countText, active: false }
  const joined = [...tokens, countToken].map((token) => token.text).join("  ")
  return {
    text: clampLine(joined, 78),
    tokens: [...tokens, countToken],
    hintOnly: false,
  }
}

// ---------------------------------------------------------------------------
// PublishConfirmDialog
// ---------------------------------------------------------------------------

export type PublishPreview = {
  runId?: string
  repository?: string
  prNumber?: number
  url?: string
  commentBody?: string
  findings?: number
  alreadyPublished?: boolean
}

export type PublishDialogState = "preview" | "publishing" | "published" | "failed" | "cancelled"

export const PUBLISH_DIALOG_STATES: PublishDialogState[] = [
  "preview",
  "publishing",
  "published",
  "failed",
  "cancelled",
]

const CREDENTIAL_PATTERNS: RegExp[] = [
  /\bgh[pousr]_[A-Za-z0-9]{16,}\b/g,
  /\bgithub_pat_[A-Za-z0-9_]{16,}\b/g,
  /\bsk-[A-Za-z0-9_-]{16,}\b/g,
  /\bAKIA[0-9A-Z]{16}\b/g,
  /\bxox[baprs]-[A-Za-z0-9-]{10,}\b/g,
  /\bBearer\s+[A-Za-z0-9._~+/=-]{12,}\b/gi,
  /\b(api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|password|passwd|secret)\s*[=:]\s*("[^"]+"|'[^']+'|\S+)/gi,
  /-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g,
]

/** Replace credential-looking substrings so the dialog can never leak them. */
export function scrubCredentials(value: string): string {
  let text = String(value ?? "")
  for (const pattern of CREDENTIAL_PATTERNS) {
    text = text.replace(pattern, "[redacted]")
  }
  return text
}

export function truncateCommentBody(
  body?: string,
  maxLines: number = 8,
): { lines: string[]; truncated: boolean; totalLines: number } {
  const raw = String(body ?? "")
  const all = raw.length === 0 ? [] : raw.replace(/\r\n/g, "\n").split("\n")
  const limit = Number.isFinite(maxLines) && maxLines > 0 ? Math.floor(maxLines) : 8
  if (all.length <= limit) {
    return { lines: all.map((line) => clampLine(scrubCredentials(line), 76)), truncated: false, totalLines: all.length }
  }
  return {
    lines: all.slice(0, limit).map((line) => clampLine(scrubCredentials(line), 76)),
    truncated: true,
    totalLines: all.length,
  }
}

export type PublishDialogView = {
  /** Title line. */
  title: string
  /** Body lines ready to render top-to-bottom. */
  lines: string[]
  /** Distinct footer prompt for the current state. */
  footer?: string
  /** Never true before the `published` state. */
  success: boolean
  state: PublishDialogState
}

function targetLine(preview?: PublishPreview | null, en?: boolean): string {
  const repo = String(preview?.repository ?? "").trim()
  const number = typeof preview?.prNumber === "number" && Number.isFinite(preview.prNumber) ? preview.prNumber : undefined
  if (repo && number !== undefined) return `${repo}#${number}`
  if (repo) return repo
  if (number !== undefined) return `#${number}`
  return en ? "unknown target" : "未知目标"
}

/**
 * Build the dialog body for one of the five states.
 *
 * - `preview` shows target / findings / URL / truncated comment body
 * - `published` is the only state that reports success
 * - `failed` prints `message` (credential-scrubbed) verbatim
 * - never emits token-looking strings
 */
export function publishDialogView(opts?: {
  state?: PublishDialogState | null
  preview?: PublishPreview | null
  message?: string
  maxBodyLines?: number
  language?: string
}): PublishDialogView {
  const en = isEnLanguage(opts?.language)
  const requested = opts?.state
  const state: PublishDialogState =
    requested && PUBLISH_DIALOG_STATES.includes(requested) ? requested : "preview"
  const preview = opts?.preview ?? null
  const message = scrubCredentials(String(opts?.message ?? ""))
  const maxBodyLines = opts?.maxBodyLines

  const target = targetLine(preview, en)
  const url = String(preview?.url ?? "").trim()
  const findings =
    typeof preview?.findings === "number" && Number.isFinite(preview.findings)
      ? Math.max(0, Math.floor(preview.findings))
      : undefined

  if (state === "publishing") {
    return {
      state,
      title: en ? "PUBLISHING" : "发布中",
      lines: [
        en ? `Posting review comment to ${target}…` : `正在向 ${target} 发布审查评论…`,
        ...(url ? [clampLine(url, 76)] : []),
      ],
      footer: en ? "Please wait." : "请稍候。",
      success: false,
    }
  }

  if (state === "published") {
    return {
      state,
      title: en ? "PUBLISHED" : "已发布",
      lines: [
        en ? `Review comment posted to ${target}.` : `审查评论已发布到 ${target}。`,
        ...(url ? [clampLine(url, 76)] : []),
        ...(findings !== undefined
          ? [en ? `Findings: ${findings}` : `问题数：${findings}`]
          : []),
        ...(preview?.alreadyPublished
          ? [
              en
                ? "Warning: this run was already published; a second comment was created."
                : "警告：该 run 此前已发布过，本次又创建了一条新评论。",
            ]
          : []),
      ],
      footer: en ? "Esc Close" : "Esc 关闭",
      success: true,
    }
  }

  if (state === "failed") {
    return {
      state,
      title: en ? "PUBLISH FAILED" : "发布失败",
      lines: message
        ? [message]
        : [en ? "Publish failed with no error message." : "发布失败，且未提供错误信息。"],
      footer: en ? "Esc Close · /publish to retry" : "Esc 关闭 · /publish 重试",
      success: false,
    }
  }

  if (state === "cancelled") {
    return {
      state,
      title: en ? "PUBLISH CANCELLED" : "发布已取消",
      lines: [
        en ? `No review comment was created for ${target}.` : `未向 ${target} 发布任何评论。`,
        ...(url ? [clampLine(url, 76)] : []),
      ],
      footer: en ? "Esc Close · /publish to retry" : "Esc 关闭 · /publish 重试",
      success: false,
    }
  }

  // preview
  const body = truncateCommentBody(preview?.commentBody, maxBodyLines ?? 8)
  const lines: string[] = [
    en ? `Target: ${target}` : `目标：${target}`,
    en
      ? `Findings: ${findings ?? 0}`
      : `问题数：${findings ?? 0}`,
    ...(url ? [en ? `URL: ${clampLine(url, 68)}` : `链接：${clampLine(url, 68)}`] : []),
    ...(preview?.alreadyPublished
      ? [
          en
            ? "Warning: already published once in this session; confirming posts a second comment."
            : "警告：本会话已发布过一次，确认后会再发一条评论。",
        ]
      : []),
    en ? `Comment body (${body.totalLines} lines):` : `评论正文（${body.totalLines} 行）：`,
    ...(body.lines.length > 0
      ? body.lines
      : [en ? "(empty comment body)" : "（评论正文为空）"]),
    ...(body.truncated
      ? [
          en
            ? `… truncated, showing ${body.lines.length}/${body.totalLines} lines`
            : `… 已截断，显示 ${body.lines.length}/${body.totalLines} 行`,
        ]
      : []),
  ]

  return {
    state: "preview",
    title: en ? "PUBLISH PREVIEW" : "发布预览",
    lines: lines.map((line) => scrubCredentials(line)),
    footer: en ? "Enter Publish · Esc Cancel" : "Enter 发布 · Esc 取消",
    success: false,
  }
}

// ---------------------------------------------------------------------------
// ShowcasePanel
// ---------------------------------------------------------------------------

export type ShowcaseStep = {
  step: number | string
  command: string
  purpose?: string
}

export type ShowcaseReadiness = {
  text: string
  color: string
  ready: boolean
}

export type ShowcaseView = {
  title: string
  readiness: ShowcaseReadiness[]
  steps: { index: number; line: string; purpose?: string }[]
}

function readinessBadge(
  ready: boolean | undefined,
  en: boolean,
  readyText: string,
  waitText: string,
): ShowcaseReadiness {
  const isReady = ready === true
  return {
    text: isReady ? readyText : waitText,
    color: isReady ? "#7edc92" : "#f3c742",
    ready: isReady,
  }
}

export function showcaseView(opts?: {
  title?: string
  offlineReady?: boolean
  realReviewReady?: boolean
  steps?: ShowcaseStep[] | null
  language?: string
}): ShowcaseView {
  const en = isEnLanguage(opts?.language)
  const steps = Array.isArray(opts?.steps) ? opts.steps : []
  return {
    title: clampLine(String(opts?.title ?? (en ? "SHOWCASE" : "演示路线")), 76),
    readiness: [
      readinessBadge(opts?.offlineReady, en, en ? "Offline ready" : "离线演示就绪", en ? "Offline pending" : "离线演示未就绪"),
      readinessBadge(
        opts?.realReviewReady,
        en,
        en ? "Real review ready" : "真实审查就绪",
        en ? "Real review pending" : "真实审查未就绪",
      ),
    ],
    steps: steps.map((step, index) => {
      const number = step?.step ?? index + 1
      const command = clampLine(String(step?.command ?? ""), 56)
      const purpose = step?.purpose ? clampLine(String(step.purpose), 40) : undefined
      return {
        index: index + 1,
        line: `${String(number)}. ${command}`,
        purpose,
      }
    }),
  }
}

// ---------------------------------------------------------------------------
// DemoResultPanel
// ---------------------------------------------------------------------------

export type DemoEvidence = {
  valid: number
  needsReview: number
  invalid: number
  unverified: number
}

export type RiskBadge = {
  text: string
  color: string
}

export type DemoFindingLine = {
  title: string
  location: string
  severity: string
  severityColor: string
  evidenceText: string
  evidenceColor: string
}

export type DemoView = {
  title: string
  caseKey?: string
  description?: string
  risk: RiskBadge
  priorityFiles: number
  evidence: EvidenceCounts
  evidenceLine: string
  durationLine?: string
  findings: DemoFindingLine[]
  empty: boolean
}

const RISK_COLORS: Record<string, string> = {
  critical: "#ff6b6b",
  high: "#fb8147",
  medium: "#f3c742",
  low: "#7edc92",
  info: "#808080",
}

export function riskBadge(riskLevel?: string, language?: string): RiskBadge {
  const en = isEnLanguage(language)
  const raw = String(riskLevel ?? "").trim()
  if (!raw) {
    return { text: en ? "Risk: unknown" : "风险：未知", color: "#808080" }
  }
  const key = raw.toLowerCase()
  const color = RISK_COLORS[key] ?? severityColor(raw)
  return { text: en ? `Risk: ${raw}` : `风险：${raw}`, color }
}

function evidenceLineOf(evidence: EvidenceCounts, language?: string): string {
  const en = isEnLanguage(language)
  const parts = [
    `${evidenceBadge("valid", language)} ${evidence?.valid ?? 0}`,
    `${evidenceBadge("needs_review", language)} ${evidence?.needsReview ?? 0}`,
    `${evidenceBadge("invalid", language)} ${evidence?.invalid ?? 0}`,
    `${evidenceBadge("unverified", language)} ${evidence?.unverified ?? 0}`,
  ]
  return en ? `Evidence ${parts.join("  ")}` : `证据校验 ${parts.join("  ")}`
}

function toFindingLine(finding: ReviewFinding, language?: string): DemoFindingLine {
  const severity = String(finding?.severity ?? "info")
  const base = String(finding?.file ?? "—")
  const location =
    typeof finding?.line_start === "number" && Number.isFinite(finding.line_start)
      ? `${base}:${finding.line_start}`
      : base
  const evidenceStatus = String(finding?.evidence_status ?? "")
  return {
    title: clampLine(
      String(finding?.title ?? finding?.message ?? (isEnLanguage(language) ? "Untitled" : "未命名问题")),
      56,
    ),
    location: clampLine(location, 48),
    severity: severity.toUpperCase(),
    severityColor: severityColor(severity),
    evidenceText: evidenceStatus ? evidenceBadge(evidenceStatus, language) : "",
    evidenceColor: evidenceStatus ? evidenceColor(evidenceStatus) : "#808080",
  }
}

/**
 * Demo result view-model. Missing / empty fields collapse to neutral copy and
 * never throw. Findings are ranked with `rankFindings` (critical first).
 */
export function demoView(opts?: {
  caseKey?: string
  title?: string
  description?: string
  riskLevel?: string
  priorityFiles?: number
  findings?: ReviewFinding[] | null
  evidence?: Partial<DemoEvidence> | null
  durationMs?: number
  language?: string
}): DemoView {
  const en = isEnLanguage(opts?.language)
  const findings = Array.isArray(opts?.findings) ? opts.findings : []
  const ranked = rankFindings(findings)
  const evidence: EvidenceCounts = {
    valid: safeCount(opts?.evidence?.valid),
    needsReview: safeCount(opts?.evidence?.needsReview),
    invalid: safeCount(opts?.evidence?.invalid),
    unverified: safeCount(opts?.evidence?.unverified),
  }
  const priorityFiles = safeCount(opts?.priorityFiles)
  const durationMs =
    typeof opts?.durationMs === "number" && Number.isFinite(opts.durationMs) && opts.durationMs >= 0
      ? opts.durationMs
      : undefined

  return {
    title: clampLine(String(opts?.title ?? (en ? "DEMO RESULT" : "演示结果")), 76),
    caseKey: opts?.caseKey ? clampLine(String(opts.caseKey), 32) : undefined,
    description: opts?.description ? clampLine(String(opts.description), 76) : undefined,
    risk: riskBadge(opts?.riskLevel, opts?.language),
    priorityFiles,
    evidence,
    evidenceLine: evidenceLineOf(evidence, opts?.language),
    durationLine:
      durationMs === undefined
        ? undefined
        : en
          ? `Duration ${formatDuration(durationMs, opts?.language)}`
          : `耗时 ${formatDuration(durationMs, opts?.language)}`,
    findings: ranked.map((finding) => toFindingLine(finding, opts?.language)),
    empty: ranked.length === 0,
  }
}

// ---------------------------------------------------------------------------
// ReviewActionBar
// ---------------------------------------------------------------------------

export type ActionBarActionId =
  | "findings"
  | "filter"
  | "explain"
  | "feedback"
  | "publish"
  | "export"

export type ActionBarAction = {
  id: ActionBarActionId
  keyHint: string
  label: string
}

export type ActionBarView = {
  title: string
  actions: ActionBarAction[]
  emptyText: string
}

/**
 * Action-bar items for the callbacks that are actually provided.
 * `publish` (Alt+P) and `filter` (Ctrl+F) are optional entries; when their
 * callback is absent the item is omitted entirely — never rendered disabled.
 */
export function actionBarView(opts?: {
  onOpenFindings?: unknown
  onFilter?: unknown
  onExplain?: unknown
  onFeedback?: unknown
  onPublish?: unknown
  onExport?: unknown
  language?: string
}): ActionBarView {
  const en = isEnLanguage(opts?.language)
  const has = (value: unknown) => typeof value === "function"
  const specs: Array<ActionBarAction & { enabled: boolean }> = [
    {
      id: "findings",
      keyHint: "Ctrl+O",
      label: en ? "Findings" : "打开 Findings",
      enabled: has(opts?.onOpenFindings),
    },
    {
      id: "filter",
      keyHint: "Ctrl+F",
      label: en ? "Filter findings" : "筛选问题",
      enabled: has(opts?.onFilter),
    },
    {
      id: "explain",
      keyHint: "Alt+E",
      label: en ? "Explain" : "解释问题",
      enabled: has(opts?.onExplain),
    },
    {
      id: "feedback",
      keyHint: "Alt+F",
      label: en ? "Feedback" : "反馈结果",
      enabled: has(opts?.onFeedback),
    },
    {
      id: "publish",
      keyHint: "Alt+P",
      label: en ? "Publish comment" : "发布评论到 GitHub",
      enabled: has(opts?.onPublish),
    },
    {
      id: "export",
      keyHint: "Alt+X",
      label: en ? "Export" : "导出报告",
      enabled: has(opts?.onExport),
    },
  ]
  return {
    title: en ? "ACTIONS" : "操作",
    emptyText: en ? "No actions available." : "暂无可用操作。",
    actions: specs
      .filter((spec) => spec.enabled)
      .map(({ enabled: _enabled, ...action }) => action),
  }
}

// ---------------------------------------------------------------------------
// Overflow budget — keep the closing border when the parent is short
// ---------------------------------------------------------------------------

/**
 * Content rows a single-border panel may spend inside `outerHeight`.
 * A bordered box always reserves one row for the top border and one for the
 * bottom border, so the closing glyph can survive a short parent.
 */
export function panelContentBudget(outerHeight: number): number {
  const height = Number.isFinite(outerHeight) ? Math.floor(outerHeight) : 0
  return Math.max(0, height - 2)
}

/**
 * Slice content lines to the panel budget. Returns the lines that may be
 * drawn above the bottom border; the caller always draws the border last.
 */
export function fitBorderedContent(lines: Array<string | null | undefined>, outerHeight: number): {
  visible: string[]
  clipped: boolean
  bottomBorderRow: string
} {
  const all = (Array.isArray(lines) ? lines : []).map((line) => String(line ?? ""))
  const budget = panelContentBudget(outerHeight)
  const visible = all.slice(0, budget)
  return {
    visible,
    clipped: all.length > visible.length,
    bottomBorderRow: "└" + "─".repeat(Math.max(0, Math.floor(outerHeight) > 2 ? 20 : 0)) + "┘",
  }
}

/** True when `line` is a single-line box bottom border (`└──┘`). */
export function hasClosingBorder(line: string): boolean {
  return /└─+┘/.test(String(line ?? ""))
}
