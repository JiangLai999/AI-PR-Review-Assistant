/**
 * P5 integration check for the Chat shell (Codex acceptance harness).
 *
 * Part A renders the real `App` against a real Python backend with an isolated
 * config under the OS temp directory, then types the new slash commands and
 * reads the frames. Part B renders the new overlays directly with fixtures,
 * because the findings filter only opens once findings exist and a live review
 * needs GitHub credentials.
 *
 * Run from `frontend/tui`. The App spawns the Python backend, and Bun only
 * forwards the environment the Bun process started with, so the config path
 * must be set by the shell before launch:
 *
 *   $env:P5_CHECK_ONLY='app'                                            # parts A + B
 *   $env:AI_PR_REVIEW_CONFIG='<isolated config.json>'
 *   bun --preload @opentui/solid/preload scripts/p5-app-integration-check.tsx
 *   $env:P5_CHECK_ONLY='publish'; $env:AI_PR_REVIEW_CONFIG='<seeded config.json>'
 *   bun --preload @opentui/solid/preload scripts/p5-app-integration-check.tsx
 */
import { testRender } from "@opentui/solid"
import { mkdirSync, readFileSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import {
  App,
  DemoOverlay,
  FindingsFilterOverlay,
  PublishOverlay,
  ShowcaseOverlay,
} from "../src/app"
import { emptyFindingsFilter } from "../src/findings-filter"

const repoRoot = join(import.meta.dir, "..", "..", "..")
const configDir = join(tmpdir(), "ai-pr-review-p5-app-check")
mkdirSync(configDir, { recursive: true })

process.env.AI_PR_REVIEW_ROOT = repoRoot
process.env.PYTHONPATH = join(repoRoot, "src")
process.env.AI_PR_REVIEW_PYTHON = process.env.AI_PR_REVIEW_PYTHON ?? "python"

const configuredPath = (process.env.AI_PR_REVIEW_CONFIG ?? "").trim()

const failures: string[] = []

function check(condition: boolean, label: string, detail = "") {
  if (condition) {
    console.log(`  PASS  ${label}`)
  } else {
    failures.push(label)
    console.log(`  FAIL  ${label}${detail ? ` :: ${detail}` : ""}`)
  }
}

/** Persist a frame and echo the lines a reviewer needs to judge a failure. */
function dumpFrame(frame: string, label: string) {
  const safe = label.replace(/[^A-Za-z0-9]+/g, "-")
  const path = join(configDir, `frame-${safe}.txt`)
  writeFileSync(path, frame, "utf8")
  console.log(`  frame saved: ${path}`)
  const interesting = frame
    .split("\n")
    .filter((line) => /pr-review|步骤|演示|STEPS/i.test(line))
    .slice(0, 8)
  for (const line of interesting) console.log(`  | ${line.trim()}`)
}

/**
 * Poll the rendered frame until `pattern` matches or the deadline passes.
 *
 * A real publish round-trip (PyGithub client + HTTPS POST) can take far longer
 * than a fixed settle window, and the first live run proved it: the dialog was
 * still on 正在发布 when the fixed 3s window closed, even though the comment
 * had already been created. Returns the last frame plus the elapsed time so the
 * caller can assert on the terminal state instead of on wall-clock luck.
 */
async function waitForFrame(
  view: { renderOnce: () => Promise<void>; captureCharFrame: () => string },
  pattern: RegExp,
  timeoutMs = 120_000,
): Promise<{ frame: string; elapsedMs: number }> {
  const started = Date.now()
  let frame = view.captureCharFrame()
  while (Date.now() - started < timeoutMs) {
    if (pattern.test(frame)) return { frame, elapsedMs: Date.now() - started }
    await new Promise((resolve) => setTimeout(resolve, 200))
    await view.renderOnce()
    frame = view.captureCharFrame()
  }
  return { frame, elapsedMs: Date.now() - started }
}

async function settle(view: { renderOnce: () => Promise<void> }, times = 12) {
  // The backend is a child process: give the protocol round-trip room to land.
  for (let i = 0; i < times; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 120))
    await view.renderOnce()
  }
}

