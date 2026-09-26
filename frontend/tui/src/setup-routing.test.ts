import { expect, test } from "bun:test"
import {
  CHAT_SLOT_VALUES,
  REVIEW_SLOT_VALUES,
  FALLBACK_REVIEW_EFFORT_OPTIONS,
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
  slotDetail,
  slotIndexOf,
  slotLabel,
  validateSpecInput,
} from "./setup-routing"

// 与 `config.options.current` 同形：两个槽各自能用的模型名都来自后端。
const models = { remote: "deepseek-flash", local: "qwen3.5:4b" }

test("chat box offers cloud/local with the backend's model names, review box adds hybrid", () => {
  const [chat, review] = routeBoxes(models, "zh-CN")
  expect(chat.key).toBe("chat")
  expect(chat.choices.map((choice) => choice.value)).toEqual(["remote", "local"])
  expect(chat.choices.map((choice) => `${choice.label} ${choice.detail}`)).toEqual([
    "云端 deepseek-flash",
    "本地 qwen3.5:4b",
  ])
  expect(review.choices.map((choice) => choice.value)).toEqual(["remote", "local", "hybrid"])
  expect(review.choices[2].label).toBe("混合")
  expect(review.choices[2].detail).toContain("复杂度")
  // The wizard must not hard-code model names: an unconfigured slot says so.
  const bare = routeBoxes({ remote: "", local: "" }, "zh-CN")
  expect(bare[0].choices.map((choice) => choice.detail)).toEqual(["未配置", "未配置"])
})

test("the route boxes switch to English copy on en-US", () => {
  const [chat, review] = routeBoxes(models, "en-US")
  expect(chat.title).toContain("Chat model")
  expect(chat.choices.map((choice) => choice.label)).toEqual(["Cloud", "Local"])
  expect(review.choices[2]).toEqual({
    value: "hybrid",
    label: "Hybrid",
    detail: "auto-route by complexity",
  })
})

test("only the custom profile sends chat_slot/review_slot", () => {
  const selection = { chat: "remote", review: "local" } as const
  expect(setupSlotFields("custom", selection)).toEqual({
    chat_slot: "remote",
    review_slot: "local",
  })
  for (const profile of ["cloud", "local", "hybrid", "offline"]) {
    expect(setupSlotFields(profile, selection)).toEqual({})
  }
  // Case/whitespace must not smuggle the keys into a preset branch the backend
  // would answer by clearing both slots.
  expect(setupSlotFields(" CUSTOM ", selection)).toEqual(setupSlotFields("custom", selection))
})

test("the wizard preselects the preset from routing.profile, not runtime_profile", () => {
  const values = ["cloud", "local", "hybrid", "custom"]
  // A custom config reports runtime_profile=cloud/hybrid (the slot actually in
  // effect) while routing.profile stays custom.
  expect(presetIndexOf(values, "custom", "cloud")).toBe(3)
  expect(presetIndexOf(values, "hybrid", "hybrid")).toBe(2)
  // Older snapshots have no routing block at all.
  expect(presetIndexOf(values, undefined, "local")).toBe(1)
  expect(presetIndexOf(values, "unknown-value", "custom")).toBe(3)
  expect(presetIndexOf(values, undefined, undefined)).toBe(0)
})

test("slot indexes fall back to the first entry instead of going out of bounds", () => {
  expect(slotIndexOf(CHAT_SLOT_VALUES.map((value) => ({ value })), "local")).toBe(1)
  expect(slotIndexOf(CHAT_SLOT_VALUES.map((value) => ({ value })), "hybrid")).toBe(0)
  expect(slotIndexOf(REVIEW_SLOT_VALUES.map((value) => ({ value })), "hybrid")).toBe(2)
  expect(slotIndexOf(REVIEW_SLOT_VALUES.map((value) => ({ value })), undefined)).toBe(0)
})

test("the confirm page previews the preset's route and the custom selection", () => {
  const selection = { chat: "local", review: "hybrid" } as const
  expect(routeSummary("custom", selection, models, "zh-CN")).toEqual({
    chat: "本地 qwen3.5:4b",
    review: "混合 (local↔remote)",
  })
  expect(routeSummary("cloud", selection, models, "zh-CN")).toEqual({
    chat: "云端 deepseek-flash",
    review: "云端 deepseek-flash",
  })
  expect(routeSummary("local", selection, models, "zh-CN")).toEqual({
    chat: "本地 qwen3.5:4b",
    review: "本地 qwen3.5:4b",
  })
  // The hybrid preset is exactly what resolve_* derives from `balanced`.
  expect(routeSummary("hybrid", selection, models, "zh-CN")).toEqual({
    chat: "云端 deepseek-flash",
    review: "混合 (local↔remote)",
  })
  // Legacy `offline` reads as local on the backend.
  expect(routeSummary("offline", selection, models, "en-US").chat).toBe("Local qwen3.5:4b")
})

