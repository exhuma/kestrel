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
    children: [],
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

describe('RequestCard nesting', () => {
  it('renders decomposition children inside the card', () => {
    const req = request('none')
    req.children = [
      summary({ id: 'child-1', title: 'Child work', task_label: 'o/r#2' }),
    ]
    const wrapper = mountCard(req)
    expect(wrapper.text()).toContain('Child work')
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