/**
 * Slash commands that take an argument complete on the first Enter instead of
 * running, so `/demo` needs two Enters while `/showcase` needs one. The panels
 * close on Enter, so the harness must never send an extra one.
 */
async function runCommand(
  view: {
    mockInput: {
      pressKey: (key: string, modifiers?: Record<string, boolean>) => void
      pressBackspace: () => void
      typeText: (text: string) => Promise<void>
      pressEnter: () => void
    }
    renderOnce: () => Promise<void>
  },
  command: string,
  enters = 1,
) {
  view.mockInput.pressKey("a", { ctrl: true })
  view.mockInput.pressBackspace()
  await view.mockInput.typeText(command)
  for (let i = 0; i < enters; i += 1) {
    view.mockInput.pressEnter()
    await settle(view, i + 1 < enters ? 3 : 12)
  }
  await settle(view)
}

async function appFlows() {
  console.log("\n[A] integrated App against the real backend")
  const view = await testRender(() => <App />, { width: 100, height: 34, kittyKeyboard: true })
  try {
    await settle(view)
    const boot = view.captureCharFrame()
    check(/PR REVIEW|AI PR/i.test(boot), "App boots and renders the chat shell", boot.slice(0, 120))

    // `/demo` runs entirely offline.
    await runCommand(view, "/demo", 2)
    const demoFrame = view.captureCharFrame()
    check(/离线运行|DEMO/i.test(demoFrame), "`/demo` opens the offline demo panel")
    check(/风险|RISK/i.test(demoFrame), "demo panel shows the risk line")
    check(/Esc/.test(demoFrame), "demo panel advertises its close key")

    view.mockInput.pressEscape()
    await settle(view, 4)
    check(!/离线运行/.test(view.captureCharFrame()), "Escape closes the demo panel")

    // `/showcase` prints the competition path.
    await runCommand(view, "/showcase")
    const showcaseFrame = view.captureCharFrame()
    check(/Showcase|演示/.test(showcaseFrame), "`/showcase` opens the showcase panel")
    const hasDoctor = /doctor/.test(showcaseFrame)
    check(hasDoctor, "showcase panel lists the doctor step")
    if (!hasDoctor) dumpFrame(showcaseFrame, "showcase")
    view.mockInput.pressEscape()
    await settle(view, 4)
    check(!/pr-review doctor/.test(view.captureCharFrame()), "Escape closes the showcase panel")

    // Ctrl+F without a report must explain how to get findings.
    view.mockInput.pressKey("f", { ctrl: true })
    await settle(view)
    const noFindings = view.captureCharFrame()
    check(/Findings|问题/.test(noFindings), "Ctrl+F without findings answers with guidance")
    check(!/FINDINGS FILTER/.test(noFindings), "the filter overlay does not open without findings")

    // Alt+P without a report must fail with actionable text, never a bogus post.
    view.mockInput.pressKey("p", { meta: true })
    // Exercises `waitForFrame` on a terminal state we can reach offline.
    const { frame: publishFrame, elapsedMs } = await waitForFrame(
      view,
      /发布失败|发布预览|已发布/,
      60_000,
    )
    check(/PUBLISH/i.test(publishFrame), "Alt+P opens the publish dialog")
    check(
      /FAILED|失败/i.test(publishFrame),
      `publishing without a run reports a failure instead of success (${elapsedMs}ms)`,
      publishFrame.slice(0, 200),
    )
    check(
      !/已发布|published/i.test(publishFrame),
      "the dialog never claims success when the preview failed",
    )
    view.mockInput.pressEscape()
    await settle(view, 4)
  } finally {
    view.renderer.destroy()
  }
}

