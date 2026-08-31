import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('setAuthSuccessHandler', () => {
  it('fires on a successful response', async () => {
    const { api, setAuthSuccessHandler } = await import('../../src/api')
    const onSuccess = vi.fn()
    setAuthSuccessHandler(onSuccess)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({}), { status: 200 })),
    )
    await api.get('/api/whatever')
    expect(onSuccess).toHaveBeenCalledTimes(1)
  })

  it('does not fire on a 401', async () => {
    const { api, setAuthSuccessHandler, ApiError } = await import(
      '../../src/api'
    )
    const onSuccess = vi.fn()
    setAuthSuccessHandler(onSuccess)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('nope', { status: 401 })),
    )
    await expect(api.get('/api/whatever')).rejects.toBeInstanceOf(ApiError)
    expect(onSuccess).not.toHaveBeenCalled()
  })
})
