import { describe, it, expect, vi, afterEach } from 'vitest'
import { useSessions } from '../../src/composables/useSessions'

afterEach(() => vi.restoreAllMocks())

describe('useSessions', () => {
  it('refresh populates sessions from api', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
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

  it('surfaces a failed start via the error ref', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ detail: 'boom' }), { status: 502 }),
      ),
    )
    const { error, start } = useSessions()
    await start('hi')
    expect(error.value).toBeTruthy()
  })
})
