import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function stubFetchSequence(responses: unknown[]) {
  const queue = [...responses]
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      const body = queue.shift()
      return new Response(JSON.stringify(body), { status: 200 })
    }),
  )
}

async function loadModule() {
  vi.resetModules()
  return import('../../src/auth/sseTicket')
}

describe('eventSourceUrl', () => {
  it('returns the plain URL, with no ticket fetch, when auth is disabled', async () => {
    stubFetchSequence([{ enabled: false, authority: '', client_id: '' }])
    const { eventSourceUrl } = await loadModule()
    const url = await eventSourceUrl('/api/workflows/events')
    expect(url).toBe('http://localhost:8000/api/workflows/events')
    expect(fetch).toHaveBeenCalledTimes(1) // only the /api/auth/config call
  })

  it('appends a ticket when auth is enabled', async () => {
    stubFetchSequence([
      {
        enabled: true,
        authority: 'https://idp.example.com/realms/kestrel',
        client_id: 'kestrel-spa',
      },
      { ticket: 'abc123' },
    ])
    const { eventSourceUrl } = await loadModule()
    const url = await eventSourceUrl('/api/workflows/events')
    expect(url).toBe(
      'http://localhost:8000/api/workflows/events?ticket=abc123',
    )
  })
})
