/** Human Windows Terminal verification for Finding focus + Shift+Arrow. */
import { render } from "@opentui/solid"
import { FindingsDialog } from "../src/app"

// No backend, network, token, or user config is read by this fixture.
render(
  () => <FindingsDialog
    findings={[
      {
        title: "FIRST FINDING — keep selected",
        file: "src/example.py",
        severity: "high",
        line_start: 1,
        problem: ["DETAIL TOP", ...Array.from({ length: 22 }, (_, index) => `FIRST ONLY LINE ${index}`)].join("\n"),
        suggestion: "DETAIL BOTTOM — scroll target",
      },
      {
        title: "SECOND FINDING — must stay unselected",
        file: "src/second.py",
        severity: "low",
        line_start: 2,
        problem: "SECOND DETAIL — error if this appears on Shift+Down",
      },
    ]}
    onClose={() => process.exit(0)}
  />,
  { exitOnCtrlC: true },
).catch((error) => {
  console.error(error)
  process.exitCode = 1
})
