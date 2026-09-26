import { For, Show } from "solid-js"
import type { EvidenceCounts, ReviewFinding, SeverityCounts } from "./types"
import {
  evidenceBadge,
  evidenceColor,
  evidenceTotals,
  formatConfidence,
  formatCost,
  formatDuration,
  isEnLanguage,
  rankFindings,
  severityBar,
  severityColor,
  severityPercent,
  severityTotals,
} from "./helpers"

export type ReviewSummaryPanelProps = {
  repository?: string
  prNumber?: number
  /** PR 网址：与 PR 号一起作为"这次审查是谁"的关键指标（历史框同步显示）。 */
  url?: string
  title?: string
  severity: SeverityCounts
  evidence: EvidenceCounts
  filesReviewed: number
  filesSkipped: number
  findings: ReviewFinding[]
  durationSeconds?: number
  cost?: number
  runId?: string
  model?: string
  language?: string
  onOpenFindings?: () => void
}

const SEVERITY_KEYS = ["critical", "high", "medium", "low", "info"] as const

const EVIDENCE_KEYS: Array<keyof EvidenceCounts & string> = [
  "valid",
  "needsReview",
  "invalid",
  "unverified",
]

const EVIDENCE_LABEL: Record<
  keyof EvidenceCounts & string,
  { en: string; zh: string; status: string }
> = {
  valid: { en: "validated", zh: "校验通过", status: "valid" },
  needsReview: { en: "needs review", zh: "待人工确认", status: "needs_review" },
  invalid: { en: "invalid", zh: "校验不成立", status: "invalid" },
  unverified: { en: "unverified", zh: "未校验", status: "unverified" },
}

export function ReviewSummaryPanel(props: ReviewSummaryPanelProps) {
  const en = () => isEnLanguage(props.language)
  const severity = (): SeverityCounts =>
    props.severity ?? { critical: 0, high: 0, medium: 0, low: 0, info: 0 }
  const evidence = (): EvidenceCounts =>
    props.evidence ?? { valid: 0, needsReview: 0, invalid: 0, unverified: 0 }
  const findings = () => (Array.isArray(props.findings) ? props.findings : [])
  const ranked = () => rankFindings(findings()).slice(0, 5)
  const title = () => (en() ? "REVIEW SUMMARY" : "审查摘要")
  const identityLine = () => {
    const bits: string[] = []
    if (props.repository) bits.push(props.repository)
    if (typeof props.prNumber === "number") bits.push(`#${props.prNumber}`)
    if (props.title) bits.push(props.title)
    return bits.length > 0 ? bits.join(" · ") : "—"
  }
  const filesLine = () =>
    `${en() ? "Files" : "文件"} ${props.filesReviewed ?? 0}${en() ? " reviewed · " : " 已审查 · "}${props.filesSkipped ?? 0}${en() ? " skipped · Findings " : " 已跳过 · 问题 "}${findings().length}`
  const metaLine = () => {
    const bits = [
      `${en() ? "Duration" : "耗时"} ${formatDuration((props.durationSeconds ?? 0) * 1000, props.language)}`,
      `${en() ? "Cost" : "成本"} ${formatCost(props.cost)}`,
    ]
    if (props.runId) bits.push(`run ${props.runId}`)
    if (props.model) bits.push(props.model)
    return bits.join(" · ")
  }

  return (
    <box
      width="100%"
      backgroundColor="#1e1e1e"
      borderStyle="single"
      borderColor="#fb8147"
      paddingLeft={1}
      paddingRight={1}
      flexDirection="column"
      overflow="hidden"
      flexShrink={1}
      minHeight={0}
    >
      <box flexGrow={1} minHeight={0} overflow="hidden" flexDirection="column">
      <text height={1} fg="#fb8147">{title()}</text>
      <text height={1} fg="#eeeeee">{identityLine()}</text>
      {/* PR 网址作为关键指标常显：报告/历史/对话都以它为准，而不是 run id。 */}
      <Show when={props.url}>
        <text height={1} fg="#808080">{String(props.url)}</text>
      </Show>

      <text height={1} marginTop={1}>
        <span style={{ fg: "#f3c742" }}>{en() ? "Severity " : "严重级别 "}</span>
        <span style={{ fg: "#fb8147" }}>{severityBar(severity(), 16)}</span>
        <span style={{ fg: "#eeeeee" }}>{` ${severityPercent(severity())}%`}</span>
        <span style={{ fg: "#808080" }}>{en() ? " high+" : " 高危及以上"}</span>
      </text>
      <text height={1}>
        <For each={SEVERITY_KEYS}>
          {(key, index) => (
            <span style={{ fg: severityColor(key) }}>
              {index() > 0 ? "  " : ""}
              {key} {severity()[key] ?? 0}
            </span>
          )}
        </For>
      </text>

      <text height={1} marginTop={1}>
        <span style={{ fg: "#f3c742" }}>{en() ? "Evidence " : "证据校验 "}</span>
        <span style={{ fg: "#808080" }}>
          {en() ? "total" : "合计"} {evidenceTotals(evidence())}
        </span>
      </text>
      <text height={1}>
        <For each={EVIDENCE_KEYS}>
          {(key, index) => {
            const meta = EVIDENCE_LABEL[key]
            return (
              <span style={{ fg: evidenceColor(meta.status) }}>
                {index() > 0 ? "  " : ""}
                {evidenceBadge(meta.status, props.language)} {evidence()[key] ?? 0}
              </span>
            )
          }}
        </For>
      </text>

      <text height={1} fg="#808080" marginTop={1}>{filesLine()}</text>
      <text height={1} fg="#808080">{metaLine()}</text>

      <text height={1} fg="#f3c742" marginTop={1}>
        {en() ? "Top findings" : "重点问题"}
      </text>
      <Show
        when={ranked().length > 0}
        fallback={<text height={1} fg="#808080">{en() ? "No findings." : "暂无问题。"}</text>}
      >
        <For each={ranked()}>
          {(finding, index) => {
            const confidence = () => formatConfidence(finding.confidence)
            const location = () => {
              const base = finding.file ?? "—"
              return typeof finding.line_start === "number" ? `${base}:${finding.line_start}` : base
            }
            return (
              <box flexDirection="column">
                <text height={1}>
                  <span style={{ fg: "#808080" }}>{`${index() + 1}. `}</span>
                  <span style={{ fg: severityColor(finding.severity ?? "info") }}>
                    {`[${String(finding.severity ?? "info").toUpperCase()}]`}
                  </span>
                  <span style={{ fg: "#eeeeee" }}>
                    {` ${finding.title ?? finding.message ?? (en() ? "Untitled" : "未命名问题")}`}
                  </span>
                </text>
                <text height={1} fg="#808080">
                  {location()}
                  <Show when={confidence()}>
                    <span style={{ fg: "#7edc92" }}>{` · ${confidence()}`}</span>
                  </Show>
                  <Show when={finding.evidence_status}>
                    <span style={{ fg: evidenceColor(finding.evidence_status ?? "") }}>
                      {` · ${evidenceBadge(finding.evidence_status ?? "", props.language)}`}
                    </span>
                  </Show>
                </text>
              </box>
            )
          }}
        </For>
      </Show>

      <Show when={Boolean(props.onOpenFindings)}>
        <text height={1} fg="#808080" marginTop={1}>
          {en() ? "Ctrl+O Open findings" : "Ctrl+O 打开 Findings"}
        </text>
      </Show>
      </box>
    </box>
  )
}
