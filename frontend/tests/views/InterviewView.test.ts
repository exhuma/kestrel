import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { ref } from 'vue'
import { withVuetify } from '../support/vuetify'
import { testRouter, boardSnapshot, workCardSummary } from '../support/board'
import { __resetInterviewDrafts } from '../../src/composables/useInterviewDraft'
import type { BoardSnapshot } from '../../src/types/workflows'

const current = ref<BoardSnapshot | null>(null)
const error = ref<string | null>(null)
const loading = ref(false)
const mockSelect = vi.fn(async () => true)
const mockStop = vi.fn()
const mockApplyIntervention = vi.fn(async (cardId: string) =>
  workCardSummary({ id: cardId }),
)
vi.mock('../../src/composables/useBoard', () => ({
  useBoard: () => ({
    current,
    error,
    loading,
    select: mockSelect,
    stop: mockStop,
    applyIntervention: mockApplyIntervention,
    resolveQuarantine: vi.fn(),
  }),
}))

import InterviewView from '../../src/views/InterviewView.vue'

const router = testRouter()
let wrappers: VueWrapper[] = []

function interviewGate(overrides: Parameters<typeof workCardSummary>[0] = {}) {
  return workCardSummary({
    id: 'gate-pm',
    title: 'pm interview (2 questions)',
    state: 'awaiting_human',
    allowed_actions: ['resolve_gate'],
    gate: { requested_decision: 'answer', decision: null, round: 1, cap: 2 },
    latest_artifact: { id: 'art-pm', label: 'questions', revision: 1 },
    ...overrides,
  })
}

function stubArtifacts(byArtifactId: Record<string, string[] | null>): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      const match = /\/api\/board\/artifacts\/([^/]+)\/content/.exec(url)
      const id = match?.[1]
      const questions = id ? byArtifactId[id] : undefined
      if (!questions) return new Response('not found', { status: 404 })
      return new Response(
        JSON.stringify({
          content: JSON.stringify({ questions }),
          trust: 'agent_output',
        }),
        { status: 200 },
      )
    }),
  )
}

async function mountInterview(id = 'wf-1'): Promise<VueWrapper> {
  await router.push(`/requests/${id}/interview`)
  await router.isReady()
  const wrapper = mount(
    InterviewView,
    withVuetify({ global: { plugins: [router] } }),
  )
  await flushPromises()
  wrappers.push(wrapper)
  return wrapper
}

