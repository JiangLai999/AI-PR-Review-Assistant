export type BackendRequest = {
  id: string
  method: string
  params?: Record<string, unknown>
}

export type BackendEvent = {
  id?: string | null
  ok?: boolean
  event?: string
  result?: any
  error?: { code?: string; message?: string }
  [key: string]: unknown
}

// ---------------------------------------------------------------------
// Chat 契约 v1（前端消费侧）——后端可能后落地，字段缺失时必须不崩溃、不显示。
// ---------------------------------------------------------------------

/** assistant.finished.usage */
export type AssistantUsage = {
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
}

/** assistant.finished.context */
export type AssistantContext = {
  used_tokens?: number
  budget_tokens?: number
  used_percent?: number
  trimmed_messages?: number
  compacted?: boolean
}

export type AssistantWarning = "over_budget"

/** assistant.finished 里本批新增的可选元数据（全部允许缺失）。 */
export type AssistantFinishMeta = {
  durationSeconds?: number
  usage?: AssistantUsage
  context?: AssistantContext
  reasoning?: string
  warning?: AssistantWarning
}

const asFiniteNumber = (value: unknown): number | undefined =>
  typeof value === "number" && Number.isFinite(value) ? value : undefined

const asOptionalString = (value: unknown): string | undefined =>
  typeof value === "string" && value.length > 0 ? value : undefined

/** 契约里的 token 计数字段：有限数字才收，null/字符串/NaN 一律丢弃。 */
function parseUsage(raw: unknown): AssistantUsage | undefined {
  if (!raw || typeof raw !== "object") return undefined
  const record = raw as Record<string, unknown>
  const usage: AssistantUsage = {
    prompt_tokens: asFiniteNumber(record.prompt_tokens),
    completion_tokens: asFiniteNumber(record.completion_tokens),
    total_tokens: asFiniteNumber(record.total_tokens),
  }
  if (
    usage.prompt_tokens === undefined &&
    usage.completion_tokens === undefined &&
    usage.total_tokens === undefined
  ) {
    return undefined
  }
  return usage
}

function parseContext(raw: unknown): AssistantContext | undefined {
  if (!raw || typeof raw !== "object") return undefined
  const record = raw as Record<string, unknown>
  const context: AssistantContext = {
    used_tokens: asFiniteNumber(record.used_tokens),
    budget_tokens: asFiniteNumber(record.budget_tokens),
    used_percent: asFiniteNumber(record.used_percent),
    trimmed_messages: asFiniteNumber(record.trimmed_messages),
    compacted: typeof record.compacted === "boolean" ? record.compacted : undefined,
  }
  if (
    context.used_tokens === undefined &&
    context.budget_tokens === undefined &&
    context.used_percent === undefined &&
    context.trimmed_messages === undefined &&
    context.compacted === undefined
  ) {
    return undefined
  }
  return context
}

/**
 * 从 `assistant.finished` 事件解析本批新增元数据。
 * 字段缺席（旧后端）时对应键为 undefined，调用方直接不显示。
 */
export function parseAssistantFinishMeta(event: BackendEvent): AssistantFinishMeta {
  const warningRaw = event.warning
  return {
    durationSeconds: asFiniteNumber(event.duration_seconds),
    usage: parseUsage(event.usage),
    context: parseContext(event.context),
    reasoning: asOptionalString(event.reasoning),
    warning: warningRaw === "over_budget" ? "over_budget" : undefined,
  }
}

/**
 * `assistant.reasoning_delta`：思考流与正文流分开累积。
 * 非 reasoning 事件或缺 text 时返回 undefined。
 */
export function parseReasoningDelta(event: BackendEvent): string | undefined {
  if (event.event !== "assistant.reasoning_delta") return undefined
  return typeof event.text === "string" ? event.text : undefined
}

// ---------------------------------------------------------------------
// 命令返回 kind: "compact" | "think"（契约 v1）
// ---------------------------------------------------------------------

export type ThinkLevel = "off" | "low" | "high" | "max" | "auto"

export type ThinkCommandResult = {
  kind: "think"
  /** applied = 已切换；unsupported = 后端不支持，reason 给出置灰说明。 */
  state?: "applied" | "unsupported" | string
  level?: ThinkLevel | string
  reason?: string
}

export type CompactCommandResult = {
  kind: "compact"
  ok?: boolean
  before_tokens?: number
  after_tokens?: number
  kept_turns?: number
  error?: string
  message?: string
}

const THINK_LEVELS: readonly string[] = ["off", "low", "high", "max", "auto"]

/** /think 返回：level 只认契约枚举，其它原样保留在 level 字符串里供展示。 */
export function parseThinkCommandResult(result: unknown): ThinkCommandResult | undefined {
  if (!result || typeof result !== "object") return undefined
  const record = result as Record<string, unknown>
  if (record.kind !== "think") return undefined
  const levelRaw = typeof record.level === "string" ? record.level : undefined
  return {
    kind: "think",
    state: typeof record.state === "string" ? record.state : undefined,
    level: levelRaw && THINK_LEVELS.includes(levelRaw) ? (levelRaw as ThinkLevel) : levelRaw,
    reason: asOptionalString(record.reason),
  }
}

/** /compact 返回：tokens / kept_turns 缺失时不显示对应段。 */
export function parseCompactCommandResult(result: unknown): CompactCommandResult | undefined {
  if (!result || typeof result !== "object") return undefined
  const record = result as Record<string, unknown>
  if (record.kind !== "compact") return undefined
  return {
    kind: "compact",
    ok: typeof record.ok === "boolean" ? record.ok : undefined,
    before_tokens: asFiniteNumber(record.before_tokens),
    after_tokens: asFiniteNumber(record.after_tokens),
    kept_turns: asFiniteNumber(record.kept_turns),
    error: asOptionalString(record.error),
    message: asOptionalString(record.message),
  }
}

/** Drop late deltas from a cancelled turn, a previous session, or a restarted backend. */
export function isCurrentAssistantEvent(
  event: BackendEvent,
  sessionId: string | undefined,
  requestId: string | undefined,
): boolean {
  return Boolean(
    event.event?.startsWith("assistant.") &&
    sessionId &&
    requestId &&
    event.session_id === sessionId &&
    event.request_id === requestId,
  )
}

/**
 * Drop events that belong to another session (e.g. a review still running on a
 * session the user has already left).
 *
 * Events without a session id are kept: absence is not evidence of a foreign
 * session, and dropping them would silently hide global notifications.
 */
export function isForeignSessionEvent(event: BackendEvent, sessionId: string | undefined): boolean {
  const eventSession = typeof event.session_id === "string" ? event.session_id : ""
  return Boolean(eventSession && eventSession !== sessionId)
}
