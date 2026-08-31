import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

beforeEach(() => {
  sessionStorage.clear()
})

afterEach(() => {
  vi.restoreAllMocks()
})

async function loadGuard() {
  vi.resetModules()
  return import('../../src/auth/reauthGuard')
}

describe('handleUnauthorized', () => {
  it('redirects once on a genuine expiry', async () => {
    const { handleUnauthorized, authError } = await loadGuard()
    const redirect = vi.fn()
    handleUnauthorized(redirect)
    expect(redirect).toHaveBeenCalledTimes(1)
    expect(authError.value).toBeNull()
    expect(sessionStorage.getItem('kestrel.reauthAttempts')).toBe('1')
  })

  it('trips the breaker on the next 401 after a redirect round-trip', async () => {
    // A real signinRedirect() navigates the page away, so the second 401
    // arrives on a fresh page load (a new module instance) — the
    // sessionStorage attempt counter is what carries "already tried once"
    // across that navigation; redirectInFlight itself resets naturally.
    const first = await loadGuard()
    first.handleUnauthorized(vi.fn())

    const second = await loadGuard()
    const redirect = vi.fn()
    second.handleUnauthorized(redirect)
    // The fresh token was still rejected -> no second redirect, just the
    // surfaced error.
    expect(redirect).not.toHaveBeenCalled()
    expect(second.authError.value).toMatch(/could not be authenticated/)
  })

  it('collapses a burst of near-simultaneous 401s into one redirect', async () => {
    const { handleUnauthorized } = await loadGuard()
    const redirect = vi.fn()
    handleUnauthorized(redirect)
    handleUnauthorized(redirect)
    handleUnauthorized(redirect)
    expect(redirect).toHaveBeenCalledTimes(1)
  })
})

describe('notifyAuthSuccess', () => {
  it('clears the attempt counter so a later, unrelated 401 gets its own redirect', async () => {
    const first = await loadGuard()
    first.handleUnauthorized(vi.fn())
    first.notifyAuthSuccess()
    expect(sessionStorage.getItem('kestrel.reauthAttempts')).toBeNull()

    // Simulate the fresh page load a real signinRedirect() would cause —
    // a brand new module instance, exactly like a browser navigation
    // would reset all in-memory state (redirectInFlight included).
    const second = await loadGuard()
    const redirect = vi.fn()
    second.handleUnauthorized(redirect)
    expect(redirect).toHaveBeenCalledTimes(1)
    expect(second.authError.value).toBeNull()
  })
})
