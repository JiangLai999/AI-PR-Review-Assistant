/**
 * CHAT/REVIEW 双槽路由在配置助手里的前端投影（docs/dual-model-roles-plan.md §4/§5.4）。
 *
 * 槽位的唯一推导点是后端 `jsonl_server.JsonlBackend._routing_snapshot()`；前端不得由
 * `hybrid_strategy` 反推。这里只做三件事：
 *
 *   1. 把 `config.options` 的模型名（`current.remote_model` / `current.local_model`）与
 *      `routing` 快照整理成细化页要渲染的两个方框（槽别名 + 实际模型名，不硬编码模型）；
 *   2. 组装 `config.setup` 载荷里的槽位字段：**只有 `runtime_profile="custom"` 才附带**
 *      `chat_slot` / `review_slot`，其它预设保持旧载荷（后端 preset 分支会清空槽位，
 *      见 `_clear_route_slots`）；
 *   3. 生成确认页的三行摘要与状态栏的 `CHAT x · REVIEW y` 文案。
 *
 * 语言：`ui_language` 以 `en-US` 开头走英文，其余一律中文，与 app.tsx 的 `isEn` 一致。
 */

export type RouteSlotValue = "remote" | "local" | "hybrid"

/** `routing.chat` / `routing.review` 的形状（方案 §5.4）。 */
export type RoutingSlotSnapshot = {
  slot?: string
  label?: string
  model?: string
}

/** `config.snapshot` / `config.options` / `model.status` 共用的 `routing` 块。 */
export type RoutingSnapshot = {
  profile?: string
  chat?: RoutingSlotSnapshot
  review?: RoutingSlotSnapshot
}

/** `config.options.runtime_profiles` 的单项（后端只给 value + 中文 label）。 */
export type SetupPreset = {
  value: string
  label?: string
}

/** 两个槽各自指向的模型名，来自 `config.options.current`。 */
export type SlotModelNames = {
  remote?: string
  local?: string
}

export type RouteSelection = {
  chat: RouteSlotValue
  review: RouteSlotValue
}

export type RouteChoice = {
  value: RouteSlotValue
  /** 槽别名（云端 / 本地 / 混合）。 */
  label: string
  /** 该槽当前指向的模型名；混合槽没有单一模型，写分流说明。 */
  detail: string
}

export type RouteBox = {
  key: "chat" | "review"
  title: string
  choices: RouteChoice[]
}

/** 聊天槽只有两个值——`CHAT_SLOT_VALUES`（config.py 是同一个字面量集合）。 */
export const CHAT_SLOT_VALUES: RouteSlotValue[] = ["remote", "local"]
/** 审查槽多一个 hybrid（`REVIEW_SLOT_VALUES`）。 */
export const REVIEW_SLOT_VALUES: RouteSlotValue[] = ["remote", "local", "hybrid"]

/**
 * 槽别名。中文与后端 `ROUTE_SLOT_LABELS` 逐字一致；`config.options` 目前只返回
 * **当前生效**槽位的中文 label，未选中的槽没有别名来源，所以整张表留在这里。
 */
const SLOT_LABELS: Record<RouteSlotValue, { zh: string; en: string }> = {
  remote: { zh: "云端", en: "Cloud" },
  local: { zh: "本地", en: "Local" },
  hybrid: { zh: "混合", en: "Hybrid" },
}

/** 运行模式预设的英文名（中文名以后端 `runtime_profiles[].label` 为准）。 */
const PRESET_LABELS: Record<string, { zh: string; en: string }> = {
  cloud: { zh: "云端", en: "Cloud" },
  local: { zh: "本地", en: "Local" },
  hybrid: { zh: "混合", en: "Hybrid" },
  custom: { zh: "自定义", en: "Custom" },
  // 旧值：后端读取时等价于"本地"（`_apply_setup` 仍接受以兼容旧载荷）。
  offline: { zh: "离线", en: "Offline" },
}

