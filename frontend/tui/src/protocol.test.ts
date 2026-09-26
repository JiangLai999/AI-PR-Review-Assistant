import { expect, test } from "bun:test"
import {
  isForeignSessionEvent,
  parseAssistantFinishMeta,
  parseCompactCommandResult,
  parseReasoningDelta,
  parseThinkCommandResult,
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

test("finish meta parses duration, usage, context, reasoning and warning", () => {
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
  })
  expect(meta.durationSeconds).toBe(3.25)
  expect(meta.usage?.total_tokens).toBe(1500)
  expect(meta.context?.used_percent).toBe(12)
  expect(meta.reasoning).toBe("先定位再改")
  expect(meta.warning).toBe("over_budget")
})

test("finish meta tolerates missing fields from an older backend", () => {
  const meta = parseAssistantFinishMeta({ event: "assistant.finished", text: "ok" })
  expect(meta.durationSeconds).toBeUndefined()
  expect(meta.usage).toBeUndefined()
  expect(meta.context).toBeUndefined()
  expect(meta.reasoning).toBeUndefined()
  expect(meta.warning).toBeUndefined()
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
