import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useConnectivity } from '../../src/composables/useConnectivity'
import { api } from '../../src/api'

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(async () => {
  // Drain any pending retry interval and restore reachable=true — the
  // module-level signal is a singleton shared across every test in this file.
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response('{}', { status: 200 })),
  )
  await api.get('/livez').catch(() => {})
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('useConnectivity', () => {
  it('starts reachable and flips false on a network failure', async () => {
    const { reachable } = useConnectivity()
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch')
      }),
    )
    await api.get('/x').catch(() => {})
    expect(reachable.value).toBe(false)
  })

  it('flips back to true once a request resolves again', async () => {
    const { reachable } = useConnectivity()
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch')
      }),
    )
    await api.get('/x').catch(() => {})
    expect(reachable.value).toBe(false)

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('{}', { status: 200 })),
    )
    await api.get('/x').catch(() => {})
    expect(reachable.value).toBe(true)
  })

  it('probes /livez on an interval while unreachable, then stops once healthy', async () => {
    useConnectivity()
    let healthy = false
    const fetchMock = vi.fn(async () => {
      if (!healthy) throw new TypeError('Failed to fetch')
      return new Response('{}', { status: 200 })
    })
    vi.stubGlobal('fetch', fetchMock)

    await api.get('/x').catch(() => {}) // trip unreachable, arms the retry
    await vi.advanceTimersByTimeAsync(5000)
    const livezCalls = fetchMock.mock.calls.filter((c) =>
      String(c[0]).endsWith('/livez'),
    )
    expect(livezCalls.length).toBeGreaterThanOrEqual(1)

    healthy = true
    await vi.advanceTimersByTimeAsync(5000) // this probe succeeds, stops the timer
    const callsAfterRecovery = fetchMock.mock.calls.length

    await vi.advanceTimersByTimeAsync(20000) // no further probes should land
    expect(fetchMock.mock.calls.length).toBe(callsAfterRecovery)
  })
})