const PRESET_DESCRIPTIONS: Record<string, { zh: string; en: string }> = {
  cloud: { zh: "对话与审查都使用云端模型（质量优先）", en: "Chat and review both use the cloud model (quality first)" },
  local: { zh: "对话与审查都使用本地模型（离线可用）", en: "Chat and review both use the local model (works offline)" },
  hybrid: { zh: "对话用云端；审查按复杂度自动分流", en: "Chat on the cloud; review auto-routes by complexity" },
  custom: { zh: "分别指定「对话模型」和「审查模型」", en: "Pick the chat model and the review model separately" },
  offline: { zh: "离线优先：只使用本地运行时", en: "Offline first: local runtime only" },
}

const isEnglish = (language?: string): boolean =>
  String(language ?? "zh-CN").toLowerCase().startsWith("en")

/** 槽别名（中文与 `ROUTE_SLOT_LABELS` 一致）。 */
export function slotLabel(slot: string | undefined, language?: string): string {
  const entry = SLOT_LABELS[slot as RouteSlotValue]
  if (!entry) return String(slot ?? "")
  return isEnglish(language) ? entry.en : entry.zh
}

/**
 * 预设显示名：中文优先后端给的 label（后端是文案的 owner），没有才用本地表。
 */
export function presetLabel(preset: SetupPreset, language?: string): string {
  const table = PRESET_LABELS[preset.value]
  if (isEnglish(language)) return table?.en ?? preset.label ?? preset.value
  return preset.label ?? table?.zh ?? preset.value
}

/** 预设说明（后端 `runtime_profiles` 不含描述，这段文案由前端补）。 */
export function presetDescription(value: string, language?: string): string {
  const table = PRESET_DESCRIPTIONS[value]
  if (!table) return ""
  return isEnglish(language) ? table.en : table.zh
}

/**
 * 选中项的序号：显式槽位非法或缺失时回落到第一项，绝不越界。
 */
export function slotIndexOf(choices: readonly { value: string }[], slot?: string): number {
  const index = choices.findIndex((choice) => choice.value === slot)
  return index >= 0 ? index : 0
}

/**
 * 预设选中项的序号。
 *
 * 优先读 `routing.profile`：`runtime_profile` 回答"实际哪个槽在生效"（custom 会被
 * `_infer_runtime_profile` 折算成 cloud/local/hybrid），只有 `routing.profile` 才是
 * "用户上次选的是哪一档预设"，custom 配置重新打开助手必须能回到"自定义"。
 */
export function presetIndexOf(
  values: readonly string[],
  routingProfile?: string,
  runtimeProfile?: string,
): number {
  const index = values.indexOf(String(routingProfile ?? ""))
  if (index >= 0) return index
  const fallback = values.indexOf(String(runtimeProfile ?? ""))
  return fallback >= 0 ? fallback : 0
}

const notConfigured = (language?: string): string =>
  isEnglish(language) ? "not configured" : "未配置"

/** 一个槽位指向的模型名，未配置时给出可读占位而不是空白。 */
export function slotDetail(slot: string | undefined, models: SlotModelNames, language?: string): string {
  const remote = String(models.remote ?? "").trim()
  const local = String(models.local ?? "").trim()
  if (slot === "hybrid") {
    return isEnglish(language) ? "auto-route by complexity" : "按文件复杂度自动分流"
  }
  const model = slot === "local" ? local : remote
  return model || notConfigured(language)
}

/** 细化页两个方框（两屏都渲染同样的两个方框，焦点决定谁吃 ↑↓）。 */
export function routeBoxes(models: SlotModelNames, language?: string): RouteBox[] {
  const choice = (value: RouteSlotValue): RouteChoice => ({
    value,
    label: slotLabel(value, language),
    detail: slotDetail(value, models, language),
  })
  return [
    {
      key: "chat",
      title: isEnglish(language) ? "Chat model · used by the chat pane" : "对话模型 · 聊天区使用",
      choices: CHAT_SLOT_VALUES.map(choice),
    },
    {
      key: "review",
      title: isEnglish(language) ? "Review model · used by /review" : "审查模型 · /review 使用",
      choices: REVIEW_SLOT_VALUES.map(choice),
    },
  ]
}

