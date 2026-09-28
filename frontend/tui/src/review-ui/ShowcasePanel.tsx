import { For, Show } from "solid-js"
import { showcaseView, type ShowcaseStep } from "./panel-model"
import { BorderedPanel } from "./BorderedPanel"

export type ShowcasePanelProps = {
  title?: string
  offlineReady?: boolean
  realReviewReady?: boolean
  steps: ShowcaseStep[]
  language?: string
}

/**
 * Offline showcase roadmap: numbered steps plus readiness as text+colour.
 * Missing / empty input renders a neutral panel, never a crash.
 */
export function ShowcasePanel(props: ShowcasePanelProps) {
  const isEn = () => String(props.language ?? "zh-CN").toLowerCase().startsWith("en")
  const view = () =>
    showcaseView({
      title: props.title,
      offlineReady: props.offlineReady,
      realReviewReady: props.realReviewReady,
      steps: props.steps,
      language: props.language,
    })

  return (
    <BorderedPanel borderColor="#7edc92">
      <text height={1} fg="#7edc92">
        {view().title}
      </text>

      <For each={view().readiness}>
        {(item, index) => (
          <text height={1} marginTop={index() === 0 ? 1 : 0}>
            <span style={{ fg: "#808080" }}>{index() === 0 ? "offline " : "real "}</span>
            <span style={{ fg: item.color }}>{item.text}</span>
          </text>
        )}
      </For>

      <Show
        when={view().steps.length > 0}
        fallback={
          <text height={1} fg="#808080" marginTop={1}>
            {isEn() ? "No showcase steps." : "暂无演示步骤。"}
          </text>
        }
      >
        <text height={1} fg="#f3c742" marginTop={1}>
          {isEn() ? "Steps" : "步骤"}
        </text>
        <For each={view().steps}>
          {(step) => (
            <box height={1} flexDirection="row">
              <text height={1} fg="#eeeeee" flexGrow={1}>
                {step.line}
              </text>
              <Show when={step.purpose}>
                <text height={1} fg="#808080">
                  {step.purpose}
                </text>
              </Show>
            </box>
          )}
        </For>
      </Show>
    </BorderedPanel>
  )
}
