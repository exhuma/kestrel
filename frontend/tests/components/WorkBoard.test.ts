import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref } from 'vue'
import { mount } from '@vue/test-utils'
import { withVuetify } from '../support/vuetify'
import type {
  BoardSnapshot,
  BoardWorkflowSummary,
  WorkCardSummary,
} from '../../src/types/workflows'

const state = {
  workflows: ref<BoardWorkflowSummary[]>([]),
  current: ref<BoardSnapshot | null>(null),
  error: ref<string | null>(null),
}
const mockRefresh = vi.fn()
const mockStartList = vi.fn()
const mockStopList = vi.fn()
const mockSelect = vi.fn()
const mockStop = vi.fn()
vi.mock('../../src/composables/useBoard', () => ({
  useBoard: () => ({
    workflows: state.workflows,
    current: state.current,
    error: state.error,
    refresh: mockRefresh,
    startList: mockStartList,
    stopList: mockStopList,
    select: mockSelect,
    stop: mockStop,
    applyIntervention: vi.fn(),
    resolveQuarantine: vi.fn(),
  }),
}))

import WorkBoard from '../../src/components/WorkBoard.vue'

function card(overrides: Partial<WorkCardSummary> = {}): WorkCardSummary {
  return {
    id: 'card-1',
    title: 'Investigate',
    card_type: 'analysis',
    state: 'ready',
    eligible_roles: [],
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

function snapshot(overrides: Partial<BoardSnapshot> = {}): BoardSnapshot {
  return {
    id: 'wf-1',
    revision: 1,
    task_label: 'o/r#1',
    status: 'active',
    cards: [],
    relationships: [],
    state_counts: {},
    phase: 'done',
    stage: 'Done',
    ...overrides,
  }
}

beforeEach(() => {
  state.workflows.value = []
  state.current.value = null
  state.error.value = null
  vi.clearAllMocks()
})
afterEach(() => vi.restoreAllMocks())

function mountBoard() {
  return mount(WorkBoard, withVuetify())
}

describe('WorkBoard lifecycle', () => {
  it('refreshes and starts the live list on mount', () => {
    mountBoard()
    expect(mockRefresh).toHaveBeenCalled()
    expect(mockStartList).toHaveBeenCalled()
  })

  it('shows a prompt when no workflow is selected', () => {
    const wrapper = mountBoard()
    expect(wrapper.text()).toContain('Select a workflow')
  })

  it('surfaces an error banner', () => {
    state.error.value = 'boom'
    const wrapper = mountBoard()
    expect(wrapper.text()).toContain('boom')
  })
})

describe('WorkBoard state grouping', () => {
  it('groups cards under their state heading', () => {
    state.current.value = snapshot({
      cards: [
        card({ id: 'a', state: 'ready' }),
        card({ id: 'b', state: 'done' }),
      ],
    })
    const wrapper = mountBoard()
    expect(wrapper.text()).toContain('Ready (1)')
    expect(wrapper.text()).toContain('Done (1)')
  })

  it('omits a state heading with no cards in it', () => {
    state.current.value = snapshot({ cards: [card({ state: 'ready' })] })
    const wrapper = mountBoard()
    expect(wrapper.text()).not.toContain('Failed')
  })

  it('distinguishes dependency-waiting from human-waiting groups', () => {
    state.current.value = snapshot({
      cards: [
        card({ id: 'a', state: 'waiting_dependency' }),
        card({ id: 'b', state: 'awaiting_human' }),
      ],
    })
    const wrapper = mountBoard()
    expect(wrapper.text()).toContain('Waiting on dependency (1)')
    expect(wrapper.text()).toContain('Awaiting a decision (1)')
  })

  it('surfaces quarantined cards in their own group', () => {
    state.current.value = snapshot({
      cards: [card({ state: 'quarantined' })],
    })
    const wrapper = mountBoard()
    expect(wrapper.text()).toContain('Quarantined (1)')
  })
})

describe('WorkBoard selection', () => {
  it('selecting a workflow calls select with its id', async () => {
    state.workflows.value = [
      {
        id: 'wf-1',
        task_label: 'o/r#1',
        status: 'active',
        state_counts: {},
        action_required_count: 0,
        phase: 'done',
        stage: 'Done',
      },
    ]
    const wrapper = mountBoard()
    await wrapper.findComponent({ name: 'VListItem' }).trigger('click')
    expect(mockSelect).toHaveBeenCalledWith('wf-1')
  })

  it('selecting a card opens its detail panel', async () => {
    state.current.value = snapshot({
      cards: [card({ title: 'Investigate the bug' })],
    })
    const wrapper = mountBoard()
    const cardItem = wrapper
      .findAllComponents({ name: 'VListItem' })
      .find((item) => item.text().includes('Investigate the bug'))
    await cardItem!.trigger('click')
    expect(wrapper.findComponent({ name: 'WorkCardDetail' }).exists()).toBe(
      true,
    )
  })
})
