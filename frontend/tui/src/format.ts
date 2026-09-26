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
 * `/think` 的 **transparent** 态（中转/自定义端点，C 组）：
 * 档位已写入请求，但只是把 `reasoning_effort` 透传给上游——是否生效取决于上游服务。
 * 展示档位 + 后端 reason（缺省时给通用提示），避免用户误以为一定生效。
 */
export function formatThinkTransparent(
  level: string | undefined,
  reason: string | undefined,
  language?: string,
): string {
  const en = String(language ?? "zh-CN").toLowerCase().startsWith("en")
  const base = formatThinkLevel(level, language)
  const note =
    reason ||
    (en
      ? "Whether it takes effect depends on the upstream provider"
      : "是否生效取决于上游服务")
  return `${base} · ${note}`
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
    replaced_messages?: number
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
  if (typeof data.replaced_messages === "number" && data.replaced_messages > 0) {
    parts.push(
      en
        ? `${data.replaced_messages} messages summarized`
        : `已压缩 ${data.replaced_messages} 条`,
    )
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

// ---------------------------------------------------------------------
// C2 · 长代码块折叠（docs/mimo-chat-render-c.md / mimo-chat-render-c3.md）
// 纯函数，便于单测；app.tsx 负责状态与 JSX 接线。
// ---------------------------------------------------------------------

/** >15 行的围栏代码块默认折叠。 */
export const CODE_FOLD_LINE_THRESHOLD = 15

/** 角标文案（zh 固定，与 en UI 提示分离；用户指定文案不变）。 */
export function codeFoldBadge(lineCount: number, expanded: boolean): string {
  return expanded ? "▾ 收起" : `▸ 展开（共 ${lineCount} 行）`
}

/** Fold state key: message id + code-block index inside that message. */
export function codeFoldStateKey(messageKey: string, blockIndex: number): string {
  return `${messageKey}#${blockIndex}`
}

export type FoldableCodeBlock = { index: number; lineCount: number }

/**
 * 围栏代码块扫描：`index` 是消息内第几个代码块（从 0 起，短块也计数），
 * `lineCount` 是块体行数。折叠状态按「消息 id + 块序号」对齐。
 */
export function foldableCodeBlocks(content: string): FoldableCodeBlock[] {
  const lines = content.split("\n")
  const blocks: FoldableCodeBlock[] = []
  let blockIndex = 0
  let i = 0
  while (i < lines.length) {
    if (!/^```/.test(lines[i])) {
      i += 1
      continue
    }
    const body: string[] = []
    let j = i + 1
    while (j < lines.length && !/^```[ \t]*$/.test(lines[j])) {
      body.push(lines[j])
      j += 1
    }
    if (body.length > CODE_FOLD_LINE_THRESHOLD) {
      blocks.push({ index: blockIndex, lineCount: body.length })
    }
    blockIndex += 1
    i = j < lines.length ? j + 1 : lines.length
  }
  return blocks
}

/**
 * 按展开状态重写 markdown：长块截到阈值行并在块内末尾加角标。
 * `isExpanded` 收到块序号（与 `foldableCodeBlocks` 的 index 一致）。
 */
export function foldMarkdownCodeBlocks(
  content: string,
  isExpanded: (blockIndex: number) => boolean,
): string {
  const lines = content.split("\n")
  const out: string[] = []
  let blockIndex = 0
  let i = 0
  while (i < lines.length) {
    const open = lines[i]
    if (!/^```/.test(open)) {
      out.push(open)
      i += 1
      continue
    }
    const body: string[] = []
    let j = i + 1
    while (j < lines.length && !/^```[ \t]*$/.test(lines[j])) {
      body.push(lines[j])
      j += 1
    }
    const closed = j < lines.length
    const idx = blockIndex
    blockIndex += 1
    if (body.length > CODE_FOLD_LINE_THRESHOLD) {
      const expanded = isExpanded(idx)
      const visible = expanded ? body : body.slice(0, CODE_FOLD_LINE_THRESHOLD)
      out.push(open, ...visible, codeFoldBadge(body.length, expanded))
    } else {
      out.push(open, ...body)
    }
    if (closed) out.push(lines[j])
    i = closed ? j + 1 : lines.length
  }
  return out.join("\n")
}

// ---------------------------------------------------------------------
// C3 批次 · 角标可点击：markdown 分段 + 块尾角标位置
// 把可折叠代码块的角标从 markdown 内容中拆出，渲染为独立的
// `<text onMouseDown>` 元素（方案 A）。`foldMarkdownCodeBlocks` 仍保留
// 纯字符串路径供兼容/对照，但 app.tsx 的聊天渲染改走本分段函数。
// ---------------------------------------------------------------------

export type MarkdownSegment =
  | { kind: "markdown"; content: string; foldable?: boolean }
  | {
      kind: "foldBadge"
      blockIndex: number
      lineCount: number
      expanded: boolean
    }

/**
 * 把 markdown 切成「正文段 + 角标位」序列：
 * - 可折叠长代码块 → 自成一段 markdown（截断/展开，**不含**角标，`foldable: true`），
 *   其后紧跟一个 `foldBadge` 段；调用方把 `foldBadge` 渲染成独立可点击 `<text>`。
 *   `foldable` 让 renderNode 去掉块尾 marginBottom，角标才能贴住块尾（方案 A）。
 * - 短块与其它内容留在 markdown 流里，不打断分段。
 * - 空段不会产生（首/尾/连续折叠块都能正确处理）。
 */
export function splitFoldableMarkdown(
  content: string,
  isExpanded: (blockIndex: number) => boolean,
): MarkdownSegment[] {
  const lines = content.split("\n")
  const segments: MarkdownSegment[] = []
  let buffer: string[] = []
  let blockIndex = 0
  let i = 0

  const flushMarkdown = () => {
    if (buffer.length > 0) {
      segments.push({ kind: "markdown", content: buffer.join("\n") })
      buffer = []
    }
  }

  while (i < lines.length) {
    const open = lines[i]
    if (!/^```/.test(open)) {
      buffer.push(open)
      i += 1
      continue
    }
    const body: string[] = []
    let j = i + 1
    while (j < lines.length && !/^```[ \t]*$/.test(lines[j])) {
      body.push(lines[j])
      j += 1
    }
    const closed = j < lines.length
    const idx = blockIndex
    blockIndex += 1
    if (body.length > CODE_FOLD_LINE_THRESHOLD) {
      flushMarkdown()
      const expanded = isExpanded(idx)
      const visible = expanded ? body : body.slice(0, CODE_FOLD_LINE_THRESHOLD)
      const blockLines = [open, ...visible]
      if (closed) blockLines.push(lines[j])
      segments.push({ kind: "markdown", content: blockLines.join("\n"), foldable: true })
      segments.push({
        kind: "foldBadge",
        blockIndex: idx,
        lineCount: body.length,
        expanded,
      })
    } else {
      buffer.push(open, ...body)
      if (closed) buffer.push(lines[j])
    }
    i = closed ? j + 1 : lines.length
  }
  flushMarkdown()
  return segments
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
// ---------------------------------------------------------------------
// B2/B3 模型规格展示（docs/mimo-config-wizard-ui.md）
// 纯函数，便于单测；app.tsx 只负责取数与排版。
// ---------------------------------------------------------------------

/**
 * source 徽标（任务要求的三态 + unknown）：
 *   models.dev → `models.dev ✓`；cache → `缓存`/`cache`；
 *   builtin → `内置`/`builtin`；unknown/缺失 → `未知`/`unknown`。
 */
export function formatSourceBadge(source: string | undefined, language?: string): string {
  const en = String(language ?? "zh-CN").toLowerCase().startsWith("en")
  const value = String(source ?? "").trim().toLowerCase()
  if (value === "models.dev") return "models.dev ✓"
  if (value === "cache") return en ? "cache" : "缓存"
  if (value === "builtin") return en ? "builtin" : "内置"
  return en ? "unknown" : "未知"
}

/** `needs_verification` 提示：两个数字都摆出来，不覆盖用户值（§2.8 硬规则 1）。 */
export function formatNeedsVerification(
  block: { context_window?: number; catalog?: { context_window?: number; max_output?: number } | null; max_output?: number },
  language?: string,
): string {
  const en = String(language ?? "zh-CN").toLowerCase().startsWith("en")
  const current = block.context_window
  const catalog = block.catalog?.context_window
  if (typeof current !== "number" || typeof catalog !== "number") {
    return en ? "Differs from models.dev (values unavailable)" : "与官方数据不一致（数值不可用）"
  }
  return en
    ? `Differs from models.dev: current ${current} / models.dev ${catalog}`
    : `与官方数据不一致：当前 ${current} / models.dev ${catalog}`
}

/** 编辑边界提示：`范围 1024–10000000`。缺边界返回空串。 */
export function formatSpecBoundHint(
  bounds: [number, number] | undefined,
  language?: string,
): string {
  if (!bounds) return ""
  const en = String(language ?? "zh-CN").toLowerCase().startsWith("en")
  return en ? `range ${bounds[0]}–${bounds[1]}` : `范围 ${bounds[0]}–${bounds[1]}`
}

/**
 * 一行规格摘要：`provider · model`；缺字段时不显示（兼容旧后端）。
 * `provider`/`model` 都缺失返回空串。
 */
export function formatModelHeadline(
  block: { provider?: string; model?: string },
  language?: string,
): string {
  const provider = String(block.provider ?? "").trim()
  const model = String(block.model ?? "").trim()
  if (!provider && !model) return ""
  return [provider, model].filter(Boolean).join(" · ")
}

/** 数字行：`上下文长度  1000000`。值缺失返回空串（调用方整行不显示）。 */
export function formatSpecValueLine(
  label: string,
  value: number | undefined,
  hint?: string,
): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return ""
  return hint ? `${label}  ${value}  (${hint})` : `${label}  ${value}`
}

/** `config.catalog.refresh` 状态文案（刷新中/成功/失败）。 */
export function formatCatalogRefreshStatus(
  state: "idle" | "refreshing" | "success" | "error",
  detail?: string,
  language?: string,
): string {
  const en = String(language ?? "zh-CN").toLowerCase().startsWith("en")
  if (state === "refreshing") return en ? "Refreshing catalog…" : "目录刷新中…"
  if (state === "success") {
    const badge = detail ? ` · ${detail}` : ""
    return en ? `Catalog refreshed${badge}` : `目录已刷新${badge}`
  }
  if (state === "error") {
    const reason = detail ? ` · ${detail}` : ""
    return en
      ? `Catalog refresh failed, previous values kept${reason}`
      : `目录刷新失败，已保留旧值${reason}`
  }
  return ""
}

// ---------------------------------------------------------------------
// chat 上下文预算来源展示（docs/mimo-config-wizard-fix2.md §4）
// ---------------------------------------------------------------------

/** 预算来源标签（config / model_spec / fallback 三态）。 */
const BUDGET_SOURCE_LABELS: Record<string, [string, string]> = {
  config: ["配置", "config"],
  model_spec: ["模型规格", "model spec"],
  fallback: ["兜底", "fallback"],
}

/**
 * 「上下文预算 N（来源：…）」一行；缺字段时返回空串（兼容旧后端）。
 *
 * `/context` 结果与配置助手规格屏共用同一条格式化规则。
 */
export function formatBudgetSource(
  budget: number | undefined,
  source: string | undefined,
  language?: string,
): string {
  if (typeof budget !== "number" || !Number.isFinite(budget) || budget < 0) return ""
  const key = String(source ?? "").trim()
  if (!key) return ""
  const en = String(language ?? "zh-CN").toLowerCase().startsWith("en")
  const label = BUDGET_SOURCE_LABELS[key]?.[en ? 1 : 0] ?? key
  return en
    ? `Context budget ${budget} (source: ${label})`
    : `上下文预算 ${budget}（来源：${label}）`
}

/**
 * 中转站五项表单的行标签（双语）。
 * 顺序固定：base_url / api_key / model / context_window / max_output。
 */
export function customEndpointFieldLabels(language?: string): Array<{
  key: "base_url" | "api_key" | "model" | "context_window" | "max_output"
  label: string
}> {
  const en = String(language ?? "zh-CN").toLowerCase().startsWith("en")
  return en
    ? [
        { key: "base_url", label: "Base URL" },
        { key: "api_key", label: "API Key" },
        { key: "model", label: "Model" },
        { key: "context_window", label: "Context window" },
        { key: "max_output", label: "Max output" },
      ]
    : [
        { key: "base_url", label: "Base URL" },
        { key: "api_key", label: "API Key" },
        { key: "model", label: "模型名" },
        { key: "context_window", label: "上下文长度" },
        { key: "max_output", label: "最大输出" },
      ]
}

// ---------------------------------------------------------------------
// review 思考档位展示（docs/mimo-review-effort-ui.md）
// 纯函数；app.tsx 只负责取数与排版。
// ---------------------------------------------------------------------

/**
 * 后端双语 label 取一侧：`"关闭 / Off（不思考，默认）"` → 中文侧 / 英文侧。
 *
 * 与 `setup-repo-context.ts` 的 `bilingualLabel` 同口径（那个文件不在本任务 write_scope，
 * 这里重列一份）；没有 `" / "` 分隔符时原样返回，绝不拼出空串。
 */
export function reviewEffortBilingualLabel(label: string, language?: string): string {
  const parts = String(label ?? "").split(" / ")
  if (parts.length < 2) return String(label ?? "")
  const en = String(language ?? "zh-CN").toLowerCase().startsWith("en")
  return (en ? parts[parts.length - 1] : parts[0]).trim()
}

/**
 * 档位的成本提示（docs/review-reasoning-assessment.md §0.3 真机实测，max 档）。
 *
 * `off` = 与现状相同（基线）；`low/high/max` = 思考会放大输出 tokens 与耗时；
 * `auto` = 不干预，由供应商默认决定。数字取 max 档实测（约 3.6× 输出 tokens、
 * 2.9× 单文件耗时），低档实际介于基线与 max 之间——如实标注测量条件，不编造分档数字。
 */
export function formatReviewEffortCost(level: string | undefined, language?: string): string {
  const en = String(language ?? "zh-CN").toLowerCase().startsWith("en")
  const key = String(level ?? "").trim().toLowerCase()
  if (key === "off") return en ? "same as today (baseline)" : "与现状相同（基线）"
  if (key === "low" || key === "high" || key === "max") {
    return en
      ? "≈×3.6 output tokens, ≈×2.9 latency (measured at max)"
      : "输出 tokens 约 ×3.6、耗时约 ×2.9（真机实测，max 档）"
  }
  if (key === "auto") {
    return en ? "up to the provider default" : "不干预，由供应商默认决定"
  }
  return ""
}

/**
 * review 档位被置灰时的说明（后端 `reason` 优先，缺省给通用文案）。
 *
 * 只在后端显式给出 `state === "unsupported"` 时调用；没有字段就不置灰（不推导能力）。
 */
export function formatReviewEffortDisabled(
  reason: string | undefined,
  language?: string,
): string {
  const en = String(language ?? "zh-CN").toLowerCase().startsWith("en")
  const fallback = en
    ? "The review-slot provider does not accept thinking parameters; the level will not take effect"
    : "审查槽供应商不接受思考参数，档位不会生效"
  return reason || fallback
}

/**
 * 确认页的 review 档位行：`off` 显示基线说明，思考档显示成本短语。
 * 裸值不在确认页出现——用户要看到的是"代价"，不是枚举名。
 */
export function formatReviewEffortSummary(level: string | undefined, language?: string): string {
  const en = String(language ?? "zh-CN").toLowerCase().startsWith("en")
  const key = String(level ?? "").trim().toLowerCase()
  const name = key || "off"
  const cost = formatReviewEffortCost(name, language)
  return cost ? `${name} · ${cost}` : name
}
