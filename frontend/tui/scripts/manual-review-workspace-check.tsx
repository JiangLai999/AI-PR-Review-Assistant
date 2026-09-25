/**
 * Manual visual check for the review workspace panels.
 *
 * Run (from frontend/tui):
 *   bun --preload @opentui/solid/preload scripts/manual-review-workspace-check.tsx
 *
 * Renders fixed fixtures at 80x24 and 120x30:
 *   1. ReviewProgressPanel alone (full fixture)
 *   2. ReviewSummaryPanel alone (full fixture)
 *   3. both panels stacked (compact fixture, like the integrated workspace)
 *
 * No backend, network, tokens, or user config are read.
 */
import { testRender } from "@opentui/solid"
import {
  ReviewProgressPanel,
  ReviewSummaryPanel,
  type EvidenceCounts,
  type ReviewFileState,
  type ReviewFinding,
  type ReviewStageState,
  type SeverityCounts,
} from "../src/review-ui"

const stages: ReviewStageState[] = [
  { id: "fetch", label: "拉取 PR 元数据", status: "done", durationMs: 1200 },
  { id: "plan", label: "规划审查范围", status: "done", durationMs: 3400 },
  { id: "review", label: "执行 AI 审查", status: "active", detail: "src/auth_service.py" },
  { id: "summarize", label: "汇总报告", status: "pending" },
  { id: "publish", label: "发布评论", status: "skipped" },
]

const fileStates: ReviewFileState[] = [
  { filename: "src/auth_service.py", status: "reviewed", findingsCount: 2, durationMs: 4200 },
  { filename: "src/db/session.py", status: "reviewed", findingsCount: 0, durationMs: 2100 },
  { filename: "docs/readme.md", status: "skipped", reason: "filtered_by_policy" },
  { filename: "src/legacy.py", status: "failed", error: "timeout" },
  { filename: "src/pending.py", status: "pending", findingsCount: null },
]

const severity: SeverityCounts = { critical: 2, high: 9, medium: 3, low: 1, info: 0 }
const evidence: EvidenceCounts = { valid: 11, needsReview: 3, invalid: 1, unverified: 0 }

const findings: ReviewFinding[] = [
  {
    severity: "high",
    title: "SQL 拼接导致注入风险",
    file: "src/auth_service.py",
    line_start: 88,
    confidence: 0.95,
    evidence_status: "valid",
  },
  {
    severity: "critical",
    title: "鉴权中间件可被绕过",
    file: "src/auth_service.py",
    line_start: 12,
    confidence: 0.8,
    evidence_status: "needs_review",
  },
  {
    severity: "low",
    title: "日志缺少 request id",
    file: "src/db/session.py",
    line_start: 3,
    evidence_status: "unverified",
  },
]

const compactStages: ReviewStageState[] = [
  { id: "fetch", label: "拉取 PR", status: "done", durationMs: 1200 },
  { id: "review", label: "AI 审查", status: "active", detail: "auth_service.py" },
  { id: "summarize", label: "汇总", status: "pending" },
]

function FullProgress() {
  return (
    <box width="100%" height="100%" flexDirection="column" backgroundColor="#0a0a0a">
      <ReviewProgressPanel
        url="https://github.com/JiangLai999/AI-PR-Review-Assistant/pull/31"
        stageId="review"
        stageLabel="执行 AI 审查"
        progress={70}
        stages={stages}
        filesDone={7}
        filesTotal={18}
        currentFile="src/auth_service.py"
        fileStates={fileStates}
        routing={{
          runtimeProfile: "hybrid",
          routerModel: "ollama/qwen3.5:4b",
          deepModel: "deepseek/deepseek-flash",
          reason: "light tasks local, deep review remote",
        }}
        elapsedMs={25_800}
        cost={0.0124}
        onCancel={() => {}}
      />
    </box>
  )
}

function FullSummary() {
  return (
    <box width="100%" height="100%" flexDirection="column" backgroundColor="#0a0a0a">
      <ReviewSummaryPanel
        repository="JiangLai999/AI-PR-Review-Assistant"
        prNumber={31}
        title="Fix auth middleware"
        severity={severity}
        evidence={evidence}
        filesReviewed={18}
        filesSkipped={4}
        findings={findings}
        durationSeconds={42.3}
        cost={0.0124}
        runId="run-1"
        model="deepseek/deepseek-flash"
        onOpenFindings={() => {}}
      />
    </box>
  )
}

