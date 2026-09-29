import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { ref } from 'vue'
import { withVuetify } from '../../support/vuetify'
import { testRouter, workCardSummary } from '../../support/board'
import type { WorkCardSummary } from '../../../src/types/workflows'

const mockApplyIntervention = vi.fn()
const mockResolveQuarantine = vi.fn()
const boardError = ref<string | null>(null)
vi.mock('../../../src/composables/useBoard', () => ({
  useBoard: () => ({
    applyIntervention: mockApplyIntervention,
    resolveQuarantine: mockResolveQuarantine,
    error: boardError,
  }),
}))

import ActionBanner from '../../../src/components/cockpit/ActionBanner.vue'

const router = testRouter()
let wrappers: VueWrapper[] = []

function gateCard(
  requested: string,
  overrides: Partial<WorkCardSummary> = {},
): WorkCardSummary {
  return workCardSummary({
    state: 'awaiting_human',
    allowed_actions: ['resolve_gate'],
    gate: {
      requested_decision: requested,
      decision: null,
      round: null,
      cap: null,
      target_artifact: null,
    },
    ...overrides,
  })
}

function mountBanner(cards: WorkCardSummary[]): VueWrapper {
  const wrapper = mount(
    ActionBanner,
    withVuetify({
      props: { cards, workflowId: 'wf-1' },
      global: { plugins: [router] },
    }),
  )
  wrappers.push(wrapper)
  return wrapper
}

function button(wrapper: VueWrapper, label: string) {
  return wrapper
    .findAllComponents({ name: 'VBtn' })
    .find((b) => b.text() === label)
}

/** Open the confirmation and press its primary action. */
async function confirmVia(wrapper: VueWrapper, label: string): Promise<void> {
  await button(wrapper, label)?.trigger('click')
  await flushPromises()
  const confirmBtn = wrapper
    .findAllComponents({ name: 'VBtn' })
    .filter((b) => b.text() === label)
    .at(-1)
  await confirmBtn?.trigger('click')
  await flushPromises()
}

beforeEach(async () => {
  mockApplyIntervention.mockReset()
  mockResolveQuarantine.mockReset()
  boardError.value = null
  await router.push('/')
  await router.isReady()
})
afterEach(() => {
  for (const w of wrappers) w.unmount()
  wrappers = []
  document.body.innerHTML = ''
})

describe('ActionBanner presence', () => {
  it('renders no element at all when nothing is pending', () => {
    const wrapper = mountBanner([workCardSummary({ state: 'claimed' })])
    expect(wrapper.find('[data-testid="action-banner"]').exists()).toBe(false)
    expect(wrapper.findComponent({ name: 'VAlert' }).exists()).toBe(false)
  })

  it('states a pending gate exactly once', () => {
    const wrapper = mountBanner([gateCard('approve_prd')])
    expect(wrapper.findAll('[data-testid="action-banner"]')).toHaveLength(1)
    expect(wrapper.text()).toContain('Sign off the PRD')
  })

  it('still shows one banner when several asks are outstanding, noting the rest', () => {
    const wrapper = mountBanner([
      gateCard('approve_prd', { id: 'g1' }),
      gateCard('confirm_understanding', { id: 'g2' }),
    ])
    expect(wrapper.findAll('[data-testid="action-banner"]')).toHaveLength(1)
    expect(wrapper.text()).toContain('1 other decision(s) also waiting')
  })
})

describe('ActionBanner approval decisions', () => {
  it('approves through a confirmation, not immediately on click', async () => {
    const wrapper = mountBanner([gateCard('confirm_understanding')])
    await button(wrapper, 'Approve')?.trigger('click')
    await flushPromises()
    expect(mockApplyIntervention).not.toHaveBeenCalled()

    await wrapper
      .findAllComponents({ name: 'VBtn' })
      .filter((b) => b.text() === 'Approve')
      .at(-1)
      ?.trigger('click')
    await flushPromises()
    expect(mockApplyIntervention).toHaveBeenCalledWith(
      'card-1',
      'resolve_gate',
      'approved',
    )
  })

  it('uses a dialog rather than window.confirm', async () => {
    const confirmSpy = vi.fn(() => true)
    vi.stubGlobal('confirm', confirmSpy)
    const wrapper = mountBanner([gateCard('confirm_understanding')])
    await confirmVia(wrapper, 'Approve')
    expect(confirmSpy).not.toHaveBeenCalled()
    expect(wrapper.findComponent({ name: 'VDialog' }).exists()).toBe(true)
    vi.unstubAllGlobals()
  })

  it('refuses a PRD rejection with no feedback, then sends it once given', async () => {
    const wrapper = mountBanner([gateCard('approve_prd')])
    await button(wrapper, 'Reject')?.trigger('click')
    await flushPromises()

    const submit = wrapper
      .findAllComponents({ name: 'VBtn' })
      .filter((b) => b.text() === 'Reject')
      .at(-1)
    expect(submit?.props('disabled')).toBe(true)

    await wrapper
      .findComponent({ name: 'VTextarea' })
      .setValue('The scope is wrong.')
    await flushPromises()
    await submit?.trigger('click')
    await flushPromises()

    expect(mockApplyIntervention).toHaveBeenCalledWith(
      'card-1',
      'resolve_gate',
      'rejected',
      'The scope is wrong.',
    )
  })

  it('rejects without feedback where none is required', async () => {
    const wrapper = mountBanner([gateCard('confirm_understanding')])
    await confirmVia(wrapper, 'Reject')
    expect(mockApplyIntervention).toHaveBeenCalledWith(
      'card-1',
      'resolve_gate',
      'rejected',
      undefined,
    )
  })
})