async function overlayStates() {
  console.log("\n[B] overlay states with fixtures")
  const preview = {
    runId: "run-42",
    repository: "example/repo",
    prNumber: 7,
    url: "https://github.com/example/repo/pull/7",
    commentBody: ["## 🤖 PR Review", "", "### Summary", "| Metric | Value |"]
      .concat(Array.from({ length: 20 }, (_, i) => `body line ${i}`))
      .join("\n"),
    findings: 4,
    alreadyPublished: false,
  }

  for (const [state, expectText] of [
    ["preview", "发布预览"],
    ["publishing", "发布"],
    ["published", "已发布"],
    ["failed", "失败"],
    ["cancelled", "取消"],
  ] as const) {
    const view = await testRender(
      () => (
        <PublishOverlay
          state={state}
          preview={preview}
          message={state === "failed" ? "上游错误：GitHub API 500" : "状态说明"}
          language="zh-CN"
          busy={false}
          onConfirm={() => {}}
          onCancel={() => {}}
          onClose={() => {}}
        />
      ),
      { width: 100, height: 30, kittyKeyboard: true },
    )
    try {
      await view.renderOnce()
      const frame = view.captureCharFrame()
      check(new RegExp(expectText).test(frame), `publish dialog renders the ${state} state`)
      if (state === "preview") {
        check(/example\/repo/.test(frame), "preview names the publish target")
        check(/截断|…|\.\.\./.test(frame), "preview marks the truncated comment body")
      }
      if (state === "failed") {
        check(/GitHub API 500/.test(frame), "failed state shows the upstream message")
      }
      if (state !== "published") {
        check(!/审查评论已发布/.test(frame), `the ${state} state never renders the success line`)
      }
    } finally {
      view.renderer.destroy()
    }
  }

  const filterState = {
    ...emptyFindingsFilter(),
    active: true,
    query: "sql",
    severity: "high" as const,
  }
  const filterView = await testRender(
    () => (
      <FindingsFilterOverlay
        state={filterState}
        shown={2}
        total={9}
        language="zh-CN"
        onQuery={() => {}}
        onShortcut={() => {}}
        onApply={() => {}}
        onClear={() => {}}
      />
    ),
    { width: 100, height: 30, kittyKeyboard: true },
  )
  try {
    await filterView.renderOnce()
    const frame = filterView.captureCharFrame()
    check(/FINDINGS FILTER/.test(frame), "filter overlay renders its title")
    check(/sql/.test(frame), "filter overlay shows the query token")
    check(/2\/9/.test(frame), "filter overlay shows shown/total")
    check(/Enter/.test(frame) && /Esc/.test(frame), "filter overlay documents apply/clear keys")
  } finally {
    filterView.renderer.destroy()
  }

  const demoView = await testRender(
    () => (
      <DemoOverlay
        language="zh-CN"
        onClose={() => {}}
        data={{
          caseKey: "sql-injection",
          title: "SQL 注入演示",
          description: "参数拼接进查询",
          riskLevel: "critical",
          priorityFiles: 2,
          findings: [
            { severity: "critical", title: "SQL 注入", file: "a.py", evidence_status: "valid" },
          ],
          evidence: { valid: 1, needsReview: 0, invalid: 0, unverified: 0 },
        }}
      />
    ),
    { width: 100, height: 30, kittyKeyboard: true },
  )
  try {
    await demoView.renderOnce()
    const frame = demoView.captureCharFrame()
    check(/SQL 注入演示/.test(frame), "demo overlay renders the case title")
    check(/CRITICAL|critical/i.test(frame), "demo overlay renders the risk badge")
    check(/a\.py/.test(frame), "demo overlay renders the finding location")
  } finally {
    demoView.renderer.destroy()
  }

  const showcaseView = await testRender(
    () => (
      <ShowcaseOverlay
        language="zh-CN"
        onClose={() => {}}
        data={{
          title: "参赛演示路径",
          offlineReady: true,
          realReviewReady: false,
          steps: [
            { step: 1, command: "pr-review doctor", purpose: "检查环境" },
            { step: 2, command: "pr-review demo --case sql-injection", purpose: "离线证据" },
          ],
        }}
      />
    ),
    { width: 100, height: 30, kittyKeyboard: true },
  )
  try {
    await showcaseView.renderOnce()
    const frame = showcaseView.captureCharFrame()
    check(/参赛演示路径/.test(frame), "showcase overlay renders its title")
    check(/pr-review doctor/.test(frame), "showcase overlay lists the first step")
    check(/离线证据/.test(frame), "showcase overlay renders step purposes")
  } finally {
    showcaseView.renderer.destroy()
  }
}

