import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { withVuetify } from '../support/vuetify'
import type { WorkCardSummary } from '../../src/types/workflows'

const mockApplyIntervention = vi.fn()
vi.mock('../../src/composables/useBoard', () => ({
  useBoard: () => ({ applyIntervention: mockApplyIntervention }),
}))

import WorkCardDetail from '../../src/components/WorkCardDetail.vue'

function card(overrides: Partial<WorkCardSummary> = {}): WorkCardSummary {
  return {
    id: 'card-1',
    title: 'Investigate the bug',
    card_type: 'analysis',
    state: 'ready',
    eligible_roles: [{ id: 'developer', label: 'Developer' }],
    owner: null,
    lease: null,
    waiting_reason: null,
    dependency_count: 0,
    latest_artifact: null,
    allowed_actions: [],
    ...overrides,
  }
}

beforeEach(() => {
  mockApplyIntervention.mockReset()
  vi.stubGlobal(
    'confirm',
    vi.fn(() => true),
  )
})
afterEach(() => vi.restoreAllMocks())

function mountCard(c: WorkCardSummary) {
  return mount(WorkCardDetail, withVuetify({ props: { card: c } }))
}

describe('WorkCardDetail safe rendering', () => {
  it('renders the card title and type', () => {
    const wrapper = mountCard(card())
    expect(wrapper.text()).toContain('Investigate the bug')
    expect(wrapper.text()).toContain('analysis')
  })

  it('shows a waiting reason when present', () => {
    const wrapper = mountCard(card({ waiting_reason: 'blocked on gate' }))
    expect(wrapper.text()).toContain('Waiting: blocked on gate')
  })

  it('labels a quarantined card\'s reason as "Reason", not "Waiting"', () => {
    const wrapper = mountCard(
      card({ state: 'quarantined', waiting_reason: 'exceeds input bounds' }),
    )
    expect(wrapper.text()).toContain('Reason: exceeds input bounds')
    expect(wrapper.text()).not.toContain('Waiting:')
  })

  it('shows no action buttons when none are allowed', () => {
    const wrapper = mountCard(card({ allowed_actions: [] }))
    expect(wrapper.findAllComponents({ name: 'VBtn' })).toHaveLength(0)
  })
})

describe('WorkCardDetail permitted actions', () => {
  it('renders a button only for each allowed action', () => {
    const wrapper = mountCard(card({ allowed_actions: ['retry', 'cancel'] }))
    const labels = wrapper
      .findAllComponents({ name: 'VBtn' })
      .map((b) => b.text())
    expect(labels).toEqual(['Retry', 'Cancel'])
  })

  it('renders approve/reject instead of a generic button for resolve_gate', () => {
    const wrapper = mountCard(card({ allowed_actions: ['resolve_gate'] }))
    const labels = wrapper
      .findAllComponents({ name: 'VBtn' })
      .map((b) => b.text())
    expect(labels).toEqual(['Approve', 'Reject'])
  })

  it('clicking retry calls applyIntervention with the card id', async () => {
    const wrapper = mountCard(card({ allowed_actions: ['retry'] }))
    await wrapper.findComponent({ name: 'VBtn' }).trigger('click')
    expect(mockApplyIntervention).toHaveBeenCalledWith(
      'card-1',
      'retry',
      undefined,
    )
  })

  it('clicking approve sends the approved decision', async () => {
    const wrapper = mountCard(card({ allowed_actions: ['resolve_gate'] }))
    await wrapper.findAllComponents({ name: 'VBtn' })[0]!.trigger('click')
    expect(mockApplyIntervention).toHaveBeenCalledWith(
      'card-1',
      'resolve_gate',
      'approved',
    )
  })

  it('does not apply cancel when the confirmation is declined', async () => {
    vi.stubGlobal(
      'confirm',
      vi.fn(() => false),
    )
    const wrapper = mountCard(card({ allowed_actions: ['cancel'] }))
    await wrapper.findComponent({ name: 'VBtn' }).trigger('click')
    expect(mockApplyIntervention).not.toHaveBeenCalled()
  })
})
