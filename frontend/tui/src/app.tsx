import { createSignal, For, Show, onMount, onCleanup } from "solid-js"
import { useKeyboard, useRenderer, useTerminalDimensions } from "@opentui/solid"
import { BackendClient } from "./backend"
import { isCurrentAssistantEvent, isForeignSessionEvent } from "./protocol"
import { sendWithSessionRecovery } from "./session-recovery"
import { commandCompletion, commandEnterAction, commandMatches } from "./command-menu"
import { truncateMiddle, workspaceRootLabel } from "./format"
import { detailScrollDelta } from "./keymap"
import {
  demoPanelFromPayload,
  publishPreviewFromPayload,
  reviewReportPanels,
  reviewWorkspaceFromReport,
  showcasePanelFromPayload,
  type DemoPanelData,
  type EvidenceCounts,
  type PublishPreviewData,
  type ReviewWorkspaceData,
  type SeverityCounts,
  type ShowcasePanelData,
} from "./review-report"
import { ReviewProgressPanel } from "./review-ui/ReviewProgressPanel"
import { ReviewStatusBar } from "./review-ui/ReviewStatusBar"
import { ReviewSummaryPanel } from "./review-ui/ReviewSummaryPanel"
import { ReviewActionBar } from "./review-ui/ReviewActionBar"
import { ReviewWorkspace } from "./review-ui/ReviewWorkspace"
import { DemoResultPanel } from "./review-ui/DemoResultPanel"
import { FindingsFilterBar } from "./review-ui/FindingsFilterBar"
import { PublishConfirmDialog } from "./review-ui/PublishConfirmDialog"
import { ShowcasePanel } from "./review-ui/ShowcasePanel"
import type { PublishDialogState } from "./review-ui/panel-model"
import {
  applyFindingsFilter,
  cycleEvidence,
  cycleSeverity,
  cycleSort,
  describeFilter,
  emptyFindingsFilter,
  filterCounts,
  hasActiveCriteria,
  type FindingsFilterState,
} from "./findings-filter"
import { emptyFindingsMessage } from "./empty-findings"
import type { InputRenderable, TextareaRenderable, KeyBinding, ScrollBoxRenderable } from "@opentui/core"

const orange = "#fb8147"
const muted = "#808080"
const panel = "#1e1e1e"
const background = "#0a0a0a"

// Requests that must never hang the UI forever. The review budget mirrors the
// backend's own 30-minute cap with headroom; chat is capped well above the
// slowest local model we have measured.
const CHAT_TIMEOUT_MS = 15 * 60_000
const REVIEW_TIMEOUT_MS = 40 * 60_000
const PROBE_TIMEOUT_MS = 30_000
const CANCEL_TIMEOUT_MS = 15_000

type KeyLike = { name: string; ctrl?: boolean }
// OpenTUI emits `{ name: "p", ctrl: true }` and `{ name: "return" }`.
// Normalize both spellings so shortcuts work regardless of representation.
const isEnterKey = (key: KeyLike): boolean => key.name === "enter" || key.name === "return"
const isCtrlKey = (key: KeyLike, letter: string) =>
  (key.ctrl === true && key.name === letter) || key.name === `ctrl+${letter}`


type AppStatus = "CONNECTING" | "READY" | "THINKING" | "REVIEWING" | "CANCELLING" | "CANCELLED" | "ERROR" | "FALLBACK"

const statusLabels: Record<AppStatus, string> = {
  CONNECTING: "连接中",
  READY: "就绪",
  THINKING: "思考中",
  REVIEWING: "审查中",
  CANCELLING: "取消中",
  CANCELLED: "已取消",
  ERROR: "错误",
  FALLBACK: "降级模式",
}

const statusColors: Record<AppStatus, string> = {
  CONNECTING: "#f3c742",
  READY: "#7edc92",
  THINKING: orange,
  REVIEWING: orange,
  CANCELLING: "#f3c742",
  CANCELLED: muted,
  ERROR: "#ff6b6b",
  FALLBACK: "#f3c742",
}

const modes = ["Build", "Plan", "Compose"]


type RuntimeSnapshot = {
  provider_display?: string
  provider?: string
  model?: string
  strategy?: string
  runtime_profile?: string
  /** auto | always | off — when the review workbench shows itself. */
  workbench_mode?: string
  local?: boolean
  api_key_configured?: boolean
  available?: boolean | null
  message?: string
  ui_language?: string
  configuration_warnings?: string[]
}

const BRAND_PIXEL = [
  "██████  ██████      ██████  ███████ ██    ██ ██ ███████ ██  ██",
  "██   ██ ██   ██     ██   ██ ██      ██    ██ ██ ██      ██  ██",
  "██████  ██████      ██████  █████   ██    ██ ██ █████   ██████",
  "██      ██   ██     ██   ██ ██       ██  ██  ██ ██      ██  ██",
  "██      ██   ██     ██   ██ ███████   ████   ██ ███████ ██  ██",
]

const isEn = (language?: string) => String(language ?? "zh-CN").toLowerCase().startsWith("en")

function PixelLogo(props: { language?: string }) {
  return (
    <box width={76} height={8} flexDirection="column" alignItems="center" marginTop={1}>
      <For each={BRAND_PIXEL}>{(line) => <text width={66} height={1} fg={orange} attributes={1}>{line}</text>}</For>
      <text width={66} height={1} marginTop={1} fg={muted}>
        {isEn(props.language)
          ? "AI PR REVIEW ASSISTANT · EVIDENCE-FIRST · MULTI-MODEL"
          : "AI PR 审查智能体 · 证据优先 · 多模型协作"}
      </text>
    </box>
  )
}

function QuickStartPanel(props: { language?: string }) {
  const rows = (): Array<[string, string]> =>
    isEn(props.language)
      ? [
          ["/review <PR_URL>", "Run an AI review on a pull request"],
          ["/model", "Switch model (local Ollama / cloud)"],
          ["/history", "Review history and insights"],
          ["/setup", "Configuration wizard"],
        ]
      : [
          ["/review <PR_URL>", "发起 PR 智能审查"],
          ["/model", "模型切换（本地 Ollama ⇄ 云端）"],
          ["/history", "审查历史与复盘"],
          ["/setup", "配置向导"],
        ]
  return (
    <box width={76} marginTop={1} flexDirection="column">
      <text fg="#f3c742">{isEn(props.language) ? "QUICK START" : "快速开始"}</text>
      <For each={rows()}>{(row) =>
        <box flexDirection="row" gap={2}>
          <text width={18} fg={orange}>{row[0]}</text>
          <text fg={muted}>{row[1]}</text>
        </box>
      }</For>
    </box>
  )
}

type ChatMessage = { role: "user" | "assistant"; content: string }
type ReviewFinding = {
  severity?: string
  category?: string
  title?: string
  file?: string
  line_start?: number
  line_end?: number
  problem?: string
  message?: string
  suggestion?: string
  confidence?: number
  code_snippet?: string
  sources?: string[]
  evidence_status?: string
  evidence_issues?: string[]
  evidence?: Array<{ source?: string; validation_status?: string; validation_messages?: string[]; code_snippet?: string }>
}
type ReviewReport = {
  summary?: string
  findings?: ReviewFinding[]
  counts?: { total_findings?: number; by_severity?: Record<string, number> }
  pr?: { title?: string; repository?: string; author?: string; url?: string; files_reviewed?: number; files_skipped?: number }
  run?: { id?: string; duration_seconds?: number; total_cost?: number }
}

type ReviewStageState = {
  id: string
  label: string
  status: "pending" | "active" | "done" | "failed" | "skipped"
  durationMs?: number
  detail?: string
}

type ReviewFileState = {
  filename: string
  status: "pending" | "reviewed" | "skipped" | "failed"
  findingsCount?: number | null
  durationMs?: number
  reason?: string
  error?: string
}

type ReviewModelRouting = {
  runtimeProfile?: string
  routerModel?: string
  deepModel?: string
  reason?: string
}

const REVIEW_STAGE_ORDER: Array<{ id: string; label: string }> = [
  { id: "fetching", label: "获取 PR 数据" },
  { id: "filtering", label: "过滤变更文件" },
  { id: "context", label: "构建代码上下文" },
  { id: "static_rules", label: "运行静态规则" },
  { id: "reviewing", label: "执行 AI 审查" },
  { id: "cross_file", label: "分析跨文件影响" },
  { id: "persisting", label: "保存审查记录" },
]

const emptySeverityCounts = (): SeverityCounts => ({
  critical: 0,
  high: 0,
  medium: 0,
  low: 0,
  info: 0,
})

const emptyEvidenceCounts = (): EvidenceCounts => ({
  valid: 0,
  needsReview: 0,
  invalid: 0,
  unverified: 0,
})

const emptyReviewWorkspace = (): ReviewWorkspaceData => ({
  summary: "",
  findings: [],
  severity: emptySeverityCounts(),
  evidence: emptyEvidenceCounts(),
  filesReviewed: 0,
  filesSkipped: 0,
})

const stageIdFromEvent = (stageId: unknown, stage: unknown): string => {
  const explicit = String(stageId ?? "").trim()
  if (explicit) return explicit
  const label = String(stage ?? "").trim()
  const match = REVIEW_STAGE_ORDER.find((item) => item.label === label || item.id === label)
  return match?.id ?? label
}
type HistoryRun = { id?: string; repo_owner?: string; repo_name?: string; pr_url?: string; total_findings?: number; duration_seconds?: number; total_cost?: number; created_at?: string; model?: string }
type HistoryStats = { total_runs?: number; unique_prs?: number; total_findings?: number; total_cost?: number; latest_run_at?: string }

const isGithubPrUrl = (value: string) => /^https?:\/\/github\.com\/[^\s/]+\/[^\s/]+\/pull\/\d+(?:\/[^\s]*)?$/i.test(value.trim())

