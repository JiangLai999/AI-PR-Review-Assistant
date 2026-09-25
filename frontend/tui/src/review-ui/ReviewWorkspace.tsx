import { For, Show } from "solid-js"
import type { ReviewFinding } from "./types"
import {
  evidenceBadge,
  evidenceColor,
  formatConfidence,
  isEnLanguage,
  rankFindings,
  severityColor,
} from "./helpers"
import { ReviewProgressPanel, type ReviewProgressPanelProps } from "./ReviewProgressPanel"
import { ReviewSummaryPanel, type ReviewSummaryPanelProps } from "./ReviewSummaryPanel"
import { ReviewActionBar } from "./ReviewActionBar"

export type ReviewWorkspaceLayout = "wide" | "narrow"

export type ReviewWorkspaceProps = {
  layout: ReviewWorkspaceLayout
  progress?: ReviewProgressPanelProps
  summary?: ReviewSummaryPanelProps
  findings?: ReviewFinding[]
  onOpenFindings?: () => void
  onFilter?: () => void
  onExplain?: () => void
  onFeedback?: () => void
  onPublish?: () => void
  onExport?: () => void
  language?: string
}

function FindingsList(props: { findings: ReviewFinding[]; language?: string }) {
  const en = () => isEnLanguage(props.language)
  const ranked = () => rankFindings(Array.isArray(props.findings) ? props.findings : [])

  return (
    <box
      width="100%"
      backgroundColor="#1e1e1e"
      borderStyle="single"
      borderColor="#f3c742"
      paddingLeft={1}
      paddingRight={1}
      flexDirection="column"
      flexGrow={1}
      overflow="hidden"
      flexShrink={1}
      minHeight={0}
    >
      <box flexGrow={1} minHeight={0} overflow="hidden" flexDirection="column">
      <text height={1} fg="#f3c742">
        {en() ? `FINDINGS (${ranked().length})` : `问题列表 (${ranked().length})`}
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
      </box>
    </box>
  )
}

function FindingsHint(props: { count: number; language?: string; showHint: boolean }) {
  const en = () => isEnLanguage(props.language)
  return (
    <text height={1} fg="#808080">
      {en() ? `Findings ${props.count}` : `问题 ${props.count}`}
      <Show when={props.showHint}>
        <span style={{ fg: "#f3c742" }}>
          {en() ? " · Ctrl+O Open findings" : " · Ctrl+O 打开 Findings"}
        </span>
      </Show>
    </text>
  )
}

export function ReviewWorkspace(props: ReviewWorkspaceProps) {
  const en = () => isEnLanguage(props.language)
  const isWide = () => props.layout === "wide"
  const findings = () => (Array.isArray(props.findings) ? props.findings : [])
  const hasProgress = () => Boolean(props.progress)
  const hasSummary = () => Boolean(props.summary)
  const showHint = () => typeof props.onOpenFindings === "function"

  const actionBar = () => (
    <ReviewActionBar
      onOpenFindings={props.onOpenFindings}
      onFilter={props.onFilter}
      onExplain={props.onExplain}
      onFeedback={props.onFeedback}
      onPublish={props.onPublish}
      onExport={props.onExport}
      language={props.language}
    />
  )

  return (
    <box
      width="100%"
      height="100%"
      backgroundColor="#0a0a0a"
      flexDirection={isWide() ? "row" : "column"}
      overflow="hidden"
    >
      <Show when={isWide()} fallback={null}>
        <box width="50%" height="100%" flexDirection="column" overflow="hidden">
          <box flexGrow={1} minHeight={0} overflow="hidden" flexDirection="column">
            <Show when={hasProgress()}>
              <ReviewProgressPanel {...props.progress!} language={props.progress?.language ?? props.language} />
            </Show>
            <Show when={hasSummary()}>
              <ReviewSummaryPanel {...props.summary!} language={props.summary?.language ?? props.language} />
            </Show>
            <Show when={!hasProgress() && !hasSummary()}>
              <box
                width="100%"
                backgroundColor="#1e1e1e"
                borderStyle="single"
                borderColor="#808080"
                paddingLeft={1}
                paddingRight={1}
                flexDirection="column"
                overflow="hidden"
                flexShrink={1}
                minHeight={0}
              >
                <text height={1} fg="#808080">
                  {en() ? "No progress or summary yet." : "暂无进度或摘要。"}
                </text>
              </box>
            </Show>
          </box>
        </box>
        <box width="50%" height="100%" flexDirection="column" overflow="hidden">
          <FindingsList findings={findings()} language={props.language} />
          {actionBar()}
        </box>
      </Show>

      <Show when={!isWide()}>
        <box flexGrow={1} minHeight={0} overflow="hidden" flexDirection="column">
          <Show when={hasProgress()}>
            <ReviewProgressPanel {...props.progress!} language={props.progress?.language ?? props.language} />
          </Show>
          <Show when={hasSummary()}>
            <ReviewSummaryPanel {...props.summary!} language={props.summary?.language ?? props.language} />
          </Show>
        </box>
        <box flexShrink={0} flexDirection="column">
          <FindingsHint count={findings().length} language={props.language} showHint={showHint()} />
          {actionBar()}
        </box>
      </Show>
    </box>
  )
}
