import { createSignal, For, Show, onMount, onCleanup } from "solid-js"
import { useKeyboard, useRenderer, useTerminalDimensions } from "@opentui/solid"
import { BackendClient } from "./backend"
import { isCurrentAssistantEvent, isForeignSessionEvent } from "./protocol"
import { sendWithSessionRecovery } from "./session-recovery"
import { commandCompletion, commandEnterAction, commandMatches } from "./command-menu"
import { truncateMiddle, workspaceRootLabel } from "./format"
import { detailScrollDelta } from "./keymap"
import { reviewReportPanels } from "./review-report"
import type { TextareaRenderable, KeyBinding, ScrollBoxRenderable } from "@opentui/core"

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
  const renderer = useRenderer()
  const dimensions = useTerminalDimensions()
  let textarea: TextareaRenderable | undefined
  let submitLock = false
  let dismissedDraft: string | undefined
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
  ]

  const setDraft = (text: string) => {
    textarea?.setText(text)
    setValue(text)
    props.onDraftChange(text)
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
    // Ctrl+C must keep working while a dialog owns the focus: otherwise the
    // only way out of a running task is killing the terminal.
    if (isCtrlKey(key, "c")) {
      if (props.busy) {
        props.onCancel()
        key.stopPropagation()
      } else {
        renderer.destroy()
      }
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
    if (isCtrlKey(key, "o") && !props.busy) {
      props.onOpenFindings()
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
      <box flexDirection="row" justifyContent="space-between" paddingLeft={1} paddingRight={1} marginTop={1}>
        <text><span style={{ fg: "#eeeeee" }}>Enter</span> <span style={{ fg: muted }}>发送</span></text>
        <text><span style={{ fg: "#eeeeee" }}>Shift+Enter</span> <span style={{ fg: muted }}>换行</span></text>
        <text><span style={{ fg: "#eeeeee" }}>Ctrl+P</span> <span style={{ fg: muted }}>设置</span></text>
        <text><span style={{ fg: "#eeeeee" }}>Ctrl+L</span> <span style={{ fg: muted }}>历史</span></text>
        <text><span style={{ fg: "#eeeeee" }}>Ctrl+K</span> <span style={{ fg: muted }}>模型</span></text>
      </box>
    </box>
  )
}

type RuntimeDialogProps = {
  backend: BackendClient
  runtime: RuntimeSnapshot
  onClose: () => void
  onApplied: (snapshot: RuntimeSnapshot) => void
}

const runtimeOptions = [
  { name: "Cloud", description: "第三方 API：适合高质量审查与远程模型", value: "cloud" },
  { name: "Local", description: "Ollama 本地模型：离线可用，数据留在本机", value: "local" },
  { name: "Hybrid", description: "混合策略：按任务在本地与云端之间协作", value: "hybrid" },
  { name: "Offline", description: "离线优先：只使用本地运行时", value: "offline" },
]

function RuntimeDialog(props: RuntimeDialogProps) {
  const initial = runtimeOptions.findIndex((option) => option.value === props.runtime.runtime_profile)
  const [selectedIndex, setSelectedIndex] = createSignal(initial >= 0 ? initial : 0)
  const [busy, setBusy] = createSignal(false)
  const [error, setError] = createSignal("")

  const apply = async () => {
    const option = runtimeOptions[selectedIndex()]
    setBusy(true)
    setError("")
    try {
      const response = await props.backend.request("config.apply", { section: "runtime", value: option.value })
      if (!response.ok) {
        setError(response.error?.message ?? "配置保存失败")
        return
      }
      props.onApplied(response.result as RuntimeSnapshot)
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
    <box position="absolute" left={10} top={4} width={58} height={17} backgroundColor="#171717" borderStyle="single" borderColor={orange} padding={2} zIndex={100} flexDirection="column">
      <text fg={orange}>配置助手 // RUNTIME PROFILE</text>
      <text fg={muted}>选择 Chat 的默认运行时（↑↓ / Enter，Esc 取消）</text>
      <box marginTop={1} flexGrow={1}>
        <select
          options={runtimeOptions}
          selectedIndex={selectedIndex()}
          focused
          showDescription
          selectedBackgroundColor="#5a2e1c"
          selectedTextColor="#ffffff"
          descriptionColor={muted}
          selectedDescriptionColor="#ffd0bb"
          onChange={(index) => setSelectedIndex(index)}
        />
      </box>
      <Show when={error()}><text fg="#ff6b6b">{error()}</text></Show>
      <text fg={busy() ? orange : muted}>{busy() ? "保存中..." : "Enter 保存 · Esc 取消"}</text>
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
    <box position="absolute" left={8} top={5} width={64} height={14} backgroundColor="#171717" borderStyle="single" borderColor={orange} padding={2} zIndex={120} flexDirection="column">
      <text fg={orange}>开始 PR 审查 // CONFIRM</text>
      <text fg={muted}>已识别 GitHub Pull Request：</text>
      <text fg="#eeeeee">{props.url}</text>
      <box marginTop={1} flexGrow={1}>
        <select
          options={options}
          selectedIndex={selectedIndex()}
          focused
          showDescription
          selectedBackgroundColor="#5a2e1c"
          selectedTextColor="#ffffff"
          descriptionColor={muted}
          selectedDescriptionColor="#ffd0bb"
          onChange={(index) => setSelectedIndex(index)}
        />
      </box>
      <text fg={muted}>↑↓ 选择 · Enter 确认 · Esc 返回</text>
    </box>
  )
}

export function FindingsDialog(props: { findings: ReviewFinding[]; onClose: () => void }) {
  const pageSize = 8
  const [selectedIndex, setSelectedIndex] = createSignal(0)
  const [page, setPage] = createSignal(0)
  let detailScroll: ScrollBoxRenderable | undefined
  const pageCount = () => Math.max(1, Math.ceil(props.findings.length / pageSize))
  const pageFindings = () => props.findings.slice(page() * pageSize, (page() + 1) * pageSize)
  const selected = () => props.findings[selectedIndex()] ?? {}
  useKeyboard((key) => {
    if (key.name === "escape") props.onClose()
    const detailDelta = detailScrollDelta(key.name, key.shift === true)
    if (detailDelta !== undefined) {
      // The footer promised "详情滚动" but only the mouse could scroll it.
      detailScroll?.scrollBy(detailDelta)
      key.preventDefault()
      key.stopPropagation()
      return
    }
    if (key.name === "pageup" || key.name === "left") {
      setPage((current) => Math.max(0, current - 1))
      setSelectedIndex((current) => Math.max(0, current - pageSize))
    }
    if (key.name === "pagedown" || key.name === "right") {
      setPage((current) => Math.min(pageCount() - 1, current + 1))
      setSelectedIndex((current) => Math.min(props.findings.length - 1, current + pageSize))
    }
  })
  return (
    <box position="absolute" left={5} top={2} width={70} height={22} backgroundColor="#171717" borderStyle="single" borderColor={orange} padding={2} zIndex={130} flexDirection="column">
      <text fg={orange}>FINDINGS // DETAIL</text>
      <box height={8} marginTop={1}>
        <select
          options={pageFindings().map((finding, offset) => ({
            name: `[${String(finding.severity ?? "info").toUpperCase()}] ${finding.title ?? finding.message ?? "未命名问题"}`,
            description: `${finding.file ?? "unknown"}:${finding.line_start ?? "?"}-${finding.line_end ?? finding.line_start ?? "?"}`,
            value: page() * pageSize + offset,
          }))}
          selectedIndex={Math.max(0, selectedIndex() - page() * pageSize)}
          focused
          showDescription
          selectedBackgroundColor="#5a2e1c"
          selectedTextColor="#ffffff"
          descriptionColor={muted}
          selectedDescriptionColor="#ffd0bb"
          onChange={(index) => setSelectedIndex(page() * pageSize + index)}
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
      <text fg={muted}>↑↓ 选择 · Shift+↑↓ 详情 · ←→/Pg 翻页 ({page() + 1}/{pageCount()}) · Esc 返回</text>
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
        <select options={options} selectedIndex={selectedIndex()} focused showDescription selectedBackgroundColor="#5a2e1c" selectedTextColor="#ffffff" descriptionColor={muted} selectedDescriptionColor="#ffd0bb" onChange={(index) => setSelectedIndex(index)} />
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
  const [findingsOpen, setFindingsOpen] = createSignal(false)
  const [historyOpen, setHistoryOpen] = createSignal(false)
  const [historyRuns, setHistoryRuns] = createSignal<HistoryRun[]>([])
  const [historyStats, setHistoryStats] = createSignal<HistoryStats>({})
  const [historyStoreNote, setHistoryStoreNote] = createSignal("")
  const [modelOpen, setModelOpen] = createSignal(false)
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

  // Single place that turns a report into visible panels, so a new caller
  // cannot populate the summary while forgetting the findings list.
  const applyReviewReport = (report: ReviewReport) => {
    const panels = reviewReportPanels(report)
    setReviewReport(report)
    setReviewSummary(panels.summary)
    setReviewFindings(panels.findings as ReviewFinding[])
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
    if (url && !reviewing()) void startReview(url)
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
          setReviewProgress(0)
          setReviewUrl(String(event.url ?? ""))
          setBackendStatus("REVIEWING")
          setReviewStage("准备审查")
          setReviewDetail(`正在处理 ${String(event.url ?? "PR")}`)
          setReviewFile("")
          setReviewFilesDone(0)
        }
        if (event.event === "review.stage") {
          const stage = String(event.stage ?? "审查中")
          const progressByStage: Record<string, number> = {
            "获取 PR 数据": 5,
            "过滤变更文件": 10,
            "构建代码上下文": 20,
            "执行 AI 审查": 70,
            "分析跨文件影响": 90,
            "保存审查记录": 98,
          }
          setBackendStatus("REVIEWING")
          setReviewProgress(progressByStage[stage] ?? reviewProgress())
          setReviewStage(stage)
          setReviewDetail(String(event.detail ?? ""))
        }
        if (event.event === "review.file_started") {
          setReviewFile(String(event.filename ?? ""))
        }
        if (event.event === "review.file_done") {
          setReviewFilesDone((count) => count + 1)
        }
        if (event.event === "review.completed") {
          setReviewing(false)
          setReviewProgress(100)
          setBackendStatus("READY")
          setReviewStage("审查完成")
          setReviewDetail(`发现 ${String(event.finding_count ?? 0)} 个问题 · Run ${String(event.run_id ?? "")}`)
          setReviewFile("")
        }
        if (event.event === "review.failed") {
          setReviewing(false)
          setBackendStatus("ERROR")
          setReviewStage("审查失败")
          setReviewDetail(String(event.message ?? "未知错误"))
          setErrorMessage(`${String(event.title ?? "请求失败")}：${String(event.message ?? "未知错误")}\n${String(event.recovery ?? "检查模型状态后重试。")}`)
          setReviewFile("")
        }
        if (event.event === "review.cancelled") {
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
      <scrollbox width="100%" flexGrow={1} scrollY stickyScroll stickyStart="bottom" scrollbarOptions={{ showArrows: false }}>
        <box width="100%" alignItems="center" flexDirection="column">
      <Show when={messages().length === 0 && !composerDraft() && !streamingAssistant() && !errorMessage() && !reviewStage() && !compactHome()}>
        <QuickStartPanel language={runtime().ui_language} />
      </Show>
      <Show when={errorMessage()}>
        <box width={76} backgroundColor="#241616" borderStyle="single" borderColor="#ff6b6b" paddingLeft={2} paddingRight={2} marginTop={2} flexDirection="column">
          <text fg="#ff6b6b">ERROR // RECOVERY</text>
          <text fg="#eeeeee">{errorMessage()}</text>
          <text fg={muted}>建议：检查模型状态、配置 Endpoint，或使用 Ctrl+P 切换运行时。</text>
          <text fg={muted}>可用恢复：Ctrl+R /retry · /model status · /model local · /model cloud · /new</text>
        </box>
      </Show>
      <Show when={reviewStage()}>
        <box width={76} backgroundColor="#161616" borderStyle="single" borderColor={reviewStage() === "审查完成" ? "#5b9b6d" : orange} paddingLeft={2} paddingRight={2} marginTop={2} flexDirection="column">
          <box flexDirection="row" justifyContent="space-between">
            <text fg={reviewStage() === "审查完成" ? "#7edc92" : reviewStage() === "审查失败" ? "#ff6b6b" : orange}>● {reviewStage()}</text>
            <text fg={muted}>{reviewProgress()}% · {reviewFilesDone() > 0 ? `已完成 ${reviewFilesDone()} 个文件` : ""}</text>
          </box>
          <text fg="#b0b0b0">{reviewFile() ? `正在分析 ${reviewFile()}` : reviewDetail()}</text>
          <Show when={reviewProgress() > 0}>
            <text fg={muted}>{`${"█".repeat(Math.max(1, Math.floor(reviewProgress() / 5)))}${"░".repeat(20 - Math.max(1, Math.floor(reviewProgress() / 5)))} ${reviewProgress()}%`}</text>
          </Show>
          <Show when={reviewUrl()}>
            {/* PR URLs are long and differ at both ends; cut the middle so the
                repo and the PR number both stay readable in 80 columns. The
                panel is 76 wide, minus its border (2) and padding (4). */}
            <text fg={muted}>{truncateMiddle(reviewUrl(), 68)}</text>
          </Show>
        </box>
      </Show>
      <Show when={messages().length > 0 || streamingAssistant()}>
        <box width={76} marginTop={2} flexDirection="column">
          <For each={messages()}>{(message) =>
            <box flexDirection="row" gap={1} paddingBottom={1}>
              <text fg={message.role === "user" ? orange : "#eeeeee"}>{message.role === "user" ? ">" : "●"}</text>
              <text width={70} fg={message.role === "user" ? "#eeeeee" : muted}>{message.content}</text>
            </box>
          }</For>
          <Show when={streamingAssistant()}>
            <box flexDirection="row" gap={1}>
              <text fg={orange}>●</text>
              <text width={70} fg="#eeeeee">{streamingAssistant()}</text>
            </box>
          </Show>
        </box>
      </Show>
      <Show when={reviewReport().pr || reviewReport().counts}>
        <box width={76} backgroundColor="#141414" borderStyle="single" borderColor="#5b9b6d" paddingLeft={2} paddingRight={2} marginTop={1} flexDirection="column">
          <text fg="#7edc92">REVIEW SUMMARY {reviewReport().pr?.repository ? `· ${reviewReport().pr?.repository}` : ""}</text>
          <text fg="#eeeeee">{reviewReport().pr?.title ?? "Pull Request"}</text>
          <text fg={muted}>{reviewReport().pr?.author ? `Author ${reviewReport().pr?.author} · ` : ""}Files {reviewReport().pr?.files_reviewed ?? "?"} reviewed · {reviewReport().pr?.files_skipped ?? "?"} skipped · Findings {reviewReport().counts?.total_findings ?? reviewFindings().length}</text>
          <text fg={muted}>Critical {reviewReport().counts?.by_severity?.critical ?? 0} · High {reviewReport().counts?.by_severity?.high ?? 0} · Medium {reviewReport().counts?.by_severity?.medium ?? 0} · Low {reviewReport().counts?.by_severity?.low ?? 0}</text>
          <text fg={muted}>耗时 {reviewReport().run?.duration_seconds?.toFixed(1) ?? "?"}s · 成本 ${reviewReport().run?.total_cost?.toFixed(4) ?? "?"} · Run {reviewReport().run?.id ?? "?"}</text>
        </box>
      </Show>
      <Show when={reviewFindings().length > 0}>
        <box width={76} backgroundColor="#141414" borderStyle="single" borderColor="#6b6b6b" paddingLeft={2} paddingRight={2} marginTop={1} flexDirection="column">
          <text fg="#f3c742">FINDINGS {reviewSummary() ? `· ${reviewSummary()}` : ""}</text>
          <For each={reviewFindings().slice(0, 5)}>{(finding) =>
            <box flexDirection="row" gap={1}>
              <text fg={finding.severity === "critical" || finding.severity === "high" ? "#ff6b6b" : orange}>[{String(finding.severity ?? "info").toUpperCase()}]</text>
              <text width={42} fg="#eeeeee">{String(finding.title ?? finding.message ?? "未命名问题")}</text>
              <text fg={muted}>{finding.file ? `${finding.file}:${finding.line_start ?? "?"}` : ""}</text>
            </box>
          }</For>
          <Show when={reviewFindings().length > 5}><text fg={muted}>还有 {reviewFindings().length - 5} 个问题，可通过报告详情查看。</text></Show>
          <text fg={muted}>Ctrl+O Finding · Ctrl+L 历史 · Ctrl+K 模型</text>
        </box>
      </Show>
        </box>
      </scrollbox>
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
        onOpenFindings={() => { if (reviewFindings().length > 0) setFindingsOpen(true) }}
        onOpenHistory={() => void openHistory()}
        onOpenModel={() => setModelOpen(true)}
        onRetry={retryLastReview}
        reviewing={reviewing()}
        onCancel={cancelCurrentTask}
        onDraftChange={setComposerDraft}
        onChatRequestStart={setActiveChatRequestId}
        onChatRequestEnd={() => setActiveChatRequestId(undefined)}
        hasRenderedAssistantReply={hasRenderedAssistantReply}
        busy={backendStatus() === "THINKING" || backendStatus() === "REVIEWING" || backendStatus() === "CANCELLING"}
        focused={!findingsOpen() && !historyOpen() && !modelOpen() && !setupOpen() && pendingReviewUrl() === "" && reviewStage() !== "审查失败"}
      />
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
        <FindingsDialog findings={reviewFindings()} onClose={() => setFindingsOpen(false)} />
      </Show>
      <Show when={reviewStage() === "审查失败" && reviewUrl()}>
        <ReviewFailureDialog
          url={reviewUrl()}
          message={reviewDetail()}
          onRetry={() => { setFindingsOpen(false); void startReview(reviewUrl()) }}
          onClose={() => setReviewStage("")}
        />
      </Show>
      <Show when={setupOpen()}>
        <RuntimeDialog
          backend={backend}
          runtime={runtime()}
          onClose={() => setSetupOpen(false)}
          onApplied={(snapshot) => {
            setRuntime(snapshot)
            setBackendStatus("READY")
            appendMessage({ role: "assistant", content: `运行时已切换为 ${snapshot.runtime_profile ?? "unknown"}` })
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
        <text fg={statusColors[backendStatus()]}>{runtime().runtime_profile ?? "RUNTIME"} · {statusLabels[backendStatus()]} · {runtime().model ?? "model"} · {runtime().available === false ? "OFFLINE" : runtime().available === true ? "ONLINE" : "0.1.0"}</text>
      </box>
    </box>
  )
}