function Composer(props: {
  mode: string
  setMode: (mode: string) => void
  backend: BackendClient
  sessionId: string | undefined
  onEnsureSession: (force?: boolean) => Promise<string>
  onMessage: (message: ChatMessage) => void
  onStatus: (status: AppStatus) => void
  onRuntimeChange: (runtime: RuntimeSnapshot) => void
  runtime: RuntimeSnapshot
  onSetup: () => void
  onSessionChange: (sessionId: string) => void
  onNewSession: () => void
  onReviewReport: (report: ReviewReport) => void
  onReviewRequest: (url: string) => void
  onOpenFindings: () => void
  onOpenHistory: () => void
  onOpenModel: () => void
  onExplain: () => void
  onFeedback: () => void
  onExport: () => void
  /** Publish flow: preview first, then confirm (contract §12.2). */
  onPublish: (args: string) => void
  /** Offline demo panel; empty string runs the default case. */
  onDemo: (caseKey: string) => void
  onShowcase: () => void
  /** Focus the findings filter overlay (`Ctrl+F`). */
  onFilterFindings: () => void
  /** Fold / unfold the review workbench (`Alt+W`, `/workbench`). */
  onToggleWorkbench: () => void
  /** Show the `Alt+W 工作台` hint only when a workbench exists. */
  workbenchActive?: boolean
  onRetry: () => void
  reviewing: boolean
  busy: boolean
  onCancel: () => void
  onDraftChange: (draft: string) => void
  onChatRequestStart: (id: string) => void
  onChatRequestEnd: () => void
  /** Whether the streamed reply for this request already reached the transcript. */
  hasRenderedAssistantReply: (requestId: string | undefined) => boolean
  focused?: boolean
}) {
  // `pr-review chat --message "..."` (and the Web→CLI hand-off) seeds this.
  const initialDraft =
    (typeof process !== "undefined" ? process.env?.AI_PR_REVIEW_INITIAL_MESSAGE ?? "" : "").trim()
  const [value, setValue] = createSignal(initialDraft)
  const [modeIndex, setModeIndex] = createSignal(0)
  const [menuOpen, setMenuOpen] = createSignal(true)
  const [menuIndex, setMenuIndex] = createSignal(0)
  const [copyNotice, setCopyNotice] = createSignal("")
  const renderer = useRenderer()
  const dimensions = useTerminalDimensions()
  let textarea: TextareaRenderable | undefined
  let submitLock = false
  let dismissedDraft: string | undefined
  let lastCtrlCPressedAt = 0
  let copyNoticeTimer: ReturnType<typeof setTimeout> | undefined
  const compact = () => dimensions().height < 28
  const matches = () => menuOpen() && dismissedDraft !== value() && props.focused !== false ? commandMatches(value()) : []
  const visibleMatches = () => {
    const all = matches()
    // Short terminals lose rows fastest to an expanded menu, so show fewer
    // entries there instead of pushing the composer off-screen.
    const limit = compact() ? 3 : 5
    const start = Math.max(0, Math.min(menuIndex() - 2, all.length - limit))
    return all.slice(start, start + limit).map((command, offset) => ({ command, index: start + offset }))
  }
  const bindings: KeyBinding[] = [
    { name: "return", action: "submit" },
    { name: "return", shift: true, action: "newline" },
    { name: "enter", action: "submit" },
    { name: "enter", shift: true, action: "newline" },
    { name: "a", ctrl: true, action: "select-all" },
  ]

  const setDraft = (text: string) => {
    textarea?.setText(text)
    setValue(text)
    props.onDraftChange(text)
  }

  const showCopyNotice = (message: string, durationMs = 1500) => {
    if (copyNoticeTimer) clearTimeout(copyNoticeTimer)
    setCopyNotice(message)
    copyNoticeTimer = setTimeout(() => setCopyNotice(""), durationMs)
  }

  const copyToClipboard = (text: string): boolean => {
    if (!text) return false
    // Windows clip.exe is synchronous and handles CJK/emoji reliably. OSC52
    // remains the fallback for remote/alternate terminals and non-Windows.
    if (process.platform === "win32") {
      try {
        const result = Bun.spawnSync({ cmd: ["clip.exe"], stdin: new Blob([text]) })
        if (result.exitCode === 0) return true
      } catch {
        // Fall through to OSC52.
      }
    }
    try {
      return renderer.copyToClipboardOSC52(text)
    } catch {
      return false
    }
  }

  const selectedText = (): string => {
    const editorSelection =
      props.focused !== false && textarea?.hasSelection()
        ? textarea.getSelectedText()
        : ""
    const screenSelection = renderer.hasSelection
      ? renderer.getSelection()?.getSelectedText() ?? ""
      : ""
    return editorSelection || screenSelection
  }

  onMount(() => {
    if (!initialDraft) return
    // The textarea ref is only usable after mount, so seed the draft on the
    // next tick instead of dropping the value on the floor.
    setTimeout(() => {
      // Never replace text typed between mount and this timer.
      if ((textarea?.plainText ?? "") === "" && value() === initialDraft) {
        setDraft(initialDraft)
      }
    }, 0)
  })

  onCleanup(() => {
    if (copyNoticeTimer) clearTimeout(copyNoticeTimer)
  })

  const submit = async (override?: string) => {
    if (submitLock) return
    // Textarea can emit submit before its keydown/menu handler. Resolve the
    // visible slash option here too, so fast paste + Enter does not run /he.
    const liveDraft = textarea?.plainText ?? value()
    if (override === undefined && menuOpen() && dismissedDraft !== liveDraft) {
      const options = commandMatches(liveDraft)
      const selected = options[Math.min(menuIndex(), options.length - 1)]
      if (selected) {
        const action = commandEnterAction(liveDraft, selected, options.length)
        if (action.kind === "complete") {
          dismissedDraft = action.draft
          setDraft(action.draft)
          setMenuOpen(false)
          return
        }
        override = selected.name
      }
    }
    const text = (override ?? liveDraft).trim()
    if (!text || props.busy) return
    submitLock = true
    setMenuOpen(false)
    dismissedDraft = undefined
    setDraft("")
    if (text === "/setup") {
      props.onSetup()
      submitLock = false
      return
    }
    if (text === "/history") {
      props.onOpenHistory()
      submitLock = false
      return
    }
    if (text === "/retry") {
      props.onRetry()
      submitLock = false
      return
    }
    // P5 commands own their own panels, so they never reach `chat.send` and
    // never leave the user staring at a bare text reply.
    if (text === "/showcase") {
      props.onShowcase()
      submitLock = false
      return
    }
    if (text === "/workbench") {
      props.onToggleWorkbench()
      submitLock = false
      return
    }
    if (text === "/demo" || text.startsWith("/demo ")) {
      props.onDemo(text.slice("/demo".length).trim())
      submitLock = false
      return
    }
    if (text === "/publish" || text.startsWith("/publish ")) {
      props.onPublish(text.slice("/publish".length).trim())
      submitLock = false
      return
    }
    const commandParts = text.split(/\s+/)
    const reviewUrl = commandParts[0].toLowerCase() === "/review" ? commandParts[1] : isGithubPrUrl(text) ? text : undefined
    if (reviewUrl && isGithubPrUrl(reviewUrl)) {
      props.onReviewRequest(reviewUrl)
      submitLock = false
      return
    }
    props.onMessage({ role: "user", content: text })
    props.onStatus("THINKING")
    // Track the id assigned to this chat turn so the fallback below can tell
    // whether `assistant.finished` already wrote the reply.
    let chatRequestId: string | undefined
    try {
      const send = (activeSession: string) => text.startsWith("/")
        ? props.backend.request("command.execute", {
            name: text.slice(1).split(/\s+/, 1)[0],
            args: text.slice(1).split(/\s+/).slice(1),
            session_id: activeSession,
          })
        : props.backend.request(
            "chat.send",
            { session_id: activeSession, text },
            {
              onId: (id: string) => {
                chatRequestId = id
                props.onChatRequestStart(id)
              },
              timeoutMs: CHAT_TIMEOUT_MS,
            },
          )
      const response = await sendWithSessionRecovery(props.onEnsureSession, send)
      if (!response.ok) {
        if (!textarea?.plainText) setDraft(text)
        props.onMessage({ role: "assistant", content: response.error?.message ?? "Backend request failed" })
        props.onStatus("ERROR")
      } else {
        if (text.startsWith("/") && response.result?.text) {
          props.onMessage({ role: "assistant", content: String(response.result.text) })
        }
        // A dropped `assistant.finished` frame used to swallow the reply
        // silently; fall back to the request's own result text.
        if (
          !text.startsWith("/") &&
          response.result?.text &&
          !props.hasRenderedAssistantReply(chatRequestId)
        ) {
          props.onMessage({ role: "assistant", content: String(response.result.text) })
        }
        if (text.startsWith("/") && response.result?.session_id) {
          props.onSessionChange(String(response.result.session_id))
          if (text.split(/\s+/, 1)[0].toLowerCase() === "/new") props.onNewSession()
        }
        if (text.toLowerCase().startsWith("/model") && response.result?.config) {
          props.onRuntimeChange(response.result.config as RuntimeSnapshot)
        }
        // Any command can return a report — `/review` finishes one, `/history
        // <run>` restores one. Both must fill the review panels, otherwise the
        // FINDINGS list stays empty and Ctrl+O silently refuses to open.
        if (response.result?.report) {
          props.onReviewReport(response.result.report as ReviewReport)
        }
        props.onStatus("READY")
      }
    } catch (error) {
      if (!textarea?.plainText) setDraft(text)
      props.onMessage({ role: "assistant", content: String(error) })
      props.onStatus("ERROR")
    } finally {
      props.onChatRequestEnd()
      submitLock = false
    }
  }

  const onEditorKeyDown = (key: { name: string; preventDefault(): void }) => {
    if (props.focused === false) return
    const draft = textarea?.plainText ?? value()
    const options = menuOpen() && dismissedDraft !== draft ? commandMatches(draft) : []
    if (options.length === 0) return
    if (key.name === "down" || key.name === "up") {
      key.preventDefault()
      setMenuIndex((index) => (index + (key.name === "down" ? 1 : -1) + options.length) % options.length)
    } else if (key.name === "tab") {
      const selected = options[Math.min(menuIndex(), options.length - 1)]
      if (!selected) return
      key.preventDefault()
      const completed = commandCompletion(selected)
      dismissedDraft = completed
      setDraft(completed)
      setMenuOpen(false)
    } else if (key.name === "escape") {
      key.preventDefault()
      dismissedDraft = draft
      setMenuOpen(false)
    }
    // Enter belongs exclusively to textarea.onSubmit; handling it here as
    // well reintroduces the double-submit race seen in MiMo's prompt.
  }

  useKeyboard((key) => {
    // Ctrl+C is copy-first. A dialog must not lose its running-task cancel
    // path, and an idle Chat must not quit on a single accidental press.
    if (isCtrlKey(key, "c")) {
      key.stopPropagation?.()
      key.preventDefault?.()
      const text = selectedText()
      if (text) {
        const copied = copyToClipboard(text)
        showCopyNotice(copied ? "已复制选中文本到剪贴板" : "复制失败：剪贴板不可用")
        return
      }
      if (props.busy) {
        props.onCancel()
        showCopyNotice("已请求取消当前任务")
        return
      }
      const now = Date.now()
      if (now - lastCtrlCPressedAt <= 1500) {
        renderer.destroy()
        return
      }
      lastCtrlCPressedAt = now
      showCopyNotice("没有选中文本；再按一次 Ctrl+C 退出", 1600)
      return
    }
    // Ctrl+O must work even while another dialog owns the focus, otherwise it
    // silently does nothing until the user finds and closes that dialog.
    if (isCtrlKey(key, "o")) {
      props.onOpenFindings()
      key.stopPropagation?.()
      return
    }
    if (key.meta === true && key.name === "e") {
      props.onExplain()
      key.stopPropagation?.()
      return
    }
    if (key.meta === true && key.name === "f") {
      props.onFeedback()
      key.stopPropagation?.()
      return
    }
    if (key.meta === true && key.name === "x") {
      props.onExport()
      key.stopPropagation?.()
      return
    }
    // The P5 shortcuts only fire while the composer owns the focus; a dialog
    // that is already open must not restart the flow underneath the user.
    if (props.focused !== false && key.meta === true && key.name === "p") {
      props.onPublish("")
      key.stopPropagation?.()
      return
    }
    if (props.focused !== false && key.meta === true && key.name === "d") {
      props.onDemo("")
      key.stopPropagation?.()
      return
    }
    if (props.focused !== false && isCtrlKey(key, "f")) {
      props.onFilterFindings()
      key.stopPropagation?.()
      return
    }
    if (props.focused !== false && key.meta === true && key.name === "w") {
      props.onToggleWorkbench()
      key.stopPropagation?.()
      return
    }
    if (props.focused === false) return
    if (key.name === "tab" && matches().length === 0) {
      key.preventDefault()
      // Slash commands with arguments own Tab; do not silently switch modes.
      if ((textarea?.plainText ?? value()).trimStart().startsWith("/")) return
      const next = (modeIndex() + 1) % modes.length
      setModeIndex(next)
      props.setMode(modes[next])
      return
    }
    if (isCtrlKey(key, "p")) {
      props.onSetup()
      return
    }
    if (isCtrlKey(key, "l") && !props.busy) {
      props.onOpenHistory()
      return
    }
    if (isCtrlKey(key, "k") && !props.busy) {
      props.onOpenModel()
      return
    }
    if (isCtrlKey(key, "r") && !props.busy) {
      props.onRetry()
      return
    }
    if (key.name === "escape") {
      // Escape closes the command menu first; cancelling needs a second press
      // with the menu already dismissed.
      if (matches().length > 0) {
        dismissedDraft = value()
        setMenuOpen(false)
        key.preventDefault()
        key.stopPropagation()
        return
      }
      if (props.busy) {
        props.onCancel()
        key.preventDefault()
        key.stopPropagation()
      }
      return
    }
  })

  return (
    <box width={76} marginTop={1} flexDirection="column">
      <Show when={matches().length > 0}>
        <box backgroundColor="#202020" borderStyle="single" borderColor="#555555" paddingLeft={1} paddingRight={1} flexDirection="column">
          <For each={visibleMatches()}>{(entry) =>
            <text bg={entry.index === menuIndex() ? "#5a2e1c" : "#202020"}>
              <span style={{ fg: entry.index === menuIndex() ? "#ffffff" : orange }}>{entry.command.name}{entry.command.argument ? ` ${entry.command.argument}` : ""}</span>
              <span style={{ fg: muted }}>  {entry.command.description}</span>
            </text>
          }</For>
          <text fg={muted}>↑↓ 选择 · Tab 补全 · Enter 执行或补全 · Esc 关闭</text>
        </box>
      </Show>
      <box backgroundColor={panel} borderStyle="single" borderColor={props.focused === false ? muted : orange} paddingLeft={2} paddingRight={2} paddingTop={1} paddingBottom={1}>
        <textarea
          ref={(node) => { textarea = node }}
          onContentChange={() => {
            const draft = textarea?.plainText ?? ""
            setValue(draft)
            props.onDraftChange(draft)
            if (draft !== dismissedDraft) {
              dismissedDraft = undefined
              setMenuIndex(0)
              setMenuOpen(true)
            }
          }}
          onKeyDown={onEditorKeyDown}
          onSubmit={() => void submit()}
          keyBindings={bindings}
          placeholder={props.reviewing ? "审查进行中...(Esc / Ctrl+C 取消)" : props.busy ? "正在处理..." : "输入消息或粘贴 PR URL；输入 / 查看命令"}
          focused={props.focused ?? true}
          minHeight={1}
          maxHeight={compact() ? 3 : 6}
          wrapMode="word"
          flexGrow={1}
        />
      </box>
      <box paddingLeft={2} marginTop={1} gap={2} flexDirection="row" alignItems="center">
        <text fg={orange}>{props.mode}</text>
        <text fg={muted}>·</text>
        <text fg="#eeeeee">{props.runtime.model ?? "model"}</text>
        <text fg={muted}>{props.runtime.provider_display ?? props.runtime.provider ?? "provider"}</text>
      </box>
      <Show when={copyNotice()}>
        <text fg="#f3c742" paddingLeft={2} marginTop={1}>{copyNotice()}</text>
      </Show>
      <box flexDirection="row" justifyContent="space-between" paddingLeft={1} paddingRight={1} marginTop={1}>
        <text><span style={{ fg: "#eeeeee" }}>Enter</span> <span style={{ fg: muted }}>发送</span></text>
        <text><span style={{ fg: "#eeeeee" }}>Shift+Enter</span> <span style={{ fg: muted }}>换行</span></text>
        <text><span style={{ fg: "#eeeeee" }}>Ctrl+P</span> <span style={{ fg: muted }}>设置</span></text>
        <text><span style={{ fg: "#eeeeee" }}>Ctrl+L</span> <span style={{ fg: muted }}>历史</span></text>
        <text><span style={{ fg: "#eeeeee" }}>Ctrl+K</span> <span style={{ fg: muted }}>模型</span></text>
        <Show when={props.workbenchActive}>
          <text><span style={{ fg: "#eeeeee" }}>Alt+W</span> <span style={{ fg: muted }}>工作台</span></text>
        </Show>
      </box>
    </box>
  )
}

type SetupDialogProps = {
  backend: BackendClient
  runtime: RuntimeSnapshot
  onClose: () => void
  onApplied: (snapshot: RuntimeSnapshot) => void
}

type ProviderSetupOption = {
  name: string
  display_name: string
  base_url: string
  api_format: string
  env_var: string
  default_model: string
  models: string[]
}

type LocalSetupOption = {
  provider: string
  display_name: string
  base_url: string
  api_format: string
  default_model: string
  models: string[]
}

type ChoiceOption = {
  value: string
  label: string
}

type SetupOptions = {
  providers: ProviderSetupOption[]
  api_formats?: ChoiceOption[]
  ui_languages?: ChoiceOption[]
  output_formats?: ChoiceOption[]
  chat_layouts?: ChoiceOption[]
  workbench_modes?: ChoiceOption[]
  local: LocalSetupOption
  current: {
    runtime_profile?: string
    provider?: string
    model?: string
    api_format?: string
    api_key_configured?: boolean
    github_token_configured?: boolean
    remote_provider?: string
    remote_model?: string
    remote_base_url?: string
    remote_api_format?: string
    remote_api_key_configured?: boolean
    ui_language?: string
    response_language?: string
    output_format?: string
    auto_publish_comment?: boolean
    chat_layout?: string
    workbench_mode?: string
    local_model?: string
  }
}

type SetupStep = "runtime" | "provider" | "model" | "key" | "local" | "summary"

const runtimeOptions = [
  { name: "Cloud", description: "第三方 API：适合高质量审查与远程模型", value: "cloud" },
  { name: "Local", description: "Ollama 本地模型：离线可用，数据留在本机", value: "local" },
  { name: "Hybrid", description: "混合策略：按任务在本地与云端之间协作", value: "hybrid" },
  { name: "Offline", description: "离线优先：只使用本地运行时", value: "offline" },
]

const stepTitles: Record<SetupStep, string> = {
  runtime: "1 / 4 · 选择运行方式",
  provider: "2 / 4 · 选择云端 Provider",
  model: "3 / 4 · 选择模型",
  key: "4 / 4 · 配置 API Key",
  local: "2 / 4 · 选择本地模型",
  summary: "确认并保存",
}

