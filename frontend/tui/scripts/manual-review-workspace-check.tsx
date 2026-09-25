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
 *   6. action bar availability (callbacks present vs absent), including the
 *      optional publish (Alt+P) and filter (Ctrl+F) entries at 80x10, wide
 *      120x30, and narrow 80x24
 *   7. FindingsFilterBar (inactive hint + active filters)
 *   8. PublishConfirmDialog all five states (preview/publishing/published/failed/cancelled)
 *   9. ShowcasePanel and DemoResultPanel (including empty/missing data)
 *  10. 80x24 overflow scene with deliberately over-long content — the last
 *      drawn row must still carry the closing border glyph
 *
 * No backend, network, tokens, or user config are read.
 */
import { testRender } from "@opentui/solid"
import {
  DemoResultPanel,
  FindingsFilterBar,
  PublishConfirmDialog,
  ReviewActionBar,
  ReviewProgressPanel,
  ReviewSummaryPanel,
  ReviewWorkspace,
  ShowcasePanel,
  filterFindings,
  hasClosingBorder,
  sortFindings,
  type EvidenceCounts,
  type PublishDialogState,
  type PublishPreview,
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
        onFilter={props.onFilter}
        onExplain={props.onExplain}
        onFeedback={props.onFeedback}
        onPublish={props.onPublish}
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

const publishFilterActions = {
  ...allActions,
  onPublish: () => {},
  onFilter: () => {},
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
  {
    name: "workspace-wide-action-bar-publish-filter",
    layout: "wide",
    width: 120,
    height: 30,
    props: {
      progress: workspaceProgress,
      summary: workspaceSummary,
      findings: workspaceFindings,
      language: "en",
      ...publishFilterActions,
    },
    expectLabels: [
      "ACTIONS",
      "Ctrl+O",
      "Ctrl+F",
      "Alt+E",
      "Alt+F",
      "Alt+P",
      "Alt+X",
      "Findings",
      "Filter findings",
      "Explain",
      "Feedback",
      "Publish comment",
      "Export",
    ],
    forbidLabels: ["No actions available"],
  },
  {
    name: "workspace-narrow-action-bar-publish-filter",
    layout: "narrow",
    width: 80,
    height: 24,
    props: {
      progress: workspaceProgress,
      summary: workspaceSummary,
      findings: workspaceFindings,
      language: "en",
      ...publishFilterActions,
    },
    expectLabels: [
      "ACTIONS",
      "Ctrl+O",
      "Ctrl+F",
      "Alt+E",
      "Alt+F",
      "Alt+P",
      "Alt+X",
      "Findings",
      "Filter findings",
      "Explain",
      "Feedback",
      "Publish comment",
      "Export",
    ],
    forbidLabels: ["No actions available"],
  },
  {
    name: "workspace-wide-action-bar-optional-absent",
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
    expectLabels: ["ACTIONS", "Ctrl+O", "Explain", "Feedback", "Export"],
    forbidLabels: ["Alt+P", "Ctrl+F", "Publish comment", "Filter findings"],
  },
  {
    name: "workspace-narrow-action-bar-optional-absent",
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
    expectLabels: ["ACTIONS", "Ctrl+O", "Explain", "Feedback", "Export"],
    forbidLabels: ["Alt+P", "Ctrl+F", "Publish comment", "Filter findings"],
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
        onFilter={scene.props.onFilter}
        onExplain={scene.props.onExplain}
        onFeedback={scene.props.onFeedback}
        onPublish={scene.props.onPublish}
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
    onFilter?: () => void
    onExplain?: () => void
    onFeedback?: () => void
    onPublish?: () => void
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
    forbidLabels: ["No actions available", "Publish comment", "Filter findings", "Alt+P", "Ctrl+F"],
  },
  {
    name: "action-bar-publish-filter",
    props: { ...publishFilterActions, language: "en" },
    expectLabels: [
      "ACTIONS",
      "Ctrl+O",
      "Ctrl+F",
      "Alt+P",
      "Findings",
      "Filter findings",
      "Explain",
      "Feedback",
      "Publish comment",
      "Export",
    ],
    forbidLabels: ["No actions available"],
  },
  {
    name: "action-bar-publish-only",
    props: { ...allActions, onPublish: () => {}, language: "en" },
    expectLabels: ["ACTIONS", "Alt+P", "Publish comment"],
    forbidLabels: ["Filter findings", "Ctrl+F"],
  },
  {
    name: "action-bar-filter-only",
    props: { ...allActions, onFilter: () => {}, language: "en" },
    expectLabels: ["ACTIONS", "Ctrl+F", "Filter findings"],
    forbidLabels: ["Publish comment", "Alt+P"],
  },
  {
    name: "action-bar-partial",
    props: { onExplain: () => {}, language: "en" },
    expectLabels: ["ACTIONS", "Explain"],
    forbidLabels: ["Feedback", "Export", "Ctrl+O", "No actions available", "Publish comment", "Filter findings"],
  },
  {
    name: "action-bar-empty",
    props: { language: "en" },
    expectLabels: ["ACTIONS", "No actions available"],
    forbidLabels: ["Explain", "Feedback", "Export", "Ctrl+O", "Publish comment", "Filter findings"],
  },
  {
    name: "action-bar-zh",
    props: { ...publishFilterActions, language: "zh-CN" },
    expectLabels: [
      "操作",
      "打开 Findings",
      "筛选问题",
      "解释问题",
      "反馈结果",
      "发布评论到 GitHub",
      "导出报告",
    ],
    forbidLabels: ["No actions available"],
  },
]

for (const scene of actionOnlyCases) {
  const view = await testRender(
    () => (
      <box width="100%" height="100%" flexDirection="column" backgroundColor="#0a0a0a">
        <ReviewActionBar
          onOpenFindings={scene.props.onOpenFindings}
          onFilter={scene.props.onFilter}
          onExplain={scene.props.onExplain}
          onFeedback={scene.props.onFeedback}
          onPublish={scene.props.onPublish}
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

// ---------------------------------------------------------------------------
// FindingsFilterBar: inactive hint row vs active filter chips
// ---------------------------------------------------------------------------

type FilterBarCase = {
  name: string
  props: {
    active: boolean
    query?: string
    severity?: string
    evidence?: string
    sort?: "severity" | "file" | "confidence"
    shown: number
    total: number
    language?: string
  }
  expectLabels: string[]
  forbidLabels: string[]
}

const filterBarCases: FilterBarCase[] = [
  {
    name: "filter-bar-inactive-hint",
    props: { active: false, shown: 3, total: 15, language: "en" },
    expectLabels: ["Ctrl+F to filter", "3/15"],
    forbidLabels: ["q:", "sev:"],
  },
  {
    name: "filter-bar-active",
    props: {
      active: true,
      query: "auth",
      severity: "high",
      evidence: "valid",
      sort: "file",
      shown: 2,
      total: 9,
      language: "en",
    },
    expectLabels: ["q:auth", "sev:high", "ev:valid", "sort:file", "2/9"],
    forbidLabels: ["Ctrl+F to filter"],
  },
  {
    name: "filter-bar-zh-hint",
    props: { active: false, shown: 0, total: 0, language: "zh-CN" },
    expectLabels: ["Ctrl+F 过滤", "0/0"],
    forbidLabels: ["Ctrl+F to filter"],
  },
  {
    name: "filter-bar-undefined-safe",
    props: {
      active: true,
      query: undefined,
      severity: undefined,
      evidence: undefined,
      sort: undefined,
      shown: Number.NaN,
      total: 1,
      language: "en",
    },
    expectLabels: ["0/1"],
    forbidLabels: ["undefined", "NaN"],
  },
]

for (const scene of filterBarCases) {
  const view = await testRender(
    () => (
      <box width="100%" height="100%" flexDirection="column" backgroundColor="#0a0a0a">
        <FindingsFilterBar
          active={scene.props.active}
          query={scene.props.query}
          severity={scene.props.severity}
          evidence={scene.props.evidence}
          sort={scene.props.sort}
          shown={scene.props.shown}
          total={scene.props.total}
          language={scene.props.language}
        />
      </box>
    ),
    { width: 80, height: 6 },
  )
  try {
    await view.renderOnce()
    const frame = view.captureCharFrame()
    console.log(`\n===== 80x6 · ${scene.name} =====\n`)
    console.log(frame)
    const rows = frame.split("\n").filter((line) => line.trim().length > 0)
    if (rows.length !== 1) {
      throw new Error(`${scene.name}: expected exactly 1 content row, got ${rows.length}`)
    }
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

// ---------------------------------------------------------------------------
// PublishConfirmDialog: all five states
// ---------------------------------------------------------------------------

const publishPreview: PublishPreview = {
  runId: "run-1",
  repository: "JiangLai999/AI-PR-Review-Assistant",
  prNumber: 31,
  url: "https://github.com/JiangLai999/AI-PR-Review-Assistant/pull/31",
  commentBody: Array.from({ length: 12 }, (_, i) => `comment body line ${i + 1}`).join("\n"),
  findings: 15,
  alreadyPublished: false,
}

type PublishCase = {
  name: string
  open: boolean
  state?: PublishDialogState
  preview?: PublishPreview
  message?: string
  expectLabels: string[]
  forbidLabels: string[]
}

const publishCases: PublishCase[] = [
  {
    name: "publish-closed",
    open: false,
    state: "preview",
    preview: publishPreview,
    expectLabels: [],
    forbidLabels: ["PUBLISH PREVIEW", "PUBLISHING", "PUBLISHED", "PUBLISH FAILED", "PUBLISH CANCELLED"],
  },
  {
    name: "publish-preview",
    open: true,
    state: "preview",
    preview: publishPreview,
    expectLabels: [
      "PUBLISH PREVIEW",
      "JiangLai999/AI-PR-Review-Assistant#31",
      "15",
      "comment body line 1",
      "comment body line 8",
      "truncated",
      "8/12",
    ],
    forbidLabels: ["comment body line 9", "PUBLISHED", "PUBLISHING", "PUBLISH FAILED"],
  },
  {
    name: "publish-publishing",
    open: true,
    state: "publishing",
    preview: publishPreview,
    expectLabels: ["PUBLISHING"],
    forbidLabels: ["PUBLISHED", "PUBLISH PREVIEW", "PUBLISH FAILED", "successfully"],
  },
  {
    name: "publish-published",
    open: true,
    state: "published",
    preview: publishPreview,
    expectLabels: ["PUBLISHED", "JiangLai999/AI-PR-Review-Assistant#31"],
    forbidLabels: ["PUBLISH PREVIEW", "PUBLISHING", "PUBLISH FAILED"],
  },
  {
    name: "publish-failed",
    open: true,
    state: "failed",
    preview: publishPreview,
    message: "GitHub API 502: upstream unavailable",
    expectLabels: ["PUBLISH FAILED", "GitHub API 502: upstream unavailable"],
    forbidLabels: ["PUBLISHED", "PUBLISH PREVIEW", "successfully"],
  },
  {
    name: "publish-cancelled",
    open: true,
    state: "cancelled",
    preview: publishPreview,
    expectLabels: ["PUBLISH CANCELLED", "No review comment was created"],
    forbidLabels: ["PUBLISHED", "successfully", "comment posted"],
  },
  {
    name: "publish-preview-redacts-credentials",
    open: true,
    state: "preview",
    preview: {
      ...publishPreview,
      commentBody: "ok line\ntoken ghp_abcdefghijklmnopqrstuvwxyz012345\napi_key=sk-abcdefghijklmnopqrstuv",
    },
    expectLabels: ["[redacted]", "PUBLISH PREVIEW"],
    forbidLabels: ["ghp_abcdefghijklmnopqrstuvwxyz012345", "sk-abcdefghijklmnopqrstuv"],
  },
]

for (const scene of publishCases) {
  const view = await testRender(
    () => (
      <box width="100%" height="100%" flexDirection="column" backgroundColor="#0a0a0a">
        <PublishConfirmDialog
          open={scene.open}
          state={scene.state}
          preview={scene.preview}
          message={scene.message}
          maxBodyLines={8}
          language="en"
        />
      </box>
    ),
    { width: 80, height: 24 },
  )
  try {
    await view.renderOnce()
    const frame = view.captureCharFrame()
    console.log(`\n===== 80x24 · ${scene.name} =====\n`)
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

// ---------------------------------------------------------------------------
// ShowcasePanel + DemoResultPanel
// ---------------------------------------------------------------------------

const demoFindings: ReviewFinding[] = [
  { severity: "low", title: "日志缺少 request id", file: "src/db/session.py", line_start: 3, evidence_status: "unverified" },
  {
    severity: "critical",
    title: "鉴权中间件可被绕过",
    file: "src/auth_service.py",
    line_start: 12,
    confidence: 0.8,
    evidence_status: "needs_review",
  },
  {
    severity: "high",
    title: "SQL 拼接导致注入风险",
    file: "src/auth_service.py",
    line_start: 88,
    confidence: 0.95,
    evidence_status: "valid",
  },
]

type PanelCase = {
  name: string
  node: () => any
  expectLabels: string[]
  forbidLabels: string[]
  width?: number
  height?: number
}

const showcaseDemoCases: PanelCase[] = [
  {
    name: "showcase-ready",
    width: 80,
    height: 16,
    node: () => (
      <ShowcasePanel
        title="Showcase"
        offlineReady={true}
        realReviewReady={false}
        language="en"
        steps={[
          { step: 1, command: "pr-review demo --case sql-injection", purpose: "offline demo" },
          { step: 2, command: "pr-review plan <PR_URL>", purpose: "review plan" },
          { step: 3, command: "pr-review review <PR_URL>", purpose: "real review" },
        ]}
      />
    ),
    expectLabels: ["Showcase", "1. pr-review demo", "2. pr-review plan", "3. pr-review review", "Offline ready", "Real review pending"],
    forbidLabels: ["undefined"],
  },
  {
    name: "showcase-empty",
    width: 80,
    height: 12,
    node: () => <ShowcasePanel title="Showcase" steps={[]} language="en" />,
    expectLabels: ["Showcase", "No showcase steps.", "Offline pending", "Real review pending"],
    forbidLabels: ["undefined"],
  },
  {
    name: "demo-full",
    width: 80,
    height: 24,
    node: () => (
      <DemoResultPanel
        caseKey="sql-injection"
        title="SQL injection demo"
        description="seeded benchmark case"
        riskLevel="high"
        priorityFiles={3}
        findings={demoFindings}
        evidence={{ valid: 2, needsReview: 1, invalid: 0, unverified: 1 }}
        durationMs={1500}
        language="en"
      />
    ),
    expectLabels: [
      "SQL injection demo",
      "Risk: high",
      "Priority files 3",
      "Findings (3)",
      "[CRITICAL]",
      "[HIGH]",
      "[LOW]",
      "Needs review",
    ],
    forbidLabels: ["undefined"],
  },
  {
    name: "demo-empty",
    width: 80,
    height: 16,
    node: () => <DemoResultPanel findings={[]} language="en" />,
    expectLabels: ["Risk: unknown", "Priority files 0", "No findings in this demo case."],
    forbidLabels: ["undefined", "NaN"],
  },
  {
    name: "demo-malformed",
    width: 80,
    height: 16,
    node: () => (
      <DemoResultPanel
        findings={[{} as ReviewFinding, { severity: "weird", title: "bare" }]}
        language="en"
      />
    ),
    expectLabels: ["Findings (2)", "[WEIRD]"],
    forbidLabels: ["undefined"],
  },
]

for (const scene of showcaseDemoCases) {
  const view = await testRender(
    () => (
      <box width="100%" height="100%" flexDirection="column" backgroundColor="#0a0a0a">
        {scene.node()}
      </box>
    ),
    { width: scene.width ?? 80, height: scene.height ?? 20 },
  )
  try {
    await view.renderOnce()
    const frame = view.captureCharFrame()
    console.log(`\n===== ${scene.width ?? 80}x${scene.height ?? 20} · ${scene.name} =====\n`)
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

// ---------------------------------------------------------------------------
// Overflow scene: 80x24 over-long content must keep the closing border
// ---------------------------------------------------------------------------

function OverflowPanel(props: { label: string }) {
  const rows = Array.from({ length: 40 }, (_, i) => `${props.label} overlong content line ${i + 1}`)
  return (
    <box width="100%" height="100%" flexDirection="column" backgroundColor="#0a0a0a">
      <box
        width="100%"
        backgroundColor="#1e1e1e"
        borderStyle="single"
        borderColor="#fb8147"
        paddingLeft={1}
        paddingRight={1}
        flexDirection="column"
        overflow="hidden"
        flexShrink={1}
        minHeight={0}
      >
        <box flexGrow={1} minHeight={0} overflow="hidden" flexDirection="column">
          {rows.map((row) => (
            <text height={1} fg="#eeeeee">{row}</text>
          ))}
        </box>
      </box>
    </box>
  )
}

function OverflowStackedPanels() {
  return (
    <box width="100%" height="100%" flexDirection="column" backgroundColor="#0a0a0a">
      <ReviewProgressPanel
        url="https://github.com/JiangLai999/AI-PR-Review-Assistant/pull/31"
        stageId="review"
        stageLabel="执行 AI 审查"
        progress={70}
        stages={Array.from({ length: 12 }, (_, i) => ({
          id: `s${i}`,
          label: `阶段 ${i} 名称比较长用来制造溢出`,
          status: "done" as const,
          durationMs: 1000,
        }))}
        filesDone={7}
        filesTotal={18}
        currentFile="src/auth_service.py"
        fileStates={Array.from({ length: 20 }, (_, i) => ({
          filename: `src/module_${i}.py`,
          status: "reviewed" as const,
          findingsCount: i,
        }))}
        elapsedMs={25800}
        cost={0.0124}
        language="zh-CN"
        onCancel={() => {}}
      />
      <ReviewSummaryPanel
        repository="JiangLai999/AI-PR-Review-Assistant"
        prNumber={31}
        severity={severity}
        evidence={evidence}
        filesReviewed={18}
        filesSkipped={4}
        findings={findings}
        durationSeconds={42.3}
        cost={0.0124}
        language="zh-CN"
      />
    </box>
  )
}

type OverflowCase = {
  name: string
  width: number
  height: number
  node: () => any
  /** Assert the last non-empty row is a clean closing border. */
  expectClosingBorder: boolean
}

const overflowCases: OverflowCase[] = [
  {
    name: "overflow-80x24-overlong",
    width: 80,
    height: 24,
    node: () => <OverflowPanel label="A" />,
    expectClosingBorder: true,
  },
  {
    name: "overflow-80x24-stacked-panels",
    width: 80,
    height: 24,
    node: () => <OverflowStackedPanels />,
    expectClosingBorder: true,
  },
  {
    name: "overflow-120x30-overlong",
    width: 120,
    height: 30,
    node: () => <OverflowPanel label="B" />,
    expectClosingBorder: true,
  },
]

for (const scene of overflowCases) {
  const view = await testRender(scene.node, { width: scene.width, height: scene.height })
  try {
    await view.renderOnce()
    const frame = view.captureCharFrame()
    console.log(`\n===== ${scene.width}x${scene.height} · ${scene.name} =====\n`)
    console.log(frame)
    const rows = frame.split("\n")
    const nonEmpty = rows.filter((line) => line.trim().length > 0)
    const last = nonEmpty[nonEmpty.length - 1] ?? ""
    console.log(`${scene.name}: last drawn row = ${JSON.stringify(last)}`)
    if (scene.expectClosingBorder) {
      if (!hasClosingBorder(last)) {
        throw new Error(
          `${scene.name}: last drawn row is missing the closing border glyph: ${JSON.stringify(last)}`,
        )
      }
    }
  } finally {
    view.renderer.destroy()
  }
}

console.log(
  "\nmanual-review-workspace-check: rendered progress/summary/stacked/empty at 80x24 and 120x30; wide@120x30, narrow@80x24, and action availability (incl. publish Alt+P / filter Ctrl+F at wide 120x30 and narrow 80x24); filter bar; publish dialog (5 states); showcase; demo; overflow closing-border at 80x24 and 120x30",
)
