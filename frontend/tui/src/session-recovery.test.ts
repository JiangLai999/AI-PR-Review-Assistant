import { expect, test } from "bun:test"
import { sendWithSessionRecovery } from "./session-recovery"

test("rebuilds a missing session and retries exactly once", async () => {
  const force: Array<boolean | undefined> = []
  const requests: string[] = []
  const response = await sendWithSessionRecovery(
    async (forced) => { force.push(forced); return forced ? "new" : "stale" },
    async (session) => {
      requests.push(session)
      return session === "stale"
        ? { ok: false, error: { code: "not_found", message: "Session not found" } }
        : { ok: true, result: { text: "ok" } }
    },
  )
  expect(response.ok).toBe(true)
  expect(force).toEqual([undefined, true])
  expect(requests).toEqual(["stale", "new"])
})

test("never replays a request after ambiguous transport/backend failure", async () => {
  const requests: string[] = []
  const response = await sendWithSessionRecovery(
    async () => "old",
    async (session) => { requests.push(session); return { ok: false, error: { code: "backend_error" } } },
  )
  expect(response.ok).toBe(false)
  expect(requests).toEqual(["old"])
})