function StackedCompact(props: { progressHeight: number; summaryHeight: number }) {
  return (
    <box width="100%" height="100%" flexDirection="column" backgroundColor="#0a0a0a">
      <box height={props.progressHeight} overflow="hidden" flexDirection="column">
        <ReviewProgressPanel
          url="https://github.com/JiangLai999/AI-PR-Review-Assistant/pull/31"
          stageId="review"
          stageLabel="AI 审查"
          progress={70}
          stages={compactStages}
          filesDone={7}
          filesTotal={18}
          currentFile="src/auth_service.py"
          elapsedMs={25_800}
          cost={0.0124}
          onCancel={() => {}}
        />
      </box>
      <box height={props.summaryHeight} overflow="hidden" flexDirection="column">
        <ReviewSummaryPanel
          repository="JiangLai999/AI-PR-Review-Assistant"
          prNumber={31}
          severity={severity}
          evidence={evidence}
          filesReviewed={18}
          filesSkipped={4}
          findings={findings.slice(0, 1)}
          durationSeconds={42.3}
          cost={0.0124}
          onOpenFindings={() => {}}
        />
      </box>
    </box>
  )
}

function EmptyPanels() {
  return (
    <box width="100%" height="100%" flexDirection="column" backgroundColor="#0a0a0a">
      <ReviewProgressPanel
        url=""
        stageId=""
        stageLabel=""
        progress={0}
        stages={[]}
        filesDone={0}
        fileStates={[]}
        onCancel={() => {}}
      />
      <ReviewSummaryPanel
        severity={{ critical: 0, high: 0, medium: 0, low: 0, info: 0 }}
        evidence={{ valid: 0, needsReview: 0, invalid: 0, unverified: 0 }}
        filesReviewed={0}
        filesSkipped={0}
        findings={[]}
      />
    </box>
  )
}

const scenes = [
  { name: "progress", node: () => <FullProgress /> },
  { name: "summary", node: () => <FullSummary /> },
  { name: "empty", node: () => <EmptyPanels /> },
] as const

for (const [width, height] of [
  [80, 24],
  [120, 30],
] as const) {
  for (const scene of scenes) {
    const view = await testRender(scene.node, { width, height })
    try {
      await view.renderOnce()
      const frame = view.captureCharFrame()
      console.log(`\n===== ${width}x${height} · ${scene.name} =====\n`)
      console.log(frame)
      const emptyScene = scene.name === "empty"
      const expectProgress = scene.name === "progress" || emptyScene
      const expectSummary = scene.name === "summary" || emptyScene
      if (expectProgress && !frame.includes("REVIEW PROGRESS") && !frame.includes("审查进度")) {
        throw new Error(`${width}x${height} ${scene.name}: progress panel missing`)
      }
      if (expectSummary && !frame.includes("REVIEW SUMMARY") && !frame.includes("审查摘要")) {
        throw new Error(`${width}x${height} ${scene.name}: summary panel missing`)
      }
    } finally {
      view.renderer.destroy()
    }
  }

  // Stacked workspace preview: both panels share the terminal height.
  const stacked = await testRender(
    () => (
      <StackedCompact
        progressHeight={Math.floor(height / 2)}
        summaryHeight={height - Math.floor(height / 2)}
      />
    ),
    { width, height },
  )
  try {
    await stacked.renderOnce()
    const frame = stacked.captureCharFrame()
    console.log(`\n===== ${width}x${height} · stacked =====\n`)
    console.log(frame)
    if (!frame.includes("REVIEW PROGRESS") && !frame.includes("审查进度")) {
      throw new Error(`${width}x${height} stacked: progress panel missing`)
    }
    if (!frame.includes("REVIEW SUMMARY") && !frame.includes("审查摘要")) {
      throw new Error(`${width}x${height} stacked: summary panel missing`)
    }
  } finally {
    stacked.renderer.destroy()
  }
}

console.log("\nmanual-review-workspace-check: rendered progress/summary/stacked/empty at 80x24 and 120x30")
