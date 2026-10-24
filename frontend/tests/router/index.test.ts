import { describe, it, expect, vi } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter, router } from '../../src/router'

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

  it('resolves an unmatched path to the not-found catch-all', () => {
    const resolved = router.resolve('/nothing/here')
    expect(resolved.name).toBe('not-found')
  })

  it('navigates to each named route from a cold router', async () => {
    for (const target of [
      { name: 'board' },
      { name: 'cockpit', params: { id: 'wf-1' } },
      { name: 'interview', params: { id: 'wf-1' } },
    ] as const) {
      await router.push(target)
      expect(router.currentRoute.value.name).toBe(target.name)
    }
  })
})

describe('router history', () => {
  it('walks back and forward through board, cockpit and interview', async () => {
    const r = createAppRouter(createMemoryHistory())
    await r.push({ name: 'board' })
    await r.push({ name: 'cockpit', params: { id: 'wf-1' } })
    await r.push({ name: 'interview', params: { id: 'wf-1' } })

    const visited: unknown[] = []
    for (const step of [r.back, r.back, r.forward, r.forward]) {
      const before = r.currentRoute.value.fullPath
      step()
      await vi.waitFor(() =>
        expect(r.currentRoute.value.fullPath).not.toBe(before),
      )
      visited.push(r.currentRoute.value.name)
    }

    expect(visited).toEqual(['cockpit', 'board', 'cockpit', 'interview'])
  })
})

describe('router not-found', () => {
  it('routes an unmatched path to the not-found surface', async () => {
    const r = createAppRouter(createMemoryHistory())

    await r.push('/definitely/not/a/page')

    expect(r.currentRoute.value.name).toBe('not-found')
  })

  it('keeps ids opaque: the id is the only parameter on request routes', () => {
    const r = createAppRouter(createMemoryHistory())

    const cockpit = r.resolve({ name: 'cockpit', params: { id: 'wf-1' } })
    const interview = r.resolve({ name: 'interview', params: { id: 'wf-1' } })

    expect(Object.keys(cockpit.params)).toEqual(['id'])
    expect(Object.keys(interview.params)).toEqual(['id'])
  })
})

describe('router lazy loading', () => {
  const component = (r: ReturnType<typeof createAppRouter>, name: string) =>
    r.getRoutes().find((route) => route.name === name)!.components!.default

  it('ships the board eagerly', () => {
    const r = createAppRouter(createMemoryHistory())

    expect(typeof component(r, 'board')).toBe('object')
  })

  it.each(['cockpit', 'interview'])(
    'loads %s only once it is visited',
    async (name) => {
      const r = createAppRouter(createMemoryHistory())
      expect(typeof component(r, name)).toBe('function')

      await r.push({ name, params: { id: 'wf-1' } })

      expect(typeof component(r, name)).toBe('object')
    },
  )
})
