import { describe, it, expect, vi, afterEach } from 'vitest'
import { ref } from 'vue'
import { mount } from '@vue/test-utils'
import { withVuetify } from '../support/vuetify'
import type { SessionSummary } from '../../src/types/sessions'

afterEach(() => vi.restoreAllMocks())

const state = {
  sessions: ref<SessionSummary[]>([]),
}
// Controlled per test: the set of permissions the mocked usePermissions()
// reports as held.
let granted = new Set<string>()

vi.mock('../../src/composables/useSessions', () => ({
  useSessions: () => ({
    sessions: state.sessions,
    events: ref([]),
    loading: ref(false),
    error: ref(null),
    refresh: vi.fn(),
    start: vi.fn(),
    resume: vi.fn(),
    poll: vi.fn(),
    watchEvents: vi.fn(),
    stopEvents: vi.fn(),
    remove: vi.fn(),
  }),
}))
vi.mock('../../src/composables/usePermissions', () => ({
  usePermissions: () => ({ can: (p: string) => granted.has(p) }),
}))

import SessionPanel from '../../src/components/SessionPanel.vue'

function findButtonByText(html: ReturnType<typeof mount>, text: string) {
  return html.findAll('button').find((b) => b.text().includes(text))
}

describe('SessionPanel permission gating: launch/resume', () => {
  it('disables launch/resume without sessions:write', () => {
    granted = new Set()
    const wrapper = mount(SessionPanel, withVuetify())
    expect(
      findButtonByText(wrapper, 'Launch session')?.attributes('disabled'),
    ).toBeDefined()
  })

  it('enables launch when the prompt is filled and sessions:write is held', async () => {
    granted = new Set(['sessions:write'])
    const wrapper = mount(SessionPanel, withVuetify())
    const textarea = wrapper.find('textarea')
    await textarea.setValue('do something')
    expect(
      findButtonByText(wrapper, 'Launch session')?.attributes('disabled'),
    ).toBeUndefined()
  })
})

describe('SessionPanel permission gating: abandon', () => {
  it('disables the abandon-session icon button without sessions:delete', () => {
    granted = new Set()
    state.sessions.value = [
      { session_id: 's1', status: 'idle', event_count: 0 },
    ]
    const wrapper = mount(SessionPanel, withVuetify())
    const abandon = wrapper
      .findAll('button.v-btn--icon')
      .find((b) => b.attributes('title') === 'Abandon session')
    expect(abandon?.attributes('disabled')).toBeDefined()
  })

  it('enables the abandon-session icon button with sessions:delete', () => {
    granted = new Set(['sessions:delete'])
    state.sessions.value = [
      { session_id: 's1', status: 'idle', event_count: 0 },
    ]
    const wrapper = mount(SessionPanel, withVuetify())
    const abandon = wrapper
      .findAll('button.v-btn--icon')
      .find((b) => b.attributes('title') === 'Abandon session')
    expect(abandon?.attributes('disabled')).toBeUndefined()
  })
})
