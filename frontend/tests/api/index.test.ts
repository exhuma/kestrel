import { describe, it, expect, vi, afterEach } from 'vitest'
import { api, ApiError, setUnauthorizedHandler } from '../../src/api'

afterEach(() => {
  vi.restoreAllMocks()
  setUnauthorizedHandler(() => {})
})

describe('api', () => {
  it('returns parsed json on success', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ ok: true }), { status: 200 }),
      ),
    )
    const data = await api.get<{ ok: boolean }>('/x')
    expect(data.ok).toBe(true)
  })

  it('throws ApiError on non-2xx', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('nope', { status: 500 })),
    )
    await expect(api.get('/x')).rejects.toBeInstanceOf(ApiError)
  })

  it('invokes the unauthorized handler on 401', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('no', { status: 401 })),
    )
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)
    await expect(api.get('/x')).rejects.toBeInstanceOf(ApiError)
    expect(onUnauthorized).toHaveBeenCalledOnce()
  })

  it('sends the right method for put and delete', async () => {
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify({}), { status: 200 }),
    )
    vi.stubGlobal('fetch', fetchMock)
    await api.put('/x', { a: 1 })
    await api.delete('/x')
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: 'PUT' })
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: 'DELETE' })
  })
})
