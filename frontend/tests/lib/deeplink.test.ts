import { describe, it, expect, vi } from 'vitest'
import { runIdFromSearch, applyDeepLink } from '../../src/lib/deeplink'

describe('runIdFromSearch', () => {
  it('extracts the run id from the query string', () => {
    expect(runIdFromSearch('?run=wf-123')).toBe('wf-123')
  })

  it('returns null when there is no run param', () => {
    expect(runIdFromSearch('')).toBeNull()
    expect(runIdFromSearch('?other=1')).toBeNull()
  })

  it('treats an empty run param as absent', () => {
    expect(runIdFromSearch('?run=')).toBeNull()
  })
})

describe('applyDeepLink', () => {
  it('selects the run exactly once when present', () => {
    const select = vi.fn()
    applyDeepLink('?run=wf-9', select)
    expect(select).toHaveBeenCalledTimes(1)
    expect(select).toHaveBeenCalledWith('wf-9')
  })

  it('does not select when no run param is present', () => {
    const select = vi.fn()
    applyDeepLink('?foo=bar', select)
    expect(select).not.toHaveBeenCalled()
  })
})
