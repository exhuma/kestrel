import { describe, it, expect, vi, afterEach } from 'vitest'
import { useNotifications } from '../../src/composables/useNotifications'

afterEach(() => {
  useNotifications().stop()
  vi.restoreAllMocks()
  vi.useRealTimers()
})

const sample = [
  {
    id: 2, workflow_id: 'wf-1', repo: 'o/r', issue_number: 5,
    status: 'done', message: 'PR opened for o/r#5.',
    created_at: '2026-07-03T00:00:00Z', read: false,
  },
  {
    id: 1, workflow_id: 'wf-1', repo: 'o/r', issue_number: 5,
    status: 'awaiting_plan_approval',
    message: 'Implementation plan ready for review: o/r#5.',
    created_at: '2026-07-02T00:00:00Z', read: true,
  },
]

describe('useNotifications', () => {
  it('refresh populates items and unreadCount', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(sample), { status: 200 })),
    )
    const { items, unreadCount, refresh } = useNotifications()
    await refresh()
    expect(items.value.map((n) => n.id)).toEqual([2, 1])
    expect(unreadCount.value).toBe(1)
  })

  it('markRead posts then refreshes', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) =>
      String(input).includes('/read')
        ? new Response(JSON.stringify({ status: 'ok' }), { status: 200 })
        : new Response(JSON.stringify(sample), { status: 200 }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const { markRead } = useNotifications()
    await markRead(1)
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/notifications/1/read'),
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('start opens a stream that populates items; stop closes it', () => {
    const close = vi.fn()
    let es: FakeEventSource | null = null
    class FakeEventSource {
      onmessage: ((e: MessageEvent) => void) | null = null
      close = close
      constructor(public url: string) {
        es = this
      }
    }
    vi.stubGlobal('EventSource', FakeEventSource)

    const { items, unreadCount, start, stop } = useNotifications()
    start()
    expect(es!.url).toContain('/api/notifications/events')
    es!.onmessage?.({
      data: JSON.stringify({ notifications: sample }),
    } as MessageEvent)
    expect(items.value.map((n) => n.id)).toEqual([2, 1])
    expect(unreadCount.value).toBe(1)

    stop()
    expect(close).toHaveBeenCalled()
  })
})
