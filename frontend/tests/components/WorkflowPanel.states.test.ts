import { describe, it, expect, vi } from 'vitest'
import { ref } from 'vue'
import { mount } from '@vue/test-utils'
import { withVuetify } from '../support/vuetify'
import type { WorkflowDetail, WorkflowSummary } from '../../src/types/workflows'

// Build a controllable useWorkflows mock so we can render a Jira vs GitHub run.
const state = {
  current: ref<WorkflowDetail | null>(null),
  workflows: ref<WorkflowSummary[]>([]),
}
vi.mock('../../src/composables/useWorkflows', () => ({
  useWorkflows: () => ({
    workflows: state.workflows,
    current: state.current,
    events: ref([]),
    error: ref(null),
    refresh: vi.fn(),
    select: vi.fn(),
    ensureLive: vi.fn(),
    streamSession: vi.fn(),
    closeSession: vi.fn(),
    createWorkflow: vi.fn(),
    reply: vi.fn(),
    submitAnswers: vi.fn(),
    saveDraft: vi.fn(),
    approve: vi.fn(),
    reject: vi.fn(),
    stop: vi.fn(),
    remove: vi.fn(),
  }),
}))

import WorkflowPanel from '../../src/components/WorkflowPanel.vue'

function detail(over: Partial<WorkflowDetail>): WorkflowDetail {
  return {
    id: 'wf-1',
    repo: 'team/svc',
    issue_number: null,
    issue_title: 'RFC title',
    status: 'coding',
    branch: 'kestrel/RFC-1',
    steps: [
      { name: 'refine', status: 'done' } as never,
      { name: 'design', status: 'done' } as never,
      { name: 'code', status: 'running' } as never,
      { name: 'verify', status: 'pending' } as never,
    ],
    current_session_id: null,
    active_sessions: [],
    refine_round_cap: 1,
    refine_max_rounds: 3,
    allow_incomplete_answers: false,
    pr_url: null,
    error: null,
    ...over,
  }
}

describe('WorkflowPanel run identity + steps', () => {
  it('renders the reshaped design/code/verify step chips', () => {
    state.current.value = detail({})
    state.workflows.value = [
      { id: 'wf-1', repo: 'team/svc', issue_number: null, status: 'coding' },
    ]
    const html = mount(WorkflowPanel, withVuetify()).html()
    for (const step of ['refine', 'design', 'code', 'verify']) {
      expect(html).toContain(step)
    }
  })

  it('shows a Jira run by repo only, with no broken GitHub issue link', () => {
    state.current.value = detail({ issue_number: null })
    const wrapper = mount(WorkflowPanel, withVuetify())
    const header = wrapper.find('.stage__id')
    expect(header.text()).toBe('team/svc')
    // No GitHub issue anchor for a Jira run (issue_number is null).
    expect(wrapper.find('a.stage__id').exists()).toBe(false)
  })

  it('shows a GitHub run as repo#number with an issue link', () => {
    state.current.value = detail({
      repo: 'o/r',
      issue_number: 5,
      branch: 'kestrel/issue-5',
    })
    const wrapper = mount(WorkflowPanel, withVuetify())
    const link = wrapper.find('a.stage__id')
    expect(link.exists()).toBe(true)
    expect(link.text()).toBe('o/r#5')
    expect(link.attributes('href')).toBe('https://github.com/o/r/issues/5')
  })
})
