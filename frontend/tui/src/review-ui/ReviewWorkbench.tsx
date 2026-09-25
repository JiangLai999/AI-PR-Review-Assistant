import type { JSX } from "solid-js"
import { Show } from "solid-js"
import { isEnLanguage } from "./helpers"
import type { ReviewFinding } from "./types"
import { effectiveWorkbenchLayout } from "./panel-model"
import { ReviewProgressPanel, type ReviewProgressPanelProps } from "./ReviewProgressPanel"
import { ReviewSummaryPanel, type ReviewSummaryPanelProps } from "./ReviewSummaryPanel"
import { ReviewActionBar } from "./ReviewActionBar"
import { ReviewStatusBar, type ReviewStatusBarProps } from "./ReviewStatusBar"

export type ReviewWorkbenchLayout = "three" | "two" | "bar"

export type ReviewWorkbenchProps = {
  layout: ReviewWorkbenchLayout
  /** 折叠时只渲染状态条 */
  collapsed?: boolean
  progress?: ReviewProgressPanelProps
  summary?: ReviewSummaryPanelProps
  findings?: ReviewFinding[]
  status?: ReviewStatusBarProps
  onOpenFindings?: () => void
  onExplain?: () => void
  onFeedback?: () => void
  onExport?: () => void
  onPublish?: () => void
  onFilter?: () => void
  onToggle?: () => void
  language?: string
  /** 聊天列原样透传，工作台只在它左右排布 */
  children: JSX.Element
}

function EmptyRail(props: { text: string }) {
  return (
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
        {props.text}
      </text>
    </box>
  )
}

/**
 * Review workbench shell: arranges the chat column (`children`) next to the
 * progress / summary / action rails. Display-only; `layout` is supplied by the
 * parent (this component never reads the terminal size). `collapsed` always
 * forces the one-row `bar` presentation.
 */
export function ReviewWorkbench(props: ReviewWorkbenchProps) {
  const en = () => isEnLanguage(props.language)
  const layout = () => effectiveWorkbenchLayout(props.layout, props.collapsed)
  const hasProgress = () => Boolean(props.progress)
  const hasSummary = () => Boolean(props.summary)

  const summaryFindings = (): ReviewFinding[] => {
    if (props.summary && Array.isArray(props.summary.findings)) return props.summary.findings
    return Array.isArray(props.findings) ? props.findings : []
  }

  const statusBar = () => (
    <ReviewStatusBar
      phase={props.status?.phase ?? "idle"}
      progress={props.status?.progress}
      stageLabel={props.status?.stageLabel}
      filesDone={props.status?.filesDone}
      filesTotal={props.status?.filesTotal}
      findingCount={props.status?.findingCount}
      severity={props.status?.severity}
      threshold={props.status?.threshold}
      belowThreshold={props.status?.belowThreshold}
      toggleKey={props.status?.toggleKey}
      language={props.status?.language ?? props.language}
      width={props.status?.width}
    />
  )

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

  const progressPanel = () => (
    <Show
      when={hasProgress()}
      fallback={<EmptyRail text={en() ? "No progress yet." : "暂无进度。"} />}
    >
      <ReviewProgressPanel
        {...props.progress!}
        language={props.progress?.language ?? props.language}
      />
    </Show>
  )

  const summaryPanel = () => (
    <Show
      when={hasSummary()}
      fallback={<EmptyRail text={en() ? "No summary yet." : "暂无摘要。"} />}
    >
      <ReviewSummaryPanel
        {...props.summary!}
        findings={summaryFindings()}
        language={props.summary?.language ?? props.language}
      />
    </Show>
  )

  return (
    <box
      width="100%"
      height="100%"
      backgroundColor="#0a0a0a"
      flexDirection="column"
      overflow="hidden"
    >
      <Show when={layout() === "bar"}>
        <box width="100%" height={1} flexDirection="column" flexShrink={0}>
          {statusBar()}
        </box>
        <box width="100%" flexGrow={1} minHeight={0} flexDirection="column" overflow="hidden">
          {props.children}
        </box>
      </Show>

      <Show when={layout() === "three"}>
        <box width="100%" height="100%" flexDirection="row" overflow="hidden">
          <box width={26} height="100%" flexDirection="column" overflow="hidden" flexShrink={1}>
            {progressPanel()}
          </box>
          <box
            flexGrow={1}
            height="100%"
            flexDirection="column"
            overflow="hidden"
          >
            {statusBar()}
            <box flexGrow={1} minHeight={0} flexDirection="column" overflow="hidden">
              {props.children}
            </box>
          </box>
          <box width={52} height="100%" flexDirection="column" overflow="hidden" flexShrink={1}>
            <box flexGrow={1} minHeight={0} flexDirection="column" overflow="hidden">
              {summaryPanel()}
            </box>
            {actionBar()}
          </box>
        </box>
      </Show>

      <Show when={layout() === "two"}>
        <box width="100%" height="100%" flexDirection="row" overflow="hidden">
          <box
            flexGrow={1}
            height="100%"
            flexDirection="column"
            overflow="hidden"
          >
            {statusBar()}
            <box flexGrow={1} minHeight={0} flexDirection="column" overflow="hidden">
              {props.children}
            </box>
          </box>
          <box width={44} height="100%" flexDirection="column" overflow="hidden" flexShrink={1}>
            <box flexGrow={1} minHeight={0} flexDirection="column" overflow="hidden">
              {progressPanel()}
              {summaryPanel()}
            </box>
            {actionBar()}
          </box>
        </box>
      </Show>
    </box>
  )
}
