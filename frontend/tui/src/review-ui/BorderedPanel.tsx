import type { JSX } from "solid-js"
import { Show } from "solid-js"

/**
 * Bordered panel shell that keeps its closing border visible.
 *
 * When the parent hands out less height than the content wants, OpenTUI would
 * otherwise paint the last content row over the bottom border (or push the
 * border out of the clipped viewport). The shell:
 *   - shrinks to the parent budget (`flexShrink` + `minHeight={0}`)
 *   - clips its content inside an inner column (`overflow="hidden"`)
 * so the bottom border is always the last drawn row of the panel.
 */
export type BorderedPanelProps = {
  borderColor?: string
  backgroundColor?: string
  flexGrow?: number
  children: JSX.Element
}

export function BorderedPanel(props: BorderedPanelProps) {
  return (
    <box
      width="100%"
      backgroundColor={props.backgroundColor ?? "#1e1e1e"}
      borderStyle="single"
      borderColor={props.borderColor ?? "#808080"}
      paddingLeft={1}
      paddingRight={1}
      flexDirection="column"
      overflow="hidden"
      flexShrink={1}
      minHeight={0}
      flexGrow={props.flexGrow}
    >
      <box flexGrow={1} minHeight={0} overflow="hidden" flexDirection="column">
        {props.children}
      </box>
    </box>
  )
}
