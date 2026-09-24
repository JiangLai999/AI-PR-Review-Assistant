import type { BackendEvent, BackendRequest } from "./protocol"

export class BackendClient {
  private process?: ReturnType<typeof Bun.spawn>
  private nextId = 1
  private processGeneration = 0

  get generation(): number {
    return this.processGeneration
  }
  private backendErrors: string[] = []
  private pending = new Map<string, { resolve: (event: BackendEvent) => void; reject: (error: Error) => void }>()
  private listeners = new Set<(event: BackendEvent) => void>()

  async start(): Promise<void> {
    if (this.process?.exitCode === null) return
    if (this.process) {
      this.rejectPending(new Error("Python backend exited"))
      this.process = undefined
    }
    const python = process.env.AI_PR_REVIEW_PYTHON ?? "python"
    const cwd = process.env.AI_PR_REVIEW_ROOT ?? process.cwd()
    const spawned = Bun.spawn([python, "-m", "ai_pr_review.backend.jsonl_server"], {
      cwd,
      stdin: "pipe",
      stdout: "pipe",
      stderr: "pipe",
    })
    this.process = spawned
    this.processGeneration += 1
    const stdout = spawned.stdout
    if (stdout instanceof ReadableStream) {
      void this.readOutput(stdout, spawned)
    }
    const stderr = spawned.stderr
    if (stderr instanceof ReadableStream) {
      // A verbose backend must never block on a full stderr pipe, and its last
      // lines are the only useful diagnostics when the process dies.
      void this.readErrors(stderr, spawned)
    }
  }

  onEvent(listener: (event: BackendEvent) => void): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  async request(
    method: string,
    params: Record<string, unknown> = {},
    options?: { onId?: (id: string) => void; timeoutMs?: number },
  ): Promise<BackendEvent> {
    await this.start()
    const id = String(this.nextId++)
    options?.onId?.(id)
    const request: BackendRequest = { id, method, params }
    const promise = new Promise<BackendEvent>((resolve, reject) => this.pending.set(id, { resolve, reject }))
    const stdin = this.process!.stdin
    if (typeof stdin === "number" || !stdin) throw new Error("Backend stdin is unavailable")
    try {
      stdin.write(JSON.stringify(request) + "\n")
    } catch (error) {
      this.pending.delete(id)
      throw error
    }
    if (options?.timeoutMs && options.timeoutMs > 0) {
      const timeoutMs = options.timeoutMs
      const timer = setTimeout(() => {
        const entry = this.pending.get(id)
        if (!entry) return
        this.pending.delete(id)
        entry.reject(new Error(`后端请求超时（${Math.round(timeoutMs / 1000)}s）：${method}`))
      }, timeoutMs)
      const entry = this.pending.get(id)
      if (entry) {
        this.pending.set(id, {
          resolve: (event) => { clearTimeout(timer); entry.resolve(event) },
          reject: (error) => { clearTimeout(timer); entry.reject(error) },
        })
      }
    }
    return promise
  }

  async stop(): Promise<void> {
    const process = this.process
    if (!process) return
    process.kill()
    try {
      await process.exited
    } catch {
      // The process may already have exited; cleanup remains idempotent.
    }
    this.rejectPending(new Error("Python backend stopped"))
    if (this.process === process) this.process = undefined
  }

  private rejectPending(error: Error): void {
    for (const pending of this.pending.values()) pending.reject(error)
    this.pending.clear()
  }

  private async readErrors(
    stream: ReadableStream<Uint8Array>,
    spawned: ReturnType<typeof Bun.spawn>,
  ): Promise<void> {
    const decoder = new TextDecoder()
    let buffer = ""
    try {
      for await (const chunk of stream) {
        buffer += decoder.decode(chunk, { stream: true })
        const lines = buffer.split("\n")
        buffer = lines.pop() ?? ""
        for (const line of lines) {
          if (!line.trim() || this.process !== spawned) continue
          this.backendErrors.push(line)
          if (this.backendErrors.length > 20) this.backendErrors.shift()
        }
      }
    } catch {
      // Diagnostics are best-effort; the stdout stream owns lifecycle state.
    }
  }

  private async readOutput(
    stream: ReadableStream<Uint8Array>,
    spawned: ReturnType<typeof Bun.spawn>,
  ): Promise<void> {
    const decoder = new TextDecoder()
    let buffer = ""
    try {
      for await (const chunk of stream) {
        buffer += decoder.decode(chunk, { stream: true })
        const lines = buffer.split("\n")
        buffer = lines.pop() ?? ""
        for (const line of lines) {
          if (!line.trim()) continue
          try {
            const event = JSON.parse(line) as BackendEvent
            if (event.id && this.pending.has(event.id)) {
              this.pending.get(event.id)!.resolve(event)
              this.pending.delete(event.id)
            }
            for (const listener of this.listeners) listener(event)
          } catch {
            // Backend stdout is a protocol stream; ignore malformed frames defensively.
          }
        }
      }
    } finally {
      // Closing/aborting a pipe can throw before the normal EOF branch.
      if (this.process === spawned) {
        const tail = this.backendErrors.length > 0 ? `\n${this.backendErrors.join("\n")}` : ""
        this.backendErrors = []
        this.rejectPending(new Error(`Python backend connection closed${tail}`))
        this.process = undefined
      }
    }

  }
}


