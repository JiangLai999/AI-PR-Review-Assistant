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
  /** 本轮实际模型名（按轮下发；用户中途 /model 切换后历史消息各归各）。 */
  model?: string
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
    model: asOptionalString(event.model),
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
  /**
   * set / applied = 已切换（后端现用 `set`，历史契约写作 `applied`，两者都放行）；
   * unsupported = 后端不支持，reason 给出置灰说明。
   */
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
  replaced_messages?: number
  summary_chars?: number
  error?: string
  message?: string
}

const THINK_LEVELS: readonly string[] = ["off", "low", "high", "max", "auto"]

/**
 * 命令结果是否由**专用渲染器**接管（`/think`、`/compact`）。
 *
 * 通用回显（直接显示 `result.text`）遇到它们必须跳过，否则同一条命令会显示两遍——
 * 实测 `/think max` 曾输出「思考档位已设置为 max。」+「思考档位：最大」两行。
 * 后端 `text` 继续保留给 CLI 等其它消费方，这里只约束 TUI 不重复。
 */
export function hasDedicatedCommandRenderer(result: unknown): boolean {
  return Boolean(parseThinkCommandResult(result) || parseCompactCommandResult(result))
}

/** /think 返回：level 只认契约枚举，其它原样保留在 level 字符串里供展示。 */
export function parseThinkCommandResult(result: unknown): ThinkCommandResult | undefined {
  if (!result || typeof result !== "object") return undefined
  const record = result as Record<string, unknown>
  if (record.kind !== "think") return undefined
  // 后端返回 `effort`（jsonl_server /think）；旧契约写作 `level`。
  // 先读 effort，再回退 level，避免档位回显为空。
  const levelRaw =
    typeof record.effort === "string"
      ? record.effort
      : typeof record.level === "string"
        ? record.level
        : undefined
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
    replaced_messages: asFiniteNumber(record.replaced_messages),
    summary_chars: asFiniteNumber(record.summary_chars),
    error: asOptionalString(record.error),
    message: asOptionalString(record.message),
  }
}

/**
 * `/context` 与 `config.snapshot` 的预算字段（docs/claude-backend-followup.md §4）。
 * 缺字段时对应键为 undefined（兼容旧后端），调用方直接不显示。
 */
export type ContextBudgetInfo = {
  budget_tokens?: number
  budget_source?: string
}

