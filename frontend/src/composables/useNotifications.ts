import { computed, ref } from 'vue'
import { api } from '../api'
import type { Notification } from '../types/notifications'

const items = ref<Notification[]>([])
let poll: ReturnType<typeof setInterval> | null = null

export function useNotifications() {
  async function refresh(): Promise<void> {
    items.value = await api.get<Notification[]>('/api/notifications')
  }

  async function markRead(id: number): Promise<void> {
    await api.post(`/api/notifications/${id}/read`)
    await refresh()
  }

  function start(): void {
    if (poll) return
    void refresh()
    poll = setInterval(() => void refresh(), 5000)
  }

  function stop(): void {
    if (poll) {
      clearInterval(poll)
      poll = null
    }
  }

  const unreadCount = computed(() => items.value.filter((n) => !n.read).length)

  return { items, unreadCount, refresh, markRead, start, stop }
}
