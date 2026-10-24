import { describe, it, expect } from 'vitest'
import { router } from '../../src/router'

describe('router', () => {
  it('resolves board at /', () => {
    const resolved = router.resolve({ name: 'board' })
    expect(resolved.path).toBe('/')
  })

  it('resolves cockpit at /requests/:id', () => {
    const resolved = router.resolve({ name: 'cockpit', params: { id: 'wf-1' } })
    expect(resolved.path).toBe('/requests/wf-1')
  })

  it('resolves interview at /requests/:id/interview', () => {
    const resolved = router.resolve({
      name: 'interview',
      params: { id: 'wf-1' },
    })
    expect(resolved.path).toBe('/requests/wf-1/interview')
  })

  it('resolves sessions at /sessions', () => {
    const resolved = router.resolve({ name: 'sessions' })
    expect(resolved.path).toBe('/sessions')
  })

  it('resolves an unmatched path to the not-found catch-all', () => {
    const resolved = router.resolve('/nothing/here')
    expect(resolved.name).toBe('not-found')
  })

  it('navigates to each named route from a cold router', async () => {
    for (const target of [
      { name: 'board' },
      { name: 'cockpit', params: { id: 'wf-1' } },
      { name: 'interview', params: { id: 'wf-1' } },
      { name: 'sessions' },
    ] as const) {
      await router.push(target)
      expect(router.currentRoute.value.name).toBe(target.name)
    }
  })
})
