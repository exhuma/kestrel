import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { ref } from 'vue'
import { withVuetify } from '../support/vuetify'
import { testRouter, boardSnapshot, workCardSummary } from '../support/board'
import type { BoardSnapshot, BoardEvent } from '../../src/types/workflows'

const current = ref<BoardSnapshot | null>(null)
const error = ref<string | null>(null)
const loading = ref(false)
const mockSelect = vi.fn()
const mockStop = vi.fn()
vi.mock('../../src/composables/useBoard', () => ({
  useBoard: () => ({
    current,
    error,
    loading,
    select: mockSelect,
    stop: mockStop,
    applyIntervention: vi.fn(),
    resolveQuarantine: vi.fn(),
  }),
}))

const events = ref<BoardEvent[]>([])
const mockStartEvents = vi.fn()
const mockStopEvents = vi.fn()
vi.mock('../../src/composables/useBoardEvents', () => ({
  useBoardEvents: () => ({
    events,
    error: ref(null),
    loading: ref(false),
    start: mockStartEvents,
    stop: mockStopEvents,
  }),
}))

import RequestCockpitView from '../../src/views/RequestCockpitView.vue'

const router = testRouter()
let wrappers: VueWrapper[] = []

async function mountCockpit(id = 'wf-1'): Promise<VueWrapper> {
  await router.push(`/requests/${id}`)
  await router.isReady()
  const wrapper = mount(
    RequestCockpitView,
    withVuetify({ global: { plugins: [router] } }),
  )
  await flushPromises()
  wrappers.push(wrapper)
  return wrapper
}

beforeEach(() => {
  current.value = null
  error.value = null
  loading.value = false
  events.value = []
  mockSelect.mockReset()
  mockStop.mockReset()
  mockStartEvents.mockReset()
  mockStopEvents.mockReset()
})
afterEach(() => {
  for (const w of wrappers) w.unmount()
  wrappers = []
  document.body.innerHTML = ''
})

describe('RequestCockpitView regions', () => {
  it('renders the spine, feed and rail for a loaded request', async () => {
    current.value = boardSnapshot({
      phase: 'PRD sign-off',
      cards: [workCardSummary({ card_type: 'prd', state: 'done' })],
    })
    const wrapper = await mountCockpit()
    expect(wrapper.findComponent({ name: 'PhaseSpine' }).exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'NarrativeFeed' }).exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'ArtifactRail' }).exists()).toBe(true)
  })

  it('shows the banner only when something is pending', async () => {
    current.value = boardSnapshot({ cards: [] })
    const quiet = await mountCockpit()
    expect(quiet.find('[data-testid="action-banner"]').exists()).toBe(false)

    current.value = boardSnapshot({
      cards: [
        workCardSummary({
          state: 'awaiting_human',
          allowed_actions: ['resolve_gate'],
          gate: {
            requested_decision: 'approve_prd',
            decision: null,
            round: null,
            cap: null,
          },
        }),
      ],
    })
    await flushPromises()
    expect(quiet.find('[data-testid="action-banner"]').exists()).toBe(true)
  })

  it('names the request by title and source ref, never by bare id', async () => {
    current.value = boardSnapshot({
      title: 'Add CSV export',
      task_label: 'o/r#1',
    })
    const wrapper = await mountCockpit()
    expect(wrapper.text()).toContain('Add CSV export')
    expect(wrapper.text()).toContain('o/r#1')
  })
})

describe('RequestCockpitView scoping', () => {
  it('loads exactly the request in the address', async () => {
    current.value = boardSnapshot({ id: 'wf-9' })
    await mountCockpit('wf-9')
    expect(mockSelect).toHaveBeenCalledWith('wf-9')
    expect(mockStartEvents).toHaveBeenCalledWith('wf-9')
  })

  it('does not render another request’s snapshot under this address', async () => {
    current.value = boardSnapshot({ id: 'wf-other', title: 'Someone else' })
    const wrapper = await mountCockpit('wf-1')
    expect(wrapper.text()).not.toContain('Someone else')
    expect(wrapper.findComponent({ name: 'PhaseSpine' }).exists()).toBe(false)
  })

  it('reloads when the address changes to another request', async () => {
    current.value = boardSnapshot({ id: 'wf-1' })
    await mountCockpit('wf-1')
    await router.push('/requests/wf-2')
    await flushPromises()
    expect(mockSelect).toHaveBeenLastCalledWith('wf-2')
    expect(mockStartEvents).toHaveBeenLastCalledWith('wf-2')
  })

  it('stops both streams when it is left', async () => {
    current.value = boardSnapshot()
    const wrapper = await mountCockpit()
    wrapper.unmount()
    expect(mockStop).toHaveBeenCalled()
    expect(mockStopEvents).toHaveBeenCalled()
  })
})

describe('RequestCockpitView failure paths', () => {
  it('gives an unknown request the explanatory surface with a way back', async () => {
    error.value = 'Request failed (404)'
    const wrapper = await mountCockpit('nope')
    expect(wrapper.findComponent({ name: 'NotFoundView' }).exists()).toBe(true)
    expect(wrapper.text()).toContain('Back to board')
  })

  it('states a load failure plainly and offers a route back, not a trace', async () => {
    error.value = 'Request failed (500)'
    const wrapper = await mountCockpit()
    expect(wrapper.findComponent({ name: 'NotFoundView' }).exists()).toBe(false)
    expect(wrapper.text()).toContain('Request failed (500)')
    const back = wrapper
      .findAllComponents({ name: 'VBtn' })
      .find((b) => b.text() === 'Back to board')
    expect(back?.props('to')).toEqual({ name: 'board' })
  })

  it('shows progress while the first snapshot is still loading', async () => {
    loading.value = true
    const wrapper = await mountCockpit()
    expect(wrapper.findComponent({ name: 'VProgressLinear' }).exists()).toBe(
      true,
    )
  })
})

describe('RequestCockpitView keeps answering off the cockpit', () => {
  it('sends an interview gate to the interview route (FR-017)', async () => {
    current.value = boardSnapshot({
      cards: [
        workCardSummary({
          state: 'awaiting_human',
          allowed_actions: ['resolve_gate'],
          gate: {
            requested_decision: 'answer',
            decision: null,
            round: null,
            cap: null,
          },
        }),
      ],
    })
    const wrapper = await mountCockpit()
    const cta = wrapper
      .findAllComponents({ name: 'VBtn' })
      .find((b) => b.text() === 'Answer the interview')
    expect(cta?.props('to')).toEqual({
      name: 'interview',
      params: { id: 'wf-1' },
    })
  })

  it('offers no free-text input anywhere on the cockpit itself', async () => {
    current.value = boardSnapshot({
      cards: [workCardSummary({ card_type: 'prd', state: 'done' })],
    })
    events.value = []
    const wrapper = await mountCockpit()
    expect(wrapper.findAllComponents({ name: 'VTextarea' })).toHaveLength(0)
    expect(wrapper.findAllComponents({ name: 'VTextField' })).toHaveLength(0)
  })
})
