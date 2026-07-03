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

  it('start polls on an interval until stop', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(sample), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    const { start, stop } = useNotifications()
    start()
    await vi.advanceTimersByTimeAsync(0)
    const afterStart = fetchMock.mock.calls.length
    await vi.advanceTimersByTimeAsync(5000)
    expect(fetchMock.mock.calls.length).toBeGreaterThan(afterStart)
    stop()
    const afterStop = fetchMock.mock.calls.length
    await vi.advanceTimersByTimeAsync(10000)
    expect(fetchMock.mock.calls.length).toBe(afterStop)
  })
})
