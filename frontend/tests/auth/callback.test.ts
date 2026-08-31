import { describe, expect, it } from 'vitest'
import { isAuthCallbackPath, resolveReturnTo } from '../../src/auth/callback'

describe('isAuthCallbackPath', () => {
  it('matches the callback path exactly', () => {
    expect(isAuthCallbackPath('/auth/callback')).toBe(true)
  })

  it('does not match any other path', () => {
    expect(isAuthCallbackPath('/')).toBe(false)
    expect(isAuthCallbackPath('/auth/callback/')).toBe(false)
    expect(isAuthCallbackPath('/auth')).toBe(false)
  })
})

describe('resolveReturnTo', () => {
  it('returns the stashed state path when present', () => {
    expect(resolveReturnTo('/some/path')).toBe('/some/path')
  })

  it('falls back to / when state is absent', () => {
    expect(resolveReturnTo(undefined)).toBe('/')
    expect(resolveReturnTo(null)).toBe('/')
  })

  it('falls back to / when state is an empty string', () => {
    expect(resolveReturnTo('')).toBe('/')
  })

  it('falls back to / when state is not a string', () => {
    expect(resolveReturnTo({ foo: 'bar' })).toBe('/')
  })
})
