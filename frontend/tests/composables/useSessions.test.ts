import { describe, it, expect, vi, afterEach } from 'vitest'
import { useSessions } from '../../src/composables/useSessions'

afterEach(() => vi.restoreAllMocks())

describe('useSessions', () => {
  it('refresh populates sessions from api', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(
            JSON.stringify([
              { session_id: 's1', status: 'idle', event_count: 2 },
            ]),
            { status: 200 },
          ),
      ),
    )
    const { sessions, refresh } = useSessions()
    await refresh()
    expect(sessions.value.map((s) => s.session_id)).toContain('s1')
  })

  it('refreshes the session list when a result event streams in', async () => {
    let handler: ((e: { data: string }) => void) | null = null
    class FakeEventSource {
      constructor(public url: string) {}
      set onmessage(fn: (e: { data: string }) => void) {
        handler = fn
      }
      close(): void {}
    }
    vi.stubGlobal('EventSource', FakeEventSource)
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify([]), { status: 200 }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const { watchEvents } = useSessions()
    watchEvents('s1')
    const before = fetchMock.mock.calls.length

    handler!({
      data: JSON.stringify({ kind: 'result', session_id: 's1', native: {} }),
    })
    await Promise.resolve()
    await Promise.resolve()

    expect(fetchMock.mock.calls.length).toBeGreaterThan(before)
  })

  it('surfaces a failed start via the error ref', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(JSON.stringify({ detail: 'boom' }), { status: 502 }),
      ),
    )
    const { error, start } = useSessions()
    await start('hi')
    expect(error.value).toBeTruthy()
  })
})
