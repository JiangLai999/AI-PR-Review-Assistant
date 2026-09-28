import { expect, test } from "bun:test"
import {
  isForeignSessionEvent,
  parseAssistantFinishMeta,
  parseCatalogRefreshResult,
  parseCompactCommandResult,
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
} from "./protocol"

test("foreign-session filter keeps events that carry no session id", () => {
  expect(isForeignSessionEvent({ event: "backend.notice" }, "s1")).toBe(false)
  expect(isForeignSessionEvent({ event: "backend.notice", session_id: null }, "s1")).toBe(false)
})

test("foreign-session filter keeps the current session", () => {
  expect(isForeignSessionEvent({ event: "review.stage", session_id: "s1" }, "s1")).toBe(false)
})

test("foreign-session filter drops a review running on another session", () => {
  expect(isForeignSessionEvent({ event: "review.file_done", session_id: "old" }, "s1")).toBe(true)
})

test("foreign-session filter drops session events once the session is cleared", () => {
  expect(isForeignSessionEvent({ event: "review.started", session_id: "s1" }, undefined)).toBe(true)
})

// ---------------------------------------------------------------------
// 契约 v1 · assistant.finished 元数据（字段缺失时不崩溃、不显示）
// ---------------------------------------------------------------------

test("finish meta parses duration, usage, context, reasoning, warning and model", () => {
  const meta = parseAssistantFinishMeta({
    event: "assistant.finished",
    duration_seconds: 3.25,
    usage: { prompt_tokens: 1200, completion_tokens: 300, total_tokens: 1500 },
    context: {
      used_tokens: 2400,
      budget_tokens: 20000,
      used_percent: 12,
      trimmed_messages: 2,
      compacted: false,
    },
    reasoning: "先定位再改",
    warning: "over_budget",
    model: "deepseek-flash",
  })
  expect(meta.durationSeconds).toBe(3.25)
  expect(meta.usage?.total_tokens).toBe(1500)
  expect(meta.usage?.completion_tokens).toBe(300)
  expect(meta.context?.used_percent).toBe(12)
  expect(meta.reasoning).toBe("先定位再改")
  expect(meta.warning).toBe("over_budget")
  expect(meta.model).toBe("deepseek-flash")
})

test("finish meta tolerates missing fields from an older backend", () => {
  const meta = parseAssistantFinishMeta({ event: "assistant.finished", text: "ok" })
  expect(meta.durationSeconds).toBeUndefined()
  expect(meta.usage).toBeUndefined()
  expect(meta.context).toBeUndefined()
  expect(meta.reasoning).toBeUndefined()
  expect(meta.warning).toBeUndefined()
  expect(meta.model).toBeUndefined()
})

test("finish meta drops non-finite numbers and unknown warnings", () => {
  const meta = parseAssistantFinishMeta({
    event: "assistant.finished",
    duration_seconds: Number.NaN,
    usage: { total_tokens: "many" },
    context: { used_percent: Number.POSITIVE_INFINITY },
    warning: "panic",
  })
  expect(meta.durationSeconds).toBeUndefined()
  expect(meta.usage).toBeUndefined()
  expect(meta.context).toBeUndefined()
  expect(meta.warning).toBeUndefined()
  expect(meta.model).toBeUndefined()
})

test("reasoning delta only yields text for the reasoning event", () => {
  expect(
    parseReasoningDelta({ event: "assistant.reasoning_delta", text: "step " }),
  ).toBe("step ")
  expect(parseReasoningDelta({ event: "assistant.delta", text: "body" })).toBeUndefined()
  expect(parseReasoningDelta({ event: "assistant.reasoning_delta" })).toBeUndefined()
})

// ---------------------------------------------------------------------
// 契约 v1 · 命令返回 kind: "compact" | "think"
// ---------------------------------------------------------------------

test("think command result exposes level and unsupported reason", () => {
  const applied = parseThinkCommandResult({ kind: "think", state: "applied", level: "high" })
  expect(applied?.level).toBe("high")
  expect(applied?.state).toBe("applied")
  const unsupported = parseThinkCommandResult({
    kind: "think",
    state: "unsupported",
    reason: "model has no reasoning control",
  })
  expect(unsupported?.state).toBe("unsupported")
  expect(unsupported?.reason).toBe("model has no reasoning control")
  expect(parseThinkCommandResult({ kind: "compact" })).toBeUndefined()
  expect(parseThinkCommandResult(undefined)).toBeUndefined()
})

