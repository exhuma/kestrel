import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref } from 'vue'
import { mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { withVuetify } from '../support/vuetify'
import type { BoardWorkflowSummary } from '../../src/types/workflows'
import type { SessionSummary } from '../../src/types/sessions'

// App.vue has no component test today (T020) — view switching went
// untested through the old `view` ref/`v-btn-toggle`. This covers the
// shell's *routed* rendering: RouterView swaps in whatever the current
// route resolves to.

const boardState = {
  workflows: ref<BoardWorkflowSummary[]>([]),
  error: ref<string | null>(null),
}
vi.mock('../../src/composables/useBoard', () => ({
  useBoard: () => ({
    workflows: boardState.workflows,
    error: boardState.error,
    loading: ref(false),
    refresh: vi.fn(),
    startList: vi.fn(),
    stopList: vi.fn(),
  }),
}))

const sessionsState = { sessions: ref<SessionSummary[]>([]) }
vi.mock('../../src/composables/useSessions', () => ({
  useSessions: () => ({
    sessions: sessionsState.sessions,
    loading: ref(false),
  }),
}))

vi.mock('../../src/composables/useConnectivity', () => ({
  useConnectivity: () => ({
    reachable: ref(true),
    apiBase: 'http://localhost:8000',
  }),
}))

import App from '../../src/App.vue'
import StageBoardView from '../../src/views/StageBoardView.vue'
import NotFoundView from '../../src/views/NotFoundView.vue'

function testRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'board', component: StageBoardView },
      {
        path: '/requests/:id',
        name: 'cockpit',
        component: { template: '<div>cockpit stub</div>' },
      },
      {
        path: '/sessions',
        name: 'sessions',
        component: { template: '<div>sessions stub</div>' },
      },
      { path: '/:pathMatch(.*)*', name: 'not-found', component: NotFoundView },
    ],
  })
}

const stubs = {
  NotificationCenter: true,
  SourceHealthIndicator: true,
  IdentityBadge: true,
  GithubLink: true,
}

beforeEach(() => {
  boardState.workflows.value = []
  boardState.error.value = null
})
afterEach(() => vi.restoreAllMocks())

describe('App shell routed rendering', () => {
  it('renders the stage board at the root route', async () => {
    const router = testRouter()
    await router.push('/')
    const wrapper = mount(
      App,
      withVuetify({ global: { plugins: [router], stubs } }),
    )
    await router.isReady()
    expect(wrapper.findComponent(StageBoardView).exists()).toBe(true)
  })

  it('renders whatever the sessions route resolves to', async () => {
    const router = testRouter()
    await router.push('/sessions')
    const wrapper = mount(
      App,
      withVuetify({ global: { plugins: [router], stubs } }),
    )
    await router.isReady()
    expect(wrapper.text()).toContain('sessions stub')
  })

  it('renders the not-found view for an unmatched address', async () => {
    const router = testRouter()
    await router.push('/nowhere')
    const wrapper = mount(
      App,
      withVuetify({ global: { plugins: [router], stubs } }),
    )
    await router.isReady()
    expect(wrapper.findComponent(NotFoundView).exists()).toBe(true)
  })
})
