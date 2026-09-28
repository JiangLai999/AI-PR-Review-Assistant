/** P5 focused-select versus Shift+Arrow interaction verification. */
import { testRender } from "@opentui/solid"
import { FindingsDialog } from "../src/app"

const view = await testRender(
  () => <FindingsDialog
    findings={[
      { title: "FIRST FINDING", file: "src/a.py", severity: "high", line_start: 1, problem: ["DETAIL TOP", ...Array.from({ length: 18 }, (_, i) => `FIRST ONLY LINE ${i}`)].join("\n"), suggestion: "DETAIL BOTTOM" },
      { title: "SECOND FINDING", file: "src/b.py", severity: "low", line_start: 2, problem: "second detail" },
    ]}
    onClose={() => {}} />,
  { width: 100, height: 30, kittyKeyboard: true },
)
try {
  await view.renderOnce()
  const before = view.captureCharFrame()
  for (let i = 0; i < 8; i++) {
    view.mockInput.pressArrow("down", { shift: true })
    await view.renderOnce()
  }
  await view.renderOnce()
  const after = view.captureCharFrame()
  console.log(`before-first=${before.includes("DETAIL TOP")}, after-first=${after.includes("DETAIL TOP")}`)
  console.log(`after-second=${after.includes("second detail")}, frame-changed=${before !== after}`)
  if (!before.includes("DETAIL TOP")) throw new Error("Initial detail fixture did not render")
  if (!after.includes("FIRST ONLY LINE")) throw new Error("First finding detail was lost")
  if (after.includes("second detail")) throw new Error("Shift+Down changed focused finding")
  if (before === after || after.includes("DETAIL TOP")) throw new Error("Shift+Down did not move the detail viewport")
} finally {
  view.renderer.destroy()
}

