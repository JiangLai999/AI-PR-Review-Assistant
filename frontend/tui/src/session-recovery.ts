import type { BackendEvent } from "./protocol"

/** Retry only a definitive not_found (nothing executed), never a timeout/transport error. */
export async function sendWithSessionRecovery(
  ensureSession: (force?: boolean) => Promise<string>,
  send: (sessionId: string) => Promise<BackendEvent>,
): Promise<BackendEvent> {
  const first = await send(await ensureSession())
  if (first.ok || first.error?.code !== "not_found") return first
  return send(await ensureSession(true))
}