function LegacySetupDialog(props: SetupDialogProps) {
  const dimensions = useTerminalDimensions()
  const initialRuntime = runtimeOptions.findIndex((option) => option.value === props.runtime.runtime_profile)
  const [step, setStep] = createSignal<SetupStep>("runtime")
  const [options, setOptions] = createSignal<SetupOptions>()
  const [runtimeIndex, setRuntimeIndex] = createSignal(initialRuntime >= 0 ? initialRuntime : 0)
  const [providerIndex, setProviderIndex] = createSignal(0)
  const [modelIndex, setModelIndex] = createSignal(0)
  const [localModelIndex, setLocalModelIndex] = createSignal(0)
  const [apiKey, setApiKey] = createSignal("")
  const [keyFocused, setKeyFocused] = createSignal(false)
  const [busy, setBusy] = createSignal(false)
  const [loading, setLoading] = createSignal(true)
  const [error, setError] = createSignal("")
  let apiInput: InputRenderable | undefined

  const selectedRuntime = () => runtimeOptions[runtimeIndex()]?.value ?? "cloud"
  const needsCloud = () => selectedRuntime() === "cloud" || selectedRuntime() === "hybrid"
  const providers = () => options()?.providers ?? []
  const selectedProvider = () => providers()[Math.min(providerIndex(), Math.max(0, providers().length - 1))]
  const cloudModels = () => selectedProvider()?.models ?? []
  const selectedModel = () => cloudModels()[Math.min(modelIndex(), Math.max(0, cloudModels().length - 1))]
    ?? props.runtime.model
    ?? "deepseek-flash"
  const localModels = () => options()?.local.models ?? []
  const selectedLocalModel = () => localModels()[Math.min(localModelIndex(), Math.max(0, localModels().length - 1))]
    ?? props.runtime.model
    ?? "qwen3.5:4b"
  const remoteProviderName = () => options()?.current.remote_provider ?? options()?.current.provider
  const remoteKeyConfigured = () =>
    options()?.current.remote_api_key_configured ?? options()?.current.api_key_configured ?? false
  const keyState = () => {
    const provider = selectedProvider()
    if (provider && provider.name === remoteProviderName() && remoteKeyConfigured()) {
      return "已配置（留空保留现有 Key）"
    }
    return apiKey().trim() ? "将保存到本地私有配置" : "未配置"
  }

  onMount(async () => {
    try {
      const response = await props.backend.request("config.options", {}, { timeoutMs: PROBE_TIMEOUT_MS })
      if (!response.ok) throw new Error(response.error?.message ?? "无法读取配置选项")
      const payload = response.result as SetupOptions
      setOptions(payload)
      const currentProvider = payload.providers.findIndex(
        (item) => item.name === (payload.current.remote_provider ?? payload.current.provider),
      )
      setProviderIndex(currentProvider >= 0 ? currentProvider : 0)
      const provider = payload.providers[currentProvider >= 0 ? currentProvider : 0]
      const currentModel = provider?.models.indexOf(
        payload.current.remote_model ?? payload.current.model ?? "",
      ) ?? -1
      setModelIndex(currentModel >= 0 ? currentModel : 0)
      const currentLocal = payload.local.models.indexOf(payload.current.local_model ?? "")
      setLocalModelIndex(currentLocal >= 0 ? currentLocal : 0)
    } catch (cause) {
      setError(String(cause))
    } finally {
      setLoading(false)
    }
  })

  const next = () => {
    setError("")
    const current = step()
    if (current === "runtime") setStep(needsCloud() ? "provider" : "local")
    else if (current === "provider") setStep("model")
    else if (current === "model") {
      // Moving focus during the same key event that opened this step lets the
      // new input swallow Enter and skip the API-key field entirely. Focus on
      // the next tick instead.
      setKeyFocused(false)
      setStep("key")
      setTimeout(() => setKeyFocused(true), 50)
    } else if (current === "local" || current === "key") {
      setKeyFocused(false)
      setStep("summary")
    }
  }

  const previous = () => {
    setError("")
    setKeyFocused(false)
    const current = step()
    if (current === "provider") setStep("runtime")
    else if (current === "model") setStep("provider")
    else if (current === "key") setStep("model")
    else if (current === "local") setStep("runtime")
    else if (current === "summary") setStep(needsCloud() ? "key" : "local")
  }

  const apply = async () => {
    if (busy()) return
    setBusy(true)
    setError("")
    try {
      const payload: Record<string, unknown> = { runtime_profile: selectedRuntime() }
      if (needsCloud()) {
        const provider = selectedProvider()
        if (!provider) throw new Error("没有可用的云端 Provider 配置。")
        payload.provider_name = provider.name
        payload.model_name = selectedModel()
        payload.base_url = provider.base_url
        payload.api_format = provider.api_format
        if (apiKey().trim()) payload.api_key = apiKey().trim()
      } else {
        const local = options()?.local
        if (!local) throw new Error("没有可用的本地模型配置。")
        payload.local_provider = local.provider
        payload.local_model = selectedLocalModel()
        payload.local_base_url = local.base_url
      }
      const response = await props.backend.request("config.setup", payload)
      if (!response.ok) throw new Error(response.error?.message ?? "配置保存失败")
      props.onApplied(response.result as RuntimeSnapshot)
      props.onClose()
    } catch (cause) {
      const message = String(cause)
      setError(message)
      if (needsCloud() && message.includes("API Key")) {
        setKeyFocused(false)
        setStep("key")
        setTimeout(() => setKeyFocused(true), 50)
      }
    } finally {
      setBusy(false)
    }
  }

  useKeyboard((key) => {
    if (key.name === "escape" && !busy()) {
      props.onClose()
      return
    }
    if (key.name === "left" && !busy() && step() !== "key") {
      previous()
      return
    }
    if (isEnterKey(key) && !busy()) {
      // The API-key input owns Enter so the wizard does not skip the field.
      if (step() === "key") return
      if (step() === "summary") void apply()
      else next()
    }
  })

  const dialogWidth = 70
  const dialogHeight = step() === "provider" ? 24 : 20
  const left = Math.max(2, Math.floor((dimensions().width - dialogWidth) / 2))
  const top = Math.max(2, Math.floor((dimensions().height - dialogHeight) / 2))

  return (
    <box position="absolute" left={left} top={top} width={dialogWidth} height={dialogHeight} backgroundColor="#171717" borderStyle="single" borderColor={orange} padding={2} zIndex={100} flexDirection="column">
      <text fg={orange}>配置助手 // SETUP WIZARD</text>
      <text fg={muted}>{stepTitles[step()]} · ↑↓ 选择 · Enter 下一步 · Esc 取消</text>
      <Show when={loading()}><text fg={muted}>读取配置选项中...</text></Show>
      <Show when={!loading() && step() === "runtime"}>
        <box marginTop={1} flexGrow={1}>
          <select
            options={runtimeOptions}
            selectedIndex={runtimeIndex()}
            focused
            showDescription
            width="100%"
            height={8}
            selectedBackgroundColor="#5a2e1c"
            selectedTextColor="#ffffff"
            descriptionColor={muted}
            selectedDescriptionColor="#ffd0bb"
            onChange={(index) => setRuntimeIndex(index)}
          />
        </box>
      </Show>
      <Show when={!loading() && step() === "provider"}>
        <box marginTop={1} flexGrow={1}>
          <select
            options={providers().map((provider) => ({
              name: provider.display_name,
              description: `${provider.default_model} · ${provider.base_url || "需要填写 Endpoint"}`,
              value: provider.name,
            }))}
            selectedIndex={providerIndex()}
            focused
            showDescription
            width="100%"
            height={12}
            selectedBackgroundColor="#5a2e1c"
            selectedTextColor="#ffffff"
            descriptionColor={muted}
            selectedDescriptionColor="#ffd0bb"
            onChange={(index) => {
              setProviderIndex(index)
              setModelIndex(0)
              setApiKey("")
            }}
          />
          <text fg={muted}>自定义 Endpoint / headers 等高级项请使用 pr-review config 配置。</text>
        </box>
      </Show>
      <Show when={!loading() && step() === "model"}>
        <box marginTop={1} flexGrow={1}>
          <select
            options={cloudModels().map((model) => ({
              name: model,
              description: model === selectedProvider()?.default_model ? "Provider 默认模型" : "预设模型",
              value: model,
            }))}
            selectedIndex={modelIndex()}
            focused
            showDescription
            width="100%"
            height={Math.min(12, Math.max(4, cloudModels().length * 2))}
            selectedBackgroundColor="#5a2e1c"
            selectedTextColor="#ffffff"
            descriptionColor={muted}
            selectedDescriptionColor="#ffd0bb"
            onChange={(index) => setModelIndex(index)}
          />
        </box>
      </Show>
      <Show when={!loading() && step() === "key"}>
        <box marginTop={1} flexDirection="column">
          <text fg="#eeeeee">{selectedProvider()?.display_name ?? "Provider"} API Key</text>
          <text fg={muted}>{keyState()}</text>
          <box marginTop={1} backgroundColor="#202020" paddingLeft={1} paddingRight={1}>
            <input
              ref={(node) => { apiInput = node }}
              placeholder={remoteKeyConfigured() ? "留空保留现有 Key，或粘贴新 Key" : "粘贴 API Key"}
              focused={keyFocused()}
              onContentChange={() => setApiKey(apiInput?.value ?? "")}
              onSubmit={() => {
                setKeyFocused(false)
                setStep("summary")
              }}
              flexGrow={1}
            />
          </box>
          <text fg={muted}>Key 写入私有配置；项目内优先写入 .ai_pr_review/config.local.json（已默认 gitignore）。</text>
        </box>
      </Show>
      <Show when={!loading() && step() === "local"}>
        <box marginTop={1} flexGrow={1}>
          <select
            options={localModels().map((model) => ({
              name: model,
              description: model === options()?.local.default_model ? "本地默认模型" : "Ollama 本地模型",
              value: model,
            }))}
            selectedIndex={localModelIndex()}
            focused
            showDescription
            width="100%"
            height={Math.min(12, Math.max(4, localModels().length * 2))}
            selectedBackgroundColor="#5a2e1c"
            selectedTextColor="#ffffff"
            descriptionColor={muted}
            selectedDescriptionColor="#ffd0bb"
            onChange={(index) => setLocalModelIndex(index)}
          />
          <text fg={muted}>Endpoint: {options()?.local.base_url ?? "http://127.0.0.1:11434/v1"}</text>
        </box>
      </Show>
      <Show when={!loading() && step() === "summary"}>
        <box marginTop={1} flexDirection="column">
          <text><span style={{ fg: orange }}>运行方式  </span><span style={{ fg: "#eeeeee" }}>{runtimeOptions[runtimeIndex()]?.name}</span></text>
          <Show when={needsCloud()}>
            <text><span style={{ fg: orange }}>Provider  </span><span style={{ fg: "#eeeeee" }}>{selectedProvider()?.display_name}</span></text>
            <text><span style={{ fg: orange }}>模型       </span><span style={{ fg: "#eeeeee" }}>{selectedModel()}</span></text>
            <text><span style={{ fg: orange }}>API Key    </span><span style={{ fg: "#eeeeee" }}>{keyState()}</span></text>
          </Show>
          <Show when={!needsCloud()}>
            <text><span style={{ fg: orange }}>本地模型  </span><span style={{ fg: "#eeeeee" }}>{selectedLocalModel()}</span></text>
            <text><span style={{ fg: orange }}>Endpoint  </span><span style={{ fg: "#eeeeee" }}>{options()?.local.base_url}</span></text>
          </Show>
          <text fg={muted}>保存后 Chat 会立即使用新配置；如需微调可再次打开 Ctrl+P。</text>
        </box>
      </Show>
      <box flexGrow={1} />
      <Show when={error()}><text fg="#ff6b6b">{error()}</text></Show>
      <text fg={busy() ? orange : muted}>
        {busy()
          ? "保存中..."
          : step() === "summary"
            ? "Enter 保存 · ← 返回修改 · Esc 取消"
            : step() === "key"
              ? "Enter 确认 Key · Esc 取消"
              : "Enter 下一步 · ← 返回 · Esc 取消"}
      </text>
    </box>
  )
}

type SetupScreen =
  | "runtime"
  | "provider"
  | "base_url"
  | "api_format"
  | "api_key"
  | "model"
  | "local_base_url"
  | "local_model"
  | "github"
  | "ui_language"
  | "response_language"
  | "output_format"
  | "auto_publish"
  | "chat_layout"
  | "workbench"
  | "summary"

const screenStages: Record<SetupScreen, number> = {
  runtime: 1,
  provider: 2,
  base_url: 2,
  api_format: 2,
  api_key: 3,
  model: 3,
  local_base_url: 2,
  local_model: 3,
  github: 4,
  ui_language: 5,
  response_language: 5,
  output_format: 5,
  auto_publish: 5,
  chat_layout: 5,
  workbench: 5,
  summary: 6,
}

const stageNames: Record<number, string> = {
  1: "运行模式",
  2: "模型服务",
  3: "凭据与模型",
  4: "GitHub Token",
  5: "界面与输出",
  6: "确认保存",
}

const screenTitles: Record<SetupScreen, string> = {
  runtime: "选择运行模式",
  provider: "选择模型供应商",
  base_url: "配置 API Base URL",
  api_format: "选择 API 协议格式",
  api_key: "配置 API Key",
  model: "选择模型",
  local_base_url: "配置本地 Ollama Endpoint",
  local_model: "选择本地模型",
  github: "配置 GitHub Token",
  ui_language: "选择界面语言",
  response_language: "选择模型回复语言",
  output_format: "选择默认输出格式",
  auto_publish: "是否自动发布 GitHub 评论",
  chat_layout: "选择 Chat 布局",
  workbench: "选择审查工作台模式",
  summary: "确认并保存",
}

