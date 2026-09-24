import { createSignal, For, Show, onMount, onCleanup } from "solid-js"
import { useKeyboard, useRenderer, useTerminalDimensions } from "@opentui/solid"
import { BackendClient } from "./backend"
import { isCurrentAssistantEvent, isForeignSessionEvent } from "./protocol"
import { sendWithSessionRecovery } from "./session-recovery"
import { commandCompletion, commandEnterAction, commandMatches } from "./command-menu"
import { truncateMiddle, workspaceRootLabel } from "./format"
import { detailScrollDelta } from "./keymap"
import { reviewReportPanels } from "./review-report"
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

type SetupOptions = {
  providers: ProviderSetupOption[]
  local: LocalSetupOption
  current: {
    runtime_profile?: string
    provider?: string
    model?: string
    api_key_configured?: boolean
    remote_provider?: string
    remote_model?: string
    remote_base_url?: string
    remote_api_key_configured?: boolean
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

function SetupDialog(props: SetupDialogProps) {
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

export function FindingsDialog(props: { findings: ReviewFinding[]; onClose: () => void }) {
  const pageSize = 8
  const [selectedIndex, setSelectedIndex] = createSignal(0)
  const [page, setPage] = createSignal(0)
  const [detailFocused, setDetailFocused] = createSignal(false)
  let detailScroll: ScrollBoxRenderable | undefined
  const pageCount = () => Math.max(1, Math.ceil(props.findings.length / pageSize))
  const pageFindings = () => props.findings.slice(page() * pageSize, (page() + 1) * pageSize)
  const selected = () => props.findings[selectedIndex()] ?? {}
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
      setSelectedIndex((current) => Math.max(0, current - pageSize))
      detailScroll?.scrollTo(0)
    }
    if (key.name === "right") {
      setPage((current) => Math.min(pageCount() - 1, current + 1))
      setSelectedIndex((current) => Math.min(props.findings.length - 1, current + pageSize))
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
            setSelectedIndex(page() * pageSize + index)
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
          ? "↑↓/Pg 滚动 · Home/End 首尾 · Tab 列表 · Esc 返回"
          : `↑↓ 选择 · Tab 详情 · Ctrl/Alt+↑↓ 滚动 · ←→ 翻页 (${page() + 1}/${pageCount()}) · Esc`}
      </text>
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
    if (!url) {
      appendMessage({
        role: "assistant",
        content: "当前会话还没有可重试的审查。粘贴一个 GitHub PR URL，或用 /history <Run ID> 打开历史记录。",
      })
      return
    }
    if (!reviewing()) void startReview(url)
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
        onOpenFindings={() => {
          setHistoryOpen(false)
          setModelOpen(false)
          setSetupOpen(false)
          setPendingReviewUrl("")
          if (reviewFindings().length > 0) {
            setFindingsOpen(true)
          } else {
            appendMessage({
              role: "assistant",
              content: "当前没有 Findings。请先执行 /review <PR_URL>，或使用 /history <run_id> 加载包含 findings 的历史报告。",
            })
          }
        }}
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
        <SetupDialog
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
        <text fg={statusColors[backendStatus()]}>{runtime().runtime_profile ?? "RUNTIME"} · {statusLabels[backendStatus()]} · {runtime().model ?? "model"} · {runtime().available === false ? "OFFLINE" : runtime().available === true ? "ONLINE" : "0.1.0"}</text>
      </box>
    </box>
  )
}









