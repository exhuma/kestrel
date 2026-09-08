import { describe, it, expect, vi, afterEach } from 'vitest'
import { useSourceHealth } from '../../src/composables/useSourceHealth'

afterEach(() => {
  useSourceHealth().stop()
  vi.restoreAllMocks()
})

const sample = [
  { name: 'github', state: 'healthy', checked_at: '2026-09-08T10:00:00' },
  { name: 'jira', state: 'unhealthy', checked_at: '2026-09-08T10:00:00' },
]

describe('useSourceHealth', () => {
  it('refresh populates items', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(sample), { status: 200 })),
    )
    const { items, refresh } = useSourceHealth()
    await refresh()
    expect(items.value.map((h) => h.name)).toEqual(['github', 'jira'])
  })

  it('recheck posts to the refresh endpoint', async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(JSON.stringify({ status: 'accepted' }), { status: 202 }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const { recheck } = useSourceHealth()
    await recheck('github')
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/health/github/refresh'),
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

    const { items, start, stop } = useSourceHealth()
    start()
    expect(es!.url).toContain('/api/health/events')
    es!.onmessage?.({
      data: JSON.stringify({ health: sample }),
    } as MessageEvent)
    expect(items.value.map((h) => h.name)).toEqual(['github', 'jira'])

    stop()
    expect(close).toHaveBeenCalled()
  })
})
