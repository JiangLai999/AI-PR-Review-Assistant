import { expect, test } from "bun:test"
import { compactPath, truncateMiddle, workspaceRootLabel } from "./format"

test("compactPath keeps the tail of an over-long path", () => {
  expect(compactPath("C:\\short", 30)).toBe("C:\\short")
  const long = "C:\\Users\\21986\\Desktop\\ican\\AI-PR-Review-Assistant\\frontend\\tui"
  const compact = compactPath(long, 20)
  expect(compact.length).toBe(20)
  expect(compact.startsWith("…")).toBe(true)
  expect(compact.endsWith("frontend\\tui")).toBe(true)
})

test("truncateMiddle preserves both ends of a PR url", () => {
  const url = "https://github.com/JiangLai999/AI-PR-Review-Assistant/pull/138"
  expect(truncateMiddle(url, 70)).toBe(url)
  const cut = truncateMiddle(url, 30)
  expect(cut.length).toBe(30)
  // Exactly `max` columns: head + ellipsis + tail.
  expect(cut).toBe(`${url.slice(0, 15)}…${url.slice(url.length - 14)}`)
  expect(cut.startsWith("https://github.")).toBe(true)
  expect(cut.endsWith("/pull/138")).toBe(true)
})

test("workspaceRootLabel folds the home prefix and never exceeds the footer budget", () => {
  expect(workspaceRootLabel("C:\\Users\\21986\\Desktop\\ican", "C:\\Users\\21986")).toBe(
    "~\\Desktop\\ican",
  )
  expect(workspaceRootLabel("/home/me/projects/app", "/home/me")).toBe("~/projects/app")
  expect(workspaceRootLabel("/opt/other/app", "/home/me")).toBe("/opt/other/app")
  expect(workspaceRootLabel("")).toBe("")
  const long = workspaceRootLabel("C:\\Users\\21986\\Desktop\\ican\\AI-PR-Review-Assistant", "")
  expect(long.length).toBe(30)
  expect(long.startsWith("…")).toBe(true)
})