/** 从任意结果对象提取预算字段（/context 的 `token_budget`/`budget_source` 等）。 */
export function parseContextBudgetInfo(raw: unknown): ContextBudgetInfo {
  if (!raw || typeof raw !== "object") return {}
  const record = raw as Record<string, unknown>
  return {
    budget_tokens: asFiniteNumber(record.token_budget) ?? asFiniteNumber(record.budget_tokens),
    budget_source: asOptionalString(record.budget_source),
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
// ---------------------------------------------------------------------
// B2/B3 模型规格契约（docs/b2b3-wiring-design.md §2.2/§2.6/§2.8）
// 后端可能未落地或部分落地，所有字段允许缺失；解析器负责兜底，不抛错。
// ---------------------------------------------------------------------

/** `catalog` 命中块（§2.2）：目录原值 + 来源 + 抓取时间。 */
export type ModelSpecCatalog = {
  context_window?: number
  max_output?: number
  source?: string
  fetched_at?: string
}

/** `bounds` 编辑边界（§2.2）：`[min, max]`。 */
export type ModelSpecBounds = {
  context_window?: [number, number]
  max_output?: [number, number]
}

/** `catalog_state` 目录状态（§2.2）。 */
export type CatalogState = {
  enabled?: boolean
  source?: string
  reason?: string
  fetched_at?: string
}

/**
 * 一个槽位的模型规格块（§2.2/§2.8）：`config.options.model` / `config.snapshot.model_spec`
 * / `model.status.model_spec` 三出口同键同形。
 */
export type ModelSpecBlock = {
  provider?: string
  model?: string
  /** models.dev | cache | builtin | unknown */
  source?: string
  context_window?: number
  max_output?: number
  reasoning?: string | null
  reasoning_controls?: Array<Record<string, unknown>>
  needs_verification?: boolean
  endpoint_matches_preset?: boolean
  catalog?: ModelSpecCatalog | null
  preset?: { context_window?: number; max_output?: number } | null
  bounds?: ModelSpecBounds
  catalog_state?: CatalogState
  slots?: { remote?: ModelSpecBlock; local?: ModelSpecBlock }
}

/** `config.options.model`：顶层描述活跃槽，`slots` 给每槽明细（§2.2）。 */
export type ModelSpecOptions = ModelSpecBlock

/** `config.options.custom_endpoint`（§2.6）：中转站读出口。 */
export type CustomEndpointOptions = {
  name?: string
  display_name?: string
  base_url?: string
  api_format?: string
  default_model?: string
  api_key_configured?: boolean
  models?: string[]
  context_window?: number
  max_output?: number
  source?: string
  needs_verification?: boolean
}

const asOptionalNumber = (value: unknown): number | undefined =>
  typeof value === "number" && Number.isFinite(value) ? value : undefined

function parseCatalogView(raw: unknown): ModelSpecCatalog | null | undefined {
  if (raw === null) return null
  if (!raw || typeof raw !== "object") return undefined
  const record = raw as Record<string, unknown>
  return {
    context_window: asOptionalNumber(record.context_window),
    max_output: asOptionalNumber(record.max_output),
    source: typeof record.source === "string" ? record.source : undefined,
    fetched_at: typeof record.fetched_at === "string" ? record.fetched_at : undefined,
  }
}

function parseBoundsPair(raw: unknown): [number, number] | undefined {
  if (!Array.isArray(raw) || raw.length < 2) return undefined
  const lo = asOptionalNumber(raw[0])
  const hi = asOptionalNumber(raw[1])
  return lo !== undefined && hi !== undefined ? [lo, hi] : undefined
}

function parseBounds(raw: unknown): ModelSpecBounds | undefined {
  if (!raw || typeof raw !== "object") return undefined
  const record = raw as Record<string, unknown>
  const context = parseBoundsPair(record.context_window)
  const output = parseBoundsPair(record.max_output)
  if (!context && !output) return undefined
  return { context_window: context, max_output: output }
}

function parseCatalogState(raw: unknown): CatalogState | undefined {
  if (!raw || typeof raw !== "object") return undefined
  const record = raw as Record<string, unknown>
  return {
    enabled: typeof record.enabled === "boolean" ? record.enabled : undefined,
    source: typeof record.source === "string" ? record.source : undefined,
    reason: typeof record.reason === "string" ? record.reason : undefined,
    fetched_at: typeof record.fetched_at === "string" ? record.fetched_at : undefined,
  }
}

function parsePresetPair(
  raw: unknown,
): { context_window?: number; max_output?: number } | null | undefined {
  if (raw === null) return null
  if (!raw || typeof raw !== "object") return undefined
  const record = raw as Record<string, unknown>
  return {
    context_window: asOptionalNumber(record.context_window),
    max_output: asOptionalNumber(record.max_output),
  }
}

/**
 * 解析一个规格块。字段缺失（旧后端）时对应键为 undefined，调用方直接不显示。
 * `slots` 递归解析 remote/local 两个子块。
 */
export function parseModelSpecBlock(raw: unknown): ModelSpecBlock | undefined {
  if (!raw || typeof raw !== "object") return undefined
  const record = raw as Record<string, unknown>
  const block: ModelSpecBlock = {
    provider: asOptionalString(record.provider),
    model: asOptionalString(record.model),
    source: asOptionalString(record.source),
    context_window: asOptionalNumber(record.context_window),
    max_output: asOptionalNumber(record.max_output),
    reasoning: typeof record.reasoning === "string" ? record.reasoning : undefined,
    needs_verification:
      typeof record.needs_verification === "boolean" ? record.needs_verification : undefined,
    endpoint_matches_preset:
      typeof record.endpoint_matches_preset === "boolean"
        ? record.endpoint_matches_preset
        : undefined,
    catalog: parseCatalogView(record.catalog),
    preset: parsePresetPair(record.preset),
    bounds: parseBounds(record.bounds),
    catalog_state: parseCatalogState(record.catalog_state),
  }
  if (Array.isArray(record.reasoning_controls)) {
    block.reasoning_controls = record.reasoning_controls.filter(
      (item): item is Record<string, unknown> => Boolean(item) && typeof item === "object",
    )
  }
  if (record.slots && typeof record.slots === "object") {
    const slots = record.slots as Record<string, unknown>
    const remote = parseModelSpecBlock(slots.remote)
    const local = parseModelSpecBlock(slots.local)
    if (remote || local) block.slots = { remote, local }
  }
  return block
}

/** 解析 `config.options.custom_endpoint`（§2.6）。 */
export function parseCustomEndpointOptions(raw: unknown): CustomEndpointOptions | undefined {
  if (!raw || typeof raw !== "object") return undefined
  const record = raw as Record<string, unknown>
  return {
    name: asOptionalString(record.name),
    display_name: asOptionalString(record.display_name),
    base_url: typeof record.base_url === "string" ? record.base_url : undefined,
    api_format: asOptionalString(record.api_format),
    default_model: asOptionalString(record.default_model),
    api_key_configured:
      typeof record.api_key_configured === "boolean" ? record.api_key_configured : undefined,
    models: Array.isArray(record.models)
      ? record.models.filter((item): item is string => typeof item === "string")
      : undefined,
    context_window: asOptionalNumber(record.context_window),
    max_output: asOptionalNumber(record.max_output),
    source: asOptionalString(record.source),
    needs_verification:
      typeof record.needs_verification === "boolean" ? record.needs_verification : undefined,
  }
}

/**
 * `config.catalog.refresh` 返回 `{model: ModelSpecOptions}`（§2.1）。
 * 解析失败返回 undefined，调用方保留旧值。
 */
export function parseCatalogRefreshResult(raw: unknown): ModelSpecOptions | undefined {
  if (!raw || typeof raw !== "object") return undefined
  const record = raw as Record<string, unknown>
  return parseModelSpecBlock(record.model)
}

// ---------------------------------------------------------------------
// review 思考档位（docs/mimo-review-effort-ui.md）
// `config.options.review_reasoning_effort` / `config.setup` / `model.status` 三出口同键同形。
// ---------------------------------------------------------------------

/** review 档位取值（= chat 词表 `REVIEW_REASONING_EFFORTS`，默认 `off`）。 */
export type ReviewEffortLevel = "off" | "low" | "high" | "max" | "auto"

/** 选项单项（后端 `REVIEW_REASONING_LABELS` 的 value + 双语 label）。 */
export type ReviewEffortOption = {
  value: string
  label: string
}

/**
 * `config.options.review_reasoning_effort` 的形状（`_review_reasoning_options`）。
 *
 * `state` / `reason` **仅在** review 槽供应商不注入思考参数时出现（`unsupported`）；
 * 正常注入（`set` / `transparent` 且无 delivery block）时没有这两个键——
 * 前端只在看到 `state === "unsupported"` 时置灰，绝不自行推导供应商能力。
 */
export type ReviewReasoningOptions = {
  value?: string
  options?: ReviewEffortOption[]
  state?: string
  reason?: string
}

/**
 * 解析 `config.options.review_reasoning_effort` / `model.status.review_reasoning_effort`。
 *
 * 旧后端缺这一块时返回 undefined（调用方不显示该屏），字段缺失时对应键为 undefined。
 */
export function parseReviewReasoningOptions(raw: unknown): ReviewReasoningOptions | undefined {
  if (!raw || typeof raw !== "object") return undefined
  const record = raw as Record<string, unknown>
  const options: ReviewEffortOption[] = Array.isArray(record.options)
    ? record.options.flatMap((item): ReviewEffortOption[] => {
        if (!item || typeof item !== "object") return []
        const entry = item as Record<string, unknown>
        const value = asOptionalString(entry.value)
        if (!value) return []
        return [{ value, label: typeof entry.label === "string" ? entry.label : value }]
      })
    : []
  return {
    value: asOptionalString(record.value),
    options,
    state: asOptionalString(record.state),
    reason: asOptionalString(record.reason),
  }
}
