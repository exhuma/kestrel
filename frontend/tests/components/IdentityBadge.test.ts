import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { withVuetify } from '../support/vuetify'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

// Each test needs its own copy of the module-level identity singleton (and
// of the component that reads it), since the composable fetches exactly once
// per module instance.
async function loadBadge(body: unknown) {
  vi.resetModules()
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(body), { status: 200 })),
  )
  const mod = await import('../../src/components/IdentityBadge.vue')
  return mod.default
}

describe('IdentityBadge', () => {
  it('renders nothing when no proxy is in front (all-null identity)', async () => {
    const IdentityBadge = await loadBadge({
      username: null,
      email: null,
      preferred_username: null,
    })
    const wrapper = mount(IdentityBadge, withVuetify())
    await flushPromises()
    expect(wrapper.find('.v-chip').exists()).toBe(false)
  })

  it('renders the preferred username when the identity is forwarded', async () => {
    const IdentityBadge = await loadBadge({
      username: 'alice',
      email: 'alice@example.com',
      preferred_username: 'Alice',
    })
    const wrapper = mount(IdentityBadge, withVuetify())
    await flushPromises()
    expect(wrapper.find('.v-chip').exists()).toBe(true)
    expect(wrapper.text()).toContain('Alice')
  })

  it('falls back to username when no preferred username is set', async () => {
    const IdentityBadge = await loadBadge({
      username: 'alice',
      email: null,
      preferred_username: null,
    })
    const wrapper = mount(IdentityBadge, withVuetify())
    await flushPromises()
    expect(wrapper.text()).toContain('alice')
  })
})