beforeEach(() => {
  current.value = null
  error.value = null
  loading.value = false
  mockSelect.mockClear()
  mockStop.mockClear()
  mockApplyIntervention.mockClear()
  mockApplyIntervention.mockImplementation(async (cardId: string) =>
    workCardSummary({ id: cardId }),
  )
  __resetInterviewDrafts()
  stubArtifacts({})
})
afterEach(() => {
  for (const w of wrappers) w.unmount()
  wrappers = []
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('InterviewView per-persona grouping (FR-021)', () => {
  it('groups each open gate’s questions under its own persona', async () => {
    stubArtifacts({ 'art-pm': ['Q1?', 'Q2?'], 'art-uiux': ['Q3?'] })
    current.value = boardSnapshot({
      cards: [
        interviewGate(),
        interviewGate({
          id: 'gate-uiux',
          title: 'uiux interview (1 question)',
          gate: {
            requested_decision: 'answer',
            decision: null,
            round: 1,
            cap: 2,
          },
          latest_artifact: { id: 'art-uiux', label: 'questions', revision: 1 },
        }),
      ],
    })
    const wrapper = await mountInterview()
    const groups = wrapper.findAllComponents({ name: 'PersonaQuestionGroup' })
    expect(groups).toHaveLength(2)
    expect(groups.map((g) => g.props('card').persona)).toEqual(['pm', 'uiux'])
  })
})

describe('InterviewView submission gating (FR-026)', () => {
  it('refuses submit while required questions are outstanding and names them', async () => {
    stubArtifacts({ 'art-pm': ['Q1?', 'Q2?'] })
    current.value = boardSnapshot({ cards: [interviewGate()] })
    const wrapper = await mountInterview()

    const submitBtn = wrapper
      .findAllComponents({ name: 'VBtn' })
      .find((b) => b.text() === 'Submit answers')
    expect(submitBtn?.props('disabled')).toBe(true)
    expect(wrapper.find('[data-testid="outstanding"]').text()).toContain('2')
  })

  it('allows submit once every question is answered or waived', async () => {
    stubArtifacts({ 'art-pm': ['Q1?', 'Q2?'] })
    current.value = boardSnapshot({ cards: [interviewGate()] })
    const wrapper = await mountInterview()

    const textareas = wrapper.findAll('[data-testid="answer-text"] textarea')
    await textareas[0].setValue('An answer')
    await wrapper
      .findAll('[data-testid="toggle-not-relevant"] input')[1]
      .setValue(true)

    const submitBtn = wrapper
      .findAllComponents({ name: 'VBtn' })
      .find((b) => b.text() === 'Submit answers')
    expect(submitBtn?.props('disabled')).toBe(false)
  })
})

describe('InterviewView submit path (FR-046, FR-020)', () => {
  it('submits each open card’s serialised answers and returns to the cockpit by name', async () => {
    stubArtifacts({ 'art-pm': ['Q1?'] })
    current.value = boardSnapshot({ cards: [interviewGate()] })
    const wrapper = await mountInterview()

    await wrapper.find('[data-testid="answer-text"] textarea').setValue('OIDC')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(mockApplyIntervention).toHaveBeenCalledWith(
      'gate-pm',
      'resolve_gate',
      'approved',
      'Q: Q1?\nA: OIDC',
    )
    expect(router.currentRoute.value.name).toBe('cockpit')
    expect(router.currentRoute.value.params.id).toBe('wf-1')
  })

  it('shows a distinct draft-saved indicator before submission, not a submitted state', async () => {
    stubArtifacts({ 'art-pm': ['Q1?'] })
    current.value = boardSnapshot({ cards: [interviewGate()] })
    const wrapper = await mountInterview()

    await wrapper.find('[data-testid="answer-text"] textarea').setValue('OIDC')
    await flushPromises()

    expect(wrapper.find('[data-testid="draft-status"]').exists()).toBe(true)
    expect(router.currentRoute.value.name).toBe('interview')
  })

  it('pops the draft-saved snackbar once a save settles, distinct from submitting', async () => {
    vi.useFakeTimers()
    stubArtifacts({ 'art-pm': ['Q1?'] })
    current.value = boardSnapshot({ cards: [interviewGate()] })
    const wrapper = await mountInterview()

    const snackbar = () => wrapper.findComponent({ name: 'VSnackbar' })
    expect(snackbar().props('modelValue')).toBe(false)

    await wrapper.find('[data-testid="answer-text"] textarea').setValue('OIDC')
    await vi.advanceTimersByTimeAsync(800)
    await wrapper.vm.$nextTick()

    expect(snackbar().props('modelValue')).toBe(true)
    vi.useRealTimers()
  })
})

describe('InterviewView failure paths', () => {
  it('states plainly when a question set cannot be read, rather than an empty interview', async () => {
    stubArtifacts({})
    current.value = boardSnapshot({ cards: [interviewGate()] })
    const wrapper = await mountInterview()

    expect(wrapper.find('[data-testid="unreadable-alert"]').exists()).toBe(true)
    expect(
      wrapper.findAllComponents({ name: 'PersonaQuestionGroup' }),
    ).toHaveLength(0)
  })

  it('surfaces a 409 on submit as a human "moved on" message', async () => {
    stubArtifacts({ 'art-pm': ['Q1?'] })
    current.value = boardSnapshot({ cards: [interviewGate()] })
    mockApplyIntervention.mockImplementation(async () => {
      error.value = 'Request failed (409)'
      return null
    })
    const wrapper = await mountInterview()

    await wrapper.find('[data-testid="answer-text"] textarea').setValue('OIDC')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[data-testid="stale-message"]').text()).toContain(
      'moved on',
    )
    expect(router.currentRoute.value.name).toBe('interview')
  })

  it('gives an unknown request id the explanatory surface', async () => {
    error.value = 'Request failed (404)'
    const wrapper = await mountInterview('nope')
    expect(wrapper.findComponent({ name: 'NotFoundView' }).exists()).toBe(true)
  })

  it('redirects to the cockpit when the request has no open interview', async () => {
    current.value = boardSnapshot({ cards: [] })
    await mountInterview()
    expect(router.currentRoute.value.name).toBe('cockpit')
  })
})
