import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { withVuetify } from '../../support/vuetify'
import RequestSubItems from '../../../src/components/board/RequestSubItems.vue'
import type { BoardWorkflowSummary } from '../../../src/types/workflows'

function child(
  overrides: Partial<BoardWorkflowSummary> = {},
): BoardWorkflowSummary {
  return {
    id: 'child-1',
    task_label: 'o/r#2',
    title: 'A decomposed child',
    parent_workflow_id: 'wf-1',
    status: 'active',
    state_counts: {},
    action_required_count: 0,
    phase: 'Build',
    stage: 'Build & deliver',
    cap_exhausted: false,
    ...overrides,
  }
}

describe('RequestSubItems', () => {
  it('renders nothing when there is no own-card activity and no children', () => {
    const wrapper = mount(
      RequestSubItems,
      withVuetify({ props: { stateCounts: {}, children: [] } }),
    )
    expect(wrapper.findComponent({ name: 'VList' }).exists()).toBe(false)
  })

  it('summarises own cards by state count', () => {
    const wrapper = mount(
      RequestSubItems,
      withVuetify({
        props: { stateCounts: { ready: 2, done: 1 }, children: [] },
      }),
    )
    expect(wrapper.text()).toContain('2 ready')
    expect(wrapper.text()).toContain('1 done')
  })

  it('lists a decomposition child by its own title and ref', () => {
    const wrapper = mount(
      RequestSubItems,
      withVuetify({ props: { stateCounts: {}, children: [child()] } }),
    )
    expect(wrapper.text()).toContain('A decomposed child')
    expect(wrapper.text()).toContain('o/r#2')
  })
})