test("think command result reads the backend's `effort` field (contract mismatch fix)", () => {
  // 后端 jsonl_server 实际返回 {state:"set", effort:"high"}；曾因只读 level 导致回显为空。
  const applied = parseThinkCommandResult({ kind: "think", state: "set", effort: "high" })
  expect(applied?.level).toBe("high")
  expect(applied?.state).toBe("set")
  // level 仍然兼容（旧契约），且 effort 优先。
  const legacy = parseThinkCommandResult({ kind: "think", level: "low" })
  expect(legacy?.level).toBe("low")
  const both = parseThinkCommandResult({ kind: "think", effort: "max", level: "low" })
  expect(both?.level).toBe("max")
})

test("dedicated command renderer detection prevents duplicate echo", () => {
  // 实测缺陷：`/think max` 曾显示两行——后端 text「思考档位已设置为 max。」
  // 加上专用格式化「思考档位：最大」。这条断言防止通用回显再次重复显示。
  expect(hasDedicatedCommandRenderer({ kind: "think", state: "set", effort: "high" })).toBe(
    true,
  )
  expect(hasDedicatedCommandRenderer({ kind: "compact", kept_turns: 8 })).toBe(true)
  // 其它命令（/status、/history…）仍走通用回显，不能被误判。
  expect(hasDedicatedCommandRenderer({ text: "/status 的普通输出" })).toBe(false)
  expect(hasDedicatedCommandRenderer({ runs: [] })).toBe(false)
  expect(hasDedicatedCommandRenderer(undefined)).toBe(false)
})

test("compact command result keeps token counts and failure emphasis fields", () => {
  const ok = parseCompactCommandResult({
    kind: "compact",
    ok: true,
    before_tokens: 12400,
    after_tokens: 3100,
    kept_turns: 8,
  })
  expect(ok?.before_tokens).toBe(12400)
  expect(ok?.after_tokens).toBe(3100)
  expect(ok?.kept_turns).toBe(8)
  const failed = parseCompactCommandResult({ kind: "compact", ok: false, error: "store locked" })
  expect(failed?.ok).toBe(false)
  expect(failed?.error).toBe("store locked")
  expect(parseCompactCommandResult({ kind: "think" })).toBeUndefined()
})

// ---------------------------------------------------------------------
// B2/B3 模型规格契约（docs/b2b3-wiring-design.md §2.2/§2.6）
// ---------------------------------------------------------------------

test("model spec block parses the full §2.2 shape including slots", () => {
  const block = parseModelSpecBlock({
    provider: "deepseek",
    model: "deepseek-flash",
    source: "models.dev",
    context_window: 1000000,
    max_output: 393216,
    reasoning: "档位 low/high/max · 开关",
    reasoning_controls: [{ kind: "effort", values: ["low", "high", "max"] }],
    needs_verification: false,
    endpoint_matches_preset: true,
    catalog: { context_window: 1000000, max_output: 393216, source: "models.dev", fetched_at: "2026-09-26T09:12:33+00:00" },
    preset: { context_window: 1048576, max_output: 384000 },
    bounds: { context_window: [1024, 10000000], max_output: [1, 10000000] },
    catalog_state: { enabled: true, source: "models.dev", reason: "", fetched_at: "2026-09-26T09:12:33+00:00" },
    slots: {
      remote: { provider: "deepseek", model: "deepseek-flash", context_window: 1000000, max_output: 393216 },
      local: { provider: "ollama", model: "qwen3.5:4b", context_window: 32768, max_output: 4096 },
    },
  })
  expect(block?.source).toBe("models.dev")
  expect(block?.context_window).toBe(1000000)
  expect(block?.catalog?.source).toBe("models.dev")
  expect(block?.bounds?.context_window).toEqual([1024, 10000000])
  expect(block?.slots?.remote?.model).toBe("deepseek-flash")
  expect(block?.slots?.local?.model).toBe("qwen3.5:4b")
})

test("model spec block tolerates missing fields from an older backend", () => {
  expect(parseModelSpecBlock(undefined)).toBeUndefined()
  expect(parseModelSpecBlock(null)).toBeUndefined()
  expect(parseModelSpecBlock("not-an-object")).toBeUndefined()
  const bare = parseModelSpecBlock({ context_window: 128 })
  expect(bare?.context_window).toBe(128)
  expect(bare?.source).toBeUndefined()
  expect(bare?.catalog).toBeUndefined()
  expect(bare?.slots).toBeUndefined()
})

test("model spec block drops non-finite numbers and keeps catalog null", () => {
  const block = parseModelSpecBlock({
    context_window: Number.NaN,
    max_output: "many",
    catalog: null,
    preset: null,
  })
  expect(block?.context_window).toBeUndefined()
  expect(block?.max_output).toBeUndefined()
  expect(block?.catalog).toBeNull()
  expect(block?.preset).toBeNull()
})

