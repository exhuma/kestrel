import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { withVuetify } from '../support/vuetify'
import SourceHealthIndicator from '../../src/components/SourceHealthIndicator.vue'
import { useSourceHealth } from '../../src/composables/useSourceHealth'

class FakeEventSource {
  onmessage: ((e: MessageEvent) => void) | null = null
  close = vi.fn()
  constructor(public url: string) {
    lastEventSource = this
  }
}
let lastEventSource: FakeEventSource | null = null

afterEach(() => {
  useSourceHealth().stop()
  vi.restoreAllMocks()
  lastEventSource = null
})

function push(health: unknown[]): void {
  lastEventSource!.onmessage?.({
    data: JSON.stringify({ health }),
  } as MessageEvent)
}

async function mountIndicator() {
  vi.stubGlobal('EventSource', FakeEventSource)
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify([]), { status: 200 })),
  )
  const wrapper = mount(SourceHealthIndicator, withVuetify())
  await flushPromises()
  return wrapper
}

async function openMenu(
  wrapper: Awaited<ReturnType<typeof mountIndicator>>,
): Promise<void> {
  await wrapper.findComponent({ name: 'VBtn' }).trigger('click')
  await flushPromises()
}

describe('SourceHealthIndicator', () => {
  it('renders nothing before any source is known', async () => {
    const wrapper = await mountIndicator()
    expect(wrapper.findComponent({ name: 'VMenu' }).exists()).toBe(false)
  })

  it('renders every source once the stream reports them', async () => {
    const wrapper = await mountIndicator()
    push([
      { name: 'github', state: 'healthy', checked_at: '2026-09-08T10:00:00' },
      { name: 'jira', state: 'unhealthy', checked_at: '2026-09-08T10:00:00' },
    ])
    await wrapper.vm.$nextTick()
    await openMenu(wrapper)
    const titles = wrapper.findAllComponents({ name: 'VListItemTitle' })
    expect(titles.map((t) => t.text())).toEqual(['github', 'jira'])
  })

  it("disables a source's refresh button while its check is in flight", async () => {
    const wrapper = await mountIndicator()
    push([
      { name: 'github', state: 'unhealthy', checked_at: '2026-09-08T10:00:00' },
    ])
    await wrapper.vm.$nextTick()
    await openMenu(wrapper)

    // The activator is also a VBtn; the per-entry refresh control is the
    // last one rendered (inside the opened list).
    const listRefresh = () => {
      const buttons = wrapper.findAllComponents({ name: 'VBtn' })
      return buttons[buttons.length - 1]
    }

    await listRefresh().trigger('click')
    await flushPromises()
    expect(listRefresh().props('disabled')).toBe(true)

    // The next push with a changed checked_at clears the pending state.
    push([
      { name: 'github', state: 'healthy', checked_at: '2026-09-08T10:05:00' },
    ])
    await wrapper.vm.$nextTick()
    expect(listRefresh().props('disabled')).toBe(false)
  })
})
