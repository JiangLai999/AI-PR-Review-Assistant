import { For, Show } from "solid-js"
import { actionBarView } from "./panel-model"

export type ReviewActionBarProps = {
  onOpenFindings?: () => void
  onFilter?: () => void
  onExplain?: () => void
  onFeedback?: () => void
  onPublish?: () => void
  onExport?: () => void
  language?: string
}

export function ReviewActionBar(props: ReviewActionBarProps) {
  const view = () =>
    actionBarView({
      onOpenFindings: props.onOpenFindings,
      onFilter: props.onFilter,
      onExplain: props.onExplain,
      onFeedback: props.onFeedback,
      onPublish: props.onPublish,
      onExport: props.onExport,
      language: props.language,
    })

  return (
    <box
      width="100%"
      backgroundColor="#1e1e1e"
      borderStyle="single"
      borderColor="#7edc92"
      paddingLeft={1}
      paddingRight={1}
      flexDirection="column"
      overflow="hidden"
      flexShrink={1}
      minHeight={0}
    >
      <box flexGrow={1} minHeight={0} overflow="hidden" flexDirection="column">
      <text height={1} fg="#7edc92">{view().title}</text>
      <Show
        when={view().actions.length > 0}
        fallback={
          <text height={1} fg="#808080">
            {view().emptyText}
          </text>
        }
      >
        <For each={view().actions}>
          {(action) => (
            <text height={1} fg="#eeeeee">
              <span style={{ fg: "#f3c742" }}>{action.keyHint}</span>
              <span style={{ fg: "#eeeeee" }}>{` ${action.label}`}</span>
            </text>
          )}
        </For>
      </Show>
      </box>
    </box>
  )
}