test("model spec block marks needs_verification without overwriting values", () => {
  const block = parseModelSpecBlock({
    context_window: 128000,
    max_output: 8192,
    needs_verification: true,
    catalog: { context_window: 1000000, max_output: 393216 },
  })
  expect(block?.needs_verification).toBe(true)
  expect(block?.context_window).toBe(128000)
  expect(block?.catalog?.context_window).toBe(1000000)
})

test("custom endpoint options parse the §2.6 shape", () => {
  const endpoint = parseCustomEndpointOptions({
    name: "custom",
    display_name: "Custom Endpoint",
    base_url: "https://relay.example.com/v1",
    api_format: "openai",
    default_model: "relay-model",
    api_key_configured: true,
    models: ["relay-model"],
    context_window: 200000,
    max_output: 16384,
    source: "unknown",
    needs_verification: false,
  })
  expect(endpoint?.base_url).toBe("https://relay.example.com/v1")
  expect(endpoint?.api_key_configured).toBe(true)
  expect(endpoint?.models).toEqual(["relay-model"])
  expect(endpoint?.source).toBe("unknown")
})

test("catalog refresh result extracts the model block", () => {
  const spec = parseCatalogRefreshResult({
    model: { provider: "deepseek", source: "models.dev", context_window: 1000000 },
  })
  expect(spec?.source).toBe("models.dev")
  expect(parseCatalogRefreshResult({})).toBeUndefined()
  expect(parseCatalogRefreshResult(undefined)).toBeUndefined()
})

// ---------------------------------------------------------------------
// review 思考档位（docs/mimo-review-effort-ui.md）
// ---------------------------------------------------------------------

test("review reasoning options parses value, options, state and reason", () => {
  const parsed = parseReviewReasoningOptions({
    value: "high",
    options: [
      { value: "off", label: "关闭 / Off（不思考，默认）" },
      { value: "low", label: "低 / Low" },
      { value: "high", label: "高 / High" },
      { value: "max", label: "最高 / Max" },
      { value: "auto", label: "自动 / Auto" },
    ],
    state: "unsupported",
    reason: "本地模型固定使用快速模式",
  })
  expect(parsed?.value).toBe("high")
  expect(parsed?.options).toHaveLength(5)
  expect(parsed?.options?.[2]).toEqual({ value: "high", label: "高 / High" })
  expect(parsed?.state).toBe("unsupported")
  expect(parsed?.reason).toBe("本地模型固定使用快速模式")
})

test("review reasoning options omits state/reason when the provider injects params", () => {
  const parsed = parseReviewReasoningOptions({
    value: "off",
    options: [{ value: "off", label: "关闭 / Off" }],
  })
  expect(parsed?.state).toBeUndefined()
  expect(parsed?.reason).toBeUndefined()
})

test("review reasoning options tolerates missing fields from an older backend", () => {
  expect(parseReviewReasoningOptions(undefined)).toBeUndefined()
  expect(parseReviewReasoningOptions(null)).toBeUndefined()
  expect(parseReviewReasoningOptions("not-an-object")).toBeUndefined()
  const bare = parseReviewReasoningOptions({})
  expect(bare?.value).toBeUndefined()
  expect(bare?.options).toEqual([])
})

test("review reasoning options drops malformed option entries", () => {
  const parsed = parseReviewReasoningOptions({
    value: "off",
    options: [null, "junk", { label: "no value" }, { value: "off", label: "关闭 / Off" }],
  })
  expect(parsed?.options).toHaveLength(1)
  expect(parsed?.options?.[0].value).toBe("off")
})

// ---------------------------------------------------------------------
// 契约 v1 · 会话协议（session.list / switch / rename / delete / create）
// ---------------------------------------------------------------------

test("session list parses sessions and top-level current", () => {
  const parsed = parseSessionListResult({
    sessions: [
      { id: "s2", title: "修复 XSS", updated_at: "2026-09-27T03:00:00Z", message_count: 12, current: true },
      { id: "s1", title: "旧会话", updated_at: "2026-09-26T01:00:00Z", message_count: 3 },
    ],
    current: "s2",
  })
  expect(parsed?.sessions).toHaveLength(2)
  expect(parsed?.current).toBe("s2")
  expect(parsed?.sessions[0].title).toBe("修复 XSS")
  expect(parsed?.sessions[0].message_count).toBe(12)
  expect(parsed?.sessions[1].current).toBeUndefined()
})

test("session list falls back to item-level current when top-level is missing", () => {
  const parsed = parseSessionListResult({
    sessions: [{ id: "s1", title: "A", current: true }, { id: "s2", title: "B" }],
  })
  expect(parsed?.current).toBe("s1")
})