test("the status bar renders both slots and marks hybrid reviews", () => {
  const routing = {
    profile: "custom",
    chat: { slot: "remote", label: "云端", model: "deepseek-flash" },
    review: { slot: "local", label: "本地", model: "qwen3.5:4b" },
  }
  expect(routingStatusText(routing, "zh-CN")).toBe("CHAT deepseek-flash · REVIEW qwen3.5:4b")
  expect(
    routingStatusText(
      { ...routing, review: { slot: "hybrid", label: "混合", model: "deepseek-flash" } },
      "zh-CN",
    ),
  ).toBe("CHAT deepseek-flash · REVIEW 混合 (local↔remote)")
  expect(
    routingStatusText(
      { ...routing, review: { slot: "hybrid", label: "混合", model: "deepseek-flash" } },
      "en-US",
    ),
  ).toBe("CHAT deepseek-flash · REVIEW Hybrid (local↔remote)")
  // A slot without a model still names itself instead of printing `undefined`.
  expect(
    routingStatusText({ chat: { slot: "local", model: "" }, review: undefined }, "zh-CN"),
  ).toBe("CHAT 本地")
  // Old backends have no routing block: the caller keeps its previous line.
  expect(routingStatusText(undefined, "zh-CN")).toBe("")
  expect(routingStatusText({}, "zh-CN")).toBe("")
})

test("slot aliases and preset copy are bilingual", () => {
  expect(slotLabel("remote", "zh-CN")).toBe("云端")
  expect(slotLabel("local", "en-US")).toBe("Local")
  expect(slotDetail("local", models, "en-US")).toBe("qwen3.5:4b")
  expect(slotDetail("local", { local: "" }, "en-US")).toBe("not configured")
  expect(presetLabel({ value: "custom", label: "自定义" }, "zh-CN")).toBe("自定义")
  expect(presetLabel({ value: "custom", label: "自定义" }, "en-US")).toBe("Custom")
  // Backend labels are Chinese-only; an unknown value keeps whatever it sent.
  expect(presetLabel({ value: "future", label: "未来" }, "zh-CN")).toBe("未来")
  expect(presetDescription("custom", "zh-CN")).toContain("对话模型")
  expect(presetDescription("custom", "en-US")).toContain("chat model")
  expect(presetDescription("future", "zh-CN")).toBe("")
})

// ---------------------------------------------------------------------
// B3 中转站载荷三态 + api_key 清空语义（docs/mimo-config-wizard-fix2.md §1/§2）
// ---------------------------------------------------------------------

test("setupCustomEndpointFields api_key three states: omit / clear / write", () => {
  // 未填写（undefined）→ 不发 api_key 键
  const omit = setupCustomEndpointFields({ base_url: "https://r.example.com" })
  expect(omit.api_key).toBeUndefined()
  expect("api_key" in omit).toBe(false)
  // 显式清空（""）→ 发空串
  const clear = setupCustomEndpointFields({ base_url: "https://r.example.com", api_key: "" })
  expect(clear.api_key).toBe("")
  expect("api_key" in clear).toBe(true)
  // 写入（非空）→ 发值
  const write = setupCustomEndpointFields({ api_key: "sk-test-123" })
  expect(write.api_key).toBe("sk-test-123")
})

test("setupCustomEndpointFields sends only filled fields and always provider_name=custom", () => {
  const empty = setupCustomEndpointFields({})
  expect(empty.provider_name).toBe("custom")
  expect(empty.api_format).toBe("openai")
  expect(empty.base_url).toBeUndefined()
  expect(empty.model_name).toBeUndefined()
  expect(empty.context_window).toBeUndefined()
  expect(empty.max_output).toBeUndefined()

  const full = setupCustomEndpointFields(
    {
      base_url: "https://relay.example.com/v1",
      api_key: "sk-abc",
      model_name: "relay-model",
      context_window: 200000.7,
      max_output: 16384,
    },
    "anthropic",
  )
  expect(full.provider_name).toBe("custom")
  expect(full.api_format).toBe("anthropic")
  expect(full.base_url).toBe("https://relay.example.com/v1")
  expect(full.api_key).toBe("sk-abc")
  expect(full.model_name).toBe("relay-model")
  expect(full.context_window).toBe(200000) // truncated
  expect(full.max_output).toBe(16384)
})

test("interpretApiKeyInput maps dash / blank / value to clear / omit / write", () => {
  expect(interpretApiKeyInput("-")).toBe("") // 显式清空
  expect(interpretApiKeyInput("  -  ")).toBe("") // trim 后仍是 -
  expect(interpretApiKeyInput("")).toBeUndefined() // 未填写
  expect(interpretApiKeyInput("   ")).toBeUndefined()
  expect(interpretApiKeyInput(undefined)).toBeUndefined()
  expect(interpretApiKeyInput("sk-real-key")).toBe("sk-real-key")
})

// ---------------------------------------------------------------------
// 规格输入边界校验（§6.3）
// ---------------------------------------------------------------------

