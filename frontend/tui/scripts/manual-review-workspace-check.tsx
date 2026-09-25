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
 *   4. ReviewWorkspace wide at 120x30 (side-by-side summary + findings/actions)
 *   5. ReviewWorkspace narrow at 80x24 (vertical stack, findings behind Ctrl+O)
 *   6. action bar availability (callbacks present vs absent)
 *
 * No backend, network, tokens, or user config are read.
 */
import { testRender } from "@opentui/solid"
import {
  ReviewActionBar,
  ReviewProgressPanel,
  ReviewSummaryPanel,
  ReviewWorkspace,
  filterFindings,
  sortFindings,
  type EvidenceCounts,
  type ReviewFileState,
  type ReviewFinding,
  type ReviewStageState,
  type ReviewWorkspaceProps,
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

const workspaceProgress = {
  url: "https://github.com/JiangLai999/AI-PR-Review-Assistant/pull/31",
  stageId: "review",
  stageLabel: "AI 审查",
  progress: 70,
  stages: compactStages.slice(0, 2),
  filesDone: 7,
  filesTotal: 18,
  currentFile: "src/auth_service.py",
  elapsedMs: 25_800,
  cost: 0.0124,
}

const workspaceSummary = {
  repository: "JiangLai999/AI-PR-Review-Assistant",
  prNumber: 31,
  severity,
  evidence,
  filesReviewed: 18,
  filesSkipped: 4,
  findings: findings.slice(0, 1),
  durationSeconds: 42.3,
  cost: 0.0124,
}

const workspaceFindings = sortFindings(filterFindings(findings, { query: "" }), "severity")

function WorkspaceScene(props: Partial<ReviewWorkspaceProps> & { layout: "wide" | "narrow" }) {
  return (
    <box width="100%" height="100%" flexDirection="column" backgroundColor="#0a0a0a">
      <ReviewWorkspace
        layout={props.layout}
        progress={props.progress}
        summary={props.summary}
        findings={props.findings}
        onOpenFindings={props.onOpenFindings}
        onExplain={props.onExplain}
        onFeedback={props.onFeedback}
        onExport={props.onExport}
        language={props.language}
      />
    </box>
  )
}

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

type WorkspaceCase = {
  name: string
  layout: "wide" | "narrow"
  width: number
  height: number
  props: Partial<ReviewWorkspaceProps>
  expectLabels: string[]
  forbidLabels: string[]
}

const allActions = {
  onOpenFindings: () => {},
  onExplain: () => {},
  onFeedback: () => {},
  onExport: () => {},
}

const workspaceCases: WorkspaceCase[] = [
  {
    name: "workspace-wide-actions",
    layout: "wide",
    width: 120,
    height: 30,
    props: {
      progress: workspaceProgress,
      summary: workspaceSummary,
      findings: workspaceFindings,
      language: "en",
      ...allActions,
    },
    expectLabels: ["FINDINGS", "ACTIONS", "Ctrl+O", "Explain", "Feedback", "Export"],
    forbidLabels: ["No actions available"],
  },
  {
    name: "workspace-narrow-actions",
    layout: "narrow",
    width: 80,
    height: 24,
    props: {
      progress: workspaceProgress,
      summary: workspaceSummary,
      findings: workspaceFindings,
      language: "en",
      ...allActions,
    },
    expectLabels: ["REVIEW PROGRESS", "REVIEW SUMMARY", "Ctrl+O", "Explain", "Feedback", "Export"],
    forbidLabels: ["No actions available"],
  },
  {
    name: "workspace-wide-no-actions",
    layout: "wide",
    width: 120,
    height: 30,
    props: {
      progress: workspaceProgress,
      summary: workspaceSummary,
      findings: workspaceFindings,
      language: "en",
    },
    expectLabels: ["FINDINGS", "ACTIONS", "No actions available"],
    forbidLabels: ["Explain", "Feedback", "Export", "Ctrl+O"],
  },
  {
    name: "workspace-narrow-no-actions",
    layout: "narrow",
    width: 80,
    height: 24,
    props: {
      progress: workspaceProgress,
      summary: workspaceSummary,
      findings: workspaceFindings,
      language: "en",
    },
    expectLabels: ["REVIEW PROGRESS", "REVIEW SUMMARY", "No actions available"],
    forbidLabels: ["Explain", "Feedback", "Export"],
  },
  {
    name: "workspace-wide-empty",
    layout: "wide",
    width: 120,
    height: 30,
    props: { language: "en", ...allActions },
    expectLabels: ["No findings", "ACTIONS", "Ctrl+O", "Explain"],
    forbidLabels: ["REVIEW PROGRESS", "REVIEW SUMMARY"],
  },
  {
    name: "workspace-narrow-empty",
    layout: "narrow",
    width: 80,
    height: 24,
    props: { language: "en" },
    expectLabels: ["ACTIONS", "No actions available"],
    forbidLabels: ["Explain", "Feedback", "Export"],
  },
  {
    name: "workspace-narrow-zh",
    layout: "narrow",
    width: 80,
    height: 24,
    props: {
      progress: workspaceProgress,
      summary: workspaceSummary,
      findings: workspaceFindings,
      language: "zh-CN",
      ...allActions,
    },
    expectLabels: ["审查进度", "审查摘要", "Ctrl+O", "打开 Findings", "解释问题", "反馈结果", "导出报告"],
    forbidLabels: ["No actions available"],
  },
]

for (const scene of workspaceCases) {
  const view = await testRender(
    () => (
      <WorkspaceScene
        layout={scene.layout}
        progress={scene.props.progress}
        summary={scene.props.summary}
        findings={scene.props.findings}
        onOpenFindings={scene.props.onOpenFindings}
        onExplain={scene.props.onExplain}
        onFeedback={scene.props.onFeedback}
        onExport={scene.props.onExport}
        language={scene.props.language}
      />
    ),
    { width: scene.width, height: scene.height },
  )
  try {
    await view.renderOnce()
    const frame = view.captureCharFrame()
    console.log(`\n===== ${scene.width}x${scene.height} · ${scene.name} =====\n`)
    console.log(frame)
    for (const label of scene.expectLabels) {
      if (!frame.includes(label)) {
        throw new Error(`${scene.name}: expected label missing: ${label}`)
      }
    }
    for (const label of scene.forbidLabels) {
      if (frame.includes(label)) {
        throw new Error(`${scene.name}: forbidden label present: ${label}`)
      }
    }
  } finally {
    view.renderer.destroy()
  }
}

// Action bar in isolation: bilingual labels only appear for provided callbacks.
type ActionOnlyCase = {
  name: string
  props: {
    onOpenFindings?: () => void
    onExplain?: () => void
    onFeedback?: () => void
    onExport?: () => void
    language?: string
  }
  expectLabels: string[]
  forbidLabels: string[]
}

const actionOnlyCases: ActionOnlyCase[] = [
  {
    name: "action-bar-all",
    props: { ...allActions, language: "en" },
    expectLabels: ["ACTIONS", "Ctrl+O", "Explain", "Feedback", "Export"],
    forbidLabels: ["No actions available"],
  },
  {
    name: "action-bar-partial",
    props: { onExplain: () => {}, language: "en" },
    expectLabels: ["ACTIONS", "Explain"],
    forbidLabels: ["Feedback", "Export", "Ctrl+O", "No actions available"],
  },
  {
    name: "action-bar-empty",
    props: { language: "en" },
    expectLabels: ["ACTIONS", "No actions available"],
    forbidLabels: ["Explain", "Feedback", "Export", "Ctrl+O"],
  },
  {
    name: "action-bar-zh",
    props: { ...allActions, language: "zh-CN" },
    expectLabels: ["操作", "打开 Findings", "解释问题", "反馈结果", "导出报告"],
    forbidLabels: ["No actions available"],
  },
]

for (const scene of actionOnlyCases) {
  const view = await testRender(
    () => (
      <box width="100%" height="100%" flexDirection="column" backgroundColor="#0a0a0a">
        <ReviewActionBar
          onOpenFindings={scene.props.onOpenFindings}
          onExplain={scene.props.onExplain}
          onFeedback={scene.props.onFeedback}
          onExport={scene.props.onExport}
          language={scene.props.language}
        />
      </box>
    ),
    { width: 80, height: 10 },
  )
  try {
    await view.renderOnce()
    const frame = view.captureCharFrame()
    console.log(`\n===== 80x10 · ${scene.name} =====\n`)
    console.log(frame)
    for (const label of scene.expectLabels) {
      if (!frame.includes(label)) {
        throw new Error(`${scene.name}: expected label missing: ${label}`)
      }
    }
    for (const label of scene.forbidLabels) {
      if (frame.includes(label)) {
        throw new Error(`${scene.name}: forbidden label present: ${label}`)
      }
    }
  } finally {
    view.renderer.destroy()
  }
}

console.log(
  "\nmanual-review-workspace-check: rendered progress/summary/stacked/empty at 80x24 and 120x30; wide@120x30, narrow@80x24, and action availability",
)
