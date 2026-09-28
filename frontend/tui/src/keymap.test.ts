import { expect, test } from "bun:test"
import { detailScrollDelta } from "./keymap"

test("Shift+Up/Down scrolls the finding detail panel", () => {
  expect(detailScrollDelta("up", true)).toBe(-1)
  expect(detailScrollDelta("down", true)).toBe(1)
})

test("plain arrows keep moving the finding selection", () => {
  expect(detailScrollDelta("up", false)).toBeUndefined()
  expect(detailScrollDelta("down", false)).toBeUndefined()
})

test("Ctrl/Alt+Up/Down also scroll the detail panel", () => {
  expect(detailScrollDelta("up", false, true)).toBe(-1)
  expect(detailScrollDelta("down", false, false, true)).toBe(1)
})

test("unrelated keys never scroll the detail panel", () => {
  expect(detailScrollDelta("left", true)).toBeUndefined()
  expect(detailScrollDelta("pageup", true)).toBeUndefined()
})