function SetupWizardDialog(props: SetupDialogProps) {
  const dimensions = useTerminalDimensions()
  const [screen, setScreen] = createSignal<SetupScreen>("runtime")
  const [options, setOptions] = createSignal<SetupOptions>()
  const [loading, setLoading] = createSignal(true)
  const [busy, setBusy] = createSignal(false)
  const [error, setError] = createSignal("")
  const [inputValue, setInputValue] = createSignal("")
  const [inputFocused, setInputFocused] = createSignal(false)
  let inputRef: InputRenderable | undefined

  const [runtimeIndex, setRuntimeIndex] = createSignal(0)
  const [providerIndex, setProviderIndex] = createSignal(0)
  const [modelIndex, setModelIndex] = createSignal(0)
  const [localModelIndex, setLocalModelIndex] = createSignal(0)
  const [apiFormatIndex, setApiFormatIndex] = createSignal(0)
  const [uiLanguageIndex, setUiLanguageIndex] = createSignal(0)
  const [responseLanguageIndex, setResponseLanguageIndex] = createSignal(0)
  const [outputFormatIndex, setOutputFormatIndex] = createSignal(0)
  const [autoPublishIndex, setAutoPublishIndex] = createSignal(1)
  const [chatLayoutIndex, setChatLayoutIndex] = createSignal(0)
  const [workbenchIndex, setWorkbenchIndex] = createSignal(0)
  const [baseUrl, setBaseUrl] = createSignal("")
  const [apiKey, setApiKey] = createSignal("")
  const [localBaseUrl, setLocalBaseUrl] = createSignal("")
  const [githubToken, setGithubToken] = createSignal("")

  const providers = () => options()?.providers ?? []
  const apiFormats = () => options()?.api_formats ?? [{ value: "openai", label: "OpenAI 兼容" }]
  const uiLanguages = () =>
    options()?.ui_languages ?? [
      { value: "zh-CN", label: "中文 / Chinese" },
      { value: "en-US", label: "English" },
    ]
  const outputFormats = () =>
    options()?.output_formats ?? [
      { value: "terminal", label: "Terminal" },
      { value: "markdown", label: "Markdown" },
      { value: "json", label: "JSON" },
    ]
  const chatLayouts = () =>
    options()?.chat_layouts ?? [
      { value: "compact", label: "紧凑 / Compact" },
      { value: "split", label: "分栏 / Split" },
      { value: "plain", label: "纯文本 / Plain" },
    ]
  const workbenchModes = () =>
    options()?.workbench_modes ?? [
      { value: "auto", label: "自动 / Auto（审查时展开，可 Alt+W 收起）" },
      { value: "always", label: "常驻 / Always（一直显示工作台）" },
      { value: "off", label: "关闭 / Off（只用一行状态条显示进度）" },
    ]
  const local = () => options()?.local
  const selectedRuntime = () => runtimeOptions[runtimeIndex()]?.value ?? "cloud"
  const needsCloud = () => selectedRuntime() === "cloud" || selectedRuntime() === "hybrid"
  const selectedProvider = () => providers()[Math.min(providerIndex(), Math.max(0, providers().length - 1))]
  const cloudModels = () => selectedProvider()?.models ?? []
  const selectedModel = () =>
    cloudModels()[Math.min(modelIndex(), Math.max(0, cloudModels().length - 1))] ?? ""
  const localModels = () => local()?.models ?? []
  const selectedLocalModel = () =>
    localModels()[Math.min(localModelIndex(), Math.max(0, localModels().length - 1))] ?? ""
  const selectedApiFormat = () => apiFormats()[apiFormatIndex()]?.value ?? "openai"
  const selectedUiLanguage = () => uiLanguages()[uiLanguageIndex()]?.value ?? "zh-CN"
  const selectedResponseLanguage = () => uiLanguages()[responseLanguageIndex()]?.value ?? "zh-CN"
  const selectedOutputFormat = () => outputFormats()[outputFormatIndex()]?.value ?? "terminal"
  const selectedChatLayout = () => chatLayouts()[chatLayoutIndex()]?.value ?? "compact"
  const selectedWorkbenchMode = () => workbenchModes()[workbenchIndex()]?.value ?? "auto"
  const autoPublish = () => autoPublishIndex() === 0
  const remoteKeyConfigured = () =>
    options()?.current.remote_api_key_configured ?? options()?.current.api_key_configured ?? false
  const githubConfigured = () => options()?.current.github_token_configured ?? false

  const indexOfValue = (items: ChoiceOption[], value?: string) => {
    const index = items.findIndex((item) => item.value === value)
    return index >= 0 ? index : 0
  }

  const isInputScreen = (value: SetupScreen) =>
    value === "base_url" || value === "api_key" || value === "local_base_url" || value === "github"

  const cloudOrder: SetupScreen[] = [
    "runtime",
    "provider",
    "base_url",
    "api_format",
    "api_key",
    "model",
    "github",
    "ui_language",
    "response_language",
    "output_format",
    "auto_publish",
    "chat_layout",
    "workbench",
    "summary",
  ]
  const localOrder: SetupScreen[] = [
    "runtime",
    "local_base_url",
    "local_model",
    "github",
    "ui_language",
    "response_language",
    "output_format",
    "auto_publish",
    "chat_layout",
    "workbench",
    "summary",
  ]
  const order = () => (needsCloud() ? cloudOrder : localOrder)

  const inputDefault = (target: SetupScreen): string => {
    if (target === "base_url") return baseUrl() || selectedProvider()?.base_url || ""
    if (target === "local_base_url") return localBaseUrl() || local()?.base_url || ""
    return ""
  }

  const focusInputSoon = () => {
    setInputFocused(false)
    setTimeout(() => setInputFocused(true), 50)
  }

  const goTo = (target: SetupScreen) => {
    setError("")
    setInputFocused(false)
    if (isInputScreen(target)) {
      setInputValue(inputDefault(target))
      setScreen(target)
      focusInputSoon()
    } else {
      setScreen(target)
    }
  }

  const commitInput = () => {
    const value = (inputRef?.value ?? inputValue()).trim()
    if (screen() === "base_url") setBaseUrl(value)
    else if (screen() === "api_key") setApiKey(value)
    else if (screen() === "local_base_url") setLocalBaseUrl(value)
    else if (screen() === "github") setGithubToken(value)
  }

  const apply = async () => {
    if (busy()) return
    if (isInputScreen(screen())) commitInput()
    setBusy(true)
    setError("")
    try {
      const payload: Record<string, unknown> = {
        runtime_profile: selectedRuntime(),
        github_token: githubToken().trim(),
        ui_language: selectedUiLanguage(),
        response_language: selectedResponseLanguage(),
        output_format: selectedOutputFormat(),
        auto_publish_comment: autoPublish(),
        chat_layout: selectedChatLayout(),
        workbench_mode: selectedWorkbenchMode(),
      }
      if (needsCloud()) {
        const provider = selectedProvider()
        if (!provider) throw new Error("没有可用的云端 Provider 配置。")
        payload.provider_name = provider.name
        payload.model_name = selectedModel()
        payload.base_url = baseUrl().trim() || provider.base_url
        payload.api_format = selectedApiFormat()
        if (apiKey().trim()) payload.api_key = apiKey().trim()
      } else {
        const localConfig = local()
        if (!localConfig) throw new Error("没有可用的本地模型配置。")
        payload.local_provider = localConfig.provider
        payload.local_model = selectedLocalModel()
        payload.local_base_url = localBaseUrl().trim() || localConfig.base_url
        payload.local_api_format = localConfig.api_format
      }
      const response = await props.backend.request("config.setup", payload)
      if (!response.ok) throw new Error(response.error?.message ?? "配置保存失败")
      props.onApplied(response.result as RuntimeSnapshot)
      props.onClose()
    } catch (cause) {
      const message = String(cause)
      setError(message)
      if (needsCloud() && message.includes("API Key")) goTo("api_key")
      else if (message.includes("GitHub Token")) goTo("github")
      else if (message.includes("模型")) goTo("model")
    } finally {
      setBusy(false)
    }
  }

  const next = () => {
    if (isInputScreen(screen())) commitInput()
    const current = screen()
    if (current === "summary") {
      void apply()
      return
    }
    const currentOrder = order()
    const index = currentOrder.indexOf(current)
    const nextScreen = currentOrder[index + 1]
    if (nextScreen) goTo(nextScreen)
  }

  const previous = () => {
    const current = screen()
    if (current === "runtime") return
    const currentOrder = order()
    const index = currentOrder.indexOf(current)
    const prevScreen = currentOrder[index - 1]
    if (prevScreen) goTo(prevScreen)
  }

  onMount(async () => {
    try {
      const response = await props.backend.request("config.options", {}, { timeoutMs: PROBE_TIMEOUT_MS })
      if (!response.ok) throw new Error(response.error?.message ?? "无法读取配置选项")
      const payload = response.result as SetupOptions
      setOptions(payload)
      const initialRuntime = runtimeOptions.findIndex((option) => option.value === props.runtime.runtime_profile)
      setRuntimeIndex(initialRuntime >= 0 ? initialRuntime : 0)
      const currentProvider = payload.providers.findIndex(
        (item) => item.name === (payload.current.remote_provider ?? payload.current.provider),
      )
      const providerIndexValue = currentProvider >= 0 ? currentProvider : 0
      setProviderIndex(providerIndexValue)
      const provider = payload.providers[providerIndexValue]
      setBaseUrl(payload.current.remote_base_url ?? provider?.base_url ?? "")
      setApiFormatIndex(
        indexOfValue(
          payload.api_formats ?? [],
          payload.current.remote_api_format ?? provider?.api_format,
        ),
      )
      const currentModel = provider?.models.indexOf(payload.current.remote_model ?? payload.current.model ?? "") ?? -1
      setModelIndex(currentModel >= 0 ? currentModel : 0)
      const localConfig = payload.local
      setLocalBaseUrl(localConfig.base_url)
      const localIndex = localConfig.models.indexOf(payload.current.local_model ?? "")
      setLocalModelIndex(localIndex >= 0 ? localIndex : 0)
      setUiLanguageIndex(indexOfValue(payload.ui_languages ?? [], payload.current.ui_language))
      setResponseLanguageIndex(
        indexOfValue(payload.ui_languages ?? [], payload.current.response_language),
      )
      setOutputFormatIndex(indexOfValue(payload.output_formats ?? [], payload.current.output_format))
      setChatLayoutIndex(indexOfValue(payload.chat_layouts ?? [], payload.current.chat_layout))
      setWorkbenchIndex(
        indexOfValue(payload.workbench_modes ?? [], payload.current.workbench_mode),
      )
      setAutoPublishIndex(payload.current.auto_publish_comment ? 0 : 1)
    } catch (cause) {
      setError(String(cause))
    } finally {
      setLoading(false)
    }
  })

  useKeyboard((key) => {
    if (key.name === "escape" && !busy()) {
      props.onClose()
      return
    }
    if (key.name === "left" && (key.ctrl === true || key.meta === true) && !busy()) {
      previous()
      return
    }
    if (key.name === "left" && !busy() && !isInputScreen(screen())) {
      previous()
      return
    }
    if (isEnterKey(key) && !busy()) {
      if (isInputScreen(screen())) return
      if (screen() === "summary") void apply()
      else next()
    }
  })

  const dialogWidth = 74
  const dialogHeight = screen() === "provider" || screen() === "summary" ? 24 : 22
  const left = Math.max(2, Math.floor((dimensions().width - dialogWidth) / 2))
  const top = Math.max(0, Math.floor((dimensions().height - dialogHeight) / 2))

  const renderInput = (title: string, placeholder: string) => (
    <box marginTop={1} flexDirection="column">
      <text fg="#eeeeee">{title}</text>
      <box marginTop={1} backgroundColor="#202020" paddingLeft={1} paddingRight={1}>
        <input
          ref={(node) => { inputRef = node }}
          value={inputValue()}
          placeholder={placeholder}
          focused={inputFocused()}
          onContentChange={() => setInputValue(inputRef?.value ?? "")}
          onSubmit={() => {
            commitInput()
            next()
          }}
          flexGrow={1}
        />
      </box>
    </box>
  )

  return (
    <box position="absolute" left={left} top={top} width={dialogWidth} height={dialogHeight} backgroundColor="#171717" borderStyle="single" borderColor={orange} padding={2} zIndex={100} flexDirection="column">
      <text fg={orange}>配置助手 // SETUP WIZARD</text>
      <text fg={muted}>
        {screenStages[screen()]}/6 · {stageNames[screenStages[screen()]]} · {screenTitles[screen()]}
      </text>
      <Show when={loading()}><text fg={muted}>读取配置选项中...</text></Show>
      <Show when={!loading() && screen() === "runtime"}>
        <box marginTop={1} flexGrow={1}>
          <select
            options={runtimeOptions}
            selectedIndex={runtimeIndex()}
            focused
            showDescription
            width="100%"
            height={8}
            selectedBackgroundColor="#5a2e1c"
            selectedTextColor="#ffffff"
            descriptionColor={muted}
            selectedDescriptionColor="#ffd0bb"
            onChange={(index) => setRuntimeIndex(index)}
          />
        </box>
      </Show>
      <Show when={!loading() && screen() === "provider"}>
        <box marginTop={1} flexGrow={1}>
          <select
            options={providers().map((provider) => ({
              name: provider.display_name,
              description: `${provider.default_model} · ${provider.base_url || "需要填写 Endpoint"}`,
              value: provider.name,
            }))}
            selectedIndex={providerIndex()}
            focused
            showDescription
            width="100%"
            height={12}
            selectedBackgroundColor="#5a2e1c"
            selectedTextColor="#ffffff"
            descriptionColor={muted}
            selectedDescriptionColor="#ffd0bb"
            onChange={(index) => {
              setProviderIndex(index)
              const provider = providers()[index]
              if (provider) {
                setBaseUrl(provider.base_url)
                setApiFormatIndex(indexOfValue(apiFormats(), provider.api_format))
                setModelIndex(0)
              }
              setApiKey("")
            }}
          />
          <text fg={muted}>自定义 Endpoint / headers 等高级项仍可通过 pr-review config --advanced 配置。</text>
        </box>
      </Show>
      <Show when={!loading() && screen() === "base_url"}>
        {renderInput("API Base URL", "https://api.example.com/v1")}
      </Show>
      <Show when={!loading() && screen() === "api_format"}>
        <box marginTop={1} flexGrow={1}>
          <select
            options={apiFormats().map((format) => ({
              name: format.label,
              description: format.value,
              value: format.value,
            }))}
            selectedIndex={apiFormatIndex()}
            focused
            showDescription
            width="100%"
            height={6}
            selectedBackgroundColor="#5a2e1c"
            selectedTextColor="#ffffff"
            descriptionColor={muted}
            selectedDescriptionColor="#ffd0bb"
            onChange={(index) => setApiFormatIndex(index)}
          />
        </box>
      </Show>
      <Show when={!loading() && screen() === "api_key"}>
        {renderInput(
          `${selectedProvider()?.display_name ?? "Provider"} API Key`,
          remoteKeyConfigured() ? "已配置，留空保留现有 Key" : "粘贴 API Key",
        )}
      </Show>
      <Show when={!loading() && screen() === "model"}>
        <box marginTop={1} flexGrow={1}>
          <select
            options={cloudModels().map((model) => ({
              name: model,
              description: model === selectedProvider()?.default_model ? "Provider 默认模型" : "预设模型",
              value: model,
            }))}
            selectedIndex={modelIndex()}
            focused
            showDescription
            width="100%"
            height={Math.min(12, Math.max(4, cloudModels().length * 2))}
            selectedBackgroundColor="#5a2e1c"
            selectedTextColor="#ffffff"
            descriptionColor={muted}
            selectedDescriptionColor="#ffd0bb"
            onChange={(index) => setModelIndex(index)}
          />
        </box>
      </Show>
      <Show when={!loading() && screen() === "local_base_url"}>
        {renderInput("本地 Ollama Endpoint", "http://127.0.0.1:11434/v1")}
      </Show>
      <Show when={!loading() && screen() === "local_model"}>
        <box marginTop={1} flexGrow={1}>
          <select
            options={localModels().map((model) => ({
              name: model,
              description: model === local()?.default_model ? "本地默认模型" : "Ollama 本地模型",
              value: model,
            }))}
            selectedIndex={localModelIndex()}
            focused
            showDescription
            width="100%"
            height={Math.min(12, Math.max(4, localModels().length * 2))}
            selectedBackgroundColor="#5a2e1c"
            selectedTextColor="#ffffff"
            descriptionColor={muted}
            selectedDescriptionColor="#ffd0bb"
            onChange={(index) => setLocalModelIndex(index)}
          />
        </box>
      </Show>
      <Show when={!loading() && screen() === "github"}>
        {renderInput(
          "GitHub Token",
          githubConfigured() ? "已配置，留空保留现有 Token" : "粘贴 GitHub Token（ghp_...）",
        )}
      </Show>
      <Show when={!loading() && screen() === "ui_language"}>
        <box marginTop={1} flexGrow={1}>
          <select
            options={uiLanguages().map((item) => ({ name: item.label, description: item.value, value: item.value }))}
            selectedIndex={uiLanguageIndex()}
            focused
            showDescription
            width="100%"
            height={6}
            selectedBackgroundColor="#5a2e1c"
            selectedTextColor="#ffffff"
            descriptionColor={muted}
            selectedDescriptionColor="#ffd0bb"
            onChange={(index) => setUiLanguageIndex(index)}
          />
        </box>
      </Show>
      <Show when={!loading() && screen() === "response_language"}>
        <box marginTop={1} flexGrow={1}>
          <select
            options={uiLanguages().map((item) => ({ name: item.label, description: item.value, value: item.value }))}
            selectedIndex={responseLanguageIndex()}
            focused
            showDescription
            width="100%"
            height={6}
            selectedBackgroundColor="#5a2e1c"
            selectedTextColor="#ffffff"
            descriptionColor={muted}
            selectedDescriptionColor="#ffd0bb"
            onChange={(index) => setResponseLanguageIndex(index)}
          />
        </box>
      </Show>
      <Show when={!loading() && screen() === "output_format"}>
        <box marginTop={1} flexGrow={1}>
          <select
            options={outputFormats().map((item) => ({ name: item.label, description: item.value, value: item.value }))}
            selectedIndex={outputFormatIndex()}
            focused
            showDescription
            width="100%"
            height={8}
            selectedBackgroundColor="#5a2e1c"
            selectedTextColor="#ffffff"
            descriptionColor={muted}
            selectedDescriptionColor="#ffd0bb"
            onChange={(index) => setOutputFormatIndex(index)}
          />
        </box>
      </Show>
      <Show when={!loading() && screen() === "auto_publish"}>
        <box marginTop={1} flexGrow={1}>
          <select
            options={[
              { name: "是 / Yes", description: "审查完成后自动发布 GitHub 评论", value: "yes" },
              { name: "否 / No", description: "只生成本地报告，不自动发布", value: "no" },
            ]}
            selectedIndex={autoPublishIndex()}
            focused
            showDescription
            width="100%"
            height={6}
            selectedBackgroundColor="#5a2e1c"
            selectedTextColor="#ffffff"
            descriptionColor={muted}
            selectedDescriptionColor="#ffd0bb"
            onChange={(index) => setAutoPublishIndex(index)}
          />
        </box>
      </Show>
      <Show when={!loading() && screen() === "chat_layout"}>
        <box marginTop={1} flexGrow={1}>
          <select
            options={chatLayouts().map((item) => ({ name: item.label, description: item.value, value: item.value }))}
            selectedIndex={chatLayoutIndex()}
            focused
            showDescription
            width="100%"
            height={8}
            selectedBackgroundColor="#5a2e1c"
            selectedTextColor="#ffffff"
            descriptionColor={muted}
            selectedDescriptionColor="#ffd0bb"
            onChange={(index) => setChatLayoutIndex(index)}
          />
        </box>
      </Show>
      <Show when={!loading() && screen() === "workbench"}>
        <box marginTop={1} flexGrow={1}>
          <select
            options={workbenchModes().map((item) => ({ name: item.label, description: item.value, value: item.value }))}
            selectedIndex={workbenchIndex()}
            focused
            showDescription
            width="100%"
            height={8}
            selectedBackgroundColor="#5a2e1c"
            selectedTextColor="#ffffff"
            descriptionColor={muted}
            selectedDescriptionColor="#ffd0bb"
            onChange={(index) => setWorkbenchIndex(index)}
          />
        </box>
      </Show>
      <Show when={!loading() && screen() === "summary"}>
        <box marginTop={1} flexDirection="column">
          <text><span style={{ fg: orange }}>运行模式  </span><span style={{ fg: "#eeeeee" }}>{runtimeOptions[runtimeIndex()]?.name}</span></text>
          <Show when={needsCloud()}>
            <text><span style={{ fg: orange }}>Provider  </span><span style={{ fg: "#eeeeee" }}>{selectedProvider()?.display_name}</span></text>
            <text><span style={{ fg: orange }}>Endpoint  </span><span style={{ fg: "#eeeeee" }}>{baseUrl() || selectedProvider()?.base_url}</span></text>
            <text><span style={{ fg: orange }}>API 格式  </span><span style={{ fg: "#eeeeee" }}>{selectedApiFormat()}</span></text>
            <text><span style={{ fg: orange }}>模型       </span><span style={{ fg: "#eeeeee" }}>{selectedModel()}</span></text>
            <text><span style={{ fg: orange }}>API Key    </span><span style={{ fg: "#eeeeee" }}>{apiKey().trim() ? "将更新" : remoteKeyConfigured() ? "保留现有" : "未配置"}</span></text>
          </Show>
          <Show when={!needsCloud()}>
            <text><span style={{ fg: orange }}>本地引擎  </span><span style={{ fg: "#eeeeee" }}>{local()?.display_name}</span></text>
            <text><span style={{ fg: orange }}>Endpoint  </span><span style={{ fg: "#eeeeee" }}>{localBaseUrl() || local()?.base_url}</span></text>
            <text><span style={{ fg: orange }}>本地模型  </span><span style={{ fg: "#eeeeee" }}>{selectedLocalModel()}</span></text>
          </Show>
          <text><span style={{ fg: orange }}>GitHub    </span><span style={{ fg: "#eeeeee" }}>{githubToken().trim() ? "将更新" : githubConfigured() ? "保留现有" : "未配置"}</span></text>
          <text><span style={{ fg: orange }}>界面语言  </span><span style={{ fg: "#eeeeee" }}>{selectedUiLanguage()}</span></text>
          <text><span style={{ fg: orange }}>回复语言  </span><span style={{ fg: "#eeeeee" }}>{selectedResponseLanguage()}</span></text>
          <text><span style={{ fg: orange }}>输出格式  </span><span style={{ fg: "#eeeeee" }}>{selectedOutputFormat()}</span></text>
          <text><span style={{ fg: orange }}>自动发布  </span><span style={{ fg: "#eeeeee" }}>{autoPublish() ? "是" : "否"}</span></text>
          <text><span style={{ fg: orange }}>Chat 布局 </span><span style={{ fg: "#eeeeee" }}>{selectedChatLayout()}</span></text>
          <text fg={muted}>Enter 保存到私有配置；高级 headers / extra params 可稍后用 pr-review config --advanced 配置。</text>
        </box>
      </Show>
      <box flexGrow={1} />
      <Show when={error()}><text fg="#ff6b6b">{error()}</text></Show>
      <text fg={busy() ? orange : muted}>
        {busy()
          ? "保存中..."
          : screen() === "summary"
            ? "Enter 保存 · ← 返回修改 · Esc 取消"
            : isInputScreen(screen())
              ? "Enter 确认 · Ctrl/Alt+← 返回 · Esc 取消"
              : "↑↓ 选择 · Enter 下一步 · ← 返回 · Esc 取消"}
      </text>
    </box>
  )
}

function ReviewConfirmDialog(props: { url: string; onConfirm: () => void; onClose: () => void }) {
  const [selectedIndex, setSelectedIndex] = createSignal(0)
  const options = [
    { name: "开始审查", description: "使用当前运行时和模型执行完整 PR 审查", value: "confirm" },
    { name: "取消", description: "返回 Chat，不启动审查", value: "cancel" },
  ]
  const choose = () => {
    if (selectedIndex() === 0) props.onConfirm()
    else props.onClose()
  }
  useKeyboard((key) => {
    if (key.name === "escape") props.onClose()
    if (isEnterKey(key)) choose()
  })
  return (
    <box position="absolute" left={8} top={5} width={64} height={15} backgroundColor="#171717" borderStyle="single" borderColor={orange} padding={2} zIndex={120} flexDirection="column">
      <text fg={orange} height={1}>开始 PR 审查 // CONFIRM</text>
      <text fg={muted} height={1}>已识别 GitHub Pull Request：</text>
      <text fg="#eeeeee">{props.url}</text>
      <box marginTop={1} flexGrow={1}>
        <select
          options={options}
          selectedIndex={selectedIndex()}
          focused
          showDescription
          width="100%"
          height={4}
          selectedBackgroundColor="#5a2e1c"
          selectedTextColor="#ffffff"
          descriptionColor={muted}
          selectedDescriptionColor="#ffd0bb"
          onChange={(index) => setSelectedIndex(index)}
        />
      </box>
      <text fg={muted} height={1}>↑↓ 选择 · Enter 确认 · Esc 返回</text>
    </box>
  )
}

