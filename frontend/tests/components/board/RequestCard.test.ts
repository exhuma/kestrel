import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { withVuetify } from '../../support/vuetify'
import { boardWorkflowSummary, testRouter } from '../../support/board'
import RequestCard from '../../../src/components/board/RequestCard.vue'
import type { AttentionState, BoardRequest } from '../../../src/lib/stages'
import type { BoardWorkflowSummary } from '../../../src/types/workflows'

const router = testRouter()

function summary(
  overrides: Partial<BoardWorkflowSummary> = {},
): BoardWorkflowSummary {
  return boardWorkflowSummary({ title: 'Add CSV export', ...overrides })
}

function request(
  attention: AttentionState = 'none',
  overrides: Partial<BoardWorkflowSummary> = {},
): BoardRequest {
  return {
    summary: summary(overrides),
    position: { ordinal: 9, isTerminal: false },
    attention,
  }
}

function mountCard(req: BoardRequest) {
  return mount(
    RequestCard,
    withVuetify({ props: { request: req }, global: { plugins: [router] } }),
  )
}

describe('RequestCard identity', () => {
  it('shows the source ref and the human title, never a bare id', () => {
    const wrapper = mountCard(request())
    expect(wrapper.text()).toContain('Add CSV export')
    expect(wrapper.text()).toContain('o/r#1')
    expect(wrapper.text()).not.toContain('wf-1')
  })

  it('states the exact phase and its position in the sequence', () => {
    const wrapper = mountCard(request())
    expect(wrapper.text()).toContain('Build')
    expect(wrapper.text()).toContain('9 of 10')
  })

  it('links to the request cockpit route', () => {
    const wrapper = mountCard(request())
    const card = wrapper.findComponent({ name: 'VCard' })
    expect(card.props('to')).toEqual({
      name: 'cockpit',
      params: { id: 'wf-1' },
    })
  })
})

describe('RequestCard attention treatments', () => {
  const cases: [AttentionState, string][] = [
    ['your-move', 'Your move'],
    ['cap-reached', 'Round cap reached'],
    ['quarantined', 'Quarantined'],
    ['done', 'Done'],
  ]

  it.each(cases)('shows the %s treatment distinguishably', (state, text) => {
    const wrapper = mountCard(request(state))
    expect(wrapper.text()).toContain(text)
  })

  it('shows no chip when nothing is wanted', () => {
    const wrapper = mountCard(request('none'))
    expect(wrapper.findComponent({ name: 'VChip' }).exists()).toBe(false)
  })
})

describe('RequestCard manual tasks (feature 031)', () => {
  it('says how many manual tasks are assigned to the operator', () => {
    const wrapper = mountCard(request('none', { open_manual_task_count: 2 }))
    expect(wrapper.text()).toContain('2 manual tasks assigned to you')
  })

  it('uses the singular for one', () => {
    const wrapper = mountCard(request('none', { open_manual_task_count: 1 }))
    expect(wrapper.text()).toContain('1 manual task assigned to you')
  })

  it('says nothing when there are none', () => {
    const wrapper = mountCard(request())
    expect(wrapper.text()).not.toContain('manual task')
  })
})

describe('RequestCard whose move (feature 035)', () => {
  it('names who acts and what, and how many more wait', () => {
    const wrapper = mountCard(
      request('your-move', {
        awaiting: [
          { actor: 'cab', ask: 'approve_strategic_fit', role: null },
          { actor: 'you', ask: 'do_task', role: null },
        ],
      }),
    )
    expect(wrapper.find('[data-testid="moves"]').text()).toBe(
      'CAB: decide strategic fit (+1 more)',
    )
  })

  it('says nothing about moves when none is wanted', () => {
    const wrapper = mountCard(request('none'))
    expect(wrapper.find('[data-testid="moves"]').exists()).toBe(false)
  })
})

describe('RequestCard outcome treatments (feature 040)', () => {
  const cases: [AttentionState, string, string][] = [
    ['failed', 'Failed', '$alertCircle'],
    ['cancelled', 'Cancelled', '$close'],
  ]

  it.each(cases)('shows %s in words, with an icon', (state, text, icon) => {
    const wrapper = mountCard(request(state))
    expect(wrapper.find('.v-chip').text()).toContain(text)
    const icons = wrapper.findAllComponents({ name: 'VIcon' })
    expect(icons.map((i) => i.props('icon'))).toContain(icon)
  })
})
