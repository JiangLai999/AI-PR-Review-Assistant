/**
 * Small display helpers shared by the TUI footer and progress panel.
 *
 * They live outside `app.tsx` so the column/fit rules are unit-testable
 * without booting the OpenTUI renderer.
 */

/** Keep the tail of a long path so a footer line still fits 80 columns. */
export function compactPath(value: string, max = 30): string {
  if (!value || value.length <= max) return value
  return `…${value.slice(value.length - (max - 1))}`
}

/** GitHub URLs differ at both ends (`owner/repo` vs `pull/123`), so cut the middle. */
export function truncateMiddle(value: string, max = 70): string {
  if (value.length <= max) return value
  const head = Math.ceil((max - 1) / 2)
  const tail = Math.floor((max - 1) / 2)
  return `${value.slice(0, head)}…${value.slice(value.length - tail)}`
}

/**
 * Render the workspace root the launcher reported, folding the home prefix to
 * `~`. The footer used to hard-code `~\Desktop\ican`, which lied for every
 * other checkout (and for the packaged build).
 */
export function workspaceRootLabel(
  root: string = typeof process !== "undefined" ? process.env?.AI_PR_REVIEW_ROOT ?? process.cwd?.() ?? "" : "",
  home: string = typeof process !== "undefined" ? process.env?.USERPROFILE ?? process.env?.HOME ?? "" : "",
  max = 30,
): string {
  if (!root) return ""
  const display =
    home && root.toLowerCase().startsWith(home.toLowerCase()) ? `~${root.slice(home.length)}` : root
  return compactPath(display, max)
}

// ---------------------------------------------------------------------
// Chat 契约 v1 展示层（C3/C4/C5 + A4/A5）
// 纯函数，便于单测；app.tsx 只负责取数与排版。
// ---------------------------------------------------------------------

/**
 * C4 · 回答耗时：`3.2s` / `0.4s` / `45s`。
 * 缺失或非有限数字返回空串（调用方整段不显示）。
 */
export function formatDurationSeconds(seconds: number | undefined): string {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return ""
  if (seconds < 10) return `${seconds.toFixed(1)}s`
  return `${Math.round(seconds)}s`
}

/**
 * token 计数的 k 缩写（A5）：<1000 原样，≥1000 用一位小数的 k（2.4k / 20k）。
 * 整千且 <10000 时省略小数（20k 而非 20.0k）。
 */
export function formatTokenCount(value: number | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return ""
  if (value < 1000) return String(Math.round(value))
  const thousands = value / 1000
  // 一位小数：2.4k / 12.4k；整千直接整数：20k。
  if (!Number.isInteger(thousands)) return `${thousands.toFixed(1)}k`
  return `${thousands}k`
}

/**
 * A5 · 上下文提示行：`上下文 12% · 2.4k/20k`。
 * context 缺失（旧后端）返回空串；used_percent 优先，缺失时用 used/budget 推。
 */
export function formatContextUsage(
  context:
    | {
        used_tokens?: number
        budget_tokens?: number
        used_percent?: number
      }
    | undefined,
  language?: string,
): string {
  if (!context) return ""
  const used = context.used_tokens
  const budget = context.budget_tokens
  const percent =
    typeof context.used_percent === "number" && Number.isFinite(context.used_percent)
      ? context.used_percent
      : typeof used === "number" && typeof budget === "number" && budget > 0
        ? (used / budget) * 100
        : undefined
  if (percent === undefined && used === undefined) return ""
  const en = String(language ?? "zh-CN").toLowerCase().startsWith("en")
  const label = en ? "context" : "上下文"
  const percentText = percent === undefined ? "" : `${Math.round(percent)}%`
  const tokensText =
    used === undefined
      ? ""
      : budget === undefined
        ? formatTokenCount(used)
        : `${formatTokenCount(used)}/${formatTokenCount(budget)}`
  const tail = [percentText, tokensText].filter(Boolean).join(" · ")
  return tail ? `${label} ${tail}` : ""
}

/**
 * A4 · 超额 tips（zh/en 两套）。
 * 用 muted/warn 语气，不用报警红；文案提到 /compact 与 /new。
 */
export function overBudgetTip(language?: string): string {
  return String(language ?? "zh-CN").toLowerCase().startsWith("en")
    ? "Context near limit: run /compact to compress, or /new to start over"
    : "上下文接近上限：可用 /compact 压缩，或 /new 重新开始"
}

