import { expect, test } from "bun:test"
import {
  chatCommands,
  commandArgumentLabel,
  commandCompletion,
  commandDescription,
  commandEnterAction,
  commandMatches,
} from "./command-menu"
import { isCurrentAssistantEvent } from "./protocol"

test("slash menu filters commands without treating arguments as commands", () => {
  expect(commandMatches("/mod").map((item) => item.name)).toEqual(["/model", "/model status"])
  expect(commandMatches("/model status").map((item) => item.name)).toEqual(["/model status"])
  expect(commandMatches("/model local")).toEqual([])
  expect(commandMatches("hello")).toEqual([])
  expect(commandMatches("/review\ntext")).toEqual([])
})

test("commands with arguments complete with a trailing space", () => {
  expect(commandCompletion(chatCommands.find((item) => item.name === "/review")!)).toBe("/review ")
  expect(commandCompletion(chatCommands.find((item) => item.name === "/help")!)).toBe("/help")
})

test("the P5 commands are advertised and complete with their arguments", () => {
  const names = chatCommands.map((item) => item.name)
  expect(names).toContain("/publish")
  expect(names).toContain("/demo")
  expect(names).toContain("/showcase")
  expect(commandCompletion(chatCommands.find((item) => item.name === "/publish")!)).toBe("/publish ")
  expect(commandCompletion(chatCommands.find((item) => item.name === "/demo")!)).toBe("/demo ")
  // `/showcase` takes no argument, so Enter runs it immediately.
  expect(commandCompletion(chatCommands.find((item) => item.name === "/showcase")!)).toBe("/showcase")
  expect(commandMatches("/show").map((item) => item.name)).toEqual(["/showcase"])
  expect(commandMatches("/pub").map((item) => item.name)).toEqual(["/publish"])
})

test("assistant deltas only update the active request and session", () => {
  const event = { event: "assistant.delta", session_id: "s1", request_id: "r1", text: "partial" }
  expect(isCurrentAssistantEvent(event, "s1", "r1")).toBe(true)
  expect(isCurrentAssistantEvent(event, "s2", "r1")).toBe(false)
  expect(isCurrentAssistantEvent(event, "s1", "r2")).toBe(false)
  expect(isCurrentAssistantEvent(event, "s1", undefined)).toBe(false)
})

test("ambiguous slash prefixes complete instead of running a command", () => {
  const options = commandMatches("/h")
  expect(options.length).toBeGreaterThan(1)
  expect(commandEnterAction("/h", options[0], options.length)).toEqual({
    kind: "complete",
    draft: "/help",
  })
})

test("a unique prefix runs the matching command", () => {
  const options = commandMatches("/he")
  expect(options.map((item) => item.name)).toEqual(["/help"])
  expect(commandEnterAction("/he", options[0], options.length)).toEqual({ kind: "run" })
})

test("a command that needs an argument completes on the first Enter", () => {
  const options = commandMatches("/review")
  expect(commandEnterAction("/review", options[0], options.length)).toEqual({
    kind: "complete",
    draft: "/review ",
  })
})

test("once the argument slot is open, Enter runs the command", () => {
  const options = commandMatches("/review ")
  expect(options.map((item) => item.name)).toEqual(["/review"])
  expect(commandEnterAction("/review ", options[0], options.length)).toEqual({ kind: "run" })
})

test("an exact command name wins over a longer sibling", () => {
  const options = commandMatches("/model")
  expect(options.map((item) => item.name)).toEqual(["/model", "/model status"])
  // `/model` takes an argument, so the first Enter opens the argument slot…
  expect(commandEnterAction("/model", options[0], options.length)).toEqual({
    kind: "complete",
    draft: "/model ",
  })
  // …while the fully written sibling runs immediately.
  expect(commandEnterAction("/model status", options[1], options.length)).toEqual({ kind: "run" })
})


test("unique argument command prefix completes rather than runs empty", () => {
  const options = commandMatches("/rev")
  expect(options.map((item) => item.name)).toEqual(["/review"])
  expect(commandEnterAction("/rev", options[0], options.length)).toEqual({
    kind: "complete", draft: "/review ",
  })
})

test("partial model argument is never replaced with status subcommand", () => {
  expect(commandMatches("/model st")).toEqual([])
  expect(commandMatches("/model status").map((item) => item.name)).toEqual(["/model status"])
  expect(commandMatches("/model status ").map((item) => item.name)).toEqual(["/model status"])
})

test("an exact no-argument command runs immediately", () => {
  const options = commandMatches("/help")
  expect(options.map((item) => item.name)).toEqual(["/help"])
  expect(commandEnterAction("/help", options[0], options.length)).toEqual({ kind: "run" })
})

