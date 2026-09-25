import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { withVuetify } from '../support/vuetify'
import type { WorkCardSummary } from '../../src/types/workflows'

const mockApplyIntervention = vi.fn()
const mockResolveQuarantine = vi.fn()
vi.mock('../../src/composables/useBoard', () => ({
  useBoard: () => ({
    applyIntervention: mockApplyIntervention,
    resolveQuarantine: mockResolveQuarantine,
  }),
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
    security_review_id: null,
    ...overrides,
  }
}

beforeEach(() => {
  mockApplyIntervention.mockReset()
  mockResolveQuarantine.mockReset()
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

describe('WorkCardDetail quarantine release/discard', () => {
  it('shows no release/discard buttons for a non-quarantined card', () => {
    const wrapper = mountCard(card({ security_review_id: 'review-1' }))
    expect(wrapper.text()).not.toContain('Release')
    expect(wrapper.text()).not.toContain('Discard')
  })

  it('shows no release/discard buttons without a security_review_id', () => {
    const wrapper = mountCard(
      card({ state: 'quarantined', security_review_id: null }),
    )
    expect(wrapper.text()).not.toContain('Release')
    expect(wrapper.text()).not.toContain('Discard')
  })

  it('renders release/discard for a quarantined card with a review', () => {
    const wrapper = mountCard(
      card({ state: 'quarantined', security_review_id: 'review-1' }),
    )
    const labels = wrapper
      .findAllComponents({ name: 'VBtn' })
      .map((b) => b.text())
    expect(labels).toEqual(['Release', 'Discard'])
  })

  it('clicking release resolves the review as released', async () => {
    const wrapper = mountCard(
      card({ state: 'quarantined', security_review_id: 'review-1' }),
    )
    await wrapper.findAllComponents({ name: 'VBtn' })[0]!.trigger('click')
    expect(mockResolveQuarantine).toHaveBeenCalledWith(
      'review-1',
      'release_quarantine',
    )
  })

  it('clicking discard resolves the review as discarded', async () => {
    const wrapper = mountCard(
      card({ state: 'quarantined', security_review_id: 'review-1' }),
    )
    await wrapper.findAllComponents({ name: 'VBtn' })[1]!.trigger('click')
    expect(mockResolveQuarantine).toHaveBeenCalledWith(
      'review-1',
      'discard_quarantine',
    )
  })

  it('does not resolve when the confirmation is declined', async () => {
    vi.stubGlobal(
      'confirm',
      vi.fn(() => false),
    )
    const wrapper = mountCard(
      card({ state: 'quarantined', security_review_id: 'review-1' }),
    )
    await wrapper.findAllComponents({ name: 'VBtn' })[0]!.trigger('click')
    expect(mockResolveQuarantine).not.toHaveBeenCalled()
  })
})