/**
 * `config.setup` 的槽位字段。
 *
 * 只有 `custom` 附带两个槽位；其它预设返回空对象，载荷与改造前逐字节一致
 * （后端 preset 分支本来就会清空槽位，前端也不该发送会被忽略的键）。
 */
export function setupSlotFields(
  profile: string,
  selection: RouteSelection,
): Record<string, string> {
  if (String(profile).trim().toLowerCase() !== "custom") return {}
  return { chat_slot: selection.chat, review_slot: selection.review }
}

/**
 * 确认页的「对话模型 / 审查模型」两行（方案 §4.3 第 6 阶段：三行摘要）。
 *
 * custom 用细化页的实时选择；其它预设显示该预设**定义**的槽位。这只是在保存前
 * 预览"即将写入的路由"，与后端 `RUNTIME_PROFILES` 的落盘规则一一对应；保存之后
 * 一律以 `routing` 快照为准（状态栏走 `routingStatusText`，不由 strategy 反推）。
 */
export function routeSummary(
  profile: string,
  selection: RouteSelection,
  models: SlotModelNames,
  language?: string,
): { chat: string; review: string } {
  const value = String(profile).trim().toLowerCase()
  const selected: RouteSelection =
    value === "custom"
      ? selection
      : value === "hybrid"
        ? { chat: "remote", review: "hybrid" }
        : value === "cloud"
          ? { chat: "remote", review: "remote" }
          : { chat: "local", review: "local" }
  const render = (slot: RouteSlotValue): string =>
    slot === "hybrid"
      ? `${slotLabel(slot, language)} (local↔remote)`
      : `${slotLabel(slot, language)} ${slotDetail(slot, models, language)}`
  return { chat: render(selected.chat), review: render(selected.review) }
}

/**
 * 状态栏的 `CHAT x · REVIEW y`（方案 §4.4）。
 *
 * `routing` 缺失（旧后端）时返回空串，调用方回落到原来的单模型文案——状态栏不能
 * 因为一个新字段缺失就整行空白。审查槽为 hybrid 时明确标记，避免用户误以为
 * 审查只会用某一个模型。
 */
export function routingStatusText(routing: RoutingSnapshot | undefined, language?: string): string {
  const chat = routing?.chat
  const review = routing?.review
  if (!chat && !review) return ""
  const detail = (slot: RoutingSlotSnapshot | undefined): string => {
    if (!slot) return ""
    if (slot.slot === "hybrid") return `${slotLabel("hybrid", language)} (local↔remote)`
    return String(slot.model ?? "").trim() || slotLabel(slot.slot, language)
  }
  const parts: string[] = []
  const chatText = detail(chat)
  const reviewText = detail(review)
  if (chatText) parts.push(`CHAT ${chatText}`)
  if (reviewText) parts.push(`REVIEW ${reviewText}`)
  return parts.join(" · ")
}
// ---------------------------------------------------------------------
// B2/B3 模型规格与中转站的 config.setup 载荷（docs/b2b3-wiring-design.md §2.5/§2.6）
// ---------------------------------------------------------------------

/** 规格编辑值：undefined = 不提交（保持落盘值，后端 `_coerce_spec_int` 的 null 语义）。 */
export type ModelSpecSetupValues = {
  context_window?: number | undefined
  max_output?: number | undefined
  local_context_window?: number | undefined
  local_max_output?: number | undefined
}

/**
 * 把规格编辑值并进 `config.setup` 载荷（§2.5）。
 *
 * 只带**给了值**的字段：undefined/null 一律不发，后端"缺失 = 保持落盘值"。
 * 远端槽用 `context_window`/`max_output`，本地槽用 `local_*`。
 */
