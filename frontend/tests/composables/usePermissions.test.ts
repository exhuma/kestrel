import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function stubPermissionsFetch(body: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(body), { status: 200 })),
  )
}

async function loadModule() {
  vi.resetModules()
  return import('../../src/composables/usePermissions')
}

describe('usePermissions', () => {
  it('treats the "*" sentinel as always-true (auth disabled)', async () => {
    stubPermissionsFetch({
      sub: null,
      email: null,
      preferred_username: null,
      permissions: ['*'],
    })
    const { usePermissions } = await loadModule()
    const { can } = usePermissions()
    // Fetch resolves asynchronously; can() must still be truthy once it
    // lands, for absolutely any permission string.
    await vi.waitFor(() => expect(can('workflows:cleanup')).toBe(true))
    expect(can('anything-not-in-the-vocabulary')).toBe(true)
  })

  it('reflects the fetched permission set exactly', async () => {
    stubPermissionsFetch({
      sub: 'user-1',
      email: null,
      preferred_username: null,
      permissions: ['workflows:approve'],
    })
    const { usePermissions } = await loadModule()
    const { can } = usePermissions()
    await vi.waitFor(() => expect(can('workflows:approve')).toBe(true))
    expect(can('workflows:cleanup')).toBe(false)
  })

  it('fetches exactly once regardless of how many callers', async () => {
    stubPermissionsFetch({
      sub: null,
      email: null,
      preferred_username: null,
      permissions: ['*'],
    })
    const { usePermissions } = await loadModule()
    usePermissions()
    usePermissions()
    const { can } = usePermissions()
    await vi.waitFor(() => expect(can('x')).toBe(true))
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('defaults to no permissions while the fetch is still in flight', async () => {
    stubPermissionsFetch({
      sub: null,
      email: null,
      preferred_username: null,
      permissions: ['workflows:approve'],
    })
    const { usePermissions } = await loadModule()
    const { can } = usePermissions()
    // Synchronously, before the fetch resolves: safe default is "no".
    expect(can('workflows:approve')).toBe(false)
  })
})
