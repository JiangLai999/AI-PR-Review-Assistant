import { createEffect, createMemo, createSignal, For, Show, onMount, onCleanup } from "solid-js"
import { useKeyboard, useRenderer, useTerminalDimensions } from "@opentui/solid"
import { SyntaxStyle } from "@opentui/core"
import { BackendClient } from "./backend"
import {
  isCurrentAssistantEvent,
  isForeignSessionEvent,
  parseAssistantFinishMeta,
  parseCatalogRefreshResult,
  parseCompactCommandResult,
  parseContextBudgetInfo,
  parseCustomEndpointOptions,
  parseModelSpecBlock,
  parseReasoningDelta,
  parseReviewReasoningOptions,
  parseSessionCreateResult,
  parseSessionDeleteResult,
  parseSessionListResult,
  parseSessionRenameResult,
  parseSessionSwitchResult,
  parseThinkCommandResult,
  hasDedicatedCommandRenderer,
  type ContextPressure,
  type CustomEndpointOptions,
  type ModelSpecBlock,
  type ModelSpecOptions,
  type ReviewReasoningOptions,
  type SessionSummary,
} from "./protocol"
import { sendWithSessionRecovery } from "./session-recovery"
import { commandArgumentLabel, commandCompletion, commandDescription, commandEnterAction, commandMatches } from "./command-menu"
import {
  codeFoldBadge,
  codeFoldStateKey,
  CODE_FOLD_LINE_THRESHOLD,
  customEndpointFieldLabels,
  cursorFrame,
  foldableCodeBlocks,
  foldMarkdownCodeBlocks,
  formatBudgetSource,
  formatCatalogRefreshStatus,
  formatChatHistoryLines,
  formatCompactFailure,
  formatCompactSummary,
  formatContextUsage,
  formatDurationSeconds,
  formatEffortBadge,
  formatMessageMetrics,
  formatModelHeadline,
  formatNeedsVerification,
  formatPressureTip,
  formatReviewBudgetCapHint,
  formatReviewEffortCost,
  formatReviewEffortDisabled,
  formatSessionBadge,
  formatSessionDeleteConfirm,
  formatSessionListEmpty,
  formatSessionListError,
  formatSessionListFooter,
  formatSessionListItem,
  formatSessionListLoading,
  formatSessionListNoSessions,
  formatSessionRenamePrompt,
  formatSessionSwitched,
  formatSessionTitle,
  formatSourceBadge,
  formatSpecBoundHint,
  formatThinkLevel,
  formatThinkTransparent,
  formatThinkUnsupported,
  contextPressureColor,
  type MarkdownSegment,
  overBudgetTip,
  reviewEffortBilingualLabel,
  reviewSlotMaxOutput,
  splitFoldableMarkdown,
  thinkingPlaceholder,
  truncateMiddle,
  workspaceRootLabel,
} from "./format"
export {
  codeFoldBadge,
  codeFoldStateKey,
  CODE_FOLD_LINE_THRESHOLD,
  foldableCodeBlocks,
  foldMarkdownCodeBlocks,
  splitFoldableMarkdown,
}
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
import {
  CHAT_SLOT_VALUES,
  REVIEW_SLOT_VALUES,
  interpretApiKeyInput,
  presetDescription,
  presetIndexOf,
  presetLabel,
  reviewEffortChoices,
  reviewEffortIndexOf,
  reviewEffortIsDisabled,
  reviewEffortStoredValue,
  reviewEffortSummary,
  reviewEffortValue,
  routeBoxes,
  routeSummary,
  routingStatusText,
  setupCustomEndpointFields,
  setupModelSpecFields,
  setupReviewEffortField,
  setupSlotFields,
  slotIndexOf,
  validateSpecInput,
  type RouteBox,
  type RouteSlotValue,
  type RoutingSnapshot,
  type SetupPreset,
  type SlotModelNames,
} from "./setup-routing"
import {
  repoContextChoices,
  repoContextDescription,
  repoContextIndexOf,
  repoContextLabel,
  repoContextStoredValue,
  repoContextSummary,
  repoContextValue,
  setupRepoContextField,
  type RepoContextOptions,
} from "./setup-repo-context"
import type { InputRenderable, TextareaRenderable, KeyBinding, ScrollBoxRenderable } from "@opentui/core"

const orange = "#fb8147"
const muted = "#808080"
const panel = "#1e1e1e"
const background = "#0a0a0a"

/**
 * Chat 消息的 Markdown 配色（与像素主题同一组颜色）。
 *
 * 背景：TUI 之前把 assistant 回复当**纯文本**渲染，于是 `##`、`**`、`| 表格 |`
 * 全部原样显示——用户实测反馈"格式不受约束，很影响美观"。OpenTUI（我们已装的
 * 0.1.101）自带 `MarkdownRenderable`，mimo-code 用的也是它；这里只负责配色，
 * 语法由渲染器自己处理（`conceal` 默认就隐藏标记符）。
 *
 * 只建一次：`SyntaxStyle` 在底层持有 native 资源。
 */
let chatMarkdownStyleCache: SyntaxStyle | undefined
export const chatMarkdownStyle = (): SyntaxStyle => {
  if (chatMarkdownStyleCache === undefined) {
    chatMarkdownStyleCache = SyntaxStyle.fromTheme([
      { scope: ["default"], style: { foreground: "#eeeeee" } },
      { scope: ["markup.strong"], style: { foreground: "#ffffff", bold: true } },
      { scope: ["markup.italic"], style: { foreground: "#e8e8e8", italic: true } },
      { scope: ["markup.raw"], style: { foreground: orange } },
      { scope: ["markup.strikethrough"], style: { foreground: muted, dim: true } },
      {
        scope: ["markup.link", "markup.link.label"],
        style: { foreground: "#7ec8ff", underline: true },
      },
      { scope: ["markup.link.url"], style: { foreground: "#5a9fd4", underline: true } },
      {
        scope: ["markup.heading", "markup.heading.1", "markup.heading.2", "markup.heading.3"],
        style: { foreground: orange, bold: true },
      },
      { scope: ["markup.list"], style: { foreground: orange } },
      { scope: ["markup.quote"], style: { foreground: muted, italic: true } },
    ])
  }
  return chatMarkdownStyleCache
}
// ---------------------------------------------------------------------
// C1 · 表格按渲染宽度分档（docs/DEV_RECORD.md）
// 窄（<100 列）贴内容、去内边距，避免小表被撑松；宽（≥100 列）铺满、
// 留 1 格内边距，避免大表右侧大片留白。分档宽度取 markdown 实际渲染宽度
// （由 chatContentWidth() 派生），不新增尺寸来源。
// ---------------------------------------------------------------------
export const CHAT_TABLE_WIDE_BREAKPOINT = 100

export type ChatTableOptions = {
  widthMode: "content" | "full"
  cellPadding: number
  wrapMode: "word"
  borders: true
}

export function chatTableOptions(renderWidth: number): ChatTableOptions {
  return renderWidth < CHAT_TABLE_WIDE_BREAKPOINT
    ? { widthMode: "content", cellPadding: 0, wrapMode: "word", borders: true }
    : // cellPadding 在 @opentui/TextTable 里是单一数字（垂直/水平共用，见
      // TextTable.js `cellY = rowOffsets + 1 + cellPadding` / `cellLeft = …`），
      // 无法只保留水平内边距。宽档原来的 cellPadding:1 会在每行数据上下各插
      // 一行空行，209×51 帧里表格行高膨胀；按 mimo-chat-render-c3 决策改为 0，
      // 保留 widthMode:"full" 铺满宽度。
      { widthMode: "full", cellPadding: 0, wrapMode: "word", borders: true }
}

// C2 · 长代码块折叠的纯函数（CODE_FOLD_LINE_THRESHOLD / codeFoldBadge /
// codeFoldStateKey / foldableCodeBlocks / foldMarkdownCodeBlocks /
// splitFoldableMarkdown）已迁至 format.ts，便于 format.test.ts 直接覆盖；
// 本文件从 "./format" 导入并 re-export，scripts/manual-*.tsx 的既有导入路径不变。


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
  /** CHAT/REVIEW 双槽路由快照（config.snapshot / model.status 共用）。 */
  routing?: RoutingSnapshot
  /**
   * 仓库上下文档位。同名键后端有两种形状：`config.snapshot` 给纯字符串，
   * `model.status` 给 `{value, options}`（后者会被 `onApplied` 并进同一个快照对象，
   * 见 `app.tsx` 的 `setRuntime((current) => ({...current, ...status.result}))`）。
   * 读取方一律走 `repoContextStoredValue()`；助手预选优先用
   * `config.options.repo_context.value`，这里只是快照侧的兜底。
   */
  repo_context?: string | RepoContextOptions
  /**
   * review 思考档位（docs/DEV_RECORD.md）。同名键后端有两种形状：
   * `config.snapshot` 给纯字符串，`model.status` / `config.options` 给
   * `{value, options, state?, reason?}`。读取方一律走 `reviewEffortValue()` 归一化。
   */
  review_reasoning_effort?: string | ReviewReasoningOptions
  /** B2 模型规格块（config.snapshot / model.status 同键同形）。 */
  model_spec?: ModelSpecBlock
  /** model.status 顶层 source 角标（= model_spec.source，状态栏一行读取）。 */
  source?: string
  needs_verification?: boolean
  /** chat 上下文预算（config.snapshot，§4）。缺字段 = 旧后端，不显示。 */
  chat_context_budget?: number
  /** 预算来源：config | model_spec | fallback（同上）。 */
  chat_context_budget_source?: string
  /** chat 思考强度（config.snapshot）。缺字段 = 旧后端，状态栏不显示该段。 */
  chat_reasoning_effort?: string
}

const BRAND_PIXEL = [
  "██████  ██████      ██████  ███████ ██    ██ ██ ███████ ██  ██",
  "██   ██ ██   ██     ██   ██ ██      ██    ██ ██ ██      ██  ██",
  "██████  ██████      ██████  █████   ██    ██ ██ █████   ██████",
  "██      ██   ██     ██   ██ ██       ██  ██  ██ ██      ██  ██",
  "██      ██   ██     ██   ██ ███████   ████   ██ ███████ ██  ██",
]

const isEn = (language?: string) => String(language ?? "zh-CN").toLowerCase().startsWith("en")

/**
 * 状态栏右侧那一行（方案 §4.4）。
 *
 * 模型段只读后端 `routing` 快照 —— `CHAT x · REVIEW y`，混合审查额外标
 * `(local↔remote)`；旧后端没有 `routing` 时回落到改造前的单模型文案，状态栏不会
 * 因为一个新字段缺失就整段空白。导出是为了让 `scripts/*.tsx` 能用 fixture 渲染出
 * 文本证据（App 本身要连真实后端才能跑到这一步）。
 */
export function RuntimeStatusLine(props: {
  runtime: RuntimeSnapshot
  status: AppStatus
  width: number
  height: number
  /** A-P3 · 当前会话标题（session.list 的 current 项 / runtime 会话字段）。 */
  sessionTitle?: string
}) {
  const routingLabel = () =>
    routingStatusText(props.runtime.routing, props.runtime.ui_language) || (props.runtime.model ?? "model")
  // 思考强度段：缺字段（旧后端）不显示；窄终端（<90 列）优先砍掉这一段，
  // 保住路由/在线状态这类运维刚需（降级策略见 docs/DEV_RECORD.md）。
  const effortBadge = () =>
    props.width >= 90
      ? formatEffortBadge(props.runtime.chat_reasoning_effort, props.runtime.ui_language)
      : ""
  // A-P3 · 会话名段：长标题截断；窄终端（<100 列）隐藏，状态栏不被挤爆。
  const sessionBadge = () => {
    if (props.width < 100) return ""
    // runtime 里的会话字段优先（若有），否则用 session.list 刷新到的标题。
    const title =
      (props.runtime as { session_title?: string; session_name?: string }).session_title ??
      (props.runtime as { session_title?: string; session_name?: string }).session_name ??
      props.sessionTitle
    return formatSessionBadge(title, 20, props.runtime.ui_language)
  }
  return (
    <text fg={statusColors[props.status]}>
      {props.runtime.runtime_profile ?? "RUNTIME"} · {statusLabels[props.status]} · {routingLabel()}
      {effortBadge() ? ` · ${effortBadge()}` : ""}
      {sessionBadge() ? ` · ${sessionBadge()}` : ""} ·{" "}
      {props.runtime.available === false ? "OFFLINE" : props.runtime.available === true ? "ONLINE" : "0.1.0"} ·{" "}
      {props.width}×{props.height}
    </text>
  )
}

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

type ChatMessage = {
  /** Transcript-stable key; code-fold state keys on this + block index. */
  id?: string
  role: "user" | "assistant"
  content: string
  /** C4 · assistant.finished.duration_seconds；缺失则不显示耗时行。 */
  durationSeconds?: number
  /** A4 · assistant.finished.warning（如 "over_budget"）。 */
  warning?: string
  /** C5 · 思考文本，独立于 content，不写入消息历史正文。 */
  thinking?: string
  /** 指标行 · 本轮实际模型名（finished.model；缺失时渲染侧回退 runtime.model）。 */
  model?: string
  /** 指标行 · 真实输出 token（usage.completion_tokens；缺失回退 content.length）。 */
  completionTokens?: number
  /** 指标行 · 消息落定本地时间 HH:MM（用户消息也记，便于回看）。 */
  timestamp?: string
}

// ---------------------------------------------------------------------
// C3/C4/C5 + A4/A5 · Chat 契约 v1 展示组件
// 导出给 scripts/manual-*.tsx 做帧断言；数据解析在 protocol.ts / format.ts。
// ---------------------------------------------------------------------

/**
 * C5 · 独立思考区：暗色斜体、可折叠。
 * 默认折叠理由：思考过程往往很长，落定后正文才是交付物；流式期间默认展开
 * （用户正在等答案，想看到模型在做什么），落定后折叠避免刷屏。
 */
export function ThinkingBlock(props: {
  text: string
  expanded: boolean
  onToggle: () => void
  language?: string
  width?: number
  streaming?: boolean
}) {
  const width = () => Math.max(24, props.width ?? 72)
  const en = () => String(props.language ?? "zh-CN").toLowerCase().startsWith("en")
  const header = () =>
    props.expanded
      ? en()
        ? "▾ Thinking"
        : "▾ 思考"
      : en()
        ? `▸ Thinking (${props.text.split("\n").length} lines)`
        : `▸ 思考（${props.text.split("\n").length} 行）`
  return (
    <box
      width={width()}
      flexDirection="column"
      marginBottom={1}
      paddingLeft={1}
      paddingRight={1}
      backgroundColor="#121212"
      border={["left"]}
      borderColor="#555555"
    >
      {/* header 可点击展开/折叠（参考代码块角标 onMouseDown 路径）。 */}
      <text fg={muted} attributes={2} onMouseDown={props.onToggle}>
        {header()}
      </text>
      <Show when={props.expanded}>
        <text width={width() - 2} fg="#9a9a9a" attributes={2}>
          {props.text}
        </text>
      </Show>
    </box>
  )
}

/**
 * 消息指标行（DurationLine 升级版）：`· deepseek-flash · 1.6s · 61 字 · 14:32`。
 * 缺数据的项逐项省略；全缺时不渲染（调用方可不用外层 Show）。
 * model 缺失时回退 fallbackModel（runtime.model），仍缺则省略该段。
 */
export function MessageMetricsLine(props: {
  model?: string
  fallbackModel?: string
  seconds: number | undefined
  completionTokens?: number
  contentLength?: number
  timestamp?: string
  language?: string
}) {
  const text = () =>
    formatMessageMetrics(
      {
        model: props.model || props.fallbackModel,
        durationSeconds: props.seconds,
        completionTokens: props.completionTokens,
        contentLength: props.contentLength,
        timestamp: props.timestamp,
      },
      props.language,
    )
  return (
    <Show when={text()}>
      <text fg={muted}>{text()}</text>
    </Show>
  )
}