export function FindingsDialog(props: {
  findings: ReviewFinding[]
  onSelect?: (index: number) => void
  onExplain?: (index: number) => void
  onFeedback?: (index: number) => void
  onExport?: () => void
  onClose: () => void
}) {
  const pageSize = 8
  const [selectedIndex, setSelectedIndex] = createSignal(0)
  const [page, setPage] = createSignal(0)
  const [detailFocused, setDetailFocused] = createSignal(false)
  let detailScroll: ScrollBoxRenderable | undefined
  const pageCount = () => Math.max(1, Math.ceil(props.findings.length / pageSize))
  const pageFindings = () => props.findings.slice(page() * pageSize, (page() + 1) * pageSize)
  const selected = () => props.findings[selectedIndex()] ?? {}
  onMount(() => props.onSelect?.(0))
  useKeyboard((key) => {
    if (key.name === "escape") {
      props.onClose()
      return
    }
    if (key.name === "tab") {
      setDetailFocused((current) => !current)
      key.preventDefault()
      key.stopPropagation()
      return
    }
    if (key.name === "e" && key.ctrl !== true && key.meta !== true) {
      props.onExplain?.(selectedIndex())
      key.preventDefault()
      key.stopPropagation()
      return
    }
    if (key.name === "f" && key.ctrl !== true && key.meta !== true) {
      props.onFeedback?.(selectedIndex())
      key.preventDefault()
      key.stopPropagation()
      return
    }
    if (key.name === "x" && key.ctrl !== true && key.meta !== true) {
      props.onExport?.()
      key.preventDefault()
      key.stopPropagation()
      return
    }
    if (detailFocused()) {
      if (key.name === "up" || key.name === "k") {
        detailScroll?.scrollBy(-1)
      } else if (key.name === "down" || key.name === "j") {
        detailScroll?.scrollBy(1)
      } else if (key.name === "pageup") {
        detailScroll?.scrollBy(-0.5, "viewport")
      } else if (key.name === "pagedown") {
        detailScroll?.scrollBy(0.5, "viewport")
      } else if (key.name === "home") {
        detailScroll?.scrollTo(0)
      } else if (key.name === "end") {
        detailScroll?.scrollTo(Number.MAX_SAFE_INTEGER)
      } else {
        return
      }
      key.preventDefault()
      key.stopPropagation()
      return
    }
    // The focused Select consumes plain and Shift+arrows. Use modifier/page
    // keys that it leaves alone so the detail pane remains reachable without
    // switching focus first.
    const detailDelta = detailScrollDelta(
      key.name,
      key.shift === true,
      key.ctrl === true,
      key.meta === true,
    )
    if (detailDelta !== undefined) {
      detailScroll?.scrollBy(detailDelta)
      key.preventDefault()
      key.stopPropagation()
      return
    }
    if (key.name === "pageup") {
      detailScroll?.scrollBy(-0.5, "viewport")
      key.preventDefault()
      key.stopPropagation()
      return
    }
    if (key.name === "pagedown") {
      detailScroll?.scrollBy(0.5, "viewport")
      key.preventDefault()
      key.stopPropagation()
      return
    }
    if (key.name === "home") {
      detailScroll?.scrollTo(0)
      key.preventDefault()
      key.stopPropagation()
      return
    }
    if (key.name === "end") {
      detailScroll?.scrollTo(Number.MAX_SAFE_INTEGER)
      key.preventDefault()
      key.stopPropagation()
      return
    }
    if (key.name === "left") {
      setPage((current) => Math.max(0, current - 1))
      const next = Math.max(0, selectedIndex() - pageSize)
      setSelectedIndex(next)
      props.onSelect?.(next)
      detailScroll?.scrollTo(0)
    }
    if (key.name === "right") {
      setPage((current) => Math.min(pageCount() - 1, current + 1))
      const next = Math.min(props.findings.length - 1, selectedIndex() + pageSize)
      setSelectedIndex(next)
      props.onSelect?.(next)
      detailScroll?.scrollTo(0)
    }
  })
  return (
    <box position="absolute" left={5} top={2} width={70} height={22} backgroundColor="#171717" borderStyle="single" borderColor={orange} padding={2} zIndex={130} flexDirection="column">
      <text fg={orange}>FINDINGS // DETAIL {detailFocused() ? "· 详情滚动" : "· 列表选择"}</text>
      <box height={6} marginTop={1}>
        <select
          options={pageFindings().map((finding, offset) => ({
            name: `[${String(finding.severity ?? "info").toUpperCase()}] ${finding.title ?? finding.message ?? "未命名问题"}`,
            description: `${finding.file ?? "unknown"}:${finding.line_start ?? "?"}-${finding.line_end ?? finding.line_start ?? "?"}`,
            value: page() * pageSize + offset,
          }))}
          selectedIndex={Math.max(0, selectedIndex() - page() * pageSize)}
          focused={!detailFocused()}
          showDescription
          width="100%"
          height={6}
          selectedBackgroundColor="#5a2e1c"
          selectedTextColor="#ffffff"
          descriptionColor={muted}
          selectedDescriptionColor="#ffd0bb"
          onChange={(index) => {
            const next = page() * pageSize + index
            setSelectedIndex(next)
            props.onSelect?.(next)
            detailScroll?.scrollTo(0)
          }}
        />
      </box>
      <scrollbox
        ref={(node) => { detailScroll = node }}
        height={8}
        marginTop={1}
        scrollY
        scrollbarOptions={{ showArrows: true }}
        flexDirection="column"
      >
        <text fg="#f3c742">{String(selected().title ?? selected().message ?? "未命名问题")}</text>
        <text fg={muted}>文件：{selected().file ?? "unknown"}:{selected().line_start ?? "?"}-{selected().line_end ?? selected().line_start ?? "?"}</text>
        <text fg={muted}>类别：{selected().category ?? "unknown"} · 置信度：{selected().confidence !== undefined ? `${Math.round((selected().confidence ?? 0) * 100)}%` : "?"}</text>
        <text fg="#eeeeee">问题：{String(selected().problem ?? selected().message ?? "暂无详细描述")}</text>
        <text fg="#7edc92">建议：{String(selected().suggestion ?? "暂无修复建议")}</text>
        <text fg={muted}>证据：{(selected().sources ?? []).join(", ") || "ai_analysis"} · 状态：{selected().evidence_status ?? "unverified"}</text>
        <Show when={selected().evidence_issues?.length}><text fg="#f3c742">证据提示：{selected().evidence_issues?.join("；")}</text></Show>
        <Show when={selected().code_snippet}>
          <text fg="#b0b0b0">代码片段：</text>
          <For each={String(selected().code_snippet ?? "").split("\n")}>{(line, index) =>
            <text fg="#b0b0b0">{`${String((selected().line_start ?? 0) + index())} │ ${line}`}</text>
          }</For>
        </Show>
        <Show when={selected().evidence?.length}>
          <text fg="#f3c742">证据明细：</text>
          <For each={selected().evidence ?? []}>{(evidence) =>
            <text fg={muted}>· {evidence.source ?? "unknown"} / {evidence.validation_status ?? "unknown"}{evidence.validation_messages?.length ? ` · ${evidence.validation_messages.join("；")}` : ""}</text>
          }</For>
        </Show>
      </scrollbox>
      <text fg={muted}>
        {detailFocused()
          ? "↑↓/Pg滚动 · Home/End · Tab列表 · E解释 · F反馈 · X导出 · Esc"
          : `↑↓选择 · Tab详情 · Ctrl/Alt+↑↓滚动 · ←→翻页 (${page() + 1}/${pageCount()}) · E解释 · F反馈 · X导出 · Esc`}
      </text>
    </box>
  )
}

function FeedbackDialog(props: {
  finding: ReviewFinding
  language?: string
  onSelect: (status: string, note: string) => void
  onClose: () => void
}) {
  const [selectedIndex, setSelectedIndex] = createSignal(0)
  const options = [
    { name: "接受 / Accepted", description: "确认这是一个需要修复的问题", value: "accepted" },
    { name: "误报 / Rejected", description: "标记为误报或不需要处理", value: "rejected" },
    { name: "已修复 / Fixed", description: "问题已经修复", value: "fixed" },
    { name: "待复核 / Needs review", description: "保留为人工复核状态", value: "needs_review" },
  ]
  useKeyboard((key) => {
    if (key.name === "escape") {
      props.onClose()
      return
    }
    if (isEnterKey(key)) {
      const option = options[selectedIndex()]
      if (option) props.onSelect(option.value, "")
    }
  })
  return (
    <box position="absolute" left={9} top={4} width={62} height={16} backgroundColor="#171717" borderStyle="single" borderColor={orange} padding={2} zIndex={150} flexDirection="column">
      <text fg={orange}>FINDING FEEDBACK // 反馈</text>
      <text fg="#eeeeee">{props.finding.title ?? props.finding.message ?? "未命名问题"}</text>
      <text fg={muted}>
        {props.finding.file ?? "unknown"}:{props.finding.line_start ?? "?"}
      </text>
      <box marginTop={1} flexGrow={1}>
        <select
          options={options}
          selectedIndex={selectedIndex()}
          focused
          showDescription={false}
          width="100%"
          height={4}
          selectedBackgroundColor="#5a2e1c"
          selectedTextColor="#ffffff"
          descriptionColor={muted}
          selectedDescriptionColor="#ffd0bb"
          onChange={(index) => setSelectedIndex(index)}
        />
      </box>
      <text fg={muted}>↑↓ 选择 · Enter 提交 · Esc 取消</text>
    </box>
  )
}

function ReviewFailureDialog(props: { url: string; message: string; onRetry: () => void; onClose: () => void }) {
  const [selectedIndex, setSelectedIndex] = createSignal(0)
  const options = [
    { name: "重试审查", description: "使用当前配置重新执行该 PR 审查", value: "retry" },
    { name: "关闭", description: "返回 Chat", value: "close" },
  ]
  useKeyboard((key) => {
    if (key.name === "escape") props.onClose()
    if (isEnterKey(key)) selectedIndex() === 0 ? props.onRetry() : props.onClose()
  })
  return (
    <box position="absolute" left={10} top={5} width={60} height={15} backgroundColor="#171717" borderStyle="single" borderColor="#ff6b6b" padding={2} zIndex={125} flexDirection="column">
      <text fg="#ff6b6b">审查失败 // RETRY</text>
      <text fg={muted}>{props.message}</text>
      <text fg="#eeeeee">{props.url}</text>
      <box marginTop={1} flexGrow={1}>
        <select options={options} selectedIndex={selectedIndex()} focused showDescription width="100%" height={4} selectedBackgroundColor="#5a2e1c" selectedTextColor="#ffffff" descriptionColor={muted} selectedDescriptionColor="#ffd0bb" onChange={(index) => setSelectedIndex(index)} />
      </box>
      <text fg={muted}>↑↓ 选择 · Enter 确认 · Esc 关闭</text>
    </box>
  )
}

function HistoryDialog(props: { runs: HistoryRun[]; statistics?: HistoryStats; fallbackNote?: string; onOpen: (run: HistoryRun) => void; onClose: () => void }) {
  const [selectedIndex, setSelectedIndex] = createSignal(0)
  const selected = () => props.runs[selectedIndex()]
  useKeyboard((key) => {
    if (key.name === "escape") props.onClose()
    if (isEnterKey(key) && selected()) props.onOpen(selected())
  })
  return (
    <box position="absolute" left={6} top={2} width={72} height={22} backgroundColor="#171717" borderStyle="single" borderColor={orange} padding={2} zIndex={135} flexDirection="column">
      <text fg={orange}>REVIEW HISTORY</text>
      <text fg={muted}>Runs {props.statistics?.total_runs ?? props.runs.length} · PRs {props.statistics?.unique_prs ?? "?"} · Findings {props.statistics?.total_findings ?? "?"}</text>
      <Show when={props.fallbackNote}><text fg="#f3c742">{props.fallbackNote}</text></Show>
      <box marginTop={1} flexGrow={1}>
        <select
          options={props.runs.map((run) => ({
            name: `${run.id ?? "?"} · ${run.repo_owner ?? "?"}/${run.repo_name ?? "?"}`,
            description: `findings=${run.total_findings ?? 0} · ${run.created_at ?? ""}`,
            value: run.id,
          }))}
          selectedIndex={selectedIndex()}
          focused
          showDescription
          width="100%"
          height={12}
          selectedBackgroundColor="#5a2e1c"
          selectedTextColor="#ffffff"
          descriptionColor={muted}
          selectedDescriptionColor="#ffd0bb"
          onChange={(index) => setSelectedIndex(index)}
        />
      </box>
      <text fg={muted}>↑↓ 选择 · Enter 查看 Run · Esc 返回</text>
    </box>
  )
}

function ModelDialog(props: { backend: BackendClient; runtime: RuntimeSnapshot; onApplied: (runtime: RuntimeSnapshot) => void; onClose: () => void }) {
  const [models, setModels] = createSignal<string[]>([])
  const [selectedIndex, setSelectedIndex] = createSignal(0)
  const [busy, setBusy] = createSignal(true)
  const [error, setError] = createSignal("")
  const [availability, setAvailability] = createSignal<boolean | null>(null)

  onMount(async () => {
    try {
      const response = await props.backend.request("model.status")
      if (!response.ok) throw new Error(response.error?.message ?? "模型状态读取失败")
      setAvailability(response.result?.available ?? null)
      const available = Array.isArray(response.result?.models) ? response.result.models.map(String) : []
      const values = available.length > 0 ? available : [props.runtime.model ?? "当前模型"]
      setModels(values)
      const current = values.indexOf(props.runtime.model ?? "")
      setSelectedIndex(current >= 0 ? current : 0)
    } catch (cause) {
      setError(String(cause))
      setModels([props.runtime.model ?? "当前模型"])
    } finally {
      setBusy(false)
    }
  })

  const apply = async () => {
    const model = models()[selectedIndex()]
    if (!model || busy()) return
    setBusy(true)
    setError("")
    try {
      const response = await props.backend.request("model.apply", { model })
      if (!response.ok) throw new Error(response.error?.message ?? "模型切换失败")
      props.onApplied(response.result?.config as RuntimeSnapshot)
      props.onClose()
    } catch (cause) {
      setError(String(cause))
    } finally {
      setBusy(false)
    }
  }

  useKeyboard((key) => {
    if (key.name === "escape") props.onClose()
    if (isEnterKey(key) && !busy()) void apply()
  })

  return (
    <box position="absolute" left={9} top={4} width={62} height={17} backgroundColor="#171717" borderStyle="single" borderColor={orange} padding={2} zIndex={140} flexDirection="column">
      <text fg={orange}>模型选择 // MODEL SELECTOR</text>
      <text fg={muted}>{props.runtime.provider_display ?? props.runtime.provider ?? "Provider"} · ↑↓ 选择模型 · {availability() === true ? "ONLINE" : availability() === false ? "OFFLINE" : "检测中"}</text>
      <box marginTop={1} flexGrow={1}>
        <select
          options={models().map((model) => ({ name: model, description: model === props.runtime.model ? "当前模型" : "可切换模型", value: model }))}
          selectedIndex={selectedIndex()}
          focused
          showDescription
          width="100%"
          height={6}
          selectedBackgroundColor="#5a2e1c"
          selectedTextColor="#ffffff"
          descriptionColor={muted}
          selectedDescriptionColor="#ffd0bb"
          onChange={(index) => setSelectedIndex(index)}
        />
      </box>
      <Show when={error()}><text fg="#ff6b6b">{error()}</text></Show>
      <Show when={availability() === false}><text fg="#f3c742">建议：/model local 或 /model cloud 快速切换</text></Show>
      <text fg={muted}>{busy() ? "读取模型列表..." : "Enter 保存 · Esc 取消"}</text>
    </box>
  )
}

/**
 * Publish confirmation overlay.
 *
 * Enter confirms a pending preview; `Esc` cancels a pending preview and closes
 * the finished states. `publishing` cannot be undone from the UI, so `Esc`
 * only dismisses the dialog and says so.
 */
export function PublishOverlay(props: {
  state: PublishDialogState
  preview?: PublishPreviewData
  message?: string
  language?: string
  busy: boolean
  onConfirm: () => void
  onCancel: () => void
  onClose: () => void
}) {
  useKeyboard((key) => {
    if (key.name === "escape") {
      key.stopPropagation?.()
      if (props.state === "preview" || props.state === "publishing") props.onCancel()
      else props.onClose()
      return
    }
    if (!isEnterKey(key)) return
    key.stopPropagation?.()
    if (props.state === "preview") {
      if (!props.busy) props.onConfirm()
      return
    }
    props.onClose()
  })

  return (
    // Height leaves room for the title, the default 8-line body window, the
    // truncation marker and the confirm/cancel footer: a shorter dialog clipped
    // the footer, so the confirm key was never visible.
    <box position="absolute" left={8} top={2} width={64} height={19} zIndex={170} flexDirection="column">
      <PublishConfirmDialog
        open
        state={props.state}
        preview={props.preview}
        message={props.message}
        language={props.language}
      />
    </box>
  )
}

/** Offline demo result overlay; `Esc`/Enter closes it. */
export function DemoOverlay(props: {
  data?: DemoPanelData
  language?: string
  onClose: () => void
}) {
  useKeyboard((key) => {
    if (key.name === "escape" || isEnterKey(key)) {
      key.stopPropagation?.()
      props.onClose()
    }
  })
  return (
    <box
      position="absolute"
      left={8}
      top={2}
      width={64}
      height={20}
      zIndex={170}
      flexDirection="column"
    >
      <box flexGrow={1} minHeight={0} flexDirection="column">
        <DemoResultPanel
          caseKey={props.data?.caseKey}
          title={props.data?.title}
          description={props.data?.description}
          riskLevel={props.data?.riskLevel}
          priorityFiles={props.data?.priorityFiles}
          findings={props.data?.findings ?? []}
          evidence={props.data?.evidence}
          durationMs={props.data?.durationMs}
          language={props.language}
        />
      </box>
      <text height={1} fg={muted}>
        Esc / Enter 关闭 · 离线运行，不调用模型与 GitHub
      </text>
    </box>
  )
}

/** Offline showcase script overlay. */
export function ShowcaseOverlay(props: {
  data?: ShowcasePanelData
  language?: string
  onClose: () => void
}) {
  useKeyboard((key) => {
    if (key.name === "escape" || isEnterKey(key)) {
      key.stopPropagation?.()
      props.onClose()
    }
  })
  return (
    <box
      position="absolute"
      left={8}
      top={3}
      width={64}
      height={16}
      zIndex={170}
      flexDirection="column"
    >
      <box flexGrow={1} minHeight={0} flexDirection="column">
        <ShowcasePanel
          title={props.data?.title}
          offlineReady={props.data?.offlineReady}
          realReviewReady={props.data?.realReviewReady}
          steps={props.data?.steps ?? []}
          language={props.language}
        />
      </box>
      <text height={1} fg={muted}>
        Esc / Enter 关闭 · 演示脚本不会改变项目状态
      </text>
    </box>
  )
}

/**
 * Findings filter overlay: one text input plus keyboard cycling of severity,
 * evidence health and sort order. `Enter` applies, `Esc` clears and closes.
 */
