import type { SessionEvent } from '../types/sessions'

export interface SessionEventStreamHandle {
  close(): void
}

const RECONNECT_DELAY_MS = 2000

/**
 * Open a resumable, de-duplicated SSE stream for one session's events.
 *
 * The backend tags each frame with an `id:` sequence number and honours
 * `Last-Event-ID` on the browser's own automatic reconnect, so a
 * transient drop resumes instead of replaying the full history from
 * scratch. This wrapper adds a second, independent safety net: it never
 * applies a frame whose id isn't strictly newer than the last one it
 * saw, so even a full replay (e.g. a manual reopen after the browser
 * gives up, which carries no Last-Event-ID) can't make the timeline
 * grow from duplicated content.
 *
 * Takes the full events URL rather than a session id/API_BASE so this
 * shared leaf module never depends on the api client (see
 * .dependency-cruiser.cjs's shared-leaves-do-not-import-up rule).
 */
export function openSessionEventStream(
  url: string,
  onEvent: (event: SessionEvent) => void,
): SessionEventStreamHandle {
  let closed = false
  let lastSeenId = 0
  let source: EventSource

  function handleMessage(e: MessageEvent): void {
    const incomingId = e.lastEventId ? Number(e.lastEventId) : 0
    if (incomingId && incomingId <= lastSeenId) return
    if (incomingId) lastSeenId = incomingId
    onEvent(JSON.parse(e.data) as SessionEvent)
  }

  function open(): void {
    source = new EventSource(url)
    source.onmessage = handleMessage
    source.onerror = () => {
      // The browser auto-reconnects on a transient drop (carrying
      // Last-Event-ID itself); only step in once it gives up entirely.
      if (!closed && source.readyState === EventSource.CLOSED) {
        setTimeout(() => {
          if (!closed) open()
        }, RECONNECT_DELAY_MS)
      }
    }
  }

  open()
  return {
    close(): void {
      closed = true
      source.close()
    },
  }
}