// ---------------------------------------------------------------------
// C3 · 动画帧（无依赖；2-3 帧循环，teardown 由调用方清定时器）
// ---------------------------------------------------------------------

const CURSOR_FRAMES = ["▌", "▍", " "] as const
const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"] as const

/** 流式正文末尾闪烁光标（2-3 帧循环）。 */
export function cursorFrame(tick: number): string {
  return CURSOR_FRAMES[Math.abs(tick) % CURSOR_FRAMES.length]
}

/** 等待首 token 时的 spinner。 */
export function spinnerFrame(tick: number): string {
  return SPINNER_FRAMES[Math.abs(tick) % SPINNER_FRAMES.length]
}

/** 等待首 token 的 spinner + 文案（C3）。 */
export function thinkingPlaceholder(tick: number, language?: string): string {
  const en = String(language ?? "zh-CN").toLowerCase().startsWith("en")
  return `${spinnerFrame(tick)} ${en ? "Thinking…" : "思考中"}`
}

// ---------------------------------------------------------------------
// 命令结果展示（/think /compact /history）
// ---------------------------------------------------------------------

const THINK_LEVEL_LABELS: Record<string, [string, string]> = {
  off: ["关闭", "off"],
  low: ["低", "low"],
  high: ["高", "high"],
  max: ["最大", "max"],
  auto: ["自动", "auto"],
}

/** /think 执行后回显当前档位。 */
export function formatThinkLevel(level: string | undefined, language?: string): string {
  const en = String(language ?? "zh-CN").toLowerCase().startsWith("en")
  const label = level ? THINK_LEVEL_LABELS[level]?.[en ? 1 : 0] ?? level : "—"
  return en ? `Thinking level: ${label}` : `思考档位：${label}`
}

/** /think unsupported 时的置灰说明（后端 reason 优先）。 */
export function formatThinkUnsupported(
  reason: string | undefined,
  language?: string,
): string {
  const en = String(language ?? "zh-CN").toLowerCase().startsWith("en")
  const fallback = en
    ? "This backend does not support /think"
    : "当前后端不支持 /think"
  return reason || fallback
}

/**
 * /compact 成功回显：`12.4k → 3.1k · 保留 8 轮`。
 * 缺失字段整段跳过，不编造数字。
 */
export function formatCompactSummary(
  data: {
    before_tokens?: number
    after_tokens?: number
    kept_turns?: number
  },
  language?: string,
): string {
  const en = String(language ?? "zh-CN").toLowerCase().startsWith("en")
  const parts: string[] = []
  if (typeof data.before_tokens === "number" && typeof data.after_tokens === "number") {
    parts.push(
      `${formatTokenCount(data.before_tokens)} → ${formatTokenCount(data.after_tokens)}`,
    )
  }
  if (typeof data.kept_turns === "number") {
    parts.push(en ? `kept ${data.kept_turns} turns` : `保留 ${data.kept_turns} 轮`)
  }
  if (parts.length === 0) return en ? "Context compressed" : "上下文已压缩"
  return parts.join(" · ")
}

/** /compact 失败文案：强调「原历史未变」。 */
export function formatCompactFailure(
  error: string | undefined,
  language?: string,
): string {
  const en = String(language ?? "zh-CN").toLowerCase().startsWith("en")
  const detail = error || (en ? "compact failed" : "压缩失败")
  return en
    ? `${detail} — original history is unchanged`
    : `${detail} — 原历史未变`
}

/**
 * /history 对话消息列表：行首序号 + 角色标签 + 截断正文。
 * 与 /history --runs 的审查列表（对话框 select）视觉区分：这是纯文本序号列表。
 */
export function formatChatHistoryLines(
  messages: Array<{ role: string; content: string }>,
  options: { maxLines?: number; contentWidth?: number; language?: string } = {},
): string[] {
  const maxLines = options.maxLines ?? 40
  const contentWidth = options.contentWidth ?? 56
  const en = String(options.language ?? "zh-CN").toLowerCase().startsWith("en")
  const label = (role: string) =>
    role === "user" ? (en ? "user" : "用户") : en ? "assistant" : "助手"
  return messages.slice(0, maxLines).map((message, index) => {
    const body = message.content.replace(/\s+/g, " ").trim()
    const truncated =
      body.length > contentWidth ? `${body.slice(0, contentWidth - 1)}…` : body
    return `${String(index + 1).padStart(2, " ")}  [${label(message.role)}] ${truncated}`
  })
}
