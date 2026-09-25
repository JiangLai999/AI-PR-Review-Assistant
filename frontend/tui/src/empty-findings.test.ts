import { expect, test } from "bun:test"
import { emptyFindingsMessage } from "./empty-findings"

test("a finished review with zero findings never tells the user to run the review again", () => {
  const message = emptyFindingsMessage("list", { hasReport: true, prNumber: 29, repository: "o/r" })

  expect(message).toContain("未发现问题")
  expect(message).toContain("o/r#29")
  expect(message).not.toContain("/review")
  expect(message).toContain("/report")
})

test("filtered candidates are explained with the recorded threshold", () => {
  const message = emptyFindingsMessage("list", {
    hasReport: true,
    prNumber: 29,
    runId: "6aa63659-1111-2222-3333-444444444444",
    threshold: 0.6,
    belowThreshold: 3,
  })

  expect(message).toContain("3 条候选")
  expect(message).toContain("0.60")
  expect(message).toContain("已过滤")
})

test("a run without threshold data simply reports zero findings", () => {
  const message = emptyFindingsMessage("list", { hasReport: true, runId: "6aa63659-aaaa" })

  expect(message).toContain("run 6aa63659")
  expect(message).not.toContain("门槛")
})

test("a review still running explains itself instead of implying no findings", () => {
  const message = emptyFindingsMessage("list", { running: true, hasReport: false })

  expect(message).toContain("仍在进行中")
})

test("a failed attempt is described as unfinished, not as a clean review", () => {
  const message = emptyFindingsMessage("list", { failed: true, hasReport: false })

  expect(message).toContain("没有完成")
  expect(message).toContain("Ctrl+R")
  expect(message).not.toContain("未发现问题")
})

test("without any review the original guidance is kept", () => {
  expect(emptyFindingsMessage("list", {})).toContain("/review")
  expect(emptyFindingsMessage("filter", {})).toContain("/history")
  expect(emptyFindingsMessage("feedback", {})).toContain("/review")
})

test("each entry point gets its own closing hint when the review is clean", () => {
  const base = { hasReport: true, prNumber: 29 }

  expect(emptyFindingsMessage("filter", base)).toContain("没有需要筛选的问题")
  expect(emptyFindingsMessage("feedback", base)).toContain("没有需要反馈的问题")
  expect(emptyFindingsMessage("list", base)).toContain("/report")
})

test("english wording mirrors the chinese one", () => {
  const message = emptyFindingsMessage("list", {
    hasReport: true,
    prNumber: 29,
    threshold: 0.6,
    belowThreshold: 2,
    language: "en",
  })

  expect(message).toContain("found no problems")
  expect(message).toContain("PR #29")
  expect(message).toContain("confidence threshold 0.60")
  expect(message).not.toContain("/review")
})