export function FindingsFilterOverlay(props: {
  state: FindingsFilterState
  shown: number
  total: number
  language?: string
  onQuery: (query: string) => void
  onShortcut: (action: "severity" | "evidence" | "sort") => void
  onApply: () => void
  onClear: () => void
}) {
  let filterInput: InputRenderable | undefined
  useKeyboard((key) => {
    if (key.name === "escape") {
      key.stopPropagation?.()
      props.onClear()
      return
    }
    if (isEnterKey(key)) {
      key.stopPropagation?.()
      props.onApply()
      return
    }
    if (key.name === "tab") {
      key.stopPropagation?.()
      props.onShortcut(key.shift === true ? "evidence" : "severity")
      return
    }
    if (isCtrlKey(key, "s")) {
      key.stopPropagation?.()
      props.onShortcut("sort")
    }
  })
  onMount(() => {
    filterInput?.focus?.()
  })
  return (
    <box
      position="absolute"
      left={9}
      top={3}
      width={62}
      height={14}
      backgroundColor="#171717"
      borderStyle="single"
      borderColor={orange}
      paddingLeft={2}
      paddingRight={2}
      zIndex={170}
      flexDirection="column"
    >
      <text fg={orange}>FINDINGS FILTER // 筛选</text>
      <text fg={muted}>输入关键词实时过滤；Tab 严重级别 · Shift+Tab 证据 · Ctrl+S 排序</text>
      <box marginTop={1} backgroundColor="#202020" paddingLeft={1} paddingRight={1}>
        <input
          ref={(node) => {
            filterInput = node
          }}
          placeholder="关键词 / 文件 / 标题"
          focused
          onContentChange={() => props.onQuery(filterInput?.value ?? "")}
          flexGrow={1}
        />
      </box>
      <box marginTop={1} flexDirection="column">
        <FindingsFilterBar
          active={props.state.active}
          query={props.state.query}
          severity={props.state.severity}
          evidence={props.state.evidence}
          sort={props.state.sort}
          shown={props.shown}
          total={props.total}
          language={props.language}
        />
      </box>
      <text fg={muted} marginTop={1}>
        Enter 应用 · Esc 清除并关闭
      </text>
    </box>
  )
}

