import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
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
    gate: null,
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
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response('not found', { status: 404 })),
  )
})
afterEach(() => vi.restoreAllMocks())

function mountCard(c: WorkCardSummary) {
  return mount(WorkCardDetail, withVuetify({ props: { card: c } }))
}

function stubArtifactContent(content: string, trust: string): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(JSON.stringify({ content, trust }), { status: 200 }),
    ),
  )
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
      undefined,
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

describe('WorkCardDetail gate answer field visibility', () => {
  it('shows no answer field for a plain approve/reject gate', () => {
    const wrapper = mountCard(
      card({
        allowed_actions: ['resolve_gate'],
        gate: { requested_decision: 'confirm_understanding', decision: null },
      }),
    )
    expect(wrapper.findComponent({ name: 'VTextarea' }).exists()).toBe(false)
  })

  it('shows an answer field for a refinement_gate', () => {
    const wrapper = mountCard(
      card({
        allowed_actions: ['resolve_gate'],
        gate: { requested_decision: 'answer', decision: null },
      }),
    )
    expect(wrapper.findComponent({ name: 'VTextarea' }).exists()).toBe(true)
  })

  it('shows an answer field for a prd_gate rejection', () => {
    const wrapper = mountCard(
      card({
        allowed_actions: ['resolve_gate'],
        gate: { requested_decision: 'approve_prd', decision: null },
      }),
    )
    expect(wrapper.findComponent({ name: 'VTextarea' }).exists()).toBe(true)
  })
})

describe('WorkCardDetail gate answer field submission', () => {
  it('disables approve for an answer gate until text is entered', async () => {
    const wrapper = mountCard(
      card({
        allowed_actions: ['resolve_gate'],
        gate: { requested_decision: 'answer', decision: null },
      }),
    )
    const approveBtn = wrapper.findAllComponents({ name: 'VBtn' })[0]!
    expect(approveBtn.props('disabled')).toBe(true)
    await wrapper.find('textarea').setValue('Ship by Friday.')
    expect(approveBtn.props('disabled')).toBe(false)
  })

  it('disables reject for a PRD gate until feedback is entered', async () => {
    const wrapper = mountCard(
      card({
        allowed_actions: ['resolve_gate'],
        gate: { requested_decision: 'approve_prd', decision: null },
      }),
    )
    const rejectBtn = wrapper.findAllComponents({ name: 'VBtn' })[1]!
    expect(rejectBtn.props('disabled')).toBe(true)
    await wrapper.find('textarea').setValue('Needs more detail.')
    expect(rejectBtn.props('disabled')).toBe(false)
  })

  it('sends the answer text when approving an answer gate', async () => {
    const wrapper = mountCard(
      card({
        allowed_actions: ['resolve_gate'],
        gate: { requested_decision: 'answer', decision: null },
      }),
    )
    await wrapper.find('textarea').setValue('Ship by Friday.')
    await wrapper.findAllComponents({ name: 'VBtn' })[0]!.trigger('click')
    expect(mockApplyIntervention).toHaveBeenCalledWith(
      'card-1',
      'resolve_gate',
      'approved',
      'Ship by Friday.',
    )
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

describe('WorkCardDetail artifact content', () => {
  it('fetches and renders content as text for a card with an artifact', async () => {
    stubArtifactContent('the *raw* draft', 'agent_output')
    const wrapper = mountCard(
      card({
        latest_artifact: { id: 'artifact-1', label: 'draft', revision: 2 },
      }),
    )
    await flushPromises()
    expect(wrapper.text()).toContain('the *raw* draft')
    expect(wrapper.text()).toContain('agent_output')
    expect(wrapper.html()).not.toContain('<em>')
  })

  it('shows an error instead of content when the fetch fails', async () => {
    const wrapper = mountCard(
      card({
        latest_artifact: { id: 'artifact-1', label: 'draft', revision: 2 },
      }),
    )
    await flushPromises()
    expect(wrapper.text()).toContain('Could not load artifact content.')
  })

  it('fetches nothing when the card has no artifact', async () => {
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify({}), { status: 200 }),
    )
    vi.stubGlobal('fetch', fetchMock)
    mountCard(card({ latest_artifact: null }))
    await flushPromises()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
