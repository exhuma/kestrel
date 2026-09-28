import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref } from 'vue'
import { mount } from '@vue/test-utils'
import { withVuetify } from '../support/vuetify'
import { boardWorkflowSummary, testRouter } from '../support/board'
import { STAGE_ORDER } from '../../src/lib/stages'
import type { BoardWorkflowSummary } from '../../src/types/workflows'

const state = {
  workflows: ref<BoardWorkflowSummary[]>([]),
  error: ref<string | null>(null),
}
const mockRefresh = vi.fn()
const mockStartList = vi.fn()
const mockStopList = vi.fn()
vi.mock('../../src/composables/useBoard', () => ({
  useBoard: () => ({
    workflows: state.workflows,
    error: state.error,
    refresh: mockRefresh,
    startList: mockStartList,
    stopList: mockStopList,
  }),
}))

import StageBoardView from '../../src/views/StageBoardView.vue'

const router = testRouter()

function summary(
  overrides: Partial<BoardWorkflowSummary> = {},
): BoardWorkflowSummary {
  return boardWorkflowSummary(overrides)
}

beforeEach(() => {
  state.workflows.value = []
  state.error.value = null
  vi.clearAllMocks()
})
afterEach(() => vi.restoreAllMocks())

function mountView() {
  return mount(StageBoardView, withVuetify({ global: { plugins: [router] } }))
}

describe('StageBoardView lifecycle', () => {
  it('refreshes and starts the live list on mount', () => {
    mountView()
    expect(mockRefresh).toHaveBeenCalled()
    expect(mockStartList).toHaveBeenCalled()
  })

  it('surfaces an error banner', () => {
    state.error.value = 'boom'
    const wrapper = mountView()
    expect(wrapper.text()).toContain('boom')
  })
})

describe('StageBoardView columns', () => {
  it('shows the empty state when no requests have been ingested', () => {
    const wrapper = mountView()
    expect(wrapper.findComponent({ name: 'VEmptyState' }).exists()).toBe(true)
  })

  it('renders the six stage columns in FR-001 order', () => {
    state.workflows.value = [summary()]
    const wrapper = mountView()
    const columns = wrapper.findAllComponents({ name: 'StageColumn' })
    expect(columns.map((c) => c.props('stage'))).toEqual(STAGE_ORDER)
  })

  it('shows exactly one card per request, with a decomposed parent nesting its children', () => {
    state.workflows.value = [
      summary({ id: 'quarantined-1', stage: 'Intake & alignment' }),
      summary({ id: 'parent-1', stage: 'Build & deliver' }),
      summary({
        id: 'child-1',
        parent_workflow_id: 'parent-1',
        stage: 'Intake & alignment',
      }),
    ]
    const wrapper = mountView()
    const cards = wrapper.findAllComponents({ name: 'RequestCard' })
    expect(cards).toHaveLength(2)
  })

  it('lists a terminal request in Done rather than dropping it', () => {
    state.workflows.value = [
      summary({ id: 'done-1', phase: 'done', stage: 'Done' }),
    ]
    const wrapper = mountView()
    const doneColumn = wrapper
      .findAllComponents({ name: 'StageColumn' })
      .find((c) => c.props('stage') === 'Done')!
    expect(doneColumn.props('requests')).toHaveLength(1)
  })
})
