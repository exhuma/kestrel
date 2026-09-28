// Shared board-domain test fixtures (feature 029): a minimal, memory-history
// router with the named routes stage-board components link to, and a
// `BoardWorkflowSummary` builder. Centralised because several stage-board
// test files each need both.
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import type { BoardWorkflowSummary } from '../../src/types/workflows'

export function testRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'board', component: { template: '<div />' } },
      {
        path: '/requests/:id',
        name: 'cockpit',
        component: { template: '<div />' },
      },
    ],
  })
}

export function boardWorkflowSummary(
  overrides: Partial<BoardWorkflowSummary> = {},
): BoardWorkflowSummary {
  return {
    id: 'wf-1',
    task_label: 'o/r#1',
    title: 'A request',
    parent_workflow_id: null,
    status: 'active',
    state_counts: {},
    action_required_count: 0,
    phase: 'Build',
    stage: 'Build & deliver',
    cap_exhausted: false,
    ...overrides,
  }
}