test("ambiguous /re completes instead of running the first command", () => {
  const options = commandMatches("/re")
  // /rename 也是 /re 前缀（2026-09-27 新增，用户反馈"改名入口太难发现"）。
  expect(options.map((item) => item.name)).toEqual(["/review", "/retry", "/report", "/rename"])
  expect(commandEnterAction("/re", options[0], options.length)).toEqual({
    kind: "complete",
    draft: "/review ",
  })
  const report = options.find((item) => item.name === "/report")!
  expect(commandEnterAction("/re", report, options.length)).toEqual({
    kind: "complete",
    draft: "/report",
  })
})

test("argument-taking sibling from an ambiguous prefix only completes", () => {
  const options = commandMatches("/h")
  const history = options.find((item) => item.name === "/history")!
  expect(commandEnterAction("/h", history, options.length)).toEqual({
    kind: "complete",
    draft: "/history ",
  })
})

test("unique multi-match prefix of an argument command completes (M1 /mod)", () => {
  const options = commandMatches("/mod")
  expect(options.map((item) => item.name)).toEqual(["/model", "/model status"])
  expect(commandEnterAction("/mod", options[0], options.length)).toEqual({
    kind: "complete",
    draft: "/model ",
  })
})

test("unique no-argument prefix still runs (M1 non-regression)", () => {
  const options = commandMatches("/ne")
  expect(options.map((item) => item.name)).toEqual(["/new"])
  expect(commandEnterAction("/ne", options[0], options.length)).toEqual({ kind: "run" })
})

test("command drafts with arguments never match (M2/M3: args are not swallowed)", () => {
  expect(commandMatches("/review https://github.com/org/repo/pull/1")).toEqual([])
  expect(commandMatches("/export json ./report.json")).toEqual([])
  expect(commandMatches("/history 5")).toEqual([])
  expect(commandMatches("/model s")).toEqual([])
  expect(commandMatches("/model stat")).toEqual([])
  expect(commandMatches("/model status ok")).toEqual([])
})

test("open argument slot matches only the base command (M2 /model st vs /model status)", () => {
  expect(commandMatches("/model ").map((item) => item.name)).toEqual(["/model"])
  expect(commandMatches("/review ").map((item) => item.name)).toEqual(["/review"])
  const options = commandMatches("/model ")
  expect(commandEnterAction("/model ", options[0], options.length)).toEqual({ kind: "run" })
})

test("/model status with trailing space runs the connectivity check", () => {
  const options = commandMatches("/model status ")
  expect(options.map((item) => item.name)).toEqual(["/model status"])
  expect(commandEnterAction("/model status ", options[0], options.length)).toEqual({ kind: "run" })
})

// ---------------------------------------------------------------------
// 契约 v1 · /think /compact /history 命令 UI
// ---------------------------------------------------------------------

test("think and compact commands are advertised with argument completion", () => {
  const names = chatCommands.map((item) => item.name)
  expect(names).toContain("/think")
  expect(names).toContain("/compact")
  const think = chatCommands.find((item) => item.name === "/think")!
  const compact = chatCommands.find((item) => item.name === "/compact")!
  expect(commandCompletion(think)).toBe("/think ")
  expect(commandCompletion(compact)).toBe("/compact ")
  expect(commandMatches("/thi").map((item) => item.name)).toEqual(["/think"])
  expect(commandMatches("/com").map((item) => item.name)).toEqual(["/compact"])
  expect(commandEnterAction("/think", think, 1)).toEqual({ kind: "complete", draft: "/think " })
  // 带参草稿不被命令菜单吞掉（与 /review 等一致）。
  expect(commandMatches("/think high")).toEqual([])
  expect(commandMatches("/compact 压缩掉旧讨论")).toEqual([])
})

test("history command description distinguishes conversation list from runs", () => {
  const history = chatCommands.find((item) => item.name === "/history")!
  expect(commandDescription(history)).toContain("对话消息列表")
  expect(commandDescription(history, "en-US")).toContain("conversation")
  expect(commandArgumentLabel(history)).toContain("--runs")
})

test("command descriptions and arguments have zh/en twins for the new commands", () => {
  for (const name of ["/think", "/compact", "/history"]) {
    const command = chatCommands.find((item) => item.name === name)!
    expect(commandDescription(command).length).toBeGreaterThan(0)
    expect(commandDescription(command, "en-US").length).toBeGreaterThan(0)
    expect(commandDescription(command)).not.toBe(commandDescription(command, "en-US"))
  }
})
