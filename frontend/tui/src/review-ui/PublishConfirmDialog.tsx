import { For, Show } from "solid-js"
import {
  publishDialogView,
  type PublishDialogState,
  type PublishPreview,
} from "./panel-model"
import { BorderedPanel } from "./BorderedPanel"

export type PublishConfirmDialogProps = {
  open: boolean
  state?: PublishDialogState
  preview?: PublishPreview
  message?: string
  maxBodyLines?: number
  language?: string
}

const STATE_BORDER: Record<PublishDialogState, string> = {
  preview: "#f3c742",
  publishing: "#fb8147",
  published: "#7edc92",
  failed: "#ff6b6b",
  cancelled: "#808080",
}

/**
 * Publish confirmation dialog. Renders nothing when `open === false`.
 *
 * Five states: preview / publishing / published / failed / cancelled.
 * Success text is impossible before `published`; comment body is truncated
 * with an explicit marker (default 8 lines); credential-looking strings are
 * scrubbed before render.
 */
export function PublishConfirmDialog(props: PublishConfirmDialogProps) {
  const state = (): PublishDialogState => props.state ?? "preview"
  const view = () =>
    publishDialogView({
      state: state(),
      preview: props.preview,
      message: props.message,
      maxBodyLines: props.maxBodyLines,
      language: props.language,
    })

  return (
    <Show when={props.open === true}>
      <BorderedPanel borderColor={STATE_BORDER[state()] ?? "#f3c742"}>
        <text height={1} fg={STATE_BORDER[state()] ?? "#f3c742"}>
          {view().title}
        </text>
        <For each={view().lines}>{(line) => <text height={1} fg="#eeeeee">{line}</text>}</For>
        <Show when={view().footer}>
          <text height={1} fg="#808080" marginTop={1}>
            {view().footer}
          </text>
        </Show>
      </BorderedPanel>
    </Show>
  )
}
