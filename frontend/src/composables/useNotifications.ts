import { computed, ref } from 'vue'
import { api, API_BASE } from '../api'
import type { Notification } from '../types/notifications'

const items = ref<Notification[]>([])
let source: EventSource | null = null

export function useNotifications() {
  async function refresh(): Promise<void> {
    items.value = await api.get<Notification[]>('/api/notifications')
  }

  async function markRead(id: number): Promise<void> {
    await api.post(`/api/notifications/${id}/read`)
    // Marking read ticks the server bus, which pushes the updated
    // list back down the stream — no manual refetch needed.
  }

  function start(): void {
    if (source) return
    // Push, don't poll: the server streams the full list on connect and
    // again on every change (new notification or one marked read).
    source = new EventSource(`${API_BASE}/api/notifications/events`)
    source.onmessage = (e) => {
      const data = JSON.parse(e.data) as { notifications: Notification[] }
      items.value = data.notifications
    }
  }

  function stop(): void {
    if (source) {
      source.close()
      source = null
    }
  }

  const unreadCount = computed(() => items.value.filter((n) => !n.read).length)

  // Split by signal class so the UI can separate gates that block on the
  // human from terminal catch-up items (module-notification-alarm-discipline).
  const actionRequired = computed(() =>
    items.value.filter((n) => n.signal_class === 'action_required'),
  )
  const summaries = computed(() =>
    items.value.filter((n) => n.signal_class === 'summary'),
  )
  // Badge = things still needing action, not "unread everything": an unread
  // summary is catch-up, not a call to act.
  const actionRequiredCount = computed(
    () => actionRequired.value.filter((n) => !n.read).length,
  )

  return {
    items,
    unreadCount,
    actionRequired,
    summaries,
    actionRequiredCount,
    refresh,
    markRead,
    start,
    stop,
  }
}