/**
 * Part C: the full publish preview through the real backend.
 *
 * `_p5_verify/p5proto/seed_publish_preview.py` seeds a stored run and an
 * isolated config; `/history <run_id>` makes it the session report and `Alt+P`
 * previews it. The seeded token is a local placeholder and this check never
 * sends `--confirm`, so nothing is ever posted to GitHub.
 */
async function publishPreviewFlow() {
  console.log("\n[C] publish preview against a seeded run (no GitHub call)")
  const publishWork = join(tmpdir(), "ai-pr-review-p5-publish-check")
  let runId = ""
  try {
    runId = readFileSync(join(publishWork, "run_id.txt"), "utf8").trim()
  } catch {
    console.log("  SKIP  seeded run not found; run _p5_verify/p5proto/seed_publish_preview.py")
    return
  }
  const expectedConfig = join(publishWork, "config.json")
  if (configuredPath.toLowerCase() !== expectedConfig.toLowerCase()) {
    console.log(
      `  SKIP  set AI_PR_REVIEW_CONFIG=${expectedConfig} in the shell before launching this script`,
    )
    return
  }

  const view = await testRender(() => <App />, { width: 100, height: 34, kittyKeyboard: true })
  try {
    await settle(view)
    await runCommand(view, `/history ${runId}`, 2)
    const historyFrame = view.captureCharFrame()
    const historyLoaded = /SQL 注入风险|独立验收摘要|历史报告/.test(historyFrame)
    check(historyLoaded, "`/history <run_id>` loads the stored run")
    if (!historyLoaded) {
      console.log(`  debug: typed draft visible = ${historyFrame.includes(runId.slice(0, 8))}`)
      console.log(
        `  debug: composer line = ${
          historyFrame
            .split("\n")
            .find((line) => line.includes("输入消息")) ?? "(composer placeholder not found)"
        }`,
      )
      writeFileSync(join(configDir, "frame-history-full.txt"), historyFrame, "utf8")
    }

    view.mockInput.pressKey("p", { meta: true })
    await settle(view)
    const frame = view.captureCharFrame()
    const ok =
      /发布预览/.test(frame) &&
      /目标：example\/repo#7/.test(frame) &&
      /已截断，显示 \d+\/\d+ 行/.test(frame) &&
      /Enter 发布 · Esc 取消/.test(frame)
    check(ok, "Alt+P previews the stored run with target, body and confirm keys")
    check(!/已发布/.test(frame), "the preview never claims the comment was published")
    if (!ok) dumpFrame(frame, "publish-preview")

    // Esc on a pending preview must cancel without posting.
    view.mockInput.pressEscape()
    await settle(view, 6)
    const cancelled = view.captureCharFrame()
    check(/发布已取消/.test(cancelled), "Esc turns the preview into the cancelled state")
    check(/没有向 GitHub 写入任何内容/.test(cancelled), "the cancelled state says nothing was posted")
    view.mockInput.pressEscape()
    await settle(view, 4)
    check(!/发布已取消/.test(view.captureCharFrame()), "a second Esc closes the cancelled dialog")
  } finally {
    view.renderer.destroy()
  }
}

