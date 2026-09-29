// Shared board-domain test fixtures (feature 029): a minimal, memory-history
// router with the named routes the board and cockpit link to, plus builders
// for the board DTOs. Centralised because several test files each need them.
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import type {
  BoardEvent,
  BoardSnapshot,
  BoardWorkflowSummary,
  WorkCardSummary,
} from '../../src/types/workflows'

const stub = { template: '<div />' }

export function testRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'board', component: stub },
      { path: '/requests/:id', name: 'cockpit', component: stub },
      { path: '/requests/:id/interview', name: 'interview', component: stub },
      { path: '/:pathMatch(.*)*', name: 'not-found', component: stub },
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
    status: 'active',
    state_counts: {},
    action_required_count: 0,
    phase: 'Build',
    stage: 'Build & deliver',
    cap_exhausted: false,
    open_manual_task_count: 0,
    ...overrides,
  }
}

export function workCardSummary(
  overrides: Partial<WorkCardSummary> = {},
): WorkCardSummary {
  return {
    id: 'card-1',
    title: 'A card',
    card_type: 'implementation',
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

export function boardSnapshot(
  overrides: Partial<BoardSnapshot> = {},
): BoardSnapshot {
  return {
    id: 'wf-1',
    revision: 1,
    task_label: 'o/r#1',
    title: 'A request',
    status: 'active',
    cards: [],
    relationships: [],
    state_counts: {},
    phase: 'Build',
    stage: 'Build & deliver',
    task_body: '',
    ...overrides,
  }
}

export function boardEvent(overrides: Partial<BoardEvent> = {}): BoardEvent {
  return {
    event_type: 'card_created',
    card_id: 'card-1',
    payload: 'something happened',
    created_at: '2026-09-28T10:00:00Z',
    specialist: null,
    ...overrides,
  }
}
