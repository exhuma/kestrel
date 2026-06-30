import { ref } from 'vue'
import { api } from '../api'
import type { SessionEvent, SessionSummary } from '../types/sessions'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

const sessions = ref<SessionSummary[]>([])
const events = ref<SessionEvent[]>([])
const loading = ref(false)

let source: EventSource | null = null

export function useSessions() {
  async function refresh(): Promise<void> {
    loading.value = true
    try {
      sessions.value = await api.get<SessionSummary[]>('/api/sessions')
    } finally {
      loading.value = false
    }
  }

  async function start(prompt: string): Promise<string> {
    const out = await api.post<{ session_id: string }>(
      '/api/sessions',
      { prompt },
    )
    await refresh()
    return out.session_id
  }

  async function resume(id: string, prompt: string): Promise<string> {
    const out = await api.post<{ session_id: string }>(
      `/api/sessions/${id}/resume`,
      { prompt },
    )
    await refresh()
    return out.session_id
  }

  function watchEvents(id: string): void {
    events.value = []
    if (source) source.close()
    source = new EventSource(`${BASE}/api/sessions/${id}/events`)
    source.onmessage = (e) => {
      events.value.push(JSON.parse(e.data) as SessionEvent)
    }
  }

  return { sessions, events, loading, refresh, start, resume, watchEvents }
}
