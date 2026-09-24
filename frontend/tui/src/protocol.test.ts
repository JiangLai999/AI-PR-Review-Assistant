import { expect, test } from "bun:test"
import { isForeignSessionEvent } from "./protocol"

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