describe('ActionBanner answer-shaped work leaves the cockpit', () => {
  it('sends an interview gate to the interview surface instead of asking inline', () => {
    const wrapper = mountBanner([gateCard('answer')])
    const cta = button(wrapper, 'Answer the interview')
    expect(cta?.props('to')).toEqual({
      name: 'interview',
      params: { id: 'wf-1' },
    })
    expect(wrapper.findComponent({ name: 'VTextarea' }).exists()).toBe(false)
  })
})

describe('ActionBanner quarantine', () => {
  const quarantined = workCardSummary({
    state: 'quarantined',
    security_review_id: 'sr-1',
  })

  it('offers release and discard for quarantined content', () => {
    const wrapper = mountBanner([quarantined])
    expect(button(wrapper, 'Release')).toBeTruthy()
    expect(button(wrapper, 'Discard')).toBeTruthy()
  })

  it('resolves the security review rather than the card', async () => {
    const wrapper = mountBanner([quarantined])
    await confirmVia(wrapper, 'Release')
    expect(mockResolveQuarantine).toHaveBeenCalledWith(
      'sr-1',
      'release_quarantine',
    )
  })
})

describe('ActionBanner stale decisions', () => {
  it('explains a 409 in human terms rather than as a status code', async () => {
    const wrapper = mountBanner([gateCard('approve_prd')])
    boardError.value = 'Request failed (409)'
    await flushPromises()
    const message = wrapper.find('[data-testid="stale-message"]')
    expect(message.exists()).toBe(true)
    expect(message.text()).toContain('moved on')
    expect(message.text()).not.toContain('409')
  })

  it('does not show that message for an unrelated failure', async () => {
    const wrapper = mountBanner([gateCard('approve_prd')])
    boardError.value = 'Request failed (500)'
    await flushPromises()
    expect(wrapper.find('[data-testid="stale-message"]').exists()).toBe(false)
  })
})

describe('ActionBanner keyboard operability', () => {
  it('exposes every action as a real button', () => {
    const wrapper = mountBanner([gateCard('confirm_understanding')])
    const tags = wrapper
      .findAllComponents({ name: 'VBtn' })
      .map((b) => b.element.tagName)
    expect(tags.length).toBeGreaterThan(0)
    expect(tags.every((t) => t === 'BUTTON' || t === 'A')).toBe(true)
  })
})

describe('ActionBanner CAB-2 executive summary (feature 030)', () => {
  const summary = { id: 'art-sum', label: 'executive_summary', revision: 1 }

  function dialogId(wrapper: VueWrapper): unknown {
    return wrapper.findComponent({ name: 'ArtifactDialog' }).props('artifactId')
  }

  it('offers the summary on a CAB-2 ask and opens it on the gate artifact', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({ content: 'x', trust: 'agent_output' }),
            { status: 200 },
          ),
      ),
    )
    const wrapper = mountBanner([
      gateCard('approve_decomposition', { latest_artifact: summary }),
    ])
    expect(dialogId(wrapper)).toBeNull()

    await button(wrapper, 'Read the executive summary')?.trigger('click')
    await flushPromises()

    expect(dialogId(wrapper)).toBe('art-sum')
    vi.unstubAllGlobals()
  })

  it('offers no summary on a CAB-2 gate opened before summaries existed', () => {
    const wrapper = mountBanner([gateCard('approve_decomposition')])
    expect(button(wrapper, 'Read the executive summary')).toBeUndefined()
  })

  it('offers no summary on any other decision', () => {
    const wrapper = mountBanner([
      gateCard('approve_prd', { latest_artifact: summary }),
    ])
    expect(button(wrapper, 'Read the executive summary')).toBeUndefined()
  })

  it("offers the gate's target to read, e.g. the PRD (#66)", () => {
    const card = gateCard('approve_prd')
    card.gate!.target_artifact = { id: 'art-prd', label: 'draft', revision: 1 }
    const wrapper = mountBanner([card])
    expect(button(wrapper, 'Read the PRD')).toBeDefined()
  })

  it('says why content was quarantined (#66)', () => {
    const wrapper = mountBanner([
      workCardSummary({
        state: 'quarantined',
        security_review_id: 'rev-1',
        waiting_reason: 'the input-security check did not finish within 30s',
      }),
    ])
    expect(wrapper.get('[data-testid="quarantine-reason"]').text()).toBe(
      'Why: the input-security check did not finish within 30s',
    )
  })
})