// `P5_CHECK_ONLY=publish` runs part C alone; the other modes exist so a failing
// section can be reproduced without the earlier App instances in the way.
/**
 * Part D: live publish against GitHub.
 *
 * Guarded twice so it can never fire by accident: `P5_CHECK_ONLY=live` plus
 * `P5_LIVE_RUN_ID=<uuid>` produces the preview, and `P5_LIVE_PUBLISH=1` is
 * required before the harness presses Enter on the confirmation dialog. This
 * mode uses the ambient config (real token, real history), so
 * `AI_PR_REVIEW_CONFIG` must stay unset.
 */
async function livePublishFlow() {
  console.log("\n[D] live publish against GitHub")
  const runId = (process.env.P5_LIVE_RUN_ID ?? "").trim()
  const mayPost = (process.env.P5_LIVE_PUBLISH ?? "") === "1"
  if (!runId) {
    console.log("  SKIP  set P5_LIVE_RUN_ID=<uuid> to preview the live run")
    return
  }
  if (configuredPath) {
    console.log("  SKIP  unset AI_PR_REVIEW_CONFIG: live mode needs the real config")
    return
  }
  console.log(`  run=${runId}  will_post=${mayPost}`)

  const view = await testRender(() => <App />, { width: 100, height: 34, kittyKeyboard: true })
  try {
    await settle(view)
    await runCommand(view, `/history ${runId}`, 2)
    const historyFrame = view.captureCharFrame()
    // The workspace renders the stored findings and the publish action once the
    // run is loaded; the transcript line has usually scrolled out of view.
    const loaded =
      /\[(CRITICAL|HIGH|MEDIUM|LOW|INFO)\]/.test(historyFrame) &&
      /Alt\+P 发布评论/.test(historyFrame)
    check(loaded, "`/history <run_id>` loads the live run into the workspace")
    if (!loaded) dumpFrame(historyFrame, "live-history")

    view.mockInput.pressKey("p", { meta: true })
    await settle(view)
    const previewFrame = view.captureCharFrame()
    const previewed =
      /发布预览/.test(previewFrame) &&
      /JiangLai999\/AI-PR-Review-Assistant#31/.test(previewFrame) &&
      /Enter 发布 · Esc 取消/.test(previewFrame)
    check(previewed, "Alt+P previews the real PR with its confirm footer")
    check(!/已发布/.test(previewFrame), "the preview does not claim a published comment")
    if (!previewed) dumpFrame(previewFrame, "live-preview")

    if (!mayPost) {
      console.log("  NOTE  preview only; set P5_LIVE_PUBLISH=1 to actually post")
      return
    }

    view.mockInput.pressEnter()
    // A live GitHub POST can take tens of seconds; wait for the terminal state
    // instead of guessing how long the round-trip needs.
    const { frame: postedFrame, elapsedMs: publishMs } = await waitForFrame(
      view,
      /已发布|发布失败|发布已取消/,
      180_000,
    )
    const posted =
      /已发布/.test(postedFrame) &&
      /JiangLai999\/AI-PR-Review-Assistant/.test(postedFrame) &&
      /github\.com\/JiangLai999\/AI-PR-Review-Assistant\/pull\/31/.test(postedFrame)
    check(posted, `Enter posts the comment and the dialog reports 已发布 (${publishMs}ms)`)
    if (!posted) dumpFrame(postedFrame, "live-posted")

    view.mockInput.pressEscape()
    await settle(view, 4)
  } finally {
    view.renderer.destroy()
  }
}

const only = (process.env.P5_CHECK_ONLY ?? "").trim().toLowerCase()
if (!only || only === "app") await appFlows()
if (!only || only === "publish") await publishPreviewFlow()
if (!only || only === "overlays") await overlayStates()
if (only === "live") await livePublishFlow()

console.log("\n== summary ==")
console.log(JSON.stringify({ failures }, null, 2))
if (failures.length > 0) {
  console.error(`P5 UI acceptance failed: ${failures.length} check(s)`)
  process.exit(1)
}
console.log("ALL P5 UI CHECKS PASSED")