/** A4 · over_budget tips：muted/warn 色，不用报警红。 */
export function OverBudgetTip(props: { language?: string; width?: number }) {
  return (
    <box width={Math.max(24, props.width ?? 72)} marginTop={1} flexDirection="column">
      <text fg="#f3c742">{overBudgetTip(props.language)}</text>
    </box>
  )
}

/**
 * A5 · 上下文提示：`上下文 12% · 2.4k/20k`；无 context 时不渲染。
 * B-P3 · 压力分级只提示不自动压缩：medium/high 上下文段变黄，critical 变红；
 * high/critical 尾部追加「可用 /compact」提示。low/null/缺失维持现状。
 */
export function ContextUsageLine(props: {
  context:
    | {
        used_tokens?: number
        budget_tokens?: number
        used_percent?: number
        pressure?: ContextPressure | null
      }
    | undefined
  language?: string
}) {
  const label = () => formatContextUsage(props.context, props.language)
  const color = () => contextPressureColor(props.context?.pressure)
  const tip = () => formatPressureTip(props.context?.pressure, props.language)
  return (
    <Show when={label()}>
      <box flexDirection="column">
        <text fg={color()}>{label()}</text>
        <Show when={tip()}>
          <text fg={color()}>{tip()}</text>
        </Show>
      </box>
    </Show>
  )
}

/**
 * C3 批次 · 可折叠 markdown 正文（方案 A：角标可点击）。
 * `splitFoldableMarkdown` 把正文切成「markdown 段 + 角标位」；可折叠代码块
 * 自成一段（`foldable: true` → renderNode 去掉块尾 marginBottom），角标作为
 * 独立 `<text onMouseDown>` 紧跟其后，视觉上仍是块尾角标。Alt+L 走上层
 * Composer 的 `onToggleCodeFold`（无障碍键盘路径保留）。
 */
export function FoldableMarkdownBlock(props: {
  content: string
  messageKey: string
  isExpanded: (blockIndex: number) => boolean
  onToggleAt: (messageKey: string, blockIndex: number) => void
  width: number
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  syntaxStyle: any
  fg: string
  bulletFg: string
  streaming?: boolean
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  tableOptions: any
}) {
  return (
    <box flexDirection="column">
      <For each={splitFoldableMarkdown(props.content, props.isExpanded)}>
        {(seg, index) =>
          seg.kind === "markdown" ? (
            <box flexDirection="row" gap={1}>
              {/* 首段用 `●` 项目符号；后续段用 1 格占位，gap=1 使 markdown
                  起点与首段对齐（● 占 1 格）。 */}
              {index() === 0 ? <text fg={props.bulletFg}>●</text> : <text width={1}> </text>}
              <markdown
                width={props.width}
                content={seg.content}
                syntaxStyle={props.syntaxStyle}
                fg={props.fg}
                conceal={true}
                streaming={props.streaming}
                // 代码块加一层底色 + 左内边距，形成"代码框"观感。
                // foldable 段去掉 marginBottom，让块尾角标贴住代码块。
                renderNode={(token, ctx) => {
                  if (token.type !== "code") return undefined
                  const code = ctx.defaultRender()
                  if (code) {
                    const styled = code as {
                      bg?: string
                      paddingLeft?: number
                      marginBottom?: number
                    }
                    styled.bg = "#141414"
                    styled.paddingLeft = 1
                    styled.marginBottom = seg.foldable ? 0 : 1
                  }
                  return code
                }}
                tableOptions={props.tableOptions}
              />
            </box>
          ) : (
            // paddingLeft=2 与代码块内文字对齐（markdown 起点 1 + code paddingLeft 1）。
            <box flexDirection="row" paddingLeft={2}>
              <text
                onMouseDown={() => props.onToggleAt(props.messageKey, seg.blockIndex)}
                fg={muted}
              >
                {codeFoldBadge(seg.lineCount, seg.expanded)}
              </text>
            </box>
          )
        }
      </For>
    </box>
  )
}

