import { ref } from 'vue'
import { api, API_BASE, ApiError } from '../api'
import type { SessionEvent, SessionSummary } from '../types/sessions'

const sessions = ref<SessionSummary[]>([])
const events = ref<SessionEvent[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

let source: EventSource | null = null

function describe(e: unknown): string {
  if (e instanceof ApiError) return `Request failed (${e.status})`
  if (e instanceof Error) return e.message
  return 'Unexpected error'
}

export function useSessions() {
  async function refresh(): Promise<void> {
    loading.value = true
    try {
      sessions.value = await api.get<SessionSummary[]>('/api/sessions')
    } finally {
      loading.value = false
    }
  }

  async function start(prompt: string): Promise<string | null> {
    error.value = null
    try {
      const out = await api.post<{ session_id: string }>(
        '/api/sessions',
        { prompt },
      )
      await refresh()
      return out.session_id
    } catch (e) {
      error.value = describe(e)
      return null
    }
  }

  async function resume(
    id: string,
    prompt: string,
  ): Promise<string | null> {
    error.value = null
    try {
      const out = await api.post<{ session_id: string }>(
        `/api/sessions/${id}/resume`,
        { prompt },
      )
      await refresh()
      return out.session_id
    } catch (e) {
      error.value = describe(e)
      return null
    }
  }

  function watchEvents(id: string): void {
    events.value = []
    if (source) source.close()
    source = new EventSource(`${API_BASE}/api/sessions/${id}/events`)
    source.onmessage = (e) => {
      const event = JSON.parse(e.data) as SessionEvent
      events.value.push(event)
      // A result event ends a run — refresh so the session's status
      // flips running -> idle in the list without a manual reload.
      if (event.type === 'result') void refresh()
    }
  }

  function stopEvents(): void {
    if (source) {
      source.close()
      source = null
    }
    events.value = []
  }

  async function remove(id: string): Promise<void> {
    error.value = null
    try {
      await api.del(`/api/sessions/${id}`)
      await refresh()
    } catch (e) {
      error.value = describe(e)
    }
  }

  return {
    sessions,
    events,
    loading,
    error,
    refresh,
    start,
    resume,
    watchEvents,
    stopEvents,
    remove,
  }
}
