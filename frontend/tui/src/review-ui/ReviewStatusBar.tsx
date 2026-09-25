import { statusBarView } from "./panel-model"
import type { SeverityCounts } from "./types"

/**
 * One-row workbench status line. Display-only — never talks to the backend and
 * never reads the terminal size (the parent may pass `width` as a clamp budget).
 */
export type ReviewStatusBarProps = {
  phase: "running" | "done" | "idle"
  progress?: number
  stageLabel?: string
  filesDone?: number
  filesTotal?: number
  findingCount?: number
  severity?: SeverityCounts
  threshold?: number | null
  belowThreshold?: number | null
  toggleKey?: string
  language?: string
  /** Optional clamp budget in columns; omit to skip clamping. */
  width?: number
}

export function ReviewStatusBar(props: ReviewStatusBarProps) {
  const view = () =>
    statusBarView({
      phase: props.phase,
      progress: props.progress,
      stageLabel: props.stageLabel,
      filesDone: props.filesDone,
      filesTotal: props.filesTotal,
      findingCount: props.findingCount,
      severity: props.severity,
      threshold: props.threshold,
      belowThreshold: props.belowThreshold,
      toggleKey: props.toggleKey,
      language: props.language,
      maxWidth: props.width,
    })

  return (
    <box height={1} width="100%" flexDirection="row" overflow="hidden" flexShrink={0}>
      <text height={1} fg="#eeeeee">
        {view().text}
      </text>
    </box>
  )
}
