import { expect, test } from "bun:test"
import {
  CHAT_SLOT_VALUES,
  REVIEW_SLOT_VALUES,
  presetDescription,
  presetIndexOf,
  presetLabel,
  routeBoxes,
  routeSummary,
  routingStatusText,
  setupSlotFields,
  slotDetail,
  slotIndexOf,
  slotLabel,
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
