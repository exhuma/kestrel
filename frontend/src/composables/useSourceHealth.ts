import { ref } from 'vue'
import { api, API_BASE } from '../api'
import type { SourceHealth } from '../types/health'

const items = ref<SourceHealth[]>([])
let source: EventSource | null = null

export function useSourceHealth() {
  async function refresh(): Promise<void> {
    items.value = await api.get<SourceHealth[]>('/api/health')
  }

  async function recheck(name: string): Promise<void> {
    await api.post(`/api/health/${name}/refresh`)
    // The server-side check ticks the bus once it completes, which
    // pushes the updated list back down the stream — no manual refetch.
  }

  function start(): void {
    if (source) return
    // Push, don't poll: the server streams the full list on connect and
    // again on every change (a completed background cycle or a manual
    // refresh landing).
    source = new EventSource(`${API_BASE}/api/health/events`)
    source.onmessage = (e) => {
      const data = JSON.parse(e.data) as { health: SourceHealth[] }
      items.value = data.health
    }
  }

  function stop(): void {
    if (source) {
      source.close()
      source = null
    }
  }

  return { items, refresh, recheck, start, stop }
}
