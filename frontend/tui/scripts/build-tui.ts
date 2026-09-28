/**
 * Builds the OpenTUI frontend into a self-contained Bun executable.
 *
 * The Python CLI launches this artifact without any node_modules present, so
 * the build inlines every JS dependency (including @opentui/core) and lets Bun
 * embed the platform's opentui.dll via its `import "./opentui.dll" with { type:
 * "file" }` resolution.
 *
 * Usage:
 *   bun run scripts/build-tui.ts                      # dist/pr-review-tui.exe
 *   bun run scripts/build-tui.ts --js-only --stage    # small Bun-dependent wheel
 *   bun run scripts/build-tui.ts --stage              # optional compiled no-Bun release
 */
import { cpSync, mkdirSync } from "node:fs"
import { basename, join } from "node:path"
import { createSolidTransformPlugin } from "@opentui/solid/bun-plugin"

const jsOnly = process.argv.includes("--js-only")
const stage = process.argv.includes("--stage")
const exePath = "dist/pr-review-tui.exe"
const staticDir = join(import.meta.dir, "..", "..", "..", "src", "ai_pr_review", "tui_static")

const result = await Bun.build({
  entrypoints: ["src/main.tsx"],
  target: "bun",
  plugins: [createSolidTransformPlugin()],
  minify: false,
  sourcemap: "none",
  // @opentui/core emits extra assets (tree-sitter wasm + highlight queries),
  // so the output must be a directory; `--js-only` keeps them loose for
  // debugging while a compiled build embeds them into the executable.
  ...(jsOnly ? { outdir: "dist", naming: "tui.js" } : { compile: { outfile: exePath } }),
})

if (!result.success) {
  for (const log of result.logs) console.error(String(log))
  process.exit(1)
}

for (const output of result.outputs) {
  const size = (output.size / 1024).toFixed(0)
  console.log(`built ${output.path} (${size} KB)`)
}

if (stage && !jsOnly) {
  mkdirSync(staticDir, { recursive: true })
  cpSync(exePath, join(staticDir, basename(exePath)))
  console.log(`staged compiled executable into ${staticDir}`)
}

if (stage && jsOnly) {
  // Bun keeps the platform package external (it resolves the native DLL through
  // node_modules at runtime), so the shipped payload is the bundle, its
  // tree-sitter assets, and that one platform package.
  mkdirSync(staticDir, { recursive: true })
  for (const output of result.outputs) {
    cpSync(output.path, join(staticDir, output.path.split(/[\\/]/).pop()!))
  }
  const platformPackage = join(import.meta.dir, "..", "node_modules", "@opentui", "core-win32-x64")
  const stagedPackage = join(staticDir, "node_modules", "@opentui", "core-win32-x64")
  mkdirSync(stagedPackage, { recursive: true })
  cpSync(platformPackage, stagedPackage, { recursive: true })
  console.log(`staged into ${staticDir}`)
}