test("validateSpecInput accepts integers and rejects out-of-range / non-integer", () => {
  const bounds: [number, number] = [1024, 10000000]
  expect(validateSpecInput("128000", bounds)).toBe("")
  expect(validateSpecInput("", bounds)).toBe("") // 空 = 合法
  expect(validateSpecInput("  ", bounds)).toBe("")
  expect(validateSpecInput("abc", bounds)).toContain("整数")
  expect(validateSpecInput("12.5", bounds)).toContain("整数")
  expect(validateSpecInput("512", bounds)).toContain("1024") // 越界
  expect(validateSpecInput("99999999", bounds)).toContain("1024") // 越界
  // 无边界时只验整数
  expect(validateSpecInput("42", undefined)).toBe("")
  expect(validateSpecInput("x", undefined)).toContain("整数")
  // en-US 文案
  expect(validateSpecInput("abc", bounds, "en-US")).toContain("integer")
  expect(validateSpecInput("1", bounds, "en-US")).toContain("between")
})

// ---------------------------------------------------------------------
// 规格载荷（§2.5）
// ---------------------------------------------------------------------

test("setupModelSpecFields only sends provided numeric fields", () => {
  const empty = setupModelSpecFields({})
  expect(Object.keys(empty)).toHaveLength(0)
  const partial = setupModelSpecFields({ context_window: 128000 })
  expect(partial).toEqual({ context_window: 128000 })
  expect(partial.max_output).toBeUndefined()
  const full = setupModelSpecFields({
    context_window: 100000.9,
    max_output: 8192,
    local_context_window: 32768,
    local_max_output: 4096,
  })
  expect(full.context_window).toBe(100000) // truncated
  expect(full.max_output).toBe(8192)
  expect(full.local_context_window).toBe(32768)
  expect(full.local_max_output).toBe(4096)
})

// ---------------------------------------------------------------------
// review 思考档位（docs/mimo-review-effort-ui.md）
// ---------------------------------------------------------------------

test("review effort choices prefer the backend list and fall back when absent", () => {
  const backendList = [
    { value: "off", label: "关闭 / Off" },
    { value: "low", label: "低 / Low" },
  ]
  expect(reviewEffortChoices({ options: backendList })).toEqual(backendList)
  expect(reviewEffortChoices(undefined)).toEqual(FALLBACK_REVIEW_EFFORT_OPTIONS)
  expect(reviewEffortChoices({ options: [] })).toEqual(FALLBACK_REVIEW_EFFORT_OPTIONS)
  // The fallback list mirrors the backend vocabulary: off|low|high|max|auto.
  expect(FALLBACK_REVIEW_EFFORT_OPTIONS.map((item) => item.value)).toEqual([
    "off",
    "low",
    "high",
    "max",
    "auto",
  ])
})

test("review effort preselect falls back to off (the backend default), never out of bounds", () => {
  const list = FALLBACK_REVIEW_EFFORT_OPTIONS
  expect(reviewEffortIndexOf(list, "high")).toBe(2)
  expect(reviewEffortIndexOf(list, "off")).toBe(0)
  expect(reviewEffortIndexOf(list, "unknown")).toBe(0)
  expect(reviewEffortIndexOf(list, undefined)).toBe(0)
  expect(reviewEffortIndexOf([], "off")).toBe(0)
})

test("review effort value clamps the index and falls back to off", () => {
  const list = FALLBACK_REVIEW_EFFORT_OPTIONS
  expect(reviewEffortValue(list, 3)).toBe("max")
  expect(reviewEffortValue(list, -5)).toBe("off")
  expect(reviewEffortValue(list, 99)).toBe("auto")
  expect(reviewEffortValue([], 0)).toBe("off")
})

test("review effort stored value normalizes both backend shapes", () => {
  expect(reviewEffortStoredValue("HIGH")).toBe("high")
  expect(reviewEffortStoredValue({ value: "max", options: [] })).toBe("max")
  expect(reviewEffortStoredValue({ options: [] })).toBe("")
  expect(reviewEffortStoredValue(undefined)).toBe("")
})

test("review effort setup field always sends the visible level", () => {
  expect(setupReviewEffortField("high")).toEqual({ review_reasoning_effort: "high" })
  expect(setupReviewEffortField("  MAX  ")).toEqual({ review_reasoning_effort: "max" })
  // Empty string = don't send (backend treats missing as "keep the stored value").
  expect(setupReviewEffortField("")).toEqual({})
})

test("review effort greys out only when the backend says unsupported", () => {
  expect(reviewEffortIsDisabled({ state: "unsupported", reason: "local" })).toBe(true)
  expect(reviewEffortIsDisabled({ state: "set" })).toBe(false)
  expect(reviewEffortIsDisabled({ state: "transparent" })).toBe(false)
  // No state field at all → never grey out (front-end must not infer provider capability).
  expect(reviewEffortIsDisabled({})).toBe(false)
  expect(reviewEffortIsDisabled(undefined)).toBe(false)
})

test("review effort summary shows the bilingual label side chosen by ui_language", () => {
  const list = FALLBACK_REVIEW_EFFORT_OPTIONS
  expect(reviewEffortSummary(list, "off", "zh-CN")).toBe("关闭")
  expect(reviewEffortSummary(list, "off", "en-US")).toContain("Off")
  expect(reviewEffortSummary(list, "unknown", "zh-CN")).toBe("unknown")
})
