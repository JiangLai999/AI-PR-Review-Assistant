/** P5 deterministic OpenTUI layout smoke. Uses a temporary config and text frames. */
import { mkdirSync, writeFileSync } from "node:fs"
import { join, resolve } from "node:path"
import { testRender } from "@opentui/solid"
import { App } from "../src/app"

const output = resolve(import.meta.dir, "../../../_p5_verify/frames")
const BRAND_LINE_COUNT = (frame: string): number => frame.split("\n").filter((line) => line.includes("██")).length
mkdirSync(output, { recursive: true })
for (const [width, height] of [[80, 24], [120, 30], [160, 40]]) {
  const view = await testRender(() => <App />, { width, height })
  try {
    await Bun.sleep(2200)
    await view.renderOnce()
    const frame = view.captureCharFrame()
    writeFileSync(join(output, `${width}x${height}.txt`), frame)
    const lines = frame.split("\n")
    const footer = lines.find((line) => line.includes("Ctrl+P") || line.includes("Shift+Enter")) ?? ""
    console.log(`${width}x${height}: lines=${lines.length}, footer=${footer.trim().slice(0, 100)}`)
    if (!frame.includes("PR REVIEW / CHAT") && !frame.includes("AI PR 审查智能体")) throw new Error(`${width}x${height}: header missing`)
    if (!frame.includes("Ctrl+P")) throw new Error(`${width}x${height}: composer footer missing`)
    if (lines.length - 1 !== height) throw new Error(`${width}x${height}: frame height mismatch`)
    if (width >= 120 && BRAND_LINE_COUNT(frame) !== 5) throw new Error(`${width}x${height}: pixel logo clipped`)
  } finally {
    view.renderer.destroy()
  }
}



