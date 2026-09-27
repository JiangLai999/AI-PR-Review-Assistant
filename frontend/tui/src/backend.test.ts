import { expect, test } from "bun:test"
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { resolve } from "node:path"
import { join } from "node:path"
import { BackendClient } from "./backend"

const root = resolve(import.meta.dir, "../../../")
const python = resolve(root, ".venv313/Scripts/python.exe")

const localTest = existsSync(python) ? test : test.skip
localTest("unexpected backend exit keeps persisted sessions alive (multi-session store)", async () => {
  const previousRoot = process.env.AI_PR_REVIEW_ROOT
  const previousPython = process.env.AI_PR_REVIEW_PYTHON
  const previousConfig = process.env.AI_PR_REVIEW_CONFIG
  process.env.AI_PR_REVIEW_ROOT = root
  process.env.AI_PR_REVIEW_PYTHON = python
  process.env.AI_PR_REVIEW_CONFIG = resolve(root, ".ai_pr_review/tui-test-nonexistent.json")
  const client = new BackendClient()
  try {
    expect((await client.request("health")).ok).toBe(true)
    const original = await client.request("session.create")
    expect(original.ok).toBe(true)
    const firstGeneration = client.generation
    await client.stop()
    expect((await client.request("health")).ok).toBe(true)
    expect(client.generation).toBe(firstGeneration + 1)
    const stale = await client.request("session.get", { session_id: original.result.session_id })
    // 2026-09-27 多会话存储落地（docs/claude-sessions-compaction.md）：会话持久化到
    // `sessions/` 目录，后端重启后旧 session_id **仍然有效**——这是行为升级
    // （重启不再丢会话），不是回归。generation 递增仍证明是新进程。
    expect(stale.ok).toBe(true)
    expect((await client.request("session.create")).ok).toBe(true)
  } finally {
    await client.stop()
    if (previousRoot === undefined) delete process.env.AI_PR_REVIEW_ROOT
    else process.env.AI_PR_REVIEW_ROOT = previousRoot
    if (previousPython === undefined) delete process.env.AI_PR_REVIEW_PYTHON
    else process.env.AI_PR_REVIEW_PYTHON = previousPython
    if (previousConfig === undefined) delete process.env.AI_PR_REVIEW_CONFIG
    else process.env.AI_PR_REVIEW_CONFIG = previousConfig
  }
})

localTest("request timeout rejects instead of hanging the composer forever", async () => {
  const previousRoot = process.env.AI_PR_REVIEW_ROOT
  const previousPython = process.env.AI_PR_REVIEW_PYTHON
  const previousConfig = process.env.AI_PR_REVIEW_CONFIG
  // A stand-in backend that accepts stdin but never answers, so the only way
  // out of the pending request is the client-side timeout.
  const root = mkdtempSync(join(tmpdir(), "tui-timeout-"))
  mkdirSync(join(root, "ai_pr_review", "backend"), { recursive: true })
  writeFileSync(join(root, "ai_pr_review", "__init__.py"), "")
  writeFileSync(join(root, "ai_pr_review", "backend", "__init__.py"), "")
  writeFileSync(
    join(root, "ai_pr_review", "backend", "jsonl_server.py"),
    "import time\nwhile True:\n    time.sleep(3600)\n",
  )
  process.env.AI_PR_REVIEW_ROOT = root
  process.env.AI_PR_REVIEW_PYTHON = python
  delete process.env.AI_PR_REVIEW_CONFIG
  const client = new BackendClient()
  try {
    const started = Date.now()
    await expect(client.request("health", {}, { timeoutMs: 1500 })).rejects.toThrow()
    expect(Date.now() - started).toBeLessThan(10000)
  } finally {
    await client.stop()
    rmSync(root, { recursive: true, force: true })
    if (previousRoot === undefined) delete process.env.AI_PR_REVIEW_ROOT
    else process.env.AI_PR_REVIEW_ROOT = previousRoot
    if (previousPython === undefined) delete process.env.AI_PR_REVIEW_PYTHON
    else process.env.AI_PR_REVIEW_PYTHON = previousPython
    if (previousConfig === undefined) delete process.env.AI_PR_REVIEW_CONFIG
    else process.env.AI_PR_REVIEW_CONFIG = previousConfig
  }
})


