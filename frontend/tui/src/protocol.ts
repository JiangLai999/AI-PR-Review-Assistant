export type BackendRequest = {
  id: string
  method: string
  params?: Record<string, unknown>
}

export type BackendEvent = {
  id?: string | null
  ok?: boolean
  event?: string
  result?: any
  error?: { code?: string; message?: string }
  [key: string]: unknown
}

/** Drop late deltas from a cancelled turn, a previous session, or a restarted backend. */
export function isCurrentAssistantEvent(
  event: BackendEvent,
  sessionId: string | undefined,
  requestId: string | undefined,
): boolean {
  return Boolean(
    event.event?.startsWith("assistant.") &&
    sessionId &&
    requestId &&
    event.session_id === sessionId &&
    event.request_id === requestId,
  )
}

/**
 * Drop events that belong to another session (e.g. a review still running on a
 * session the user has already left).
 *
 * Events without a session id are kept: absence is not evidence of a foreign
 * session, and dropping them would silently hide global notifications.
 */
export function isForeignSessionEvent(event: BackendEvent, sessionId: string | undefined): boolean {
  const eventSession = typeof event.session_id === "string" ? event.session_id : ""
  return Boolean(eventSession && eventSession !== sessionId)
}
