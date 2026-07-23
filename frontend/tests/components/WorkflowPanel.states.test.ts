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
    verify_max_iterations: 3,
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

describe('WorkflowPanel failure state', () => {
  it('shows the working spinner while a step runs and the run is healthy', () => {
    state.current.value = detail({}) // code step running, no error
    const html = mount(WorkflowPanel, withVuetify()).html()
    expect(html).toContain('agent is working')
  })

  it('stops the spinner and shows the banner when the run has failed', () => {
    // The buggy backend snapshot: run escalated (error set) yet the code
    // step is still 'running'. The activity indicator must not spin.
    state.current.value = detail({
      status: 'escalated',
      error: 'escalated: the coder produced no changes',
    })
    const html = mount(WorkflowPanel, withVuetify()).html()
    expect(html).not.toContain('agent is working')
    expect(html).toContain(
      'Run failed: escalated: the coder produced no changes',
    )
  })
})

describe('WorkflowPanel step chip cues', () => {
  it('pulses the chip of the actively-running step', () => {
    state.current.value = detail({}) // code step running, healthy
    const html = mount(WorkflowPanel, withVuetify()).html()
    expect(html).toContain('chip--pulse')
  })

  it('does not pulse any chip once the run has failed', () => {
    state.current.value = detail({ status: 'escalated', error: 'boom' })
    const html = mount(WorkflowPanel, withVuetify()).html()
    expect(html).not.toContain('chip--pulse')
  })

  it('shows a remaining-runs ring on the verify chip mid-verify', () => {
    state.current.value = detail({
      status: 'verifying',
      steps: [
        { name: 'refine', status: 'done' } as never,
        { name: 'design', status: 'done' } as never,
        { name: 'code', status: 'done' } as never,
        { name: 'verify', status: 'running', verify_round: 1 } as never,
      ],
      verify_max_iterations: 3,
    })
    const wrapper = mount(WorkflowPanel, withVuetify())
    // 3 cap − 1 entered = 2 runs left, shown in the ring.
    expect(wrapper.find('.chip__verify-count').text()).toBe('2')
    expect(wrapper.find('.v-progress-circular').exists()).toBe(true)
  })
})

describe('WorkflowPanel deliverable rendering', () => {
  it('renders the code diff in the diff viewer, not as markdown', () => {
    const diff =
      'diff --git a/x.txt b/x.txt\n' +
      '--- a/x.txt\n+++ b/x.txt\n@@ -1 +1 @@\n-old\n+new\n'
    state.current.value = detail({
      status: 'coding',
      steps: [
        { name: 'refine', status: 'done' } as never,
        { name: 'design', status: 'done' } as never,
        {
          name: 'code',
          status: 'running',
          deliverable: diff,
          deliverable_format: 'diff',
        } as never,
        { name: 'verify', status: 'pending' } as never,
      ],
    })
    const wrapper = mount(WorkflowPanel, withVuetify())
    expect(wrapper.find('.diff-view').exists()).toBe(true)
    // diff2html emits its own `d2h-*` markup for the change.
    expect(wrapper.html()).toContain('d2h-')
  })
})

describe('WorkflowPanel run list activity', () => {
  it('spins an activity indicator on active runs but not awaiting ones', () => {
    state.current.value = detail({})
    state.workflows.value = [
      { id: 'wf-1', repo: 'a/b', issue_number: null, status: 'coding' },
      {
        id: 'wf-2',
        repo: 'c/d',
        issue_number: null,
        status: 'awaiting_refine_approval',
      },
    ]
    const wrapper = mount(WorkflowPanel, withVuetify())
    const items = wrapper.findAll('.v-list-item')
    // The active (coding) run spins; the awaiting run shows the warning dot.
    expect(items[0].find('.v-progress-circular').exists()).toBe(true)
    expect(items[1].find('.v-progress-circular').exists()).toBe(false)
  })
})