export function setupModelSpecFields(values: ModelSpecSetupValues): Record<string, number> {
  const payload: Record<string, number> = {}
  if (typeof values.context_window === "number" && Number.isFinite(values.context_window)) {
    payload.context_window = Math.trunc(values.context_window)
  }
  if (typeof values.max_output === "number" && Number.isFinite(values.max_output)) {
    payload.max_output = Math.trunc(values.max_output)
  }
  if (
    typeof values.local_context_window === "number" &&
    Number.isFinite(values.local_context_window)
  ) {
    payload.local_context_window = Math.trunc(values.local_context_window)
  }
  if (typeof values.local_max_output === "number" && Number.isFinite(values.local_max_output)) {
    payload.local_max_output = Math.trunc(values.local_max_output)
  }
  return payload
}

/**
 * 中转站五项表单的编辑值（§2.6）。
 *
 * `api_key` 三态（§6.2）：`undefined` = 不填写（不发，后端保持落盘 Key）；
 * `""` = 显式清空（发空串）；非空 = 写入。其余字段 `undefined` = 不提交。
 */
export type CustomEndpointSetupValues = {
  base_url?: string | undefined
  /** 三态：undefined 不发 / "" 清空 / 非空写入。 */
  api_key?: string | undefined
  model_name?: string | undefined
  context_window?: number | undefined
  max_output?: number | undefined
}

/**
 * 中转站（custom）逐项写入的载荷（§2.6）。
 *
 * 复用 `_apply_setup` 的既有字段：`provider_name:"custom"` + `api_key`/`model_name`/
 * `base_url`/`api_format`；规格走 §2.5 的 `context_window`/`max_output`。
 * **不套用官方预设**：base_url 为空时也发（后端允许 custom 无预设端点）。
 *
 * `api_key` 三态语义（docs/mimo-config-wizard-fix2.md §2）：
 *   undefined → 不发（"未填写"，后端缺失 = 不动）；
 *   ""        → 发空串（"显式清空"，与未填写区分）；
 *   非空      → 发该值（写入）。
 */
export function setupCustomEndpointFields(
  values: CustomEndpointSetupValues,
  apiFormat = "openai",
): Record<string, unknown> {
  const payload: Record<string, unknown> = { provider_name: "custom", api_format: apiFormat }
  const baseUrl = String(values.base_url ?? "").trim()
  if (baseUrl) payload.base_url = baseUrl
  if (values.api_key !== undefined) {
    payload.api_key = String(values.api_key).trim()
  }
  const modelName = String(values.model_name ?? "").trim()
  if (modelName) payload.model_name = modelName
  if (typeof values.context_window === "number" && Number.isFinite(values.context_window)) {
    payload.context_window = Math.trunc(values.context_window)
  }
  if (typeof values.max_output === "number" && Number.isFinite(values.max_output)) {
    payload.max_output = Math.trunc(values.max_output)
  }
  return payload
}

/**
 * 解释中转站 api_key 输入框的文本为三态值（§6.2）。
 *
 * - 输入 `-`（单个减号）= 显式清空 → 返回 `""`
 * - 空串 / 空白 = 未填写 → 返回 `undefined`（不发）
 * - 其余 = 写入 → 返回 trim 后的值
 */
export function interpretApiKeyInput(raw: string | undefined): string | undefined {
  const trimmed = String(raw ?? "").trim()
  if (!trimmed) return undefined
  if (trimmed === "-") return ""
  return trimmed
}

/**
 * 规格输入的边界校验提示（前端先行提示，后端仍有最终校验）。
 * 返回空串 = 合法；返回文案 = 越界/非整数。
 */
export function validateSpecInput(
  raw: string,
  bounds: [number, number] | undefined,
  language?: string,
): string {
  const en = String(language ?? "zh-CN").toLowerCase().startsWith("en")
  const trimmed = String(raw ?? "").trim()
  if (!trimmed) return ""
  if (!/^-?\d+$/.test(trimmed)) {
    return en ? "must be an integer" : "需为整数"
  }
  const value = Number(trimmed)
  if (!Number.isFinite(value)) {
    return en ? "must be an integer" : "需为整数"
  }
  if (bounds && (value < bounds[0] || value > bounds[1])) {
    return en
      ? `must be between ${bounds[0]} and ${bounds[1]}`
      : `需在 ${bounds[0]}–${bounds[1]} 之间`
  }
  return ""
}
