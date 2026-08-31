import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref } from 'vue'
import { mount } from '@vue/test-utils'
import { withVuetify } from '../support/vuetify'
import type { WorkflowDetail, WorkflowSummary } from '../../src/types/workflows'

function stubScreenshots(): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok: true, status: 200, json: async () => [] })),
  )
}

beforeEach(() => stubScreenshots())
afterEach(() => vi.restoreAllMocks())

const state = {
  current: ref<WorkflowDetail | null>(null),
  workflows: ref<WorkflowSummary[]>([]),
}
// Controlled per test: the set of permissions the mocked usePermissions()
// reports as held.
let granted = new Set<string>()

vi.mock('../../src/composables/useWorkflows', () => ({
  useWorkflows: () => ({
    workflows: state.workflows,
    current: state.current,
    events: ref([]),
    error: ref(null),
    refresh: vi.fn(),
    startList: vi.fn(),
    stopList: vi.fn(),
    select: vi.fn(),
    ensureLive: vi.fn(),
    pollActiveStep: vi.fn(),
    streamSession: vi.fn(),
    closeSession: vi.fn(),
    reply: vi.fn(),
    submitAnswers: vi.fn(),
    saveDraft: vi.fn(),
    approve: vi.fn(),
    reject: vi.fn(),
    stop: vi.fn(),
    remove: vi.fn(),
    cleanup: vi.fn(),
    rerun: vi.fn(),
  }),
}))
vi.mock('../../src/composables/usePermissions', () => ({
  usePermissions: () => ({ can: (p: string) => granted.has(p) }),
}))

import WorkflowPanel from '../../src/components/WorkflowPanel.vue'

function detail(over: Partial<WorkflowDetail>): WorkflowDetail {
  return {
    id: 'wf-1',
    repo: 'team/svc',
    issue_number: null,
    issue_title: 'RFC title',
    status: 'awaiting_plan_approval',
    branch: 'kestrel/RFC-1',
    steps: [{ name: 'plan', status: 'awaiting_approval' } as never],
    current_session_id: null,
    active_sessions: [],
    round_history: [],
    refine_round_cap: 1,
    refine_max_rounds: 3,
    verify_max_iterations: 3,
    allow_incomplete_answers: false,
    rerunnable: true,
    task_label: 'team/svc',
    task_link: null,
    pr_url: null,
    error: null,
    ...over,
  }
}

function findButtonByText(html: ReturnType<typeof mount>, text: string) {
  return html.findAll('button').find((b) => b.text().includes(text))
}

function findIconButtonByTitle(
  html: ReturnType<typeof mount>,
  title: string,
) {
  return html
    .findAll('button.v-btn--icon')
    .find((b) => b.attributes('title') === title)
}

function mountForIconButtons(): ReturnType<typeof mount> {
  state.current.value = detail({ status: 'coding', steps: [] })
  state.workflows.value = [
    {
      id: 'wf-1', repo: 'me/sandbox', issue_number: null,
      status: 'coding', rerunnable: true,
    },
  ]
  return mount(WorkflowPanel, withVuetify())
}

describe('WorkflowPanel permission gating: approve/reject', () => {
  it('disables approve/reject when the caller lacks the permission', () => {
    granted = new Set()
    state.current.value = detail({})
    state.workflows.value = [
      { id: 'wf-1', repo: 'team/svc', issue_number: null, status: 'coding' },
    ]
    const wrapper = mount(WorkflowPanel, withVuetify())
    expect(
      findButtonByText(wrapper, 'Approve')?.attributes('disabled'),
    ).toBeDefined()
    expect(
      findButtonByText(wrapper, 'Reject')?.attributes('disabled'),
    ).toBeDefined()
  })

  it('enables approve/reject when the caller holds the matching permission', () => {
    granted = new Set(['workflows:approve', 'workflows:reject'])
    state.current.value = detail({})
    state.workflows.value = []
    const wrapper = mount(WorkflowPanel, withVuetify())
    expect(
      findButtonByText(wrapper, 'Approve')?.attributes('disabled'),
    ).toBeUndefined()
    expect(
      findButtonByText(wrapper, 'Reject')?.attributes('disabled'),
    ).toBeUndefined()
  })
})

describe('WorkflowPanel permission gating: rerun/cleanup/abandon', () => {
  it('disables the icon buttons without their permissions', () => {
    granted = new Set()
    const wrapper = mountForIconButtons()
    for (const title of [
      'Rerun workflow', 'Clean up workflow', 'Abandon workflow',
    ]) {
      expect(
        findIconButtonByTitle(wrapper, title)?.attributes('disabled'),
      ).toBeDefined()
    }
  })

  it('enables the icon buttons with their permissions', () => {
    granted = new Set([
      'workflows:rerun', 'workflows:cleanup', 'workflows:delete',
    ])
    const wrapper = mountForIconButtons()
    for (const title of [
      'Rerun workflow', 'Clean up workflow', 'Abandon workflow',
    ]) {
      expect(
        findIconButtonByTitle(wrapper, title)?.attributes('disabled'),
      ).toBeUndefined()
    }
  })
})
