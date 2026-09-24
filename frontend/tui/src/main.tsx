import { render } from "@opentui/solid"
import { ErrorBoundary } from "solid-js"
import { App } from "./app"
// exitOnCtrlC is disabled so the app owns Ctrl+C: an in-flight turn is
// cancelled in place, and only an idle Ctrl+C exits (see Composer).
render(
  () => <ErrorBoundary fallback={(error) => <box><text fg="red">{String(error)}</text></box>}><App /></ErrorBoundary>,
  { exitOnCtrlC: false },
).catch((error) => console.error(error))
