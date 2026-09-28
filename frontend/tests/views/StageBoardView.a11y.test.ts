import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref } from 'vue'
import { mount } from '@vue/test-utils'
import { withVuetify } from '../support/vuetify'
import { boardWorkflowSummary, testRouter } from '../support/board'
import type { BoardWorkflowSummary } from '../../src/types/workflows'

// FR-007 / spec 026 FR-031: every board intervention/navigation available
// by pointer must also be available by keyboard. FR-006 / spec 026
// FR-032: no drag affordance anywhere — stage placement is derived, not
// operator-set.

const state = {
  workflows: ref<BoardWorkflowSummary[]>([]),
  error: ref<string | null>(null),
}
vi.mock('../../src/composables/useBoard', () => ({
  useBoard: () => ({
    workflows: state.workflows,
    error: state.error,
    refresh: vi.fn(),
    startList: vi.fn(),
    stopList: vi.fn(),
  }),
}))

import StageBoardView from '../../src/views/StageBoardView.vue'

const router = testRouter()

function summary(
  overrides: Partial<BoardWorkflowSummary> = {},
): BoardWorkflowSummary {
  return boardWorkflowSummary({ action_required_count: 1, ...overrides })
}

beforeEach(() => {
  state.workflows.value = [
    summary({ id: 'wf-1' }),
    summary({ id: 'wf-2', stage: 'Discovery', action_required_count: 0 }),
  ]
  state.error.value = null
})
afterEach(() => vi.restoreAllMocks())

describe('StageBoardView keyboard access', () => {
  it('renders every card as a focusable, keyboard-openable link', () => {
    const wrapper = mount(
      StageBoardView,
      withVuetify({ global: { plugins: [router] } }),
    )
    const links = wrapper.findAll('a.v-card')
    expect(links).toHaveLength(2)
    for (const link of links) {
      expect(link.attributes('href')).toBeTruthy()
      expect(link.attributes('tabindex')).not.toBe('-1')
    }
  })
})

describe('StageBoardView no drag affordance', () => {
  it('has no draggable element anywhere on the board', () => {
    const wrapper = mount(
      StageBoardView,
      withVuetify({ global: { plugins: [router] } }),
    )
    expect(wrapper.find('[draggable="true"]').exists()).toBe(false)
  })
})
