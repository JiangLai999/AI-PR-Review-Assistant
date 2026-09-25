import { For, Show } from "solid-js"
import { isEnLanguage } from "./helpers"

export type ReviewActionBarProps = {
  onOpenFindings?: () => void
  onExplain?: () => void
  onFeedback?: () => void
  onExport?: () => void
  language?: string
}

type ActionSpec = {
  id: "findings" | "explain" | "feedback" | "export"
  keyHint: string
  en: string
  zh: string
  handler?: () => void
}

export function ReviewActionBar(props: ReviewActionBarProps) {
  const en = () => isEnLanguage(props.language)

  const actions = (): ActionSpec[] =>
    (
      [
        {
          id: "findings",
          keyHint: "Ctrl+O",
          en: "Findings",
          zh: "打开 Findings",
          handler: props.onOpenFindings,
        },
        {
          id: "explain",
          keyHint: "Alt+E",
          en: "Explain",
          zh: "解释问题",
          handler: props.onExplain,
        },
        {
          id: "feedback",
          keyHint: "Alt+F",
          en: "Feedback",
          zh: "反馈结果",
          handler: props.onFeedback,
        },
        {
          id: "export",
          keyHint: "Alt+X",
          en: "Export",
          zh: "导出报告",
          handler: props.onExport,
        },
      ] satisfies ActionSpec[]
    ).filter((action) => typeof action.handler === "function")

  const title = () => (en() ? "ACTIONS" : "操作")

  return (
    <box
      width="100%"
      backgroundColor="#1e1e1e"
      borderStyle="single"
      borderColor="#7edc92"
      paddingLeft={1}
      paddingRight={1}
      flexDirection="column"
    >
      <text height={1} fg="#7edc92">{title()}</text>
      <Show
        when={actions().length > 0}
        fallback={
          <text height={1} fg="#808080">
            {en() ? "No actions available." : "暂无可用操作。"}
          </text>
        }
      >
        <For each={actions()}>
          {(action) => (
            <text height={1} fg="#eeeeee">
              <span style={{ fg: "#f3c742" }}>{action.keyHint}</span>
              <span style={{ fg: "#eeeeee" }}>{` ${en() ? action.en : action.zh}`}</span>
            </text>
          )}
        </For>
      </Show>
    </box>
  )
}
