import { For } from "solid-js"
import { filterBarView, type FilterBarModel } from "./panel-model"

export type FindingsFilterBarProps = FilterBarModel

/**
 * Exactly one row high. Active filters are highlighted; `active === false`
 * shows a hint-only row suggesting `/`. Never wraps and never exceeds its
 * width (tokens are already clamped by `filterBarView`).
 */
export function FindingsFilterBar(props: FindingsFilterBarProps) {
  const view = () =>
    filterBarView({
      active: props.active === true,
      query: props.query,
      severity: props.severity,
      evidence: props.evidence,
      sort: props.sort,
      shown: props.shown,
      total: props.total,
      language: props.language,
    })

  return (
    <box
      width="100%"
      height={1}
      flexDirection="row"
      overflow="hidden"
      backgroundColor={view().hintOnly ? "#0a0a0a" : "#1e1e1e"}
      paddingLeft={1}
      paddingRight={1}
    >
      <text height={1} width="100%">
        <For each={view().tokens}>
          {(token, index) => (
            <span style={{ fg: token.active ? "#f3c742" : "#808080" }}>
              {index() === 0 ? token.text : `  ${token.text}`}
            </span>
          )}
        </For>
      </text>
    </box>
  )
}
