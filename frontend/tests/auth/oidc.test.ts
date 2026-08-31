import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function stubConfigFetch(body: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(body), { status: 200 })),
  )
}

async function loadOidc() {
  vi.resetModules()
  return import('../../src/auth/oidc')
}

describe('initAuth', () => {
  it('returns a no-op stand-in when auth is disabled', async () => {
    stubConfigFetch({ enabled: false, authority: '', client_id: '' })
    const { initAuth } = await loadOidc()
    const state = await initAuth()
    expect(state.enabled).toBe(false)
    expect(state.userManager).toBeNull()
  })

  it('constructs a real UserManager when enabled with valid config', async () => {
    stubConfigFetch({
      enabled: true,
      authority: 'https://idp.example.com/realms/kestrel',
      client_id: 'kestrel-spa',
    })
    const { initAuth } = await loadOidc()
    const state = await initAuth()
    expect(state.enabled).toBe(true)
    expect(state.userManager).not.toBeNull()
    expect(state.userManager?.settings.client_id).toBe('kestrel-spa')
  })

  it('throws when enabled but authority is empty (fail-loud)', async () => {
    stubConfigFetch({ enabled: true, authority: '', client_id: 'kestrel-spa' })
    const { initAuth } = await loadOidc()
    await expect(initAuth()).rejects.toThrow(/misconfigured/)
  })

  it('throws when enabled but client_id is empty (fail-loud)', async () => {
    stubConfigFetch({
      enabled: true,
      authority: 'https://idp.example.com/realms/kestrel',
      client_id: '',
    })
    const { initAuth } = await loadOidc()
    await expect(initAuth()).rejects.toThrow(/misconfigured/)
  })

  it('caches the result across repeated calls (fetches config once)', async () => {
    stubConfigFetch({ enabled: false, authority: '', client_id: '' })
    const { initAuth } = await loadOidc()
    const first = await initAuth()
    const second = await initAuth()
    expect(second).toBe(first)
    expect(fetch).toHaveBeenCalledTimes(1)
  })
})
