import { For, Show } from "solid-js"
import type { ReviewFileState, ReviewModelRouting, ReviewStageState } from "./types"
import { formatCost, formatDuration, isEnLanguage, progressBar } from "./helpers"

export type ReviewProgressPanelProps = {
  url: string
  stageId: string
  stageLabel: string
  progress: number
  stages: ReviewStageState[]
  filesDone: number
  filesTotal?: number
  currentFile?: string
  fileStates?: ReviewFileState[]
  routing?: ReviewModelRouting
  elapsedMs?: number
  cost?: number
  language?: string
  onCancel?: () => void
}

const STATUS_GLYPH: Record<ReviewStageState["status"], string> = {
  pending: "·",
  active: "▶",
  done: "✓",
  failed: "✗",
  skipped: "−",
}

const FILE_GLYPH: Record<ReviewFileState["status"], string> = {
  pending: "·",
  reviewed: "✓",
  skipped: "−",
  failed: "✗",
}

const STATUS_COLOR: Record<ReviewStageState["status"], string> = {
  pending: "#808080",
  active: "#fb8147",
  done: "#7edc92",
  failed: "#ff6b6b",
  skipped: "#808080",
}

const clampPercent = (value: number): number => {
  if (typeof value !== "number" || !Number.isFinite(value)) return 0
  return Math.min(100, Math.max(0, value))
}

export function ReviewProgressPanel(props: ReviewProgressPanelProps) {
  const en = () => isEnLanguage(props.language)
  const percent = () => clampPercent(props.progress)
  const stages = () => (Array.isArray(props.stages) ? props.stages : [])
  const fileStates = () => (Array.isArray(props.fileStates) ? props.fileStates : [])
  const title = () => (en() ? "REVIEW PROGRESS" : "审查进度")
  const stageLine = () => {
    const label = props.stageLabel || props.stageId || "—"
    return props.stageLabel && props.stageId ? `${label} (${props.stageId})` : label
  }
  const filesLine = () => {
    const done = Number.isFinite(props.filesDone) ? Math.max(0, props.filesDone) : 0
    const total =
      typeof props.filesTotal === "number" && Number.isFinite(props.filesTotal)
        ? Math.max(0, props.filesTotal)
        : undefined
    const counts = total === undefined ? `${done}` : `${done}/${total}`
    return props.currentFile
      ? `${en() ? "Files" : "文件"} ${counts} · ${props.currentFile}`
      : `${en() ? "Files" : "文件"} ${counts}`
  }
  const metaLine = () =>
    `${en() ? "Elapsed" : "已用时"} ${formatDuration(props.elapsedMs, props.language)} · ${en() ? "Cost" : "成本"} ${formatCost(props.cost)}`
  const hasRouting = () =>
    Boolean(props.routing?.runtimeProfile || props.routing?.routerModel || props.routing?.deepModel)

  return (
    <box
      width="100%"
      backgroundColor="#1e1e1e"
      borderStyle="single"
      borderColor="#fb8147"
      paddingLeft={1}
      paddingRight={1}
      flexDirection="column"
    >
      <text height={1} fg="#fb8147">{title()}</text>
      <text height={1} fg="#eeeeee">{props.url || "—"}</text>
      <text height={1} fg="#808080">{stageLine()}</text>
      <text height={1}>
        <span style={{ fg: "#fb8147" }}>{progressBar(percent(), 16)}</span>
        <span style={{ fg: "#eeeeee" }}>{` ${percent().toFixed(0)}%`}</span>
      </text>
      <text height={1} fg="#808080">{filesLine()}</text>
      <text height={1} fg="#808080">{metaLine()}</text>

      <Show when={stages().length > 0}>
        <text height={1} fg="#f3c742" marginTop={1}>{en() ? "Stages" : "阶段"}</text>
        <For each={stages()}>
          {(stage) => {
            const tail = () => {
              const parts: string[] = []
              if (typeof stage.durationMs === "number" && Number.isFinite(stage.durationMs)) {
                parts.push(formatDuration(stage.durationMs, props.language))
              }
              if (stage.detail) parts.push(stage.detail)
              return parts.join(" · ")
            }
            return (
              <box height={1} flexDirection="row">
                <text width={2} height={1} fg={STATUS_COLOR[stage.status] ?? "#808080"}>
                  {STATUS_GLYPH[stage.status] ?? "·"}
                </text>
                <text height={1} flexGrow={1} fg="#eeeeee">{stage.label || stage.id}</text>
                <text height={1} fg="#808080">{tail()}</text>
              </box>
            )
          }}
        </For>
      </Show>

      <Show when={fileStates().length > 0}>
        <text height={1} fg="#f3c742" marginTop={1}>{en() ? "File list" : "文件列表"}</text>
        <For each={fileStates()}>
          {(file) => {
            const tail = () => {
              const parts: string[] = []
              if (typeof file.findingsCount === "number") {
                parts.push(`${file.findingsCount}${en() ? " findings" : " 个问题"}`)
              }
              if (file.reason) parts.push(file.reason)
              if (file.error) parts.push(file.error)
              return parts.join(" · ")
            }
            return (
              <box height={1} flexDirection="row">
                <text width={2} height={1} fg={file.status === "failed" ? "#ff6b6b" : "#808080"}>
                  {FILE_GLYPH[file.status] ?? "·"}
                </text>
                <text height={1} flexGrow={1} fg="#eeeeee">{file.filename}</text>
                <text height={1} fg={file.error ? "#ff6b6b" : "#808080"}>{tail()}</text>
              </box>
            )
          }}
        </For>
      </Show>

      <Show when={hasRouting()}>
        <text height={1} fg="#f3c742" marginTop={1}>{en() ? "Routing" : "模型路由"}</text>
        <text height={1} fg="#eeeeee">
          {[
            props.routing?.runtimeProfile,
            props.routing?.routerModel ? `router ${props.routing.routerModel}` : "",
            props.routing?.deepModel ? `deep ${props.routing.deepModel}` : "",
          ]
            .filter(Boolean)
            .join(" · ")}
        </text>
        <Show when={props.routing?.reason}>
          <text height={1} fg="#808080">{props.routing?.reason}</text>
        </Show>
      </Show>

      <Show when={Boolean(props.onCancel)}>
        <text height={1} fg="#808080" marginTop={1}>
          {en() ? "Esc Cancel" : "Esc 取消审查"}
        </text>
      </Show>
    </box>
  )
}