export function App() {
  const [mode, setMode] = createSignal("Build")
  const [composerDraft, setComposerDraft] = createSignal("")
  const [backendStatus, setBackendStatus] = createSignal<AppStatus>("CONNECTING")
  const [errorMessage, setErrorMessage] = createSignal("")
  const [sessionId, setSessionId] = createSignal<string>()
  const [messages, setMessages] = createSignal<ChatMessage[]>([])
  const [streamingAssistant, setStreamingAssistant] = createSignal("")
  const [activeChatRequestId, setActiveChatRequestId] = createSignal<string>()
  // Request ids whose reply already reached the transcript through
  // `assistant.finished` / `assistant.cancelled`. Used to decide whether the
  // request result still has to be appended as a fallback.
  const renderedAssistantReplies = new Set<string>()
  const hasRenderedAssistantReply = (requestId: string | undefined) =>
    Boolean(requestId && renderedAssistantReplies.has(requestId))
  const [reviewStage, setReviewStage] = createSignal("")
  const [reviewDetail, setReviewDetail] = createSignal("")
  const [reviewFile, setReviewFile] = createSignal("")
  const [reviewFilesDone, setReviewFilesDone] = createSignal(0)
  const [reviewProgress, setReviewProgress] = createSignal(0)
  const [reviewUrl, setReviewUrl] = createSignal("")
  const [reviewSummary, setReviewSummary] = createSignal("")
  const [reviewFindings, setReviewFindings] = createSignal<ReviewFinding[]>([])
  const [reviewWorkspace, setReviewWorkspace] = createSignal<ReviewWorkspaceData>(emptyReviewWorkspace())
  const [reviewStages, setReviewStages] = createSignal<ReviewStageState[]>(
    REVIEW_STAGE_ORDER.map((stage) => ({ ...stage, status: "pending" })),
  )
  const [reviewFileStates, setReviewFileStates] = createSignal<ReviewFileState[]>([])
  const [reviewFilesTotal, setReviewFilesTotal] = createSignal(0)
  const [reviewRouting, setReviewRouting] = createSignal<ReviewModelRouting>({})
  const [reviewStartedAt, setReviewStartedAt] = createSignal<number>()
  const [reviewElapsedMs, setReviewElapsedMs] = createSignal(0)
  const [findingsOpen, setFindingsOpen] = createSignal(false)
  const [activeFindingIndex, setActiveFindingIndex] = createSignal(0)
  const [feedbackOpen, setFeedbackOpen] = createSignal(false)
  const [reviewActionMessage, setReviewActionMessage] = createSignal("")
  // Workbench (Phase 1): auto-open on review start, Alt+W to fold it away.
  // `collapsed` is per session; the persisted preference is `workbench_mode`
  // (auto | always | off) and only decides the *automatic* behaviour.
  const [workbenchCollapsed, setWorkbenchCollapsed] = createSignal(false)
  const [workbenchManualOpen, setWorkbenchManualOpen] = createSignal(false)
  const [historyOpen, setHistoryOpen] = createSignal(false)
  const [historyRuns, setHistoryRuns] = createSignal<HistoryRun[]>([])
  const [historyStats, setHistoryStats] = createSignal<HistoryStats>({})
  const [historyStoreNote, setHistoryStoreNote] = createSignal("")
  const [modelOpen, setModelOpen] = createSignal(false)
  // P5 surfaces: GitHub publish confirmation, offline demo/showcase panels and
  // the findings filter overlay.
  const [findingsFilter, setFindingsFilter] = createSignal<FindingsFilterState>(emptyFindingsFilter())
  const [filterOpen, setFilterOpen] = createSignal(false)
  const [publishOpen, setPublishOpen] = createSignal(false)
  const [publishState, setPublishState] = createSignal<PublishDialogState>("preview")
  const [publishPreview, setPublishPreview] = createSignal<PublishPreviewData | undefined>()
  const [publishMessage, setPublishMessage] = createSignal("")
  const [publishBusy, setPublishBusy] = createSignal(false)
  const [demoOpen, setDemoOpen] = createSignal(false)
  const [demoData, setDemoData] = createSignal<DemoPanelData | undefined>()
  const [showcaseOpen, setShowcaseOpen] = createSignal(false)
  const [showcaseData, setShowcaseData] = createSignal<ShowcasePanelData | undefined>()
  const [reviewReport, setReviewReport] = createSignal<ReviewReport>({})
  const [pendingReviewUrl, setPendingReviewUrl] = createSignal("")
  const [reviewing, setReviewing] = createSignal(false)
  const [reviewStarting, setReviewStarting] = createSignal(false)
  const [runtime, setRuntime] = createSignal<RuntimeSnapshot>({})
  const [setupOpen, setSetupOpen] = createSignal(false)
  const backend = new BackendClient()
  const dimensions = useTerminalDimensions()
  // Below ~28 rows the home art and quick-start list crowd the composer out of
  // an 80x24 terminal, so they collapse to the compact session header.
  const compactHome = () => dimensions().height < 28

  const appendMessage = (message: ChatMessage) => setMessages((current) => [...current, message])

  // ---------------------------------------------------------------------
  // Workbench state machine (docs/workbench-phase1-contract.md §1)
  // idle ──review──▶ running ──done──▶ collapsed ──Alt+W──▶ running/done
  // ---------------------------------------------------------------------
  const workbenchMode = (): "auto" | "always" | "off" => {
    const mode = String(runtime().workbench_mode ?? "").trim().toLowerCase()
    return mode === "always" || mode === "off" ? mode : "auto"
  }
  const reviewPhase = (): "idle" | "running" | "done" => {
    if (reviewing() || reviewStarting()) return "running"
    const report = reviewReport() as Record<string, unknown>
    const run = (report.run ?? {}) as Record<string, unknown>
    const hasReport = Boolean(
      reviewWorkspace().runId || run.id || report.pr || report.counts || reviewStage(),
    )
    return hasReport ? "done" : "idle"
  }
  /** Whether the workbench surface is on screen at all. */
  const workbenchVisible = (): boolean => {
    if (workbenchManualOpen()) return true
    const mode = workbenchMode()
    if (mode === "always") return true
    const phase = reviewPhase()
    if (mode === "off") return phase === "running"
    return phase !== "idle"
  }
  /** Expanded panels vs. a single status line. */
  const workbenchExpanded = (): boolean =>
    workbenchVisible() && !workbenchCollapsed() && workbenchMode() !== "off"
  const reviewLayout = (): "three" | "two" | "bar" => {
    if (!workbenchExpanded()) return "bar"
    if (dimensions().width >= 140 && dimensions().height >= 26) return "three"
    if (dimensions().width >= 100 && dimensions().height >= 26) return "two"
    return "bar"
  }
  /**
   * Rails can only exist in `three`/`two`; at 80 columns (or a short window) the
   * workbench degrades to the one-line status bar instead of showing nothing.
   */
  const workbenchPanelsVisible = (): boolean =>
    workbenchExpanded() && reviewLayout() !== "bar"
  /** Column widths (docs/workbench-phase1-contract.md §2). */
  const leftColumnWidth = 26
  const rightColumnWidth = (): number => (reviewLayout() === "three" ? 52 : 44)
  /**
   * Width of the chat content column. While the workbench is off this stays 76
   * so the idle layout is byte-identical to the previous release.
   */
  const chatContentWidth = (): number => {
    if (!workbenchExpanded()) return 76
    const layout = reviewLayout()
    if (layout === "three") {
      return Math.max(56, dimensions().width - leftColumnWidth - rightColumnWidth() - 2)
    }
    if (layout === "two") {
      return Math.max(56, dimensions().width - rightColumnWidth() - 2)
    }
    return Math.max(56, Math.min(96, dimensions().width - 4))
  }
  const toggleWorkbench = () => {
    if (!workbenchVisible()) {
      setWorkbenchManualOpen(true)
      setWorkbenchCollapsed(false)
      appendMessage({
        role: "assistant",
        content: reviewPhase() === "idle"
          ? "已打开审查工作台。发起一次 /review 后这里会显示进度与发现。"
          : "已打开审查工作台。",
      })
      return
    }
    const next = !workbenchCollapsed()
    setWorkbenchCollapsed(next)
    if (!next) setWorkbenchManualOpen(true)
    setReviewActionMessage(
      next ? "审查工作台已收起（Alt+W 可再次展开，数据保留）。" : "审查工作台已展开。",
    )
  }
  /** Post-processing disclosure carried by the report payload (P6 §12.4). */
  const reportFiltered = (): { threshold?: number; belowThreshold?: number } => {
    const report = reviewReport() as Record<string, unknown>
    const run = (report.run ?? {}) as Record<string, unknown>
    const filtered = (run.filtered ?? {}) as Record<string, unknown>
    const asNumber = (value: unknown): number | undefined =>
      typeof value === "number" && Number.isFinite(value) ? value : undefined
    return {
      threshold: asNumber(filtered.threshold),
      belowThreshold: asNumber(filtered.below_threshold),
    }
  }
  /**
   * One-line workbench status (collapsed, narrow terminal, or `workbench_mode=off`).
   * Superseded by MiMo Code's `ReviewStatusBar`; kept for the plain-text
   * fallback used by the harness when the component is unavailable.
   */
  const workbenchStatusText = (): string => {
    const phase = reviewPhase()
    const zh = !String(runtime().ui_language ?? "zh").toLowerCase().startsWith("en")
    const files = reviewFilesTotal() > 0 ? `${reviewFilesDone()}/${reviewFilesTotal()}` : ""
    if (phase === "running") {
      const parts = [
        zh ? "审查中" : "reviewing",
        `${reviewProgress()}%`,
        files ? (zh ? `文件 ${files}` : `files ${files}`) : "",
        zh ? "Alt+W 展开" : "Alt+W expand",
        zh ? "Ctrl+C 取消" : "Ctrl+C cancel",
      ].filter(Boolean)
      return parts.join(" · ")
    }
    if (phase === "done") {
      const counts = reviewWorkspace().severity
      const parts = [
        zh ? "审查完成" : "review done",
        zh ? `${reviewFindings().length} 问题` : `${reviewFindings().length} findings`,
        counts.critical ? `🛑${counts.critical}` : "",
        counts.high ? `⚠️${counts.high}` : "",
        zh ? "Alt+W 打开工作台" : "Alt+W open workbench",
      ].filter(Boolean)
      return parts.join(" · ")
    }
    return zh ? "工作台已打开 · 发起 /review 开始审查" : "Workbench open · run /review to start"
  }

  // Single place that turns a report into visible panels, so a new caller
  // cannot populate the summary while forgetting the findings list.
  const applyReviewReport = (report: ReviewReport) => {
    const panels = reviewReportPanels(report)
    setReviewReport(report)
    setReviewSummary(panels.summary)
    setReviewFindings(panels.findings as ReviewFinding[])
    setReviewWorkspace(reviewWorkspaceFromReport(report))
  }

  const resetReviewWorkspaceState = () => {
    setReviewWorkspace(emptyReviewWorkspace())
    setReviewStages(REVIEW_STAGE_ORDER.map((stage) => ({ ...stage, status: "pending" })))
    setReviewFileStates([])
    setReviewFilesTotal(0)
    setReviewRouting({})
    setReviewStartedAt(undefined)
    setReviewElapsedMs(0)
    setActiveFindingIndex(0)
    setFeedbackOpen(false)
    setReviewActionMessage("")
  }

  onMount(() => {
    const timer = setInterval(() => {
      const started = reviewStartedAt()
      if (reviewing() && started) setReviewElapsedMs(Date.now() - started)
    }, 1000)
    onCleanup(() => clearInterval(timer))
  })

  const updateStageState = (stageId: string, patch: Partial<ReviewStageState>) => {
    setReviewStages((current) => {
      const index = current.findIndex((stage) => stage.id === stageId)
      if (index === -1) {
        return [
          ...current,
          {
            id: stageId,
            label: patch.label ?? stageId,
            status: "pending",
            ...patch,
          },
        ]
      }
      return current.map((stage, currentIndex) =>
        currentIndex === index ? { ...stage, ...patch } : stage,
      )
    })
  }

  const updateFileState = (filename: string, patch: Partial<ReviewFileState>) => {
    setReviewFileStates((current) => {
      const index = current.findIndex((file) => file.filename === filename)
      if (index === -1) {
        return [...current, { filename, status: "pending", ...patch }]
      }
      return current.map((file, currentIndex) =>
        currentIndex === index ? { ...file, ...patch } : file,
      )
    })
  }

  const setErrorState = (message: string) => {
    setErrorMessage(message)
    setBackendStatus("ERROR")
  }

  const openHistory = async () => {
    try {
      const response = await backend.request("command.execute", { name: "history", args: [] })
      if (response.ok) {
        setHistoryRuns(Array.isArray(response.result?.runs) ? response.result.runs as HistoryRun[] : [])
        setHistoryStats((response.result?.statistics ?? {}) as HistoryStats)
        setHistoryStoreNote(String(response.result?.fallback_note ?? ""))
        setHistoryOpen(true)
      }
    } catch (error) {
      appendMessage({ role: "assistant", content: String(error) })
    }
  }

  const openHistoryRun = async (run: HistoryRun) => {
    if (!run.id) return
    const response = await backend.request("command.execute", { name: "history", args: [run.id] })
    if (response.ok && response.result?.report) {
      applyReviewReport(response.result.report as ReviewReport)
      setHistoryOpen(false)
      setReviewStage("历史报告")
      setReviewDetail(`Run ${run.id} · ${run.created_at ?? ""}`)
    }
  }

  const cancelCurrentTask = () => {
    const currentSession = sessionId()
    if (
      !currentSession ||
      (!reviewing() && !reviewStarting() && !activeChatRequestId()) ||
      backendStatus() === "CANCELLING"
    ) return
    setBackendStatus("CANCELLING")
    void backend.request(
      "command.execute",
      { name: "cancel", session_id: currentSession },
      { timeoutMs: CANCEL_TIMEOUT_MS },
    )
      .then((response) => {
        if (!response.ok || response.result?.cancelled === false) {
          // The request may not have reached the backend yet; never leave the
          // UI indefinitely stuck in CANCELLING when nothing was cancelled.
          setBackendStatus(reviewing() ? "REVIEWING" : "THINKING")
        }
      })
      .catch((error) => setErrorState(String(error)))
  }

  const startReview = async (url: string) => {
    // reviewing() only flips when the backend emits review.started, so this
    // synchronous guard is what prevents two rapid retries from launching two
    // reviews (and two bills).
    if (reviewing() || reviewStarting()) return
    setReviewStarting(true)
    setPendingReviewUrl("")
    appendMessage({ role: "user", content: `/review ${url}` })
    setBackendStatus("THINKING")
    try {
      const currentSession = await ensureSession()
      const response = await backend.request("command.execute", {
        name: "review",
        args: [url],
        session_id: currentSession,
      }, { timeoutMs: REVIEW_TIMEOUT_MS })
      if (!response.ok) {
        appendMessage({ role: "assistant", content: response.error?.message ?? "PR 审查启动失败" })
        setBackendStatus("ERROR")
      } else {
        if (response.result?.report) applyReviewReport(response.result.report as ReviewReport)
        if (response.result?.text) appendMessage({ role: "assistant", content: String(response.result.text) })
        if (!response.result?.cancelled) setBackendStatus("READY")
      }
    } catch (error) {
      appendMessage({ role: "assistant", content: String(error) })
      setErrorState(String(error))
    } finally {
      setReviewStarting(false)
    }
  }

  const retryLastReview = () => {
    const url = reviewUrl()
    if (!url) {
      appendMessage({
        role: "assistant",
        content: "当前会话还没有可重试的审查。粘贴一个 GitHub PR URL，或用 /history <Run ID> 打开历史记录。",
      })
      return
    }
    if (!reviewing()) void startReview(url)
  }

  /**
   * Context for the "nothing to show" wording: a finished review with zero
   * findings must not read like "you never ran a review".
   */
  const findingsEmptyContext = () => {
    const workspace = reviewWorkspace()
    const report = reviewReport() as Record<string, unknown>
    const run = (report.run ?? {}) as Record<string, unknown>
    const filtered = (run.filtered ?? {}) as Record<string, unknown>
    const asNumber = (value: unknown): number | null =>
      typeof value === "number" && Number.isFinite(value) ? value : null
    const stage = reviewStage()
    const failed = stage === "审查失败" || stage === "审查已取消"
    return {
      running: reviewing(),
      hasReport: Boolean(workspace.runId || run.id || report.pr || report.counts) || (!failed && Boolean(stage)),
      failed,
      repository: workspace.repository,
      prNumber: workspace.prNumber,
      runId: currentRunId(),
      threshold: asNumber(filtered.threshold),
      belowThreshold: asNumber(filtered.below_threshold),
      language: runtime().ui_language,
    }
  }

  const openFindings = () => {
    setHistoryOpen(false)
    setModelOpen(false)
    setSetupOpen(false)
    setPendingReviewUrl("")
    if (reviewFindings().length > 0) {
      setFindingsOpen(true)
    } else {
      appendMessage({
        role: "assistant",
        content: emptyFindingsMessage("list", findingsEmptyContext()),
      })
    }
  }

  const currentRunId = () => reviewWorkspace().runId ?? reviewReport().run?.id ?? ""

  // ---------------------------------------------------------------------
  // P5: findings filter, offline demo/showcase, GitHub publish
  // ---------------------------------------------------------------------
  const visibleFindings = () => applyFindingsFilter(reviewFindings(), findingsFilter())
  const visibleFindingCounts = () => filterCounts(reviewFindings(), findingsFilter())

  const updateFindingsFilter = (next: FindingsFilterState) =>
    setFindingsFilter({ ...next, active: hasActiveCriteria(next) })

  const clearFindingsFilter = () => {
    setFindingsFilter(emptyFindingsFilter())
    setFilterOpen(false)
    setReviewActionMessage("已清除 Findings 筛选。")
  }

  const openFindingsFilter = () => {
    if (reviewFindings().length === 0) {
      appendMessage({
        role: "assistant",
        content: emptyFindingsMessage("filter", findingsEmptyContext()),
      })
      return
    }
    setFindingsOpen(false)
    setFilterOpen(true)
  }

  const applyFindingsFilterShortcut = (action: "severity" | "evidence" | "sort") => {
    const current = findingsFilter()
    const next =
      action === "severity"
        ? cycleSeverity(current)
        : action === "evidence"
          ? cycleEvidence(current)
          : cycleSort(current)
    updateFindingsFilter(next)
  }

  const closeFindingsFilter = () => {
    setFilterOpen(false)
    const state = findingsFilter()
    if (hasActiveCriteria(state)) {
      setReviewActionMessage(
        `Findings 筛选已应用：${describeFilter(state)}（${visibleFindingCounts().shown}/${visibleFindingCounts().total}）`,
      )
    }
  }

  const runDemo = async (caseKey: string) => {
    const key = caseKey.trim()
    const response = await backend.request("command.execute", {
      name: "demo",
      args: key ? [key] : [],
      session_id: sessionId(),
    })
    if (!response.ok) {
      setDemoOpen(true)
      setDemoData(undefined)
      setReviewActionMessage(String(response.error?.message ?? "离线 Demo 运行失败。"))
      return
    }
    setDemoData(demoPanelFromPayload(response.result))
    setDemoOpen(true)
    if (response.result?.text) {
      appendMessage({ role: "assistant", content: String(response.result.text) })
    }
  }

  const openShowcase = async () => {
    const response = await backend.request("command.execute", {
      name: "showcase",
      args: [],
      session_id: sessionId(),
    })
    if (!response.ok) {
      setReviewActionMessage(String(response.error?.message ?? "演示路径读取失败。"))
      return
    }
    setShowcaseData(showcasePanelFromPayload(response.result))
    setShowcaseOpen(true)
    if (response.result?.text) {
      appendMessage({ role: "assistant", content: String(response.result.text) })
    }
  }

  /**
   * Publish is two-phase: without `--confirm` the backend only previews, and
   * the dialog is what turns a preview into a real GitHub comment. Posting
   * straight from a keystroke is not an option.
   */
  const startPublish = async (args: string) => {
    const tokens = args.split(/\s+/).filter((token) => token.length > 0)
    const confirm = tokens.some((token) => token === "--confirm" || token === "-c")
    const runId = tokens.find((token) => !token.startsWith("-")) ?? ""
    if (publishBusy()) return
    setPublishOpen(true)
    setPublishState("publishing")
    setPublishMessage(confirm ? "正在发布审查评论…" : "正在读取发布预览…")
    setPublishBusy(true)
    try {
      const response = await backend.request("command.execute", {
        name: "publish",
        args: [...(runId ? [runId] : []), ...(confirm ? ["--confirm"] : [])],
        session_id: sessionId(),
      })
      if (!response.ok) {
        setPublishState("failed")
        setPublishMessage(String(response.error?.message ?? "发布失败。"))
        setReviewActionMessage(String(response.error?.message ?? "发布失败。"))
        return
      }
      const payload = response.result ?? {}
      setPublishPreview(publishPreviewFromPayload(payload))
      setPublishMessage(String(payload.text ?? ""))
      if (String(payload.status) === "published") {
        setPublishState("published")
        setReviewActionMessage(String(payload.text ?? "审查评论已发布。"))
        appendMessage({ role: "assistant", content: String(payload.text ?? "审查评论已发布。") })
      } else {
        setPublishState("preview")
      }
    } catch (error) {
      setPublishState("failed")
      setPublishMessage(String(error))
      setReviewActionMessage(String(error))
    } finally {
      setPublishBusy(false)
    }
  }

  const confirmPublish = () => {
    const runId = publishPreview()?.runId ?? ""
    void startPublish(runId ? `${runId} --confirm` : "--confirm")
  }

  const dismissPublish = () => {
    setPublishOpen(false)
    setPublishState("preview")
    setPublishMessage("")
  }

  const cancelPublish = () => {
    // `publishing` cannot be interrupted client-side; the backend request owns
    // that lifecycle, so only a pending preview can be cancelled.
    if (publishState() === "publishing") {
      dismissPublish()
      setReviewActionMessage("已关闭发布对话框；若请求仍在进行，结果会写入对话记录。")
      return
    }
    setPublishState("cancelled")
    setPublishMessage("已取消发布：没有向 GitHub 写入任何内容。")
    setReviewActionMessage("已取消发布：没有向 GitHub 写入任何内容。")
  }

  const explainCurrentRun = async () => {
    const runId = currentRunId()
    if (!runId) {
      setReviewActionMessage(
        "当前没有可解释的 Run。请先完成一次审查，或用 /history <run_id> 打开历史记录。",
      )
      return
    }
    const response = await backend.request("command.execute", {
      name: "explain",
      args: [runId],
      session_id: sessionId(),
    })
    setReviewActionMessage(
      response.ok
        ? String(response.result?.text ?? "解释已生成。")
        : String(response.error?.message ?? "解释失败。"),
    )
  }

  const openFeedback = (index = activeFindingIndex()) => {
    if (!reviewFindings()[index]) {
      appendMessage({
        role: "assistant",
        content: emptyFindingsMessage("feedback", findingsEmptyContext()),
      })
      return
    }
    setActiveFindingIndex(index)
    setFindingsOpen(false)
    setFeedbackOpen(true)
  }

  const submitFindingFeedback = async (
    findingId: string,
    status: string,
    note = "",
  ) => {
    const runId = currentRunId()
    if (!runId) {
      setReviewActionMessage(
        "当前没有可反馈的 Run。请先完成一次审查，或用 /history <run_id> 打开历史记录。",
      )
      return
    }
    const response = await backend.request("command.execute", {
      name: "feedback",
      args: [runId, findingId, status, note],
      session_id: sessionId(),
    })
    setReviewActionMessage(
      response.ok
        ? String(response.result?.text ?? `已记录反馈：${findingId} → ${status}`)
        : String(response.error?.message ?? "反馈保存失败。"),
    )
  }

  const exportCurrentReport = async (format = "markdown") => {
    const response = await backend.request("command.execute", {
      name: "export",
      args: [format],
      session_id: sessionId(),
    })
    appendMessage({
      role: "assistant",
      content: response.ok
        ? String(response.result?.text ?? "报告已导出。")
        : String(response.error?.message ?? "报告导出失败。"),
    })
  }

  const isWideReview = () => dimensions().width >= 120

  const reviewProgressProps = () => {
    if (!reviewing() || !reviewStage()) return undefined
    return {
      url: reviewUrl(),
      stageId: reviewStages().find((stage) => stage.status === "active")?.id ?? "",
      stageLabel: reviewStage(),
      progress: reviewProgress(),
      stages: reviewStages(),
      filesDone: reviewFilesDone(),
      filesTotal: reviewFilesTotal() || undefined,
      currentFile: reviewFile() || undefined,
      fileStates: reviewFileStates(),
      routing: reviewRouting(),
      elapsedMs: reviewElapsedMs(),
      cost: reviewWorkspace().cost,
      language: runtime().ui_language,
      onCancel: cancelCurrentTask,
    }
  }

  const reviewSummaryProps = () => {
    if (!reviewReport().pr && !reviewReport().counts) return undefined
    return {
      repository: reviewWorkspace().repository,
      prNumber: reviewWorkspace().prNumber,
      title: reviewWorkspace().title,
      severity: reviewWorkspace().severity,
      evidence: reviewWorkspace().evidence,
      filesReviewed: reviewWorkspace().filesReviewed,
      filesSkipped: reviewWorkspace().filesSkipped,
      findings: reviewFindings(),
      durationSeconds: reviewWorkspace().durationSeconds,
      cost: reviewWorkspace().cost,
      runId: reviewWorkspace().runId,
      model: runtime().model,
      language: runtime().ui_language,
      onOpenFindings: openFindings,
    }
  }

  const resetSessionUi = () => {
    setMessages([])
    setStreamingAssistant("")
    setActiveChatRequestId(undefined)
    setReviewStage("")
    setReviewDetail("")
    setReviewFile("")
    setReviewFilesDone(0)
    setReviewProgress(0)
    setReviewUrl("")
    setReviewSummary("")
    setReviewFindings([])
    resetReviewWorkspaceState()
    setFindingsOpen(false)
    setHistoryOpen(false)
    setHistoryRuns([])
    setHistoryStats({})
    setModelOpen(false)
    setReviewReport({})
    setPendingReviewUrl("")
    setReviewing(false)
    setErrorMessage("")
    setBackendStatus("READY")
  }

  // A restarted Python process has no in-memory sessions. Bind exactly one
  // frontend session to each backend generation; never silently reuse the old ID.
  let boundGeneration = 0
  let recovering: Promise<string> | undefined
  const ensureSession = async (force = false): Promise<string> => {
    await backend.start()
    const current = sessionId()
    if (!force && current && boundGeneration === backend.generation) return current
    if (recovering) return recovering
    recovering = (async () => {
      const previous = sessionId()
      const snapshot = await backend.request("config.snapshot", {}, { timeoutMs: PROBE_TIMEOUT_MS })
      if (!snapshot.ok) throw new Error(snapshot.error?.message ?? "无法读取后端配置")
      const created = await backend.request("session.create", {}, { timeoutMs: PROBE_TIMEOUT_MS })
      if (!created.ok) throw new Error(created.error?.message ?? "无法恢复 Chat 会话")
      const next = String(created.result.session_id)
      const configuration = snapshot.result as RuntimeSnapshot
      setRuntime(configuration)
      setSessionId(next)
      for (const warning of configuration.configuration_warnings ?? []) {
        appendMessage({ role: "assistant", content: `配置提示：${warning}` })
      }
      boundGeneration = backend.generation
      // Inspect the active provider in the newly spawned backend, rather than
      // leaving the ONLINE/OFFLINE badge from the previous process.
      try {
        const status = await backend.request("model.status", {}, { timeoutMs: PROBE_TIMEOUT_MS })
        if (status.ok && boundGeneration === backend.generation) {
          setRuntime((current) => ({ ...current, ...(status.result as RuntimeSnapshot) }))
        }
      } catch {
        // A session can recover even when model discovery is offline.
      }
      if (previous) {
        setActiveChatRequestId(undefined)
        setStreamingAssistant("")
        setReviewing(false)
        setReviewStage("")
        setReviewDetail("")
        setReviewFile("")
        setReviewProgress(0)
        setReviewSummary("")
        setReviewFindings([])
        resetReviewWorkspaceState()
        setReviewReport({})
        setFindingsOpen(false)
        setErrorMessage("")
        appendMessage({ role: "assistant", content: "后端已重启，旧会话上下文和当前报告无法自动恢复；已建立新会话。历史审查可使用 /history 查看。" })
      }
      return next
    })()
    try {
      return await recovering
    } finally {
      recovering = undefined
    }
  }

  onMount(async () => {
    try {
      const health = await backend.request("health", {}, { timeoutMs: PROBE_TIMEOUT_MS })
      if (!health.ok) throw new Error(health.error?.message ?? "Backend unavailable")
      await ensureSession()
      setBackendStatus("READY")
      backend.onEvent((event) => {
        // A review (or chat) still running on a session the user has left must
        // not paint progress or findings into the current transcript.
        if (isForeignSessionEvent(event, sessionId())) return
        if (event.event?.startsWith("assistant.") && !isCurrentAssistantEvent(event, sessionId(), activeChatRequestId())) return
        if (event.event === "assistant.started") {
          setStreamingAssistant("")
          setBackendStatus("THINKING")
        }
        if (event.event === "review.started") {
          setReviewing(true)
          setReviewSummary("")
          setReviewFindings([])
          setReviewReport({})
          resetReviewWorkspaceState()
          setReviewProgress(0)
          setReviewUrl(String(event.url ?? ""))
          setReviewStartedAt(Date.now())
          setReviewElapsedMs(0)
          setBackendStatus("REVIEWING")
          setReviewStage("准备审查")
          setReviewDetail(`正在处理 ${String(event.url ?? "PR")}`)
          setReviewFile("")
          setReviewFilesDone(0)
        }
        if (event.event === "review.stage") {
          const stage = String(event.stage ?? "审查中")
          const stageId = stageIdFromEvent(event.stage_id, event.stage)
          const rawStatus = String(event.status ?? "started")
          const stageStatus =
            rawStatus === "completed"
              ? "done"
              : rawStatus === "failed"
                ? "failed"
                : rawStatus === "skipped"
                  ? "skipped"
                  : "active"
          const progressByStage: Record<string, number> = {
            "获取 PR 数据": 5,
            "过滤变更文件": 10,
            "构建代码上下文": 20,
            "运行静态规则": 30,
            "执行 AI 审查": 70,
            "分析跨文件影响": 90,
            "保存审查记录": 98,
          }
          setBackendStatus("REVIEWING")
          setReviewProgress(progressByStage[stage] ?? reviewProgress())
          setReviewStage(stage)
          setReviewDetail(String(event.detail ?? ""))
          updateStageState(stageId, {
            label: stage,
            status: stageStatus,
            detail: String(event.detail ?? ""),
            durationMs: typeof event.duration_ms === "number" ? event.duration_ms : undefined,
          })
        }
        if (event.event === "review.stage_done") {
          const stage = String(event.stage ?? "")
          const stageId = stageIdFromEvent(event.stage_id, event.stage)
          updateStageState(stageId, {
            label: stage || stageId,
            status: event.status === "failed" ? "failed" : "done",
            durationMs: typeof event.duration_ms === "number" ? event.duration_ms : undefined,
          })
          if (typeof event.progress === "number") setReviewProgress(event.progress)
        }
        if (event.event === "review.file_started") {
          const filename = String(event.filename ?? "")
          setReviewFile(filename)
          if (typeof event.total === "number" && event.total > 0) setReviewFilesTotal(event.total)
          updateFileState(filename, { status: "pending" })
        }
        if (event.event === "review.file_done") {
          const filename = String(event.filename ?? "")
          const rawStatus = String(event.status ?? "reviewed")
          const fileStatus =
            rawStatus === "skipped"
              ? "skipped"
              : rawStatus === "failed"
                ? "failed"
                : "reviewed"
          updateFileState(filename, {
            status: fileStatus,
            findingsCount: typeof event.findings_count === "number" ? event.findings_count : null,
            durationMs: typeof event.duration_ms === "number" ? event.duration_ms : undefined,
            reason: typeof event.reason === "string" ? event.reason : undefined,
            error: typeof event.message === "string" ? event.message : undefined,
          })
          setReviewFilesDone((count) => count + 1)
        }
        if (event.event === "review.model_routing") {
          setReviewRouting({
            runtimeProfile: typeof event.runtime_profile === "string" ? event.runtime_profile : undefined,
            routerModel: typeof event.router_model === "string" ? event.router_model : undefined,
            deepModel: typeof event.deep_model === "string" ? event.deep_model : undefined,
            reason: typeof event.reason === "string" ? event.reason : undefined,
          })
        }
        if (event.event === "review.completed") {
          setReviewing(false)
          setReviewProgress(100)
          setBackendStatus("READY")
          setReviewStage("审查完成")
          setReviewDetail(`发现 ${String(event.finding_count ?? 0)} 个问题 · Run ${String(event.run_id ?? "")}`)
          setReviewFile("")
          if (typeof event.duration_seconds === "number") {
            setReviewElapsedMs(Math.max(0, event.duration_seconds * 1000))
          }
          setReviewWorkspace((current) => ({
            ...current,
            filesReviewed:
              typeof event.files_reviewed === "number"
                ? event.files_reviewed
                : current.filesReviewed,
            filesSkipped:
              typeof event.files_skipped === "number"
                ? event.files_skipped
                : current.filesSkipped,
            durationSeconds:
              typeof event.duration_seconds === "number"
                ? event.duration_seconds
                : current.durationSeconds,
            cost: typeof event.cost === "number" ? event.cost : current.cost,
            runId: typeof event.run_id === "string" ? event.run_id : current.runId,
            severity:
              event.severity && typeof event.severity === "object"
                ? {
                    critical: Number((event.severity as Record<string, unknown>).critical ?? 0),
                    high: Number((event.severity as Record<string, unknown>).high ?? 0),
                    medium: Number((event.severity as Record<string, unknown>).medium ?? 0),
                    low: Number((event.severity as Record<string, unknown>).low ?? 0),
                    info: Number((event.severity as Record<string, unknown>).info ?? 0),
                  }
                : current.severity,
            evidence:
              event.evidence && typeof event.evidence === "object"
                ? {
                    valid: Number((event.evidence as Record<string, unknown>).valid ?? 0),
                    needsReview: Number(
                      (event.evidence as Record<string, unknown>).needs_review ??
                        (event.evidence as Record<string, unknown>).needsReview ??
                        0,
                    ),
                    invalid: Number((event.evidence as Record<string, unknown>).invalid ?? 0),
                    unverified: Number(
                      (event.evidence as Record<string, unknown>).unverified ?? 0,
                    ),
                  }
                : current.evidence,
          }))
        }
        if (event.event === "review.failed") {
          if (typeof event.stage_id === "string") {
            updateStageState(event.stage_id, { status: "failed" })
          }
          setReviewing(false)
          setBackendStatus("ERROR")
          setReviewStage("审查失败")
          setReviewDetail(String(event.message ?? "未知错误"))
          setErrorMessage(`${String(event.title ?? "请求失败")}：${String(event.message ?? "未知错误")}\n${String(event.recovery ?? "检查模型状态后重试。")}`)
          setReviewFile("")
        }
        if (event.event === "review.cancelled") {
          if (typeof event.stage_id === "string") {
            updateStageState(event.stage_id, { status: "skipped" })
          }
          setReviewing(false)
          setBackendStatus("READY")
          setReviewStage("审查已取消")
          setReviewDetail(String(event.message ?? "审查已取消"))
          setReviewFile("")
        }
        if (event.event === "assistant.delta") {
          setStreamingAssistant((current) => current + String(event.text ?? ""))
        }
        if (event.event === "assistant.finished") {
          const finalText = String(event.text ?? streamingAssistant())
          appendMessage({ role: "assistant", content: finalText })
          if (typeof event.request_id === "string") renderedAssistantReplies.add(event.request_id)
          setStreamingAssistant("")
          setBackendStatus("READY")
        }
        if (event.event === "assistant.cancelled") {
          const partial = streamingAssistant()
          if (partial) appendMessage({ role: "assistant", content: `${partial} [已取消]` })
          if (typeof event.request_id === "string") renderedAssistantReplies.add(event.request_id)
          setStreamingAssistant("")
          setBackendStatus("READY")
        }
        if (event.event === "assistant.failed") {
          setStreamingAssistant("")
          setBackendStatus("ERROR")
        }
      })
    } catch (error) {
      setErrorMessage(`Python 后端启动失败：${String(error)}`)
      setBackendStatus("FALLBACK")
    }
  })
  onCleanup(() => void backend.stop())

  return (
    <box width="100%" height="100%" backgroundColor={background} alignItems="center" flexDirection="column">
      <Show when={messages().length === 0 && !reviewStage() && !errorMessage() && !compactHome()} fallback={
        <box width={76} marginTop={1} flexDirection="row" justifyContent="space-between">
          <text fg={orange}>PR REVIEW / CHAT</text>
          <text fg={muted}>{runtime().provider_display ?? runtime().provider ?? ""} · {runtime().model ?? ""}</text>
        </box>
      }>
        <PixelLogo language={runtime().ui_language} />
      </Show>
      {/* Middle row: review panels live outside the chat scrollbox, so they can
          no longer push the transcript out of view. The chat column keeps a
          stable position in the tree, which is what keeps the composer's draft
          and cursor alive across Alt+W. */}
      <box width="100%" flexGrow={1} flexDirection="row" minHeight={0}>
      <Show when={reviewLayout() === "three" && reviewProgressProps()}>
        <box width={leftColumnWidth} flexShrink={0} marginRight={1} flexDirection="column" minHeight={0}>
          <ReviewProgressPanel {...reviewProgressProps()!} />
        </box>
      </Show>
      <box flexGrow={1} minWidth={0} flexDirection="column" alignItems="center">
      <scrollbox width="100%" flexGrow={1} scrollY stickyScroll stickyStart="bottom" scrollbarOptions={{ showArrows: false }}>
        <box width="100%" alignItems="center" flexDirection="column">
      <Show when={messages().length === 0 && !composerDraft() && !streamingAssistant() && !errorMessage() && !reviewStage() && !compactHome()}>
        <QuickStartPanel language={runtime().ui_language} />
      </Show>
      <Show when={errorMessage()}>
        <box width={chatContentWidth()} backgroundColor="#241616" borderStyle="single" borderColor="#ff6b6b" paddingLeft={2} paddingRight={2} marginTop={2} flexDirection="column">
          <text fg="#ff6b6b">ERROR // RECOVERY</text>
          <text fg="#eeeeee">{errorMessage()}</text>
          <text fg={muted}>建议：检查模型状态、配置 Endpoint，或使用 Ctrl+P 切换运行时。</text>
          <text fg={muted}>可用恢复：Ctrl+R /retry · /model status · /model local · /model cloud · /new</text>
        </box>
      </Show>
      <Show when={reviewFindings().length > 0}>
        <box width={chatContentWidth()} marginTop={1} flexDirection="column">
          <FindingsFilterBar
            active={hasActiveCriteria(findingsFilter()) || findingsFilter().sort !== "severity"}
            query={findingsFilter().query}
            severity={findingsFilter().severity === "all" ? undefined : findingsFilter().severity}
            evidence={findingsFilter().evidence === "all" ? undefined : findingsFilter().evidence}
            sort={findingsFilter().sort}
            shown={visibleFindingCounts().shown}
            total={visibleFindingCounts().total}
            language={runtime().ui_language}
          />
        </box>
      </Show>
      <Show when={!reviewing() && (reviewStage() === "审查失败" || reviewStage() === "审查已取消")}>
        <box width={76} backgroundColor="#161616" borderStyle="single" borderColor={reviewStage() === "审查失败" ? "#ff6b6b" : orange} paddingLeft={2} paddingRight={2} marginTop={2} flexDirection="column">
          <text fg={reviewStage() === "审查失败" ? "#ff6b6b" : orange}>● {reviewStage()}</text>
          <text fg="#b0b0b0">{reviewDetail()}</text>
          <Show when={reviewUrl()}>
            <text fg={muted}>{truncateMiddle(reviewUrl(), 68)}</text>
          </Show>
        </box>
      </Show>
      <Show when={messages().length > 0 || streamingAssistant()}>
        <box width={chatContentWidth()} marginTop={2} flexDirection="column">
          <For each={messages()}>{(message) =>
            <box flexDirection="row" gap={1} paddingBottom={1}>
              <text fg={message.role === "user" ? orange : "#eeeeee"}>{message.role === "user" ? ">" : "●"}</text>
              <text width={Math.max(24, chatContentWidth() - 6)} fg={message.role === "user" ? "#eeeeee" : muted}>{message.content}</text>
            </box>
          }</For>
          <Show when={streamingAssistant()}>
            <box flexDirection="row" gap={1}>
              <text fg={orange}>●</text>
              <text width={Math.max(24, chatContentWidth() - 6)} fg="#eeeeee">{streamingAssistant()}</text>
            </box>
          </Show>
        </box>
      </Show>
      <Show when={reviewActionMessage()}>
        <box width={chatContentWidth()} backgroundColor="#141414" borderStyle="single" borderColor="#7edc92" paddingLeft={2} paddingRight={2} marginTop={1} flexDirection="column">
          <text fg="#7edc92">REVIEW ACTION // 操作结果</text>
          <text fg="#eeeeee">{reviewActionMessage()}</text>
        </box>
      </Show>
        </box>
      </scrollbox>
      {/* Collapsed / narrow workbench: one line above the composer. The wording
          and width-safe clamping live in MiMo Code's ReviewStatusBar. */}
      <Show when={workbenchVisible() && !workbenchPanelsVisible()}>
        <ReviewStatusBar
          phase={reviewPhase()}
          progress={reviewProgress()}
          stageLabel={reviewStage()}
          filesDone={reviewFilesDone()}
          filesTotal={reviewFilesTotal() || undefined}
          findingCount={reviewFindings().length}
          severity={reviewWorkspace().severity}
          threshold={reportFiltered().threshold}
          belowThreshold={reportFiltered().belowThreshold}
          toggleKey="Alt+W"
          language={runtime().ui_language}
          width={Math.max(12, chatContentWidth() - 2)}
        />
      </Show>
      <Composer
        mode={mode()}
        setMode={setMode}
        backend={backend}
        sessionId={sessionId()}
        onEnsureSession={ensureSession}
        onMessage={appendMessage}
        onStatus={setBackendStatus}
        onRuntimeChange={setRuntime}
        runtime={runtime()}
        onSetup={() => setSetupOpen(true)}
        onSessionChange={setSessionId}
        onNewSession={resetSessionUi}
        onReviewReport={applyReviewReport}
        onReviewRequest={(url) => setPendingReviewUrl(url)}
        onOpenFindings={openFindings}
        onOpenHistory={() => void openHistory()}
        onOpenModel={() => setModelOpen(true)}
        onExplain={() => void explainCurrentRun()}
        onFeedback={() => openFeedback()}
        onExport={() => void exportCurrentReport()}
        onPublish={(args) => void startPublish(args)}
        onDemo={(caseKey) => void runDemo(caseKey)}
        onShowcase={() => void openShowcase()}
        onFilterFindings={openFindingsFilter}
        onRetry={retryLastReview}
        reviewing={reviewing()}
        onCancel={cancelCurrentTask}
        onToggleWorkbench={toggleWorkbench}
        workbenchActive={workbenchVisible()}
        onDraftChange={setComposerDraft}
        onChatRequestStart={setActiveChatRequestId}
        onChatRequestEnd={() => setActiveChatRequestId(undefined)}
        hasRenderedAssistantReply={hasRenderedAssistantReply}
        busy={backendStatus() === "THINKING" || backendStatus() === "REVIEWING" || backendStatus() === "CANCELLING"}
        focused={
          !findingsOpen() &&
          !feedbackOpen() &&
          !historyOpen() &&
          !modelOpen() &&
          !setupOpen() &&
          !filterOpen() &&
          !publishOpen() &&
          !demoOpen() &&
          !showcaseOpen() &&
          pendingReviewUrl() === "" &&
          reviewStage() !== "审查失败"
        }
      />
      </box>
      {/* Right column: summary + actions (and, in the two-column layout, the
          progress panel too — 120x30 has no room for a separate left column). */}
      <Show when={reviewLayout() !== "bar" && workbenchVisible()}>
        <box width={rightColumnWidth()} flexShrink={0} marginLeft={1} flexDirection="column" minHeight={0}>
          <Show when={reviewLayout() === "two" && reviewProgressProps()}>
            <box flexShrink={0} marginBottom={1}>
              <ReviewProgressPanel {...reviewProgressProps()!} />
            </box>
          </Show>
          <Show when={reviewSummaryProps()}>
            <box flexGrow={1} minHeight={0}>
              <ReviewSummaryPanel {...reviewSummaryProps()!} />
            </box>
          </Show>
          <ReviewActionBar
            onOpenFindings={openFindings}
            onExplain={() => void explainCurrentRun()}
            onFeedback={() => openFeedback()}
            onExport={() => void exportCurrentReport()}
            onPublish={() => void startPublish("")}
            onFilter={openFindingsFilter}
            language={runtime().ui_language}
          />
        </box>
      </Show>
      </box>
      <Show when={modelOpen()}>
        <ModelDialog
          backend={backend}
          runtime={runtime()}
          onClose={() => setModelOpen(false)}
          onApplied={(snapshot) => {
            setRuntime(snapshot)
            appendMessage({ role: "assistant", content: `模型已切换为 ${snapshot.model ?? "unknown"}` })
          }}
        />
      </Show>
      <Show when={historyOpen()}>
        <HistoryDialog runs={historyRuns()} statistics={historyStats()} fallbackNote={historyStoreNote()} onOpen={openHistoryRun} onClose={() => setHistoryOpen(false)} />
      </Show>
      <Show when={findingsOpen()}>
        <FindingsDialog
          findings={reviewFindings()}
          onSelect={setActiveFindingIndex}
          onExplain={(index) => {
            setActiveFindingIndex(index)
            setFindingsOpen(false)
            void explainCurrentRun()
          }}
          onFeedback={(index) => {
            setActiveFindingIndex(index)
            setFindingsOpen(false)
            setFeedbackOpen(true)
          }}
          onExport={() => void exportCurrentReport()}
          onClose={() => setFindingsOpen(false)}
        />
      </Show>
      <Show when={feedbackOpen() && reviewFindings()[activeFindingIndex()]}>
        <FeedbackDialog
          finding={reviewFindings()[activeFindingIndex()]}
          language={runtime().ui_language}
          onSelect={(status, note) => {
            setFeedbackOpen(false)
            void submitFindingFeedback(String(activeFindingIndex()), status, note)
          }}
          onClose={() => setFeedbackOpen(false)}
        />
      </Show>
      <Show when={reviewStage() === "审查失败" && reviewUrl()}>
        <ReviewFailureDialog
          url={reviewUrl()}
          message={reviewDetail()}
          onRetry={() => { setFindingsOpen(false); void startReview(reviewUrl()) }}
          onClose={() => setReviewStage("")}
        />
      </Show>
      <Show when={filterOpen()}>
        <FindingsFilterOverlay
          state={findingsFilter()}
          shown={visibleFindingCounts().shown}
          total={visibleFindingCounts().total}
          language={runtime().ui_language}
          onQuery={(query) => updateFindingsFilter({ ...findingsFilter(), query })}
          onShortcut={applyFindingsFilterShortcut}
          onApply={closeFindingsFilter}
          onClear={clearFindingsFilter}
        />
      </Show>
      <Show when={publishOpen()}>
        <PublishOverlay
          state={publishState()}
          preview={publishPreview()}
          message={publishMessage()}
          language={runtime().ui_language}
          busy={publishBusy()}
          onConfirm={confirmPublish}
          onCancel={cancelPublish}
          onClose={dismissPublish}
        />
      </Show>
      <Show when={demoOpen()}>
        <DemoOverlay data={demoData()} language={runtime().ui_language} onClose={() => setDemoOpen(false)} />
      </Show>
      <Show when={showcaseOpen()}>
        <ShowcaseOverlay
          data={showcaseData()}
          language={runtime().ui_language}
          onClose={() => setShowcaseOpen(false)}
        />
      </Show>
      <Show when={setupOpen()}>
        <SetupWizardDialog
          backend={backend}
          runtime={runtime()}
          onClose={() => setSetupOpen(false)}
          onApplied={(snapshot) => {
            setRuntime(snapshot)
            setBackendStatus("READY")
            appendMessage({
              role: "assistant",
              content: `配置已保存：${snapshot.provider_display ?? snapshot.provider ?? "provider"} / ${snapshot.model ?? "model"} · ${snapshot.runtime_profile ?? "runtime"}`,
            })
            void backend
              .request("model.status", {}, { timeoutMs: PROBE_TIMEOUT_MS })
              .then((status) => {
                if (status.ok) setRuntime((current) => ({ ...current, ...(status.result as RuntimeSnapshot) }))
              })
              .catch(() => {
                // The saved configuration is still valid when probing is offline.
              })
          }}
        />
      </Show>
      <Show when={pendingReviewUrl()}>
        <ReviewConfirmDialog
          url={pendingReviewUrl()}
          onConfirm={() => void startReview(pendingReviewUrl())}
          onClose={() => setPendingReviewUrl("")}
        />
      </Show>
      <box width="100%" flexShrink={0} justifyContent="space-between" paddingLeft={2} paddingRight={2} paddingBottom={1}>
        <text fg={muted}>{workspaceRootLabel()}</text>
        <text fg={statusColors[backendStatus()]}>{runtime().runtime_profile ?? "RUNTIME"} · {statusLabels[backendStatus()]} · {runtime().model ?? "model"} · {runtime().available === false ? "OFFLINE" : runtime().available === true ? "ONLINE" : "0.1.0"} · {dimensions().width}×{dimensions().height}</text>
      </box>
    </box>
  )
}









