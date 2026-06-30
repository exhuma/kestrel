import { describe, it, expect, vi, afterEach } from 'vitest'
import { api, ApiError } from '../../src/api'

afterEach(() => vi.restoreAllMocks())

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
})