type ReviewFinding = {
  /** Backend finding id; `/feedback` matches on this, never on the list index. */
  finding_id?: string
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
type HistoryRun = { id?: string; pr_number?: number; repo_owner?: string; repo_name?: string; pr_url?: string; total_findings?: number; duration_seconds?: number; total_cost?: number; created_at?: string; model?: string }
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
  /** /history 默认：对话消息列表（与 /history --runs 的审查列表区分）。 */
  onOpenChatHistory: () => void
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
  /** Toggle the focused long code block's fold badge (`Alt+L`). */
  onToggleCodeFold: () => void
  /** C5 · Toggle the thinking block fold (`Alt+T`). */
  onToggleThinking: () => void
  /** A-P2 · Open the session list dialog (`Alt+S`, `/sessions`). */
  onOpenSessions: () => void
  /** A-P2 · Rename the **current** session (`/rename <标题>`). */
  onRenameSession: (title: string) => void
  /** Show the `Alt+L 代码块` hint only when a foldable block exists. */
  codeFoldActive?: boolean
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
    // /history 分流（2026-09-27 用户反馈后调整）：**默认 = 审查列表**——"history"
    // 的直觉含义就是这个工具的核心记录；对话消息列表改由 `/history --chat` 打开，
    // 会话级管理仍在 `/sessions`。`--runs` 保留为兼容别名（既有习惯/脚本不受影响）。
    if (text === "/history") {
      props.onOpenHistory()
      submitLock = false
      return
    }
    if (text === "/history --runs" || text === "/history --runs ") {
      // 兼容别名：语义已并入默认（历史审查列表）。
      props.onOpenHistory()
      submitLock = false
      return
    }
    if (text === "/history --chat" || text === "/history --chat ") {
      props.onOpenChatHistory()
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
    // A-P2 · /sessions 前端拦截 → session.list；Alt+S 同效（见 useKeyboard）。
    if (text === "/sessions") {
      props.onOpenSessions()
      submitLock = false
      return
    }
    // 契约 v1 · /rename <标题> → 重命名**当前会话**（显式入口；会话弹窗里按 `r`
    // 是另一入口——用户反馈"想改名但不知道怎么改"，光靠弹窗快捷键发现性不够）。
    if (text === "/rename" || text.startsWith("/rename ")) {
      const title = text.slice("/rename".length).trim()
      props.onMessage({ role: "user", content: text })
      if (!title) {
        props.onMessage({
          role: "assistant",
          content: "用法：/rename <新标题>（或在会话弹窗 /sessions 里按 r 改名）",
        })
      } else {
        props.onRenameSession(title)
      }
      submitLock = false
      return
    }
    // 契约 v1 · /new → session.create（新建并切换）；旧后端无该方法时回退现有清空行为。
    if (text === "/new") {
      props.onMessage({ role: "user", content: text })
      props.onStatus("THINKING")
      try {
        const created = await props.backend.request("session.create", {}, { timeoutMs: CHAT_TIMEOUT_MS })
        if (created.ok) {
          const parsed = parseSessionCreateResult(created.result)
          const nextId = parsed?.session_id ?? String(created.result?.session_id ?? "")
          if (nextId) props.onSessionChange(nextId)
          props.onNewSession()
          const title = parsed?.session?.title ?? parsed?.title ?? ""
          if (title) {
            props.onMessage({ role: "assistant", content: formatSessionSwitched(title, props.runtime.ui_language) })
          }
        } else {
          // 旧后端：回退现有清空行为（不报错打断）。
          props.onNewSession()
        }
        props.onStatus("READY")
      } catch {
        props.onNewSession()
        props.onStatus("READY")
      } finally {
        props.onChatRequestEnd()
        submitLock = false
      }
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
        // 有专用渲染器的命令（/think、/compact）不在这里做通用回显：
        // 实测 `/think max` 曾显示两行——后端 text「思考档位已设置为 max。」
        // 加上下面专用分支的「思考档位：最大」。后端 text 继续保留（CLI 等
        // 其它消费方仍用它），TUI 侧只负责不重复。
        const thinkResult = parseThinkCommandResult(response.result)
        const compactResult = parseCompactCommandResult(response.result)
        if (
          text.startsWith("/") &&
          response.result?.text &&
          !hasDedicatedCommandRenderer(response.result)
        ) {
          // §4：/context 结果追加预算来源一行（缺字段时不显示）。
          const budgetInfo = parseContextBudgetInfo(response.result)
          const budgetLine = formatBudgetSource(
            budgetInfo.budget_tokens,
            budgetInfo.budget_source,
            props.runtime.ui_language,
          )
          const content = budgetLine
            ? `${String(response.result.text)}\n${budgetLine}`
            : String(response.result.text)
          props.onMessage({ role: "assistant", content })
        }
        // 契约 v1 · /think → kind:"think"：回显档位；unsupported 给置灰说明。
        if (thinkResult) {
          const language = props.runtime.ui_language
          const body =
            thinkResult.state === "unsupported"
              ? formatThinkUnsupported(thinkResult.reason, language)
              : thinkResult.state === "transparent"
                ? formatThinkTransparent(thinkResult.level, thinkResult.reason, language)
                : formatThinkLevel(thinkResult.level, language)
          props.onMessage({ role: "assistant", content: body })
        }
        // 契约 v1 · /compact → kind:"compact"：tokens 与保留轮数；失败强调原历史未变。
        if (compactResult) {
          const language = props.runtime.ui_language
          const body =
            compactResult.ok === false || compactResult.error
              ? formatCompactFailure(compactResult.error, language)
              : formatCompactSummary(compactResult, language)
          props.onMessage({ role: "assistant", content: body })
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
    if (props.focused !== false && key.meta === true && key.name === "l") {
      props.onToggleCodeFold()
      key.stopPropagation?.()
      return
    }
    if (props.focused !== false && key.meta === true && key.name === "t") {
      props.onToggleThinking()
      key.stopPropagation?.()
      return
    }
    // A-P2 · Alt+S 会话列表（与 Alt+L 代码块 / Alt+T 思考 / Alt+W 工作台成体系）。
    if (props.focused !== false && key.meta === true && key.name === "s") {
      props.onOpenSessions()
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
              <span style={{ fg: entry.index === menuIndex() ? "#ffffff" : orange }}>{entry.command.name}{commandArgumentLabel(entry.command, props.runtime.ui_language) ? ` ${commandArgumentLabel(entry.command, props.runtime.ui_language)}` : ""}</span>
              <span style={{ fg: muted }}>  {commandDescription(entry.command, props.runtime.ui_language)}</span>
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
        <text><span style={{ fg: "#eeeeee" }}>Alt+S</span> <span style={{ fg: muted }}>会话</span></text>
        <Show when={props.workbenchActive}>
          <text><span style={{ fg: "#eeeeee" }}>Alt+W</span> <span style={{ fg: muted }}>工作台</span></text>
        </Show>
        <Show when={props.codeFoldActive}>
          <text><span style={{ fg: "#eeeeee" }}>Alt+L</span> <span style={{ fg: muted }}>代码块</span></text>
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
  /** 后端给出的运行模式预设（含 custom「自定义」）；缺失时回落到本地兜底表。 */
  runtime_profiles?: SetupPreset[]
  api_formats?: ChoiceOption[]
  ui_languages?: ChoiceOption[]
  output_formats?: ChoiceOption[]
  chat_layouts?: ChoiceOption[]
  workbench_modes?: ChoiceOption[]
  /** `{value, options}`：仓库上下文当前值与可选值（后端 REPO_CONTEXT_MODES）。 */
  repo_context?: RepoContextOptions
  /** `{value, options, state?, reason?}`：review 思考档位（后端 REVIEW_REASONING_EFFORTS）。 */
  review_reasoning_effort?: ReviewReasoningOptions
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
    local_models?: string[]
  }
  /** 与 `config.snapshot` 同形的槽位快照（方案 §5.4）。 */
  routing?: RoutingSnapshot
  /** B2 模型规格（§2.2）：顶层描述活跃槽，`slots` 给每槽明细。缺字段时不显示。 */
  model?: ModelSpecOptions
  /** B3 中转站读出口（§2.6）。 */
  custom_endpoint?: CustomEndpointOptions
}

type SetupStep = "runtime" | "provider" | "model" | "key" | "local" | "summary"

const runtimeOptions = [
  { name: "Cloud", description: "第三方 API：适合高质量审查与远程模型", value: "cloud" },
  { name: "Local", description: "Ollama 本地模型：离线可用，数据留在本机", value: "local" },
  { name: "Hybrid", description: "混合策略：按任务在本地与云端之间协作", value: "hybrid" },
  { name: "Offline", description: "离线优先：只使用本地运行时", value: "offline" },
]

/**
 * `config.options.runtime_profiles` 不可用时的兜底（旧后端/读取失败）。
 *
 * 预设清单的 owner 是后端 `RUNTIME_PROFILES`；这里只保证「自定义」这一档不会因为
 * 一次 options 读取失败而消失，顺序与后端一致。
 */
const fallbackRuntimeProfiles: SetupPreset[] = [
  { value: "cloud", label: "云端" },
  { value: "local", label: "本地" },
  { value: "hybrid", label: "混合" },
  { value: "custom", label: "自定义" },
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
  | "route_chat"
  | "route_review"
  | "provider"
  | "base_url"
  | "api_format"
  | "api_key"
  | "model"
  | "model_spec"
  | "custom_endpoint"
  | "local_base_url"
  | "local_model"
  | "github"
  | "ui_language"
  | "response_language"
  | "output_format"
  | "auto_publish"
  | "chat_layout"
  | "workbench"
  | "repo_context"
  | "review_effort"
  | "summary"

const screenStages: Record<SetupScreen, number> = {
  runtime: 1,
  // 路由细化页仍属第 1 阶段"运行模式"：它是 custom 预设的展开，不是新阶段。
  route_chat: 1,
  route_review: 1,
  provider: 2,
  base_url: 2,
  api_format: 2,
  api_key: 3,
  model: 3,
  model_spec: 3,
  // 中转站与 api_key/model/model_spec 同属第 3 阶段"凭据与模型"：它在 cloud/local
  // 顺序里紧跟 model_spec，标成 2 会让进度条从 3/6 倒退到 2/6（实测帧见
  // .pytest_claude/ai-pr-review-route-check/frame-custom-endpoint-zh.txt）。
  custom_endpoint: 3,
  local_base_url: 2,
  local_model: 3,
  github: 4,
  ui_language: 5,
  response_language: 5,
  output_format: 5,
  auto_publish: 5,
  chat_layout: 5,
  workbench: 5,
  // 仓库上下文三选一（方案 §4.6）：与 workbench 同属第 5 阶段"界面与输出"。
  repo_context: 5,
  // review 思考档位（docs/DEV_RECORD.md）：同属第 5 阶段，紧跟仓库上下文。
  review_effort: 5,
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
  route_chat: "路由细化 · 对话模型",
  route_review: "路由细化 · 审查模型",
  provider: "选择模型供应商",
  base_url: "配置 API Base URL",
  api_format: "选择 API 协议格式",
  api_key: "配置 API Key",
  model: "选择模型",
  model_spec: "模型规格",
  custom_endpoint: "中转站配置",
  local_base_url: "配置本地 Ollama Endpoint",
  local_model: "选择本地模型",
  github: "配置 GitHub Token",
  ui_language: "选择界面语言",
  response_language: "选择模型回复语言",
  output_format: "选择默认输出格式",
  auto_publish: "是否自动发布 GitHub 评论",
  chat_layout: "选择 Chat 布局",
  workbench: "选择审查工作台模式",
  repo_context: "选择仓库上下文",
  review_effort: "选择审查思考档位",
  summary: "确认并保存",
}

/**
 * 双向文案屏幕的标题（方案 §5.2 #15、§4.6）。
 *
 * 助手其余屏幕目前是中文单语（改造前的现状），新增的屏幕（路由细化两屏、仓库上下文）
 * 按 `ui_language` 出中英两版；其余屏幕保持原文案不动，避免"顺手翻译"改变既有交互的
 * 可见文本。
 */
const bilingualScreenTitle = (value: SetupScreen, en: boolean, fallback: string): string => {
  if (value === "route_chat") return en ? "Route detail · chat model" : "路由细化 · 对话模型"
  if (value === "route_review") return en ? "Route detail · review model" : "路由细化 · 审查模型"
  if (value === "repo_context") {
    return en ? "Repository context · review prefetch" : "仓库上下文 · 审查预取"
  }
  if (value === "review_effort") {
    return en ? "Review reasoning effort" : "审查思考档位"
  }
  if (value === "model_spec") return en ? "Model spec" : "模型规格"
  if (value === "custom_endpoint") return en ? "Custom endpoint" : "中转站配置"
  return fallback
}

// 方框标题与槽别名在 setup-routing.ts（`routeBoxes`）里出，这里只放本屏独有的提示语。
const routeCopy = (en: boolean) => ({
  hybridHint: en
    ? "Hybrid review splits files by complexity between local and cloud."
    : "混合审查按文件复杂度在本地与云端之间自动分流。",
  keys: en
    ? "↑↓ select · Tab/←→ switch box · Enter next · Esc back"
    : "↑↓ 选择 · Tab/←→ 切换方框 · Enter 下一步 · Esc 返回",
})

/**
 * 仓库上下文三选一的屏内提示（选项名/说明在 setup-repo-context.ts 里出）。
 *
 * 这一屏是普通单选屏：↑↓ 选择、Enter 前进、Esc 取消助手，与 ui_language / output_format
 * 等屏完全一致（页脚用通用文案，不覆盖）。
 */
const repoContextCopy = (en: boolean) => ({
  // 一行放得下（74 列对话框内容区 68 列）：换行会白吃一行高度，其它屏的提示语同理。
  hint: en
    ? "What /review prefetches from the repo as extra model context."
    : "审查时按此范围预取仓库文件，随 PR 一起送给模型。",
})

/**
 * 配置助手（Ctrl+P）。导出仅供 `scripts/*.tsx` 的文本证据脚本以 fixture 渲染，
 * 与 FindingsDialog 等既有导出同理。
 */
export function SetupWizardDialog(props: SetupDialogProps) {
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
  const [routeChatIndex, setRouteChatIndex] = createSignal(0)
  const [routeReviewIndex, setRouteReviewIndex] = createSignal(0)
  // 细化页两个方框都在两屏上可见；焦点决定 ↑↓ 改的是哪一个（Tab/←→ 切换）。
  const [routeFocus, setRouteFocus] = createSignal<"chat" | "review">("chat")
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
  const [repoContextIndex, setRepoContextIndex] = createSignal(0)
  const [reviewEffortIndex, setReviewEffortIndex] = createSignal(0)
  const [baseUrl, setBaseUrl] = createSignal("")
  const [apiKey, setApiKey] = createSignal("")
  const [localBaseUrl, setLocalBaseUrl] = createSignal("")
  const [githubToken, setGithubToken] = createSignal("")
  // B2/B3 模型规格与中转站（docs/DEV_RECORD.md）
  const [specRemoteContext, setSpecRemoteContext] = createSignal("")
  const [specRemoteOutput, setSpecRemoteOutput] = createSignal("")
  const [specLocalContext, setSpecLocalContext] = createSignal("")
  const [specLocalOutput, setSpecLocalOutput] = createSignal("")
  const [customBaseUrl, setCustomBaseUrl] = createSignal("")
  const [customApiKey, setCustomApiKey] = createSignal("")
  const [customModelName, setCustomModelName] = createSignal("")
  const [customContextWindow, setCustomContextWindow] = createSignal("")
  const [customMaxOutput, setCustomMaxOutput] = createSignal("")
  /** 中转站表单是否被用户改动过（§6.1 dirty 标记：预填值不主动提交）。 */
  const [customDirty, setCustomDirty] = createSignal(false)
  /** 中转站表单焦点行（0..4：base_url/api_key/model/context_window/max_output）。 */
  const [customFieldIndex, setCustomFieldIndex] = createSignal(0)
  /** catalog.refresh 状态：idle | refreshing | success | error。 */
  const [catalogRefresh, setCatalogRefresh] = createSignal<"idle" | "refreshing" | "success" | "error">("idle")
  const [catalogRefreshDetail, setCatalogRefreshDetail] = createSignal("")
  /** model_spec 可编辑字段焦点行（0..3：remote_ctx/remote_out/local_ctx/local_out）。 */
  const [specFieldIndex, setSpecFieldIndex] = createSignal(0)

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
  /** 仓库上下文选项：`config.options.repo_context.options` 优先（兜底表在 setup-repo-context.ts）。 */
  const repoContexts = () => repoContextChoices(options()?.repo_context)
  /** review 思考档位选项：`config.options.review_reasoning_effort.options` 优先（兜底表在 setup-routing.ts）。 */
  const reviewEfforts = () => reviewEffortChoices(options()?.review_reasoning_effort)
  /** review 档位的 state/reason 块（置灰判定用；缺字段 = 不置灰）。 */
  const reviewEffortBlock = (): ReviewReasoningOptions | undefined =>
    options()?.review_reasoning_effort
  const local = () => options()?.local
  const selectedRuntime = () =>
    runtimeProfiles()[Math.min(runtimeIndex(), Math.max(0, runtimeProfiles().length - 1))]?.value ??
    "cloud"
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
  const selectedRepoContext = () => repoContextValue(repoContexts(), repoContextIndex())
  const selectedReviewEffort = () => reviewEffortValue(reviewEfforts(), reviewEffortIndex())
  /**
   * review 槽模型的 `max_output`（`config.options.model.slots[routing.review.slot].max_output`）。
   * hybrid / 旧后端缺字段时为 undefined —— 提示不显示（兼容 + 不打扰）。
   */
  const reviewSlotOutputLimit = () =>
    reviewSlotMaxOutput(options()?.routing?.review?.slot, modelSpec())
  /** 小 max_output × high/max 的封顶提示；空串 = 不显示。 */
  const reviewBudgetCapHint = () =>
    formatReviewBudgetCapHint(reviewSlotOutputLimit(), selectedReviewEffort(), uiLanguage())
  const autoPublish = () => autoPublishIndex() === 0
  const remoteKeyConfigured = () =>
    options()?.current.remote_api_key_configured ?? options()?.current.api_key_configured ?? false
  const githubConfigured = () => options()?.current.github_token_configured ?? false

  /** B2 模型规格块：`config.options.model` 经协议解析器兜底（旧后端缺键 → undefined）。 */
  const modelSpec = (): ModelSpecOptions | undefined => parseModelSpecBlock(options()?.model)
  /** 活跃槽规格（顶层即活跃槽，§2.2）。 */
  const activeSpec = (): ModelSpecBlock | undefined => modelSpec()
  /** 远端槽规格。 */
  const remoteSpec = (): ModelSpecBlock | undefined => modelSpec()?.slots?.remote ?? modelSpec()
  /** 本地槽规格。 */
  const localSpec = (): ModelSpecBlock | undefined => modelSpec()?.slots?.local
  /** B3 中转站读出口。 */
  const customEndpoint = (): CustomEndpointOptions | undefined =>
    parseCustomEndpointOptions(options()?.custom_endpoint)
  /** 预填规格编辑框：onMount 与刷新后各一次。 */
  const primeSpecFields = (spec: ModelSpecOptions | undefined) => {
    const remote = spec?.slots?.remote ?? spec
    const local = spec?.slots?.local
    setSpecRemoteContext(
      typeof remote?.context_window === "number" ? String(remote.context_window) : "",
    )
    setSpecRemoteOutput(typeof remote?.max_output === "number" ? String(remote.max_output) : "")
    setSpecLocalContext(
      typeof local?.context_window === "number" ? String(local.context_window) : "",
    )
    setSpecLocalOutput(typeof local?.max_output === "number" ? String(local.max_output) : "")
  }
  /** 预填中转站五项表单（同时复位 dirty 标记）。 */
  const primeCustomFields = (endpoint: CustomEndpointOptions | undefined) => {
    setCustomDirty(false)
    setCustomBaseUrl(String(endpoint?.base_url ?? ""))
    setCustomApiKey("")
    setCustomModelName(String(endpoint?.default_model ?? ""))
    setCustomContextWindow(
      typeof endpoint?.context_window === "number" ? String(endpoint.context_window) : "",
    )
    setCustomMaxOutput(typeof endpoint?.max_output === "number" ? String(endpoint.max_output) : "")
  }
  /**
   * 重新获取按钮：调 `config.catalog.refresh`，不阻塞 UI（§2.1）。
   * 成功 → 用返回的 model 块更新 options 并重填编辑框；失败 → 保留旧值 + 原因。
   */
  const refreshCatalog = async () => {
    if (catalogRefresh() === "refreshing") return
    setCatalogRefresh("refreshing")
    setCatalogRefreshDetail("")
    try {
      const response = await props.backend.request("config.catalog.refresh", {}, { timeoutMs: PROBE_TIMEOUT_MS })
      if (!response.ok) throw new Error(response.error?.message ?? "refresh failed")
      const nextModel = parseCatalogRefreshResult(response.result)
      if (nextModel) {
        setOptions((current) => (current ? { ...current, model: nextModel } : current))
        primeSpecFields(nextModel)
        // 编辑框本身也要重填（docstring 说的"重填编辑框"）：只改 signal 的话，输入框里
        // 还是刷新前的文本，下一次 ↑↓/Enter 会把它写回 signal，把刚刷新到的目录值静默盖回
        // 旧值（manual [F] 的 "刷新后 ↓ 回写的是新目录值" 就是这条的探针）。
        const field = Math.min(specFieldIndex(), Math.max(0, specFieldCount() - 1))
        setSpecFieldIndex(field)
        setInputValue(specFieldValue(field))
        const source = nextModel.catalog_state?.source ?? nextModel.source ?? ""
        setCatalogRefresh("success")
        setCatalogRefreshDetail(source ? formatSourceBadge(source, uiLanguage()) : "")
      } else {
        setCatalogRefresh("success")
      }
    } catch (cause) {
      setCatalogRefresh("error")
      setCatalogRefreshDetail(String(cause))
    }
  }

  /** 助手当前选中的界面语言：新增文案跟着它实时切换（保存前就能看到效果）。 */
  const uiLanguage = () => selectedUiLanguage()
  const runtimeProfiles = () => {
    const fromBackend = options()?.runtime_profiles ?? []
    return fromBackend.length > 0 ? fromBackend : fallbackRuntimeProfiles
  }
  const selectedPreset = (): SetupPreset =>
    runtimeProfiles()[Math.min(runtimeIndex(), Math.max(0, runtimeProfiles().length - 1))] ?? {
      value: "cloud",
      label: "云端",
    }
  const isCustom = () => selectedRuntime() === "custom"
  const isRouteScreen = (value: SetupScreen) => value === "route_chat" || value === "route_review"

  /**
   * 细化页两个方框里显示的模型名，全部来自 `config.options`（方案 §4.2）。
   *
   * 预设分支用助手当前选中的 Provider 模型（云端分支保存的就是它）；custom 分支改用
   * **已落盘**的 `current.remote_model` / `local_model`——custom 只写槽位，不保存
   * Provider / 本地端点，显示助手里的临时选择会让用户以为那张网卡已经换了。
   * 都没有就是"未配置"，绝不硬编码模型名。
   */
  const slotModels = (): SlotModelNames => {
    if (isCustom()) {
      return {
        remote: options()?.current.remote_model || "",
        local: options()?.current.local_model || "",
      }
    }
    return {
      remote: selectedModel() || options()?.current.remote_model || "",
      local: selectedLocalModel() || options()?.current.local_model || "",
    }
  }
  /**
   * 方框模型必须 memo：`routeBoxes()` 每次返回全新对象/数组，若直接喂给 `<For>`，
   * 每次按键（焦点/选中项变化）都会把两个方框连同所有行拆掉重建——像素渲染器只
   * 重画变化的单元格，重建后的行会留下上一次的字符残影。
   */
  const routeBoxViews = createMemo(() => routeBoxes(slotModels(), uiLanguage()))
  const chatChoices = () => routeBoxViews()[0].choices
  const reviewChoices = () => routeBoxViews()[1].choices
  const routeChatSlot = (): RouteSlotValue =>
    chatChoices()[Math.min(routeChatIndex(), chatChoices().length - 1)]?.value ?? "remote"
  const routeReviewSlot = (): RouteSlotValue =>
    reviewChoices()[Math.min(routeReviewIndex(), reviewChoices().length - 1)]?.value ?? "remote"
  const routeSelection = () => ({ chat: routeChatSlot(), review: routeReviewSlot() })
  /** 确认页的三行摘要：custom 用实时选择，预设显示该预设的槽位定义。 */
  const routePreview = () => routeSummary(selectedRuntime(), routeSelection(), slotModels(), uiLanguage())
  const routeStageCopy = () => routeCopy(isEn(uiLanguage()))
  /** 确认页「仓库上下文」行的显示值（双语 label，取自后端选项清单）。 */
  const repoContextPreview = () =>
    repoContextSummary(repoContexts(), selectedRepoContext(), uiLanguage())
  const reviewEffortPreview = () =>
    reviewEffortSummary(reviewEfforts(), selectedReviewEffort(), uiLanguage())

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
    "model_spec",
    "custom_endpoint",
    "github",
    "ui_language",
    "response_language",
    "output_format",
    "auto_publish",
    "chat_layout",
    "workbench",
    "repo_context",
    "review_effort",
    "summary",
  ]
  const localOrder: SetupScreen[] = [
    "runtime",
    "local_base_url",
    "local_model",
    "model_spec",
    "github",
    "ui_language",
    "response_language",
    "output_format",
    "auto_publish",
    "chat_layout",
    "workbench",
    "repo_context",
    "review_effort",
    "summary",
  ]
  /**
   * custom 顺序（方案 §4.2）：选完两个槽位就离开"运行模式"阶段。
   *
   * 细化页只决定"用哪个槽"，不决定槽里配了什么（后端 `_apply_setup` 的 custom 分支
   * 也只写槽位、读都不读 provider/local 字段）。所以这里不显示 Provider / API Key /
   * 本地端点这些屏幕——它们填了也会被后端忽略，显示出来反而是"填了没保存"的误导。
   */
  const customOrder: SetupScreen[] = [
    "runtime",
    "route_chat",
    "route_review",
    "model_spec",
    "github",
    "ui_language",
    "response_language",
    "output_format",
    "auto_publish",
    "chat_layout",
    "workbench",
    "repo_context",
    "review_effort",
    "summary",
  ]
  const order = () => {
    const base = isCustom() ? customOrder : needsCloud() ? cloudOrder : localOrder
    // 旧后端缺 `config.options.review_reasoning_effort` 时跳过该屏（缺字段不显示）。
    if (!options()?.review_reasoning_effort) return base.filter((s) => s !== "review_effort")
    return base
  }

  const inputDefault = (target: SetupScreen): string => {
    if (target === "base_url") return baseUrl() || selectedProvider()?.base_url || ""
    if (target === "local_base_url") return localBaseUrl() || local()?.base_url || ""
    return ""
  }

  const focusInputSoon = () => {
    setInputFocused(false)
    setTimeout(() => setInputFocused(true), 50)
  }

  /**
   * 读当前输入框的文本，但**只认本屏的输入框**（`owner` 必须是正在显示的屏幕）。
   *
   * opentui-solid 的 reconciler 只在挂载时回调 ref（`createRenderEffect(() =>
   * props.ref && props.ref(node))`，没有卸载回调）：切屏后旧的 `Input` 已被销毁，而
   * `inputRef` 仍指着它，读 `.value` 会抛 "EditBuffer is destroyed"。这个异常在全局
   * keypress handler 里被吞掉，表现为**按键没反应**——点一次 Enter 就卡在上一屏。
   *
   * 跨屏时返回 undefined（调用方直接跳过回写）：此时输入框里的文本属于**别的**屏幕，
   * 写进本屏的 signal 是串值（例如把 API Key 输入框的内容写进规格字段）。
   */
  const liveInputText = (owner: SetupScreen): string | undefined => {
    if (screen() !== owner) return undefined
    return (inputRef?.value ?? inputValue()).trim()
  }

  /** custom_endpoint 五项表单：把当前输入框的值写回对应 signal（值变化时标记 dirty）。 */
  const commitCustomField = () => {
    const value = liveInputText("custom_endpoint")
    if (value === undefined) return
    const index = customFieldIndex()
    const prev = customFieldValue(index)
    if (index === 0) setCustomBaseUrl(value)
    else if (index === 1) setCustomApiKey(value)
    else if (index === 2) setCustomModelName(value)
    else if (index === 3) setCustomContextWindow(value)
    else if (index === 4) setCustomMaxOutput(value)
    if (value !== prev) setCustomDirty(true)
  }

  /** custom_endpoint 五项表单：读出对应 signal 作为输入框初值。 */
  const customFieldValue = (index: number): string => {
    if (index === 0) return customBaseUrl()
    if (index === 1) return customApiKey()
    if (index === 2) return customModelName()
    if (index === 3) return customContextWindow()
    return customMaxOutput()
  }

  /** model_spec 可编辑字段：把当前输入框的值写回对应 signal（同上，只认本屏输入框）。 */
  const commitSpecField = () => {
    const value = liveInputText("model_spec")
    if (value === undefined) return
    const index = specFieldIndex()
    if (index === 0) setSpecRemoteContext(value)
    else if (index === 1) setSpecRemoteOutput(value)
    else if (index === 2) setSpecLocalContext(value)
    else if (index === 3) setSpecLocalOutput(value)
  }

  /** model_spec 可编辑字段：读出对应 signal 作为输入框初值。 */
  const specFieldValue = (index: number): string => {
    if (index === 0) return specRemoteContext()
    if (index === 1) return specRemoteOutput()
    if (index === 2) return specLocalContext()
    return specLocalOutput()
  }

  /** model_spec 可编辑字段行数：有本地槽时 4 行，否则 2 行。 */
  const specFieldCount = () => (localSpec() ? 4 : 2)

  /** api_key 输入三态（§6.2）：undefined 未填写 / "" 显式清空 / 非空写入。 */
  const customApiKeyState = () => interpretApiKeyInput(customApiKey())

  /** 当前焦点规格字段的边界校验提示（§6.3）：空串 = 合法。 */
  const specFieldError = (): string => {
    const index = specFieldIndex()
    const bounds =
      index === 0
        ? remoteSpec()?.bounds?.context_window
        : index === 1
          ? remoteSpec()?.bounds?.max_output
          : index === 2
            ? localSpec()?.bounds?.context_window
            : localSpec()?.bounds?.max_output
    return validateSpecInput(inputValue(), bounds, uiLanguage())
  }

  /**
   * 中转站字段是否会进载荷（§6.1）：只有用户主动改动过表单（dirty）且至少
   * 一项有值（含显式清空）才提交。确认页与载荷共用这一个判据，保证一致。
   */
  const willSubmitCustomEndpoint = () => {
    if (!customDirty()) return false
    const hasField =
      customBaseUrl().trim() ||
      customModelName().trim() ||
      customContextWindow().trim() ||
      customMaxOutput().trim()
    return Boolean(hasField || customApiKeyState() !== undefined)
  }

  const goTo = (target: SetupScreen) => {
    setError("")
    setInputFocused(false)
    // 进入细化页时焦点落在本屏主方框上（route_chat 选对话、route_review 选审查）。
    if (target === "route_chat") setRouteFocus("chat")
    else if (target === "route_review") setRouteFocus("review")
    // 进屏只做"复位焦点字段 + 预填初值"，**不回写**：此刻的输入框属于上一屏
    // （或已随上一屏销毁），回写等于把上一屏的文本写进本屏的 signal。
    if (target === "custom_endpoint") {
      setCustomFieldIndex(0)
      setInputValue(customFieldValue(0))
      setScreen(target)
      focusInputSoon()
      return
    }
    if (target === "model_spec") {
      setSpecFieldIndex(0)
      setInputValue(specFieldValue(0))
      setScreen(target)
      focusInputSoon()
      return
    }
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
    else if (screen() === "custom_endpoint") commitCustomField()
    else if (screen() === "model_spec") commitSpecField()
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
        // 仓库上下文（方案 §4.6）：显式发送屏幕上这一档；未改动时它就是后端当前值，
        // 全新配置的当前值 = tests+imports（与后端 DEFAULT_REPO_CONTEXT 一致）。
        ...setupRepoContextField(selectedRepoContext()),
        // review 思考档位（docs/DEV_RECORD.md）：显式发送屏幕上这一档；
        // 未改动时它就是后端当前值，全新配置的当前值 = off（= 现状）。
        ...setupReviewEffortField(selectedReviewEffort()),
      }
      if (isCustom()) {
        // 只有 custom 才附带两个槽位（`setupSlotFields` 保证其它预设返回空对象，
        // 旧载荷逐字节不变）。后端 custom 分支只写这两个键。
        Object.assign(payload, setupSlotFields(selectedRuntime(), routeSelection()))
      } else if (needsCloud()) {
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
      // B2 模型规格（§2.5）：只带用户改动过的字段，undefined 不发（后端 = 保持落盘值）。
      const remoteCtx = specRemoteContext().trim()
      const remoteOut = specRemoteOutput().trim()
      const localCtx = specLocalContext().trim()
      const localOut = specLocalOutput().trim()
      Object.assign(
        payload,
        setupModelSpecFields({
          context_window: remoteCtx ? Number(remoteCtx) : undefined,
          max_output: remoteOut ? Number(remoteOut) : undefined,
          local_context_window: localCtx ? Number(localCtx) : undefined,
          local_max_output: localOut ? Number(localOut) : undefined,
        }),
      )
      // B3 中转站逐项写入（§2.6/§6.1）：仅当用户改动过表单且至少一项有值才提交，
      // 预填值不会被动提交（dirty 标记）。api_key 走三态语义（§6.2）。
      if (willSubmitCustomEndpoint()) {
        const customCtx = customContextWindow().trim()
        const customOut = customMaxOutput().trim()
        Object.assign(
          payload,
          setupCustomEndpointFields(
            {
              base_url: customBaseUrl(),
              api_key: customApiKeyState(),
              model_name: customModelName(),
              context_window: customCtx ? Number(customCtx) : undefined,
              max_output: customOut ? Number(customOut) : undefined,
            },
            selectedApiFormat(),
          ),
        )
      }
      const response = await props.backend.request("config.setup", payload)
      if (!response.ok) throw new Error(response.error?.message ?? "配置保存失败")
      props.onApplied(response.result as RuntimeSnapshot)
      props.onClose()
    } catch (cause) {
      const message = String(cause)
      // 先"回到出错的那一屏"，再写错误文案：`goTo()` 里会 `setError("")`，反过来的
      // 话保存失败只剩一次跳屏、用户看不到原因（2026-09-27 复核发现）。
      // 路由细化页的校验错误要回到出错的那一屏：custom 顺序里没有 provider/model
      // 屏幕，落到那里会让用户卡在一个不在流程里的页面。
      if (isCustom() && message.includes("槽位")) {
        goTo(message.includes("对话模型") ? "route_chat" : "route_review")
      } else if (message.includes("模型规格")) {
        // 后端规格错误文案统一含「模型规格」（§3.6.4）；必须排在泛化的
        // `message.includes("模型")` 之前，否则永远不可达。
        goTo("model_spec")
      } else if (needsCloud() && message.includes("API Key")) goTo("api_key")
      else if (message.includes("GitHub Token")) goTo("github")
      else if (!isCustom() && message.includes("模型")) goTo("model")
      setError(message)
    } finally {
      setBusy(false)
    }
  }

  const next = () => {
    if (isInputScreen(screen()) || screen() === "model_spec" || screen() === "custom_endpoint") {
      commitInput()
    }
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
    // 「返回」= 退一级；**已经是根屏时退一级 = 退出助手**（等于 Esc 取消）。
    //
    // 这里原来是 `if (current === "runtime") return`：首屏的 ← 成了静默死键，而页脚
    // 明明写着「← 返回」——用户实测反馈「配置助手的 back 键无反应」（2026-09-27）。
    // 助手在确认页之前不写任何配置（只有 `apply()` 会落盘），所以这里退出不会丢改动。
    if (current === "runtime") {
      props.onClose()
      return
    }
    const currentOrder = order()
    const index = currentOrder.indexOf(current)
    if (index < 0) {
      // 当前屏不在本次顺序里（例如旧后端缺 review_reasoning_effort 导致该屏被过滤）：
      // 同样不能让返回变死键，按"无上一屏"处理。
      props.onClose()
      return
    }
    const prevScreen = currentOrder[index - 1]
    if (prevScreen) goTo(prevScreen)
  }

  onMount(async () => {
    try {
      const response = await props.backend.request("config.options", {}, { timeoutMs: PROBE_TIMEOUT_MS })
      if (!response.ok) throw new Error(response.error?.message ?? "无法读取配置选项")
      const payload = response.result as SetupOptions
      setOptions(payload)
      // 预设选中项优先读 routing.profile：runtime_profile 是"实际生效的槽"折算出来的
      // （custom 会被折算成 cloud/local/hybrid），只有 routing.profile 记得住"自定义"。
      const presetValues = (payload.runtime_profiles ?? fallbackRuntimeProfiles).map(
        (preset) => preset.value,
      )
      const routing = payload.routing ?? props.runtime.routing
      setRuntimeIndex(
        presetIndexOf(presetValues, routing?.profile, payload.current.runtime_profile ?? props.runtime.runtime_profile),
      )
      // 细化页两个方框的初值 = 当前生效的槽位（后端 resolve_* 的结果，前端不推导）。
      setRouteChatIndex(slotIndexOf(CHAT_SLOT_VALUES.map((value) => ({ value })), routing?.chat?.slot))
      setRouteReviewIndex(
        slotIndexOf(REVIEW_SLOT_VALUES.map((value) => ({ value })), routing?.review?.slot),
      )
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
      // 仓库上下文：预选后端落盘值；值缺失/未知时回落到推荐档（不是清单第一项）。
      setRepoContextIndex(
        repoContextIndexOf(
          repoContextChoices(payload.repo_context),
          repoContextStoredValue(payload.repo_context?.value ?? props.runtime.repo_context),
        ),
      )
      // review 思考档位：预选后端落盘值；值缺失/未知时回落到默认档 off。
      setReviewEffortIndex(
        reviewEffortIndexOf(
          reviewEffortChoices(payload.review_reasoning_effort),
          reviewEffortStoredValue(
            payload.review_reasoning_effort?.value ?? props.runtime.review_reasoning_effort,
          ),
        ),
      )
      setAutoPublishIndex(payload.current.auto_publish_comment ? 0 : 1)
      // B2/B3：预填规格编辑框与中转站五项表单。
      primeSpecFields(parseModelSpecBlock(payload.model))
      primeCustomFields(parseCustomEndpointOptions(payload.custom_endpoint))
    } catch (cause) {
      setError(String(cause))
      // `config.options` 读取失败也要给这一屏定预选：custom 分支只依赖固定的槽位取值，
      // 读不到 options 也能走到确认页；不定的话序号停在初值 0，保存时会把用户落盘的档位
      // 悄悄改成清单第一项 off。这里从快照兜底（认不出来就回落到推荐档）。
      setRepoContextIndex(
        repoContextIndexOf(
          repoContextChoices(options()?.repo_context),
          repoContextStoredValue(props.runtime.repo_context),
        ),
      )
      setReviewEffortIndex(
        reviewEffortIndexOf(
          reviewEffortChoices(options()?.review_reasoning_effort),
          reviewEffortStoredValue(props.runtime.review_reasoning_effort),
        ),
      )
    } finally {
      setLoading(false)
    }
  })

  /**
   * 细化页的键盘模型（方案 §4.2）：↑↓ 改当前方框的选择、Tab/←→ 在两个方框之间移动、
   * Enter 前进、Esc 返回。两个方框都在两屏上，焦点决定谁吃 ↑↓。
   */
  const moveRouteSelection = (delta: number) => {
    const focus = routeFocus()
    const choices = focus === "chat" ? chatChoices() : reviewChoices()
    if (choices.length === 0) return
    const current = focus === "chat" ? routeChatIndex() : routeReviewIndex()
    const nextIndex = (current + delta + choices.length) % choices.length
    if (focus === "chat") setRouteChatIndex(nextIndex)
    else setRouteReviewIndex(nextIndex)
  }

  const moveRouteFocus = (delta: number) => {
    const order: Array<"chat" | "review"> = ["chat", "review"]
    const current = order.indexOf(routeFocus())
    setRouteFocus(order[(current + delta + order.length) % order.length])
  }

  useKeyboard((key) => {
    if (key.name === "escape" && !busy()) {
      // 细化页的 Esc 是"返回上一屏"（方案 §4.2 的键盘矩阵）：先退回运行模式页，
      // 再按一次才是改造前的"Esc 取消助手"。其余屏幕语义不变。
      if (isRouteScreen(screen()) || screen() === "model_spec" || screen() === "custom_endpoint") {
        previous()
        return
      }
      props.onClose()
      return
    }
    if (isRouteScreen(screen()) && !busy()) {
      if (key.name === "tab") {
        moveRouteFocus(key.shift === true ? -1 : 1)
        key.preventDefault?.()
        key.stopPropagation?.()
        return
      }
      if (
        (key.name === "right" || key.name === "left") &&
        key.ctrl !== true &&
        key.meta !== true &&
        key.shift !== true
      ) {
        // ←→ 在细化页是"换方框"，不是"上一屏"：先拦下来，别让下面的通用规则拿走。
        // Ctrl/Alt+← 仍然落到下面的"返回"，保持与其它屏幕一致的快捷键。
        moveRouteFocus(key.name === "right" ? 1 : -1)
        key.preventDefault?.()
        key.stopPropagation?.()
        return
      }
      if (key.name === "up" || key.name === "down") {
        moveRouteSelection(key.name === "down" ? 1 : -1)
        key.preventDefault?.()
        key.stopPropagation?.()
        return
      }
    }
    // B3 中转站五项表单：↑↓ 换字段（先提交当前输入框），Enter 前进/保存。
    if (screen() === "custom_endpoint" && !busy()) {
      // Ctrl+D 在 api_key 行 = 清空（§6.2）。
      if ((key.name === "d" || key.name === "D") && key.ctrl === true && customFieldIndex() === 1) {
        setCustomApiKey("-")
        setInputValue("-")
        setCustomDirty(true)
        key.preventDefault?.()
        key.stopPropagation?.()
        return
      }
      if (key.name === "up" || key.name === "down") {
        commitCustomField()
        const nextIndex = Math.min(4, Math.max(0, customFieldIndex() + (key.name === "down" ? 1 : -1)))
        setCustomFieldIndex(nextIndex)
        setInputValue(customFieldValue(nextIndex))
        focusInputSoon()
        key.preventDefault?.()
        key.stopPropagation?.()
        return
      }
    }
    // B2 模型规格屏：R 重新获取目录；↑↓ 切换可编辑字段。
    if (screen() === "model_spec" && !busy()) {
      if (key.name === "r" || key.name === "R") {
        void refreshCatalog()
        key.preventDefault?.()
        key.stopPropagation?.()
        return
      }
      if (key.name === "up" || key.name === "down") {
        commitSpecField()
        const maxIndex = specFieldCount() - 1
        const nextIndex = Math.min(maxIndex, Math.max(0, specFieldIndex() + (key.name === "down" ? 1 : -1)))
        setSpecFieldIndex(nextIndex)
        setInputValue(specFieldValue(nextIndex))
        focusInputSoon()
        key.preventDefault?.()
        key.stopPropagation?.()
        return
      }
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
      // model_spec / custom_endpoint 的 Enter 由输入框 onSubmit 处理（先提交焦点字段）。
      if (isInputScreen(screen()) || screen() === "model_spec" || screen() === "custom_endpoint") return
      if (screen() === "summary") void apply()
      else next()
    }
  })

  const dialogWidth = 74
  /**
   * 对话框高度必须每次求值（accessor，不是常量）。
   *
   * 改造前这里是 `const dialogHeight = screen() === "provider" ? 24 : 22`，在组件
   * 初始化时求值一次——`screen()` 那时永远是 "runtime"，于是**所有屏幕都只有 22 行**。
   * 22 行的内容区 = 22 - padding 4 - 边框 2 = 16 行，超出时 opentui 会静默丢掉溢出块的
   * 首行并留下上一次的字符残影（确认页云端分支：三行摘要 + 5 行 Provider 明细 + 6 行
   * 通用项 + 提示 + 页脚 = 19 行，实测被截成 12 行）。
   *
   * 现在按屏幕返回高度：确认页 28、供应商 / 路由细化页 24（≤ 18），其余 22（≤ 16）。
   * 左/上位置同样做成 accessor，窗口尺寸变化时才会跟着重新居中。
   *
   * 确认页 28 的来由：加了「仓库上下文」一行后云端分支是 2 表头 + 1 间距 + 16 行 + 1 页脚
   * = 20 行，正好顶到 26 行的内容区上限（26 - 边框 2 - padding 4 = 20），再多一行错误提示
   * 就会溢出被渲染器静默吞掉首行；28 给内容区 22 行，留 1 行余量。
   */
  const dialogHeight = (): number =>
    screen() === "summary"
      ? 28
      : screen() === "provider" || isRouteScreen(screen())
        ? 24
        : screen() === "model_spec" || screen() === "custom_endpoint"
          ? 24
          : 22
  const left = () => Math.max(2, Math.floor((dimensions().width - dialogWidth) / 2))
  const top = () => Math.max(0, Math.floor((dimensions().height - dialogHeight()) / 2))

  /**
   * 一个路由方框（方案 §4.2 的像素风选择框）：槽别名 + 实际模型名，
   * 选中行用 accent 底色 + `▸`，非焦点的方框淡出但保持可读。
   */
  const renderRouteBox = (boxModel: RouteBox) => {
    const focused = () => routeFocus() === boxModel.key
    const selected = () => (boxModel.key === "chat" ? routeChatIndex() : routeReviewIndex())
    return (
      <box flexDirection="column" marginBottom={boxModel.key === "chat" ? 1 : 0}>
        <text fg={focused() ? "#eeeeee" : muted}>{boxModel.title}</text>
        <box
          borderStyle="single"
          borderColor={focused() ? orange : muted}
          paddingLeft={1}
          paddingRight={1}
          flexDirection="column"
        >
          <For each={boxModel.choices}>{(choice, choiceIndex) => {
            const active = () => choiceIndex() === selected()
            return (
              <text bg={active() ? "#5a2e1c" : "#171717"}>
                <span style={{ fg: active() ? orange : muted }}>{active() ? "▸ " : "  "}</span>
                <span style={{ fg: active() ? "#ffffff" : "#eeeeee" }}>{choice.label}</span>
                <span style={{ fg: active() ? "#ffd0bb" : muted }}>{`  ${choice.detail}`}</span>
              </text>
            )
          }}</For>
        </box>
      </box>
    )
  }

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
    <box position="absolute" left={left()} top={top()} width={dialogWidth} height={dialogHeight()} backgroundColor="#171717" borderStyle="single" borderColor={orange} padding={2} zIndex={100} flexDirection="column">
      <text fg={orange}>配置助手 // SETUP WIZARD</text>
      <text fg={muted}>
        {screenStages[screen()]}/6 · {stageNames[screenStages[screen()]]} ·{" "}
        {bilingualScreenTitle(screen(), isEn(uiLanguage()), screenTitles[screen()])}
      </text>
      <Show when={loading()}><text fg={muted}>读取配置选项中...</text></Show>
      <Show when={!loading() && screen() === "runtime"}>
        <box marginTop={1} flexGrow={1}>
          <select
            options={runtimeProfiles().map((preset) => ({
              name: presetLabel(preset, uiLanguage()),
              description: presetDescription(preset.value, uiLanguage()),
              value: preset.value,
            }))}
            selectedIndex={runtimeIndex()}
            focused
            showDescription
            width="100%"
            height={10}
            selectedBackgroundColor="#5a2e1c"
            selectedTextColor="#ffffff"
            descriptionColor={muted}
            selectedDescriptionColor="#ffd0bb"
            onChange={(index) => setRuntimeIndex(index)}
          />
        </box>
      </Show>
      <Show when={!loading() && isRouteScreen(screen())}>
        {/*
          高度预算（实测，见 docs/DEV_RECORD.md）：对话框内容区 =
          height - padding 4 - 边框 2；超出时渲染器**静默**丢掉溢出块的首行并留下
          上一次的字符残影。细化页内容固定 16 行 + 最多 1 行错误 = 17 ≤ 18（24 行）。
        */}
        <box flexDirection="column">
          <For each={routeBoxViews()}>{(boxModel) => renderRouteBox(boxModel)}</For>
          <text fg={muted}>{routeStageCopy().hybridHint}</text>
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
      {/*
        仓库上下文三选一（方案 §4.6）。选项清单/说明来自 setup-repo-context.ts
        （后端 `config.options.repo_context.options` 优先），键盘模型与上面几屏完全一致：
        ↑↓ 选择、Enter 下一步、Esc 取消助手——所以页脚沿用通用文案，不做特例。
      */}
      <Show when={!loading() && screen() === "repo_context"}>
        <box marginTop={1} flexGrow={1}>
          <select
            options={repoContexts().map((item) => ({
              name: repoContextLabel(item, uiLanguage()),
              description: repoContextDescription(item, uiLanguage()),
              value: item.value,
            }))}
            selectedIndex={repoContextIndex()}
            focused
            showDescription
            width="100%"
            height={8}
            selectedBackgroundColor="#5a2e1c"
            selectedTextColor="#ffffff"
            descriptionColor={muted}
            selectedDescriptionColor="#ffd0bb"
            onChange={(index) => setRepoContextIndex(index)}
          />
          <text fg={muted}>{repoContextCopy(isEn(uiLanguage())).hint}</text>
        </box>
      </Show>
      {/*
        review 思考档位（docs/DEV_RECORD.md）。选项清单/label 来自后端
        `config.options.review_reasoning_effort`（缺字段用兜底表）；成本提示独立一行，
        用户选哪一档就看到哪一档的代价。后端 state=unsupported 时置灰 + 原因。
        小 max_output × high/max 时追加封顶提示（docs/DEV_RECORD.md）。
      */}
      <Show when={!loading() && screen() === "review_effort"}>
        <box marginTop={1} flexGrow={1}>
          <Show when={reviewEffortIsDisabled(reviewEffortBlock())}>
            <text fg="#ff6b6b">
              {`⚠ ${formatReviewEffortDisabled(reviewEffortBlock()?.reason, uiLanguage())}`}
            </text>
          </Show>
          <select
            options={reviewEfforts().map((item) => ({
              name: reviewEffortBilingualLabel(item.label, uiLanguage()),
              description: formatReviewEffortCost(item.value, uiLanguage()),
              value: item.value,
            }))}
            selectedIndex={reviewEffortIndex()}
            focused
            showDescription
            width="100%"
            height={reviewEffortIsDisabled(reviewEffortBlock()) ? 9 : 10}
            selectedBackgroundColor={reviewEffortIsDisabled(reviewEffortBlock()) ? "#3a3a3a" : "#5a2e1c"}
            selectedTextColor="#ffffff"
            descriptionColor={reviewEffortIsDisabled(reviewEffortBlock()) ? "#555555" : muted}
            selectedDescriptionColor={reviewEffortIsDisabled(reviewEffortBlock()) ? "#777777" : "#ffd0bb"}
            onChange={(index) => setReviewEffortIndex(index)}
          />
          <text
            fg={
              reviewEffortIsDisabled(reviewEffortBlock())
                ? "#555555"
                : selectedReviewEffort() === "off"
                  ? muted
                  : "#ffd0bb"
            }
          >
            {formatReviewEffortCost(selectedReviewEffort(), uiLanguage())}
          </text>
          <Show when={!reviewEffortIsDisabled(reviewEffortBlock()) && reviewBudgetCapHint()}>
            <text fg="#ffd0bb">{reviewBudgetCapHint()}</text>
          </Show>
        </box>
      </Show>
      {/*
        B2 模型规格屏（docs/DEV_RECORD.md）。数据来自 config.options.model，
        缺字段不显示（兼容旧后端）。context_window / max_output 可编辑；needs_verification
        时两个数字都摆出来，不覆盖用户值。source 徽标 + R 重新获取按钮。
      */}
      <Show when={!loading() && screen() === "model_spec"}>
        {(() => {
          const spec = activeSpec()
          const badge = formatSourceBadge(spec?.source, uiLanguage())
          const headline = formatModelHeadline(spec ?? {}, uiLanguage())
          const reasoning = spec?.reasoning ?? ""
          const verifyText = spec?.needs_verification
            ? formatNeedsVerification(spec, uiLanguage())
            : ""
          const remoteBounds = remoteSpec()?.bounds?.context_window
          const remoteOutBounds = remoteSpec()?.bounds?.max_output
          const localBounds = localSpec()?.bounds?.context_window
          const localOutBounds = localSpec()?.bounds?.max_output
          const refreshText = formatCatalogRefreshStatus(
            catalogRefresh(),
            catalogRefreshDetail(),
            uiLanguage(),
          )
          const en = isEn(uiLanguage())
          const rows = [
            {
              label: en ? "Context window" : "上下文长度",
              value: specRemoteContext(),
              bounds: remoteBounds,
              index: 0,
            },
            {
              label: en ? "Max output" : "最大输出",
              value: specRemoteOutput(),
              bounds: remoteOutBounds,
              index: 1,
            },
            ...(localSpec()
              ? [
                  {
                    label: en ? "Local context" : "本地上下文",
                    value: specLocalContext(),
                    bounds: localBounds,
                    index: 2,
                  },
                  {
                    label: en ? "Local max output" : "本地最大输出",
                    value: specLocalOutput(),
                    bounds: localOutBounds,
                    index: 3,
                  },
                ]
              : []),
          ]
          return (
            <box marginTop={1} flexDirection="column">
              <Show when={headline}>
                <text>
                  <span style={{ fg: "#eeeeee" }}>{headline}</span>
                  <span style={{ fg: orange }}>{`  ${badge}`}</span>
                </text>
              </Show>
              <Show when={!headline}>
                <text fg={muted}>
                  {en ? "No model spec available" : "暂无模型规格数据"}
                </text>
              </Show>
              <For each={rows}>{(row) => {
                const focused = () => specFieldIndex() === row.index
                const hint = formatSpecBoundHint(row.bounds, uiLanguage())
                return (
                  <text bg={focused() ? "#202020" : undefined}>
                    <span style={{ fg: focused() ? orange : muted }}>
                      {focused() ? "▸ " : "  "}
                    </span>
                    <span style={{ fg: muted }}>{row.label}</span>
                    <span style={{ fg: "#eeeeee" }}>{`  ${row.value || "—"}`}</span>
                    <Show when={hint}>
                      <span style={{ fg: muted }}>{`  ${hint}`}</span>
                    </Show>
                  </text>
                )
              }}</For>
              {/* 当前焦点字段的编辑框：与 isInputScreen 的 renderInput 同一套 inputRef。 */}
              <box marginTop={1} backgroundColor="#202020" paddingLeft={1} paddingRight={1}>
                <input
                  ref={(node) => {
                    inputRef = node
                  }}
                  value={inputValue()}
                  placeholder={rows[specFieldIndex()]?.label ?? ""}
                  focused={inputFocused()}
                  onContentChange={() => setInputValue(inputRef?.value ?? "")}
                  onSubmit={() => {
                    commitSpecField()
                    // §6.3：越界/非整数阻止 Enter 前进（保持 Enter 语义不变，只是先校验）。
                    if (specFieldError()) return
                    next()
                  }}
                  flexGrow={1}
                />
              </box>
              {/* §6.3 内联校验提示：越界/非整数时显示并阻止 Enter。 */}
              <Show when={specFieldError()}>
                <text fg="#ff6b6b">{specFieldError()}</text>
              </Show>
              <Show when={reasoning}>
                <text fg={muted}>
                  {en ? "Reasoning" : "推理能力"}{" "}
                  <span style={{ fg: "#eeeeee" }}>{reasoning}</span>
                </text>
              </Show>
              <Show when={verifyText}>
                <text fg="#ffd0bb">{`⚠ ${verifyText}`}</text>
              </Show>
              <Show when={refreshText}>
                <text fg={catalogRefresh() === "error" ? "#ff6b6b" : muted}>
                  {refreshText}
                </text>
              </Show>
              {/* §4 budget_source 展示：缺字段时不显示（兼容旧后端）。 */}
              <Show when={formatBudgetSource(props.runtime.chat_context_budget, props.runtime.chat_context_budget_source, uiLanguage())}>
                <text fg={muted}>
                  {formatBudgetSource(props.runtime.chat_context_budget, props.runtime.chat_context_budget_source, uiLanguage())}
                </text>
              </Show>
              <text fg={muted}>
                {en
                  ? "R refresh catalog · ↑↓ edit fields · Enter next · Esc back"
                  : "R 重新获取 · ↑↓ 编辑字段 · Enter 下一步 · Esc 返回"}
              </text>
            </box>
          )
        })()}
      </Show>
      {/*
        B3 中转站五项表单（docs/DEV_RECORD.md）。base_url / api_key / 模型名 /
        context_window / max_output 逐项填写，不套用官方预设；保存后回显。
      */}
      <Show when={!loading() && screen() === "custom_endpoint"}>
        {(() => {
          const endpoint = customEndpoint()
          const fields = customEndpointFieldLabels(uiLanguage())
          const values = [
            customBaseUrl(),
            customApiKey(),
            customModelName(),
            customContextWindow(),
            customMaxOutput(),
          ]
          /** api_key 行显示文本：`-` = 将清空；空 = 掩码；其余 = 原文。 */
          const apiKeyDisplay = () => {
            const raw = customApiKey().trim()
            if (raw === "-") return isEn(uiLanguage()) ? "(will clear)" : "（将清空）"
            return raw || "••••"
          }
          return (
            <box marginTop={1} flexDirection="column">
              <Show when={endpoint?.display_name || endpoint?.name}>
                <text fg={muted}>
                  {endpoint?.display_name ?? endpoint?.name}
                  {endpoint?.api_key_configured ? (
                    <span style={{ fg: orange }}>{`  ${isEn(uiLanguage()) ? "key configured" : "Key 已配置"}`}</span>
                  ) : null}
                </text>
              </Show>
              <For each={fields}>{(field, index) => {
                const focused = () => customFieldIndex() === index()
                return (
                  <text bg={focused() ? "#202020" : undefined}>
                    <span style={{ fg: focused() ? orange : muted }}>{focused() ? "▸ " : "  "}</span>
                    <span style={{ fg: muted }}>{field.label}</span>
                    <span style={{ fg: "#eeeeee" }}>{`  ${field.key === "api_key" ? apiKeyDisplay() : values[index()] || "—"}`}</span>
                  </text>
                )
              }}</For>
              {/* 当前焦点字段的编辑框：与 isInputScreen 的 renderInput 同一套 inputRef。 */}
              <box marginTop={1} backgroundColor="#202020" paddingLeft={1} paddingRight={1}>
                <input
                  ref={(node) => { inputRef = node }}
                  value={inputValue()}
                  placeholder={fields[customFieldIndex()]?.label ?? ""}
                  focused={inputFocused()}
                  onContentChange={() => {
                    setInputValue(inputRef?.value ?? "")
                    setCustomDirty(true)
                  }}
                  onSubmit={() => {
                    commitCustomField()
                    next()
                  }}
                  flexGrow={1}
                />
              </box>
              <Show when={customFieldIndex() === 3 || customFieldIndex() === 4}>
                <text fg={muted}>
                  {formatSpecBoundHint(
                    customFieldIndex() === 3
                      ? remoteSpec()?.bounds?.context_window
                      : remoteSpec()?.bounds?.max_output,
                    uiLanguage(),
                  )}
                </text>
              </Show>
              <text fg={muted}>
                {isEn(uiLanguage())
                  ? "↑↓ switch field · Enter next · Esc back · type - in API Key to clear"
                  : "↑↓ 切换字段 · Enter 下一步 · Esc 返回 · API Key 输入 - 清空"}
              </text>
            </box>
          )
        })()}
      </Show>
      <Show when={!loading() && screen() === "summary"}>
        <box marginTop={1} flexDirection="column">
          {/* 三行摘要（方案 §4.3 第 6 阶段）：运行模式 + 对话模型 + 审查模型。 */}
          <text><span style={{ fg: orange }}>{isEn(uiLanguage()) ? "Runtime   " : "运行模式  "}</span><span style={{ fg: "#eeeeee" }}>{presetLabel(selectedPreset(), uiLanguage())}</span></text>
          <text><span style={{ fg: orange }}>{isEn(uiLanguage()) ? "Chat      " : "对话模型  "}</span><span style={{ fg: "#eeeeee" }}>{routePreview().chat}</span></text>
          <text><span style={{ fg: orange }}>{isEn(uiLanguage()) ? "Review    " : "审查模型  "}</span><span style={{ fg: "#eeeeee" }}>{routePreview().review}</span></text>
          <Show when={needsCloud()}>
            {/* Provider/Endpoint/模型行随中转站提交状态切换（§6.1：确认页 = 载荷）。 */}
            <text><span style={{ fg: orange }}>Provider  </span><span style={{ fg: "#eeeeee" }}>{willSubmitCustomEndpoint() ? (customEndpoint()?.display_name ?? (isEn(uiLanguage()) ? "Custom Endpoint" : "中转站")) : selectedProvider()?.display_name}</span></text>
            <text><span style={{ fg: orange }}>Endpoint  </span><span style={{ fg: "#eeeeee" }}>{willSubmitCustomEndpoint() ? (customBaseUrl() || "—") : (baseUrl() || selectedProvider()?.base_url)}</span></text>
            <text><span style={{ fg: orange }}>API 格式  </span><span style={{ fg: "#eeeeee" }}>{selectedApiFormat()}</span></text>
            <text><span style={{ fg: orange }}>模型       </span><span style={{ fg: "#eeeeee" }}>{willSubmitCustomEndpoint() ? (customModelName() || "—") : selectedModel()}</span></text>
            <text><span style={{ fg: orange }}>API Key    </span><span style={{ fg: "#eeeeee" }}>{willSubmitCustomEndpoint() ? (customApiKeyState() === "" ? "将清空" : customApiKeyState() ? "将更新" : customEndpoint()?.api_key_configured ? "保留现有" : "未配置") : (apiKey().trim() ? "将更新" : remoteKeyConfigured() ? "保留现有" : "未配置")}</span></text>
          </Show>
          <Show when={!needsCloud() && !isCustom()}>
            <text><span style={{ fg: orange }}>本地引擎  </span><span style={{ fg: "#eeeeee" }}>{local()?.display_name}</span></text>
            <text><span style={{ fg: orange }}>Endpoint  </span><span style={{ fg: "#eeeeee" }}>{localBaseUrl() || local()?.base_url}</span></text>
            <text><span style={{ fg: orange }}>本地模型  </span><span style={{ fg: "#eeeeee" }}>{selectedLocalModel()}</span></text>
          </Show>
          <Show when={isCustom()}>
            <text fg={muted}>自定义路由只写入两个槽位；各槽的 Provider / Key / 端点沿用已有配置。</text>
          </Show>
          <text><span style={{ fg: orange }}>GitHub    </span><span style={{ fg: "#eeeeee" }}>{githubToken().trim() ? "将更新" : githubConfigured() ? "保留现有" : "未配置"}</span></text>
          <text><span style={{ fg: orange }}>界面语言  </span><span style={{ fg: "#eeeeee" }}>{selectedUiLanguage()}</span></text>
          <text><span style={{ fg: orange }}>回复语言  </span><span style={{ fg: "#eeeeee" }}>{selectedResponseLanguage()}</span></text>
          <text><span style={{ fg: orange }}>输出格式  </span><span style={{ fg: "#eeeeee" }}>{selectedOutputFormat()}</span></text>
          <text><span style={{ fg: orange }}>自动发布  </span><span style={{ fg: "#eeeeee" }}>{autoPublish() ? "是" : "否"}</span></text>
          <text><span style={{ fg: orange }}>Chat 布局 </span><span style={{ fg: "#eeeeee" }}>{selectedChatLayout()}</span></text>
          {/*
            仓库上下文行（方案 §4.6）：显示双语 label，而不是 off/tests/tests+imports 裸值。
            标签走字符串字面量而不是 JSX 文本：JSX 文本节点里的连续空格会被编译器折叠成
            一个（`"Repo ctx  "` 会退成 `"Repo ctx "`），字面量才保得住对齐用的填充。
          */}
          <text><span style={{ fg: orange }}>{isEn(uiLanguage()) ? "Repo ctx  " : "仓库上下文 "}</span><span style={{ fg: "#eeeeee" }}>{repoContextPreview()}</span></text>
          {/* review 思考档位行（docs/DEV_RECORD.md）：缺字段时不显示（旧后端兼容）。 */}
          <Show when={options()?.review_reasoning_effort}>
            <text><span style={{ fg: orange }}>{isEn(uiLanguage()) ? "Review th " : "审查思考  "}</span><span style={{ fg: "#eeeeee" }}>{reviewEffortPreview()}</span></text>
          </Show>
          {/* 一行写完：这行原本会长到换行，多出的一行会把确认页挤出高度预算。 */}
          <text fg={muted}>Enter 保存到私有配置；高级项用 pr-review config --advanced。</text>
          {/* B2 模型规格摘要：只在有值时显示，缺字段整行不出现。 */}
          <Show when={specRemoteContext() || specRemoteOutput()}>
            <text fg={muted}>
              {isEn(uiLanguage()) ? "Spec       " : "模型规格  "}
              <span style={{ fg: "#eeeeee" }}>
                {[
                  specRemoteContext() ? `ctx ${specRemoteContext()}` : "",
                  specRemoteOutput() ? `out ${specRemoteOutput()}` : "",
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            </text>
          </Show>
          {/* B3 中转站摘要：只在会提交时显示（§6.1 确认页 = 载荷）。 */}
          <Show when={willSubmitCustomEndpoint()}>
            <text fg={muted}>
              {isEn(uiLanguage()) ? "Custom ep  " : "中转站    "}
              <span style={{ fg: "#eeeeee" }}>
                {[
                  customBaseUrl(),
                  customModelName(),
                  customContextWindow() ? `ctx ${customContextWindow()}` : "",
                  customMaxOutput() ? `out ${customMaxOutput()}` : "",
                ].filter(Boolean).join(" · ")}
              </span>
            </text>
          </Show>
        </box>
      </Show>
      <box flexGrow={1} />
      <Show when={error()}><text fg="#ff6b6b">{error()}</text></Show>
      <text fg={busy() ? orange : muted}>
        {busy()
          ? "保存中..."
          : screen() === "summary"
            ? "Enter 保存 · ← 返回修改 · Esc 取消"
            : isRouteScreen(screen())
              ? routeStageCopy().keys
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
            // PR 号与 PR 网址是用户真正用来"认领"一次审查的指标；run id 是
            // UUID，只作为最后兜底显示（实测：复制 run id 很不方便）。
            name: `${
              typeof run.pr_number === "number" ? `PR #${run.pr_number}` : (run.id ?? "?")
            } · ${run.repo_owner ?? "?"}/${run.repo_name ?? "?"}`,
            description: `${run.pr_url ?? "（无 PR 网址）"} · findings=${run.total_findings ?? 0} · ${run.created_at ?? ""}`,
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
      <text fg={muted}>↑↓ 选择 · Enter 打开详情（载入工作台并绑定对话） · Esc 返回</text>
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

/**
 * `/sessions` · 会话列表弹窗（A-P2，docs/DEV_RECORD.md）。
 *
 * 状态机：list ⇄ rename（内联输入） / list → confirm-delete（二次确认）。
 * `supported=false` 或 sessions 为空 → 空态文案「当前后端不支持会话列表」，
 * 只允许 Esc 关闭，绝不因为旧后端缺方法而崩溃。
 */
export function SessionsDialog(props: {
  sessions: SessionSummary[]
  currentId?: string
  /** session.list 是否可用；false = 旧后端 → 空态。 */
  supported: boolean
  /** 首次 `session.list` 还在飞：空态显示"读取中"而不是"没有会话"。 */
  loading?: boolean
  /** 上一次刷新失败的原因；仅在保留旧结果/空结果时提示，不再冒充"后端不支持"。 */
  error?: string
  language?: string
  onSwitch: (session: SessionSummary) => void
  onRename: (session: SessionSummary, title: string) => void
  onDelete: (session: SessionSummary) => void
  onClose: () => void
}) {
  type DialogMode = "list" | "rename" | "confirm-delete"
  const [mode, setMode] = createSignal<DialogMode>("list")
  const [selectedIndex, setSelectedIndex] = createSignal(0)
  const [renameDraft, setRenameDraft] = createSignal("")
  const [notice, setNotice] = createSignal("")
  let renameInput: InputRenderable | undefined

  // 选中项用**钳位**下标：列表可能晚于组件创建才到，或删除后变短，
  // 直接索引会取到 undefined（高亮消失、Enter 无反应）。
  const activeIndex = () => Math.min(selectedIndex(), Math.max(0, props.sessions.length - 1))
  const selected = () => props.sessions[activeIndex()]
  const listLabel = (): string[] =>
    props.sessions.map((session) =>
      formatSessionListItem(
        {
          title: session.title,
          updated_at: session.updated_at,
          message_count: session.message_count,
          // 顶层 current 优先（契约 v1），列表项 current 兜底。
          current: props.currentId ? session.id === props.currentId : session.current,
        },
        new Date(),
        props.language,
      ),
    )

  const startRename = () => {
    const session = selected()
    if (!session) return
    setRenameDraft(session.title ?? "")
    setMode("rename")
    setNotice("")
    // 输入框在下一帧才挂上，延迟聚焦。
    setTimeout(() => renameInput?.focus?.(), 0)
  }

  const commitRename = () => {
    const session = selected()
    if (!session) return
    const title = renameDraft().trim()
    setMode("list")
    if (title) props.onRename(session, title)
  }

  const commitDelete = () => {
    const session = selected()
    if (!session) return
    setMode("list")
    props.onDelete(session)
  }

  useKeyboard((key) => {
    if (mode() === "rename") {
      if (key.name === "escape") {
        key.stopPropagation?.()
        setMode("list")
        return
      }
      if (isEnterKey(key)) {
        key.stopPropagation?.()
        commitRename()
      }
      return
    }
    if (mode() === "confirm-delete") {
      if (key.name === "escape" || key.name === "n") {
        key.stopPropagation?.()
        setMode("list")
        return
      }
      if (isEnterKey(key) || key.name === "y") {
        key.stopPropagation?.()
        commitDelete()
      }
      return
    }
    // list 模式
    if (key.name === "escape") {
      key.stopPropagation?.()
      props.onClose()
      return
    }
    if (key.name === "up" || key.name === "down") {
      key.stopPropagation?.()
      const count = props.sessions.length
      if (count === 0) return
      setSelectedIndex((index) => (index + (key.name === "down" ? 1 : -1) + count) % count)
      setNotice("")
      return
    }
    if (isEnterKey(key)) {
      key.stopPropagation?.()
      const session = selected()
      if (session) props.onSwitch(session)
      return
    }
    if (key.name === "r") {
      key.stopPropagation?.()
      startRename()
      return
    }
    if (key.name === "d") {
      key.stopPropagation?.()
      const session = selected()
      if (session) {
        setMode("confirm-delete")
        setNotice(formatSessionDeleteConfirm(session.title, props.language))
      }
    }
  })

  // 派生状态必须是**取值函数**：Solid 的 props 是响应式 getter，写成
  // `const empty = !props.supported || ...` 只在组件创建那一刻求值一次——
  // 之后 `session.list` 回来也不会重算，列表的 `<Show when={!empty}>` 被永久
  // 禁用，于是「第一次 /sessions 只能看到空态、关掉再开才出列表」（用户实测
  // 2026-09-27，会话数在副标题里明明已经变成 2）。
  const empty = () => !props.supported || props.sessions.length === 0
  return (
    <box
      position="absolute"
      left={6}
      top={2}
      width={72}
      height={22}
      backgroundColor="#171717"
      borderStyle="single"
      borderColor={orange}
      padding={2}
      zIndex={150}
      flexDirection="column"
    >
      <text fg={orange}>SESSIONS // 会话列表</text>
      {/* 有列表数据时永远显示计数（即使某次刷新失败）——避免与"不支持"自相矛盾。 */}
      <Show when={props.supported || props.sessions.length > 0}>
        <text fg={muted}>共 {props.sessions.length} 个会话</text>
      </Show>
      {/* 「不支持」只在**确实没有失败原因**时出现：刷新失败（超时/后端报错）和旧后端
          缺方法都置 supported=false，但两者对用户是完全不同的信息。 */}
      <Show when={!props.supported && props.sessions.length === 0 && !props.error}>
        <text fg="#f3c742">{formatSessionListEmpty(props.language)}</text>
      </Show>
      {/* 刷新失败但手里还有上一份结果：说明失败原因，别把旧数据说成"不支持"。 */}
      <Show when={Boolean(props.error)}>
        <text fg="#f3c742">{formatSessionListError(props.error, props.language)}</text>
      </Show>
      <Show when={!empty()}>
        <box marginTop={1} flexDirection="column" flexGrow={1}>
          <For each={listLabel()}>{(line, index) =>
            <text
              bg={index() === activeIndex() && mode() === "list" ? "#5a2e1c" : undefined}
              fg={props.sessions[index()]?.id === props.currentId ? "#ffd0bb" : "#eeeeee"}
            >
              {line}
            </text>
          }</For>
        </box>
      </Show>
      <Show when={empty()}>
        <box marginTop={1} flexGrow={1} flexDirection="column">
          {/* 空态有两种来源，文案必须分开：读取中 / 确实还没有会话。
              （旧后端「不支持」的情况由上面的副标题给出，这里不重复。） */}
          <Show when={props.supported && props.loading}>
            <text fg={muted}>{formatSessionListLoading(props.language)}</text>
          </Show>
          <Show when={props.supported && !props.loading}>
            <text fg="#f3c742">{formatSessionListNoSessions(props.language)}</text>
          </Show>
          <text fg={muted}>
            {isEn(props.language)
              ? "Press Esc to close this dialog"
              : "按 Esc 关闭本弹窗"}
          </text>
        </box>
      </Show>
      <Show when={mode() === "rename"}>
        <box marginTop={1} flexDirection="column">
          <text fg="#f3c742">
            {isEn(props.language) ? "Rename session:" : "重命名会话："}
          </text>
          <box backgroundColor="#202020" paddingLeft={1} paddingRight={1}>
            <input
              ref={(node) => {
                renameInput = node
              }}
              value={renameDraft()}
              onContentChange={() => setRenameDraft(renameInput?.value ?? "")}
              focused
              flexGrow={1}
            />
          </box>
          <text fg={muted}>{formatSessionRenamePrompt(props.language)}</text>
        </box>
      </Show>
      <Show when={mode() === "confirm-delete"}>
        <text fg="#ff6b6b">{notice()}</text>
      </Show>
      <Show when={mode() === "list" && notice()}>
        <text fg="#7edc92">{notice()}</text>
      </Show>
      <text fg={muted}>{formatSessionListFooter(props.language)}</text>
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
  // C5 · 思考流独立累积，绝不与正文拼接，也不写入消息历史。
  const [streamingThinking, setStreamingThinking] = createSignal("")
  // C5 · 每条消息思考区展开态；默认落定后折叠（见 ThinkingBlock 注释）。
  const [thinkingExpanded, setThinkingExpanded] = createSignal<Record<string, boolean>>({})
  // C3 · 动画 tick（光标/spinner）；onCleanup 清定时器。
  const [animTick, setAnimTick] = createSignal(0)
  // A5 · 最近一次 assistant.finished.context（旧后端没有则保持 undefined）。
  // B-P3 · 第七键 pressure：只提示不自动压缩（medium/high 变黄，critical 变红）。
  const [assistantContext, setAssistantContext] = createSignal<
    | {
        used_tokens?: number
        budget_tokens?: number
        used_percent?: number
        pressure?: ContextPressure | null
      }
    | undefined
  >()
  // A-P2/A-P3 · 会话弹窗与状态栏会话名（session.list / session.switch 刷新）。
  const [sessionsOpen, setSessionsOpen] = createSignal(false)
  const [sessionList, setSessionList] = createSignal<SessionSummary[]>([])
  const [sessionListSupported, setSessionListSupported] = createSignal(true)
  /** `session.list` 是否在飞（首次打开弹窗时的"读取中"态，见 SessionsDialog）。 */
  const [sessionListLoading, setSessionListLoading] = createSignal(false)
  /** 上一次刷新失败的原因；空串 = 最近一次成功。 */
  const [sessionListError, setSessionListError] = createSignal("")
  const [sessionTitle, setSessionTitle] = createSignal("")
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

  let chatMessageSeq = 0
  /** 消息落定本地时间 HH:MM（指标行「对话时间」段；用户消息也记，便于回看）。 */
  const localHHMM = () => {
    const now = new Date()
    return `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`
  }
  const appendMessage = (message: ChatMessage) =>
    setMessages((current) => [
      ...current,
      {
        ...message,
        id: message.id ?? `msg-${(chatMessageSeq += 1)}`,
        timestamp: message.timestamp ?? localHHMM(),
      },
    ])

  // ---------------------------------------------------------------------
  // Workbench state machine (docs/DEV_RECORD.md §1)
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
  /**
   * Two rails only, at every size (user decision 2026-09-25): the full-screen
   * 209x51 terminal keeps the same two-column shape as 120x30 — chat on the
   * left, review on the right — instead of growing a second side rail.
   */
  const reviewLayout = (): "two" | "bar" => {
    if (!workbenchExpanded()) return "bar"
    if (dimensions().width >= 100 && dimensions().height >= 26) return "two"
    return "bar"
  }
  /**
   * Rails can only exist in `three`/`two`; at 80 columns (or a short window) the
   * workbench degrades to the one-line status bar instead of showing nothing.
   */
  const workbenchPanelsVisible = (): boolean =>
    workbenchExpanded() && reviewLayout() !== "bar"
  /**
   * Review rail width. Proportional so a 209-column terminal gets a roomier
   * rail than a 120-column one, while the chat column keeps at least ~60
   * columns.
   */
  const rightColumnWidth = (): number => {
    const width = dimensions().width
    const proportional = Math.round(width * 0.33)
    return Math.max(38, Math.min(proportional, width - 62))
  }
  /**
   * Width of the chat content column. While the workbench is off this stays 76
   * so the idle layout is byte-identical to the previous release.
   */
  const chatContentWidth = (): number => {
    if (!workbenchExpanded()) return 76
    const layout = reviewLayout()
    if (layout === "two") {
      return Math.max(56, dimensions().width - rightColumnWidth() - 2)
    }
    return Math.max(56, Math.min(96, dimensions().width - 4))
  }
  // ---------------------------------------------------------------------
  // C2 · 长代码块折叠（docs/DEV_RECORD.md）
  // 状态键 = 消息 id + 块序号；Alt+L 切换当前角标并跳到下一个（循环）。
  // ---------------------------------------------------------------------
  const [codeFoldExpanded, setCodeFoldExpanded] = createSignal<Record<string, boolean>>({})
  const [codeFoldCursor, setCodeFoldCursor] = createSignal(0)
  // Alt+T 思考区循环游标（与 Alt+L 代码块游标同语义）。
  const [thinkingCursor, setThinkingCursor] = createSignal(0)
  const isCodeBlockExpanded = (messageKey: string, blockIndex: number) =>
    codeFoldExpanded()[codeFoldStateKey(messageKey, blockIndex)] === true
  const codeFoldTargets = createMemo(() => {
    const targets: Array<{ messageKey: string; blockIndex: number }> = []
    for (const message of messages()) {
      const messageKey = message.id ?? "unknown"
      for (const block of foldableCodeBlocks(message.content)) {
        targets.push({ messageKey, blockIndex: block.index })
      }
    }
    for (const block of foldableCodeBlocks(streamingAssistant())) {
      targets.push({ messageKey: "streaming", blockIndex: block.index })
    }
    return targets
  })
  const toggleCodeFold = () => {
    const targets = codeFoldTargets()
    if (targets.length === 0) return
    const cursor = codeFoldCursor() % targets.length
    const target = targets[cursor]
    const key = codeFoldStateKey(target.messageKey, target.blockIndex)
    setCodeFoldExpanded((prev) => ({ ...prev, [key]: prev[key] !== true }))
    setCodeFoldCursor((cursor + 1) % targets.length)
  }
  /** 角标鼠标点击：直接切换指定块，不走 Alt+L 的游标循环。 */
  const toggleCodeFoldAt = (messageKey: string, blockIndex: number) => {
    const key = codeFoldStateKey(messageKey, blockIndex)
    setCodeFoldExpanded((prev) => ({ ...prev, [key]: prev[key] !== true }))
  }
  // C5 · Alt+T 循环切换思考区折叠态（与 Alt+L 代码块循环同语义）。
  const toggleThinking = () => {
    const withThinking = messages().filter((message) => message.thinking && message.id)
    if (withThinking.length === 0) return
    const cursor = thinkingCursor() % withThinking.length
    const target = withThinking[cursor]
    setThinkingExpanded((prev) => ({ ...prev, [target.id!]: !(prev[target.id!] ?? false) }))
    setThinkingCursor((cursor + 1) % withThinking.length)
  }
  /** C1: table tier follows the markdown render width (chatContentWidth()-6). */
  const chatMarkdownTableOptions = () => chatTableOptions(Math.max(24, chatContentWidth() - 6))

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

  // C3 · 光标/spinner 动画 tick（2-3 帧循环）；teardown 清定时器。
  createEffect(() => {
    const active = Boolean(streamingAssistant() || activeChatRequestId())
    if (!active) return
    const timer = setInterval(() => setAnimTick((tick) => tick + 1), 180)
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

  /**
   * /history（无参）：对话消息列表——行首序号 + 截断正文。
   * 与 /history --runs 的审查列表（HistoryDialog select）视觉区分：
   * 这是纯文本序号列表，直接落在 transcript 里。
   */
  const openChatHistory = () => {
    const lines = formatChatHistoryLines(messages(), {
      contentWidth: Math.max(24, chatContentWidth() - 10),
      language: runtime().ui_language,
    })
    if (lines.length === 0) {
      appendMessage({
        role: "assistant",
        content: isEn(runtime().ui_language)
          ? "No conversation messages yet."
          : "当前会话还没有对话消息。",
      })
      return
    }
    const header = isEn(runtime().ui_language)
      ? `CHAT HISTORY · ${lines.length} message(s)`
      : `对话历史 · ${lines.length} 条消息`
    appendMessage({
      role: "assistant",
      content: [header, "", ...lines].join("\n"),
    })
  }

  const openHistoryRun = async (run: HistoryRun) => {
    if (!run.id) return
    // session_id 必须带上：后端靠它把"当前正在看的审查"绑定到会话。
    // 漏传时绑定静默失败，而界面仍会宣称已绑定（实测踩过）。
    const response = await backend.request("command.execute", {
      name: "history",
      args: [run.id],
      session_id: sessionId(),
    })
    if (response.ok && response.result?.report) {
      applyReviewReport(response.result.report as ReviewReport)
      setHistoryOpen(false)
      setReviewStage("历史报告")
      const label = typeof run.pr_number === "number" ? `PR #${run.pr_number}` : `Run ${run.id}`
      setReviewDetail(`${label} · ${run.created_at ?? ""}`)
      // 提示必须反映真实结果：后端返回 bound=true 才算绑定成功。
      const bound = response.result?.bound === true
      appendMessage({
        role: "assistant",
        content: bound
          ? `已载入 ${label} 的审查报告，并绑定为接下来的对话上下文——可以直接提问（例如"第 1 条为什么判中风险"）。用 /context 可查看或解绑。`
          : `已载入 ${label} 的审查报告，但**未能绑定对话上下文**（会话状态缺失）。可以按 /new 重开会话后再从历史打开，或直接说"PR #31"。`,
      })
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
    // Say what is happening and what to expect: the user previously saw a stuck
    // "取消中" with no explanation while the backend finished an in-flight call.
    setReviewActionMessage(
      "已请求取消：正在中止当前模型调用，通常几秒内结束（若某个文件调用刚发出，最多等它返回）。",
    )
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
          setReviewActionMessage(
            `取消失败：后端未确认取消（${
              response.error?.message ?? "当前没有正在运行的任务"
            }）。审查可能仍在运行，可再按 Esc 重试，或用 /status 查看。`,
          )
          return
        }
        setReviewActionMessage("取消已确认，正在等后端收尾（不会写入历史记录）。")
      })
      .catch((error) => {
        setBackendStatus(reviewing() ? "REVIEWING" : "READY")
        setReviewActionMessage(
          `取消请求超时或失败：${String(error)}。审查可能仍在运行；可再按 Esc 重试。`,
        )
      })
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
    // 本会话跑过的 URL 优先；没有再退回工作台里当前载入报告的目标 PR。
    // 实测反馈：从历史打开 #31 后按 /retry，却被告知"当前会话还没有可
    // 重试的审查"——屏幕上的报告明明就是可重试的对象。
    const workspaceReport = reviewReport() as Record<string, unknown>
    const workspacePr = (workspaceReport.pr ?? {}) as Record<string, unknown>
    const workspaceUrl =
      typeof workspacePr.url === "string" && workspacePr.url.trim()
        ? workspacePr.url.trim()
        : ""
    const url = reviewUrl() || workspaceUrl
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
    if (!findingId) {
      setReviewActionMessage(
        "该条 Finding 没有可用的 ID（历史记录可能缺少标识），无法记录反馈。",
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
      // 工作台与历史框用同一组关键指标：PR 号 + PR 网址（run id 只是兜底）。
      url: reviewReport().pr?.url,
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
    setAssistantContext(undefined)
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

  // ---------------------------------------------------------------------
  // A-P2/A-P3 · 会话列表（/sessions、Alt+S）与状态栏会话名。
  // 与后端并行：session.list 缺失/失败 → 空态文案，不崩溃。
  // ---------------------------------------------------------------------
  /** 会话列表刷新的请求序号（防乱序竞态，见 `refreshSessionList`）。 */
  let sessionListRequest = 0
  const applySessionList = (list: ReturnType<typeof parseSessionListResult>, error = "") => {
    if (!list) {
      setSessionListSupported(false)
      setSessionListError(error)
      // 刷新失败**不清空已有列表**：清空会让「共 N 个会话」与"看不到会话"自相矛盾
      // （用户实测：弹窗同时显示 6 个会话与"当前后端不支持"）。失败只用 supported
      // 标志表达，旧数据保留到下一次成功刷新。
      return
    }
    setSessionListSupported(true)
    setSessionListError("")
    setSessionList(list.sessions)
    const current =
      list.sessions.find((item) => (list.current ? item.id === list.current : item.current)) ??
      list.sessions.find((item) => item.id === sessionId())
    if (current) setSessionTitle(current.title ?? "")
  }

  const refreshSessionList = async () => {
    // 防乱序：并发刷新时旧响应不得覆盖新状态（用户实测到的"6 个会话 + 不支持"
    // 矛盾显示，根因就是两次 refresh 竞态：失败方最后写入 supported=false）。
    const token = (sessionListRequest += 1)
    setSessionListLoading(true)
    try {
      const response = await backend.request("session.list", {}, { timeoutMs: PROBE_TIMEOUT_MS })
      if (token !== sessionListRequest) return
      if (!response.ok) {
        applySessionList(undefined, response.error?.message ?? `后端错误（${response.error?.code ?? "unknown"}）`)
        return
      }
      applySessionList(parseSessionListResult(response.result))
    } catch (error) {
      if (token !== sessionListRequest) return
      applySessionList(undefined, String(error))
    } finally {
      // 只有最新一次刷新才能清掉 loading，否则慢响应会把新请求的"读取中"提前关掉。
      if (token === sessionListRequest) setSessionListLoading(false)
    }
  }

  const openSessions = () => {
    setSessionsOpen(true)
    void refreshSessionList()
  }

  const switchToSession = async (session: SessionSummary) => {
    try {
      const response = await backend.request(
        "session.switch",
        { session_id: session.id },
        { timeoutMs: CHAT_TIMEOUT_MS },
      )
      if (!response.ok) {
        appendMessage({
          role: "assistant",
          content: response.error?.message ?? "切换会话失败",
        })
        return
      }
      const parsed = parseSessionSwitchResult(response.result)
      // 切换后刷新消息区：用 session.switch 返回的消息重建历史。
      const history = (parsed?.messages ?? []).map((item) => ({
        role: item.role === "user" ? ("user" as const) : ("assistant" as const),
        content: item.content ?? "",
        thinking: item.thinking,
        timestamp: item.timestamp,
      }))
      setMessages(
        history.map((message, index) => ({
          ...message,
          id: `sw-${index + 1}`,
          timestamp: message.timestamp ?? localHHMM(),
        })),
      )
      setStreamingAssistant("")
      setStreamingThinking("")
      setActiveChatRequestId(undefined)
      setAssistantContext(undefined)
      setSessionId(session.id)
      const title = parsed?.session?.title ?? session.title ?? ""
      setSessionTitle(title)
      setSessionsOpen(false)
      appendMessage({
        role: "assistant",
        content: formatSessionSwitched(title, runtime().ui_language),
      })
      void refreshSessionList()
    } catch (error) {
      appendMessage({ role: "assistant", content: String(error) })
    }
  }

  const renameSession = async (session: SessionSummary, title: string) => {
    try {
      const response = await backend.request(
        "session.rename",
        { session_id: session.id, title },
        { timeoutMs: PROBE_TIMEOUT_MS },
      )
      if (!response.ok) {
        appendMessage({
          role: "assistant",
          content: response.error?.message ?? "重命名会话失败",
        })
        return
      }
      const parsed = parseSessionRenameResult(response.result)
      const nextTitle = parsed?.title ?? title
      setSessionList((current) =>
        current.map((item) => (item.id === session.id ? { ...item, title: nextTitle } : item)),
      )
      if (session.id === sessionId()) setSessionTitle(nextTitle)
    } catch (error) {
      appendMessage({ role: "assistant", content: String(error) })
    }
  }

  /** `/rename <标题>`：重命名**当前会话**。
   *
   * 弹窗里的 `r` 键需要一个被选中的 `SessionSummary`，而命令入口只有标题文本——
   * 所以这里直接用 `sessionId()` 调协议（用户反馈"想改名但入口太难发现"）。
   */
  const renameCurrentSession = async (title: string) => {
    const current = sessionId()
    if (!current) {
      appendMessage({
        role: "assistant",
        content: "还没有会话可重命名——先发一条消息建立会话，再用 /rename 改标题。",
      })
      return
    }
    try {
      const response = await backend.request(
        "session.rename",
        { session_id: current, title },
        { timeoutMs: PROBE_TIMEOUT_MS },
      )
      if (!response.ok) {
        appendMessage({
          role: "assistant",
          content: response.error?.message ?? "重命名会话失败",
        })
        return
      }
      const parsed = parseSessionRenameResult(response.result)
      const nextTitle = parsed?.title ?? title
      setSessionTitle(nextTitle)
      setSessionList((list) =>
        list.map((item) => (item.id === current ? { ...item, title: nextTitle } : item)),
      )
      appendMessage({ role: "assistant", content: `会话已重命名为「${nextTitle}」。` })
    } catch (error) {
      appendMessage({ role: "assistant", content: String(error) })
    }
  }

  const deleteSession = async (session: SessionSummary) => {
    try {
      const response = await backend.request(
        "session.delete",
        { session_id: session.id },
        { timeoutMs: PROBE_TIMEOUT_MS },
      )
      if (!response.ok) {
        appendMessage({
          role: "assistant",
          content: response.error?.message ?? "删除会话失败",
        })
        return
      }
      const parsed = parseSessionDeleteResult(response.result)
      setSessionList((current) => current.filter((item) => item.id !== session.id))
      // 若当前被删则自动跟随 next（契约 v1）。
      if (session.id === sessionId()) {
        const nextId = parsed?.next
        if (nextId) {
          const next = sessionList().find((item) => item.id === nextId)
          if (next) {
            void switchToSession(next)
            return
          }
          setSessionId(nextId)
          setSessionTitle("")
          resetSessionUi()
        } else {
          setSessionTitle("")
          resetSessionUi()
        }
      }
      void refreshSessionList()
    } catch (error) {
      appendMessage({ role: "assistant", content: String(error) })
    }
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
      // A-P1 契约 v1：`session.create` 已是「**新建并切换**」——不再是无条件的
      // "确保有一个"。非强制路径先查已有会话：有就 `switch` 回最近一个（会话已
      // 持久化，重启也能接上），没有才新建；否则每次打开 chat 都会多出一个空
      // 会话，列表越堆越多（用户实测反馈）。
      // `force=true` 仅由 `sendWithSessionRecovery` 在 `not_found` 时使用——那时
      // 会话真的没了，强制新建才是对的行为。
      let next = ""
      let restored: Array<{
        role?: string
        content?: string
        thinking?: string
        timestamp?: string
      }> = []
      let restoredTitle = ""
      if (!force) {
        try {
          const listed = await backend.request("session.list", {}, { timeoutMs: PROBE_TIMEOUT_MS })
          if (listed.ok) {
            const parsedList = parseSessionListResult(listed.result)
            // 2026-09-27 用户反馈：**不要自动跳到上次的对话**——打开 chat 应该是空白的
            // 新会话（旧对话通过 `/sessions` 显式切换）。复用策略只认**最近的空会话**
            // （message_count 0）：连续打开不会堆积空会话，也永远不会把有历史的会话
            // 悄悄拉回屏幕。
            const latest = parsedList?.sessions[0]
            const target = latest && (latest.message_count ?? 0) === 0 ? latest.id : ""
            if (target) {
              const switched = await backend.request(
                "session.switch",
                { session_id: target },
                { timeoutMs: PROBE_TIMEOUT_MS },
              )
              if (switched.ok) {
                const parsedSwitch = parseSessionSwitchResult(switched.result)
                next = target
                restored = parsedSwitch?.messages ?? []
                restoredTitle = parsedSwitch?.session?.title ?? ""
              }
            }
          }
        } catch {
          // 旧后端没有 session.list/switch：回落到下面的 create（保持兼容）。
        }
      }
      if (!next) {
        const created = await backend.request("session.create", {}, { timeoutMs: PROBE_TIMEOUT_MS })
        if (!created.ok) throw new Error(created.error?.message ?? "无法恢复 Chat 会话")
        next = String(created.result.session_id)
      }
      const configuration = snapshot.result as RuntimeSnapshot
      setRuntime(configuration)
      setSessionId(next)
      if (restoredTitle) setSessionTitle(restoredTitle)
      if (restored.length > 0) {
        // 恢复的会话要把历史渲染回消息区（与 switchToSession 同一套重建规则）。
        setMessages(
          restored.map((message, index) => ({
            id: `rs-${index + 1}`,
            role: message.role === "user" ? ("user" as const) : ("assistant" as const),
            content: message.content ?? "",
            thinking: message.thinking,
            timestamp: message.timestamp ?? localHHMM(),
          })),
        )
      }
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
        // 会话已持久化（A-P1）：能恢复就说恢复，恢复不了才说新建——文案不再
        // 一律宣称"无法自动恢复"（那会让用户以为历史丢了）。
        appendMessage({
          role: "assistant",
          content:
            restored.length > 0
              ? `后端已重启，已恢复会话「${restoredTitle || "未命名"}」的历史记录；当前报告已重置，可用 /report 或 /history 重新载入。`
              : "后端已重启，已回到空白会话；旧对话可用 /sessions 切换，历史审查可用 /history 查看。",
        })
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
          setStreamingThinking("")
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
          // A failed run must not read as "发现 N 个问题": the summary already
          // explains the failure (and any static-analysis findings it carries),
          // so prefer it verbatim when it reports a failure.
          const completedSummary = typeof event.summary === "string" ? event.summary.trim() : ""
          setReviewDetail(
            completedSummary.startsWith("审查失败")
              ? completedSummary
              : `发现 ${String(event.finding_count ?? 0)} 个问题 · Run ${String(event.run_id ?? "")}`,
          )
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
        // C5 · 思考流独立累积（契约 v1）；缺字段/旧后端时不进这里。
        if (event.event === "assistant.reasoning_delta") {
          const piece = parseReasoningDelta(event)
          if (piece !== undefined) setStreamingThinking((current) => current + piece)
        }
        if (event.event === "assistant.finished") {
          const meta = parseAssistantFinishMeta(event)
          // C5 · finished.reasoning 仅作兜底：流已给过则不重复拼接。
          const streamedThinking = streamingThinking()
          const thinking =
            streamedThinking ||
            (meta.reasoning ?? "")
          const finalText = String(event.text ?? streamingAssistant())
          const messageKey = `msg-${(chatMessageSeq += 1)}`
          appendMessage({
            id: messageKey,
            role: "assistant",
            content: finalText,
            durationSeconds: meta.durationSeconds,
            warning: meta.warning,
            thinking: thinking || undefined,
            model: meta.model,
            completionTokens: meta.usage?.completion_tokens,
          })
          // 落定后思考区默认折叠（流式期间展开）。
          if (thinking) setThinkingExpanded((prev) => ({ ...prev, [messageKey]: false }))
          if (meta.context) setAssistantContext(meta.context)
          if (typeof event.request_id === "string") renderedAssistantReplies.add(event.request_id)
          setStreamingAssistant("")
          setStreamingThinking("")
          setBackendStatus("READY")
        }
        if (event.event === "assistant.cancelled") {
          const partial = streamingAssistant()
          const streamedThinking = streamingThinking()
          if (partial) {
            appendMessage({
              role: "assistant",
              content: `${partial} [已取消]`,
              thinking: streamedThinking || undefined,
            })
          }
          if (typeof event.request_id === "string") renderedAssistantReplies.add(event.request_id)
          setStreamingAssistant("")
          setStreamingThinking("")
          setBackendStatus("READY")
        }
        if (event.event === "assistant.failed") {
          setStreamingAssistant("")
          setStreamingThinking("")
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
        <box width={76} marginTop={1} flexDirection="column">
          <box flexDirection="row" justifyContent="space-between">
            <text fg={orange}>PR REVIEW / CHAT</text>
            <text fg={muted}>{runtime().provider_display ?? runtime().provider ?? ""} · {runtime().model ?? ""}</text>
          </box>
          {/* A5 · 上下文用量；无 context 字段时整行不渲染。 */}
          <box flexDirection="row" justifyContent="flex-end">
            <ContextUsageLine context={assistantContext()} language={runtime().ui_language} />
          </box>
        </box>
      }>
        <PixelLogo language={runtime().ui_language} />
      </Show>
      {/* Minimised workbench banner: full width directly under the header, so it
          never sits inside the chat column or pushes the composer around. */}
      {/* `always` keeps the *panels* available, but a banner that only says
          "就绪 0% · 0 问题" before any review has run is noise — hide it until
          there is something to report (or the user opens the workbench). */}
      <Show
        when={
          workbenchVisible() &&
          !workbenchPanelsVisible() &&
          (reviewPhase() !== "idle" || workbenchManualOpen())
        }
      >
        <box width="100%" flexShrink={0} flexDirection="column" paddingLeft={2} paddingRight={2}>
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
            width={Math.max(12, dimensions().width - 4)}
          />
          <Show when={reviewActionMessage()}>
            <text width={Math.max(12, dimensions().width - 4)} fg="#7edc92">
              {reviewActionMessage()}
            </text>
          </Show>
        </box>
      </Show>
      {/* Middle row: review panels live outside the chat scrollbox, so they can
          no longer push the transcript out of view. The chat column keeps a
          stable position in the tree, which is what keeps the composer's draft
          and cursor alive across Alt+W. */}
      <box width="100%" flexGrow={1} flexDirection="row" minHeight={0}>
      <box flexGrow={1} minWidth={0} flexDirection="column" alignItems="center">
      <scrollbox width="100%" flexGrow={1} scrollY stickyScroll stickyStart="bottom" scrollbarOptions={{ showArrows: false }}>
        <box width="100%" alignItems="center" flexDirection="column">
      <Show when={messages().length === 0 && !composerDraft() && !streamingAssistant() && !streamingThinking() && !activeChatRequestId() && !errorMessage() && !reviewStage() && !compactHome()}>
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
      <Show when={messages().length > 0 || streamingAssistant() || streamingThinking() || activeChatRequestId()}>
        <box width={chatContentWidth()} marginTop={2} flexDirection="column">
          <For each={messages()}>{(message) =>
            <Show
              when={message.role !== "user"}
              fallback={
                /* 用户输入：左侧橙色色条 + `›` 前缀 + 深色底——与 assistant 的
                   `●` + 纯 markdown 回复一眼区分（实测反馈："用户输入和 AI 输出
                   内容无法区分"）。`›` 用橙色，正文保持亮灰，zh/en 均成立。
                   落定时间（HH:MM）跟在气泡下，便于回看对话节奏。 */
                <box flexDirection="column" marginBottom={1}>
                  <box
                    flexDirection="row"
                    paddingLeft={1}
                    paddingRight={1}
                    backgroundColor="#1a1a1a"
                    border={["left"]}
                    borderColor={orange}
                  >
                    <text fg={orange}>› </text>
                    <text width={Math.max(24, chatContentWidth() - 12)} fg="#eeeeee">
                      {message.content}
                    </text>
                  </box>
                  <Show when={message.timestamp}>
                    <box flexDirection="row" paddingLeft={2}>
                      <text fg={muted}>· {message.timestamp}</text>
                    </box>
                  </Show>
                </box>
              }
            >
              {/* C5 · 独立思考区：在正文之前，绝不拼接进 content。 */}
              <Show when={message.thinking}>
                <ThinkingBlock
                  text={message.thinking!}
                  expanded={thinkingExpanded()[message.id ?? ""] === true}
                  onToggle={() =>
                    setThinkingExpanded((prev) => ({
                      ...prev,
                      [message.id ?? ""]: !(prev[message.id ?? ""] ?? false),
                    }))
                  }
                  language={runtime().ui_language}
                  width={chatContentWidth() - 6}
                />
              </Show>
              {/* C3 批次 · 方案 A：角标拆出为独立 onMouseDown 元素，Alt+L 保留。 */}
              <box flexDirection="column" paddingBottom={1}>
                <FoldableMarkdownBlock
                  content={message.content}
                  messageKey={message.id ?? "unknown"}
                  isExpanded={(blockIndex) =>
                    isCodeBlockExpanded(message.id ?? "unknown", blockIndex)
                  }
                  onToggleAt={toggleCodeFoldAt}
                  width={Math.max(24, chatContentWidth() - 6)}
                  syntaxStyle={chatMarkdownStyle()}
                  fg={muted}
                  bulletFg="#eeeeee"
                  tableOptions={chatMarkdownTableOptions()}
                />
              </box>
              {/* 指标行：模型 · 耗时 · 输出长度 · 时间（缺哪项省哪项）+ A4 超额 tips。 */}
              <box flexDirection="row" paddingLeft={2} paddingBottom={1}>
                <MessageMetricsLine
                  model={message.model}
                  fallbackModel={runtime().model}
                  seconds={message.durationSeconds}
                  completionTokens={message.completionTokens}
                  contentLength={message.content.length}
                  timestamp={message.timestamp}
                  language={runtime().ui_language}
                />
              </box>
              <Show when={message.warning === "over_budget"}>
                <OverBudgetTip language={runtime().ui_language} width={chatContentWidth() - 6} />
              </Show>
            </Show>
          }</For>
          <Show when={streamingThinking()}>
            <ThinkingBlock
              text={streamingThinking()}
              expanded
              onToggle={() => {}}
              language={runtime().ui_language}
              width={chatContentWidth() - 6}
              streaming
            />
          </Show>
          <Show when={streamingAssistant() || activeChatRequestId()}>
            <box flexDirection="column">
              <Show
                when={streamingAssistant()}
                fallback={
                  /* C3 · 等待首 token：spinner + 思考中 */
                  <box flexDirection="row" gap={1}>
                    <text fg={orange}>●</text>
                    <text fg={muted}>
                      {thinkingPlaceholder(animTick(), runtime().ui_language)}
                    </text>
                  </box>
                }
              >
                <FoldableMarkdownBlock
                  content={streamingAssistant()}
                  messageKey="streaming"
                  isExpanded={(blockIndex) => isCodeBlockExpanded("streaming", blockIndex)}
                  onToggleAt={toggleCodeFoldAt}
                  width={Math.max(24, chatContentWidth() - 6)}
                  syntaxStyle={chatMarkdownStyle()}
                  fg="#eeeeee"
                  bulletFg={orange}
                  streaming={true}
                  tableOptions={chatMarkdownTableOptions()}
                />
                {/* C3 · 流式正文末尾闪烁光标（2-3 帧循环）。 */}
                <box flexDirection="row" paddingLeft={2}>
                  <text fg={orange} attributes={1}>
                    {cursorFrame(animTick())}
                  </text>
                </box>
              </Show>
            </box>
          </Show>
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
        onOpenFindings={openFindings}
        onOpenHistory={() => void openHistory()}
        onOpenChatHistory={openChatHistory}
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
        onToggleCodeFold={toggleCodeFold}
        onToggleThinking={toggleThinking}
        onOpenSessions={openSessions}
        onRenameSession={(title) => void renameCurrentSession(title)}
        codeFoldActive={codeFoldTargets().length > 0}
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
          !sessionsOpen() &&
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
          {/* Action feedback belongs to the workbench, not to the transcript. */}
          <Show when={reviewActionMessage()}>
            <box
              width="100%"
              flexShrink={0}
              backgroundColor="#141414"
              borderStyle="single"
              borderColor="#7edc92"
              paddingLeft={1}
              paddingRight={1}
              flexDirection="column"
            >
              <text fg="#7edc92" height={1}>
                REVIEW ACTION
              </text>
              <text fg="#eeeeee">{reviewActionMessage()}</text>
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
      <Show when={sessionsOpen()}>
        <SessionsDialog
          sessions={sessionList()}
          currentId={sessionId()}
          supported={sessionListSupported()}
          loading={sessionListLoading()}
          error={sessionListError()}
          language={runtime().ui_language}
          onSwitch={(session) => void switchToSession(session)}
          onRename={(session, title) => void renameSession(session, title)}
          onDelete={(session) => void deleteSession(session)}
          onClose={() => setSessionsOpen(false)}
        />
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
            // The backend matches on the finding's own id (`/feedback`
            // validates it against the stored run); passing the list index
            // made every submission fail with "未找到 Finding：0".
            void submitFindingFeedback(
              String(reviewFindings()[activeFindingIndex()]?.finding_id ?? ""),
              status,
              note,
            )
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
        <RuntimeStatusLine
          runtime={runtime()}
          status={backendStatus()}
          width={dimensions().width}
          height={dimensions().height}
          sessionTitle={sessionTitle()}
        />
      </box>
    </box>
  )
}
