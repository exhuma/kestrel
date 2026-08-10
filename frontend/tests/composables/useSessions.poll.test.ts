import { describe, it, expect, vi, afterEach } from 'vitest'
import { useSessions } from '../../src/composables/useSessions'

afterEach(() => vi.restoreAllMocks())

describe('useSessions poll', () => {
  it('poll updates the matching session in place', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith('/api/sessions')) {
        return new Response(
          JSON.stringify([
            { session_id: 's1', status: 'running', event_count: 0 },
          ]),
          { status: 200 },
        )
      }
      return new Response(
        JSON.stringify({ session_id: 's1', status: 'error', event_count: 1 }),
        { status: 200 },
      )
    })
    vi.stubGlobal('fetch', fetchMock)

    const { sessions, refresh, poll } = useSessions()
    await refresh()
    await poll('s1')

    expect(sessions.value.find((s) => s.session_id === 's1')?.status).toBe(
      'error',
    )
  })

  it('surfaces a failed poll via the error ref', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(JSON.stringify({ detail: 'boom' }), { status: 502 }),
      ),
    )
    const { error, poll } = useSessions()
    await poll('s1')
    expect(error.value).toBeTruthy()
  })
})