test("session list tolerates a missing or malformed payload", () => {
  expect(parseSessionListResult(undefined)).toBeUndefined()
  expect(parseSessionListResult("junk")).toBeUndefined()
  const empty = parseSessionListResult({})
  expect(empty?.sessions).toEqual([])
  expect(empty?.current).toBeUndefined()
  const junkItems = parseSessionListResult({
    sessions: [null, "x", { title: "no id" }, { id: "ok", title: "T" }],
  })
  expect(junkItems?.sessions).toHaveLength(1)
  expect(junkItems?.sessions[0].id).toBe("ok")
})

test("session switch parses session block and message history", () => {
  const parsed = parseSessionSwitchResult({
    session: { id: "s9", title: "切换目标", updated_at: "2026-09-27T04:00:00Z", message_count: 2 },
    messages: [
      { role: "user", content: "看看这个 PR" },
      { role: "assistant", content: "已审查", thinking: "先定位" },
      { role: "ghost", content: "dropped" },
      "junk",
    ],
  })
  expect(parsed?.session?.id).toBe("s9")
  expect(parsed?.session?.title).toBe("切换目标")
  expect(parsed?.messages).toHaveLength(3)
  expect(parsed?.messages?.[0].role).toBe("user")
  expect(parsed?.messages?.[1].thinking).toBe("先定位")
  expect(parsed?.messages?.[2].role).toBeUndefined()
})

test("session switch tolerates a payload without session/messages", () => {
  expect(parseSessionSwitchResult(undefined)).toBeUndefined()
  const bare = parseSessionSwitchResult({ ok: true })
  expect(bare?.session).toBeUndefined()
  expect(bare?.messages).toBeUndefined()
})

test("session rename/delete/create parse their contract fields", () => {
  const renamed = parseSessionRenameResult({ id: "s1", title: "新标题" })
  expect(renamed?.id).toBe("s1")
  expect(renamed?.title).toBe("新标题")
  // 后端契约返回被删会话 **id（string）**；早期实现用 boolean，两者都要放行
  // （docs/claude-sessions-compaction.md §协议：deleted=<id>）。
  const deletedById = parseSessionDeleteResult({ deleted: "s1", next: "s2" })
  expect(deletedById?.deleted).toBe("s1")
  expect(deletedById?.next).toBe("s2")
  const deletedLegacy = parseSessionDeleteResult({ deleted: true, next: "s2" })
  expect(deletedLegacy?.deleted).toBe(true)
  expect(parseSessionDeleteResult({})?.deleted).toBeUndefined()
  const created = parseSessionCreateResult({ session_id: "s10", title: "新会话" })
  expect(created?.session_id).toBe("s10")
  expect(created?.title).toBe("新会话")
  const createdNested = parseSessionCreateResult({ session: { id: "s11", title: "嵌套" } })
  expect(createdNested?.session_id).toBe("s11")
  expect(createdNested?.session?.title).toBe("嵌套")
  expect(parseSessionRenameResult(null)).toBeUndefined()
  expect(parseSessionDeleteResult(undefined)).toBeUndefined()
})

// ---------------------------------------------------------------------
// 契约 v1 · assistant.finished.context.pressure（B-P3 前端）
// ---------------------------------------------------------------------

test("context pressure accepts the four contract levels and explicit null", () => {
  for (const level of ["low", "medium", "high", "critical"] as const) {
    const meta = parseAssistantFinishMeta({
      event: "assistant.finished",
      context: { used_percent: 50, pressure: level },
    })
    expect(meta.context?.pressure).toBe(level)
  }
  const nulled = parseAssistantFinishMeta({
    event: "assistant.finished",
    context: { used_percent: 5, pressure: null },
  })
  expect(nulled.context?.pressure).toBeNull()
})

test("context pressure drops unknown strings and missing keys (old backend)", () => {
  const unknown = parseAssistantFinishMeta({
    event: "assistant.finished",
    context: { used_percent: 40, pressure: "melting" },
  })
  expect(unknown.context?.used_percent).toBe(40)
  expect(unknown.context?.pressure).toBeUndefined()
  const missing = parseAssistantFinishMeta({
    event: "assistant.finished",
    context: { used_percent: 40 },
  })
  expect(missing.context?.pressure).toBeUndefined()
  // pressure-only context still parses (all other keys may be absent).
  const onlyPressure = parseAssistantFinishMeta({
    event: "assistant.finished",
    context: { pressure: "high" },
  })
  expect(onlyPressure.context?.pressure).toBe("high")
})
