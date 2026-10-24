import { describe, it, expect, beforeEach, vi } from 'vitest'
import {
  __resetInterviewDrafts,
  useInterviewDraft,
} from '../../src/composables/useInterviewDraft'
import type { InterviewQuestion } from '../../src/types/interview'

beforeEach(() => {
  __resetInterviewDrafts()
  vi.useRealTimers()
})

describe('useInterviewDraft singleton', () => {
  it('returns the same reactive answers across separate calls for one workflow', () => {
    const a = useInterviewDraft('wf-1')
    a.setAnswer('g1:0', { state: 'answered', text: 'OIDC' })
    const b = useInterviewDraft('wf-1')
    expect(b.answers['g1:0']).toEqual({ state: 'answered', text: 'OIDC' })
  })

  it('keeps different workflows independent', () => {
    const a = useInterviewDraft('wf-1')
    a.setAnswer('g1:0', { state: 'answered', text: 'OIDC' })
    const b = useInterviewDraft('wf-2')
    expect(b.answers['g1:0']).toBeUndefined()
  })

  it('survives across "unmount" — the state is module-level, not component-local', () => {
    useInterviewDraft('wf-1').setAnswer('g1:0', {
      state: 'answered',
      text: 'OIDC',
    })
    // Simulate leaving and returning to the route: a fresh call, no
    // component instance carried over.
    expect(useInterviewDraft('wf-1').answers['g1:0']?.text).toBe('OIDC')
  })
})

describe('useInterviewDraft status transitions', () => {
  it('goes idle -> dirty -> saved on a debounced commit', async () => {
    vi.useFakeTimers()
    const draft = useInterviewDraft('wf-1')
    expect(draft.status.value).toBe('idle')

    draft.setAnswer('g1:0', { state: 'answered', text: 'OIDC' })
    expect(draft.status.value).toBe('dirty')

    await vi.advanceTimersByTimeAsync(800)
    expect(draft.status.value).toBe('saved')
  })

  it('coalesces rapid edits into a single settle, not one per keystroke', async () => {
    vi.useFakeTimers()
    const draft = useInterviewDraft('wf-1')
    draft.setAnswer('g1:0', { state: 'answered', text: 'O' })
    await vi.advanceTimersByTimeAsync(400)
    draft.setAnswer('g1:0', { state: 'answered', text: 'OI' })
    await vi.advanceTimersByTimeAsync(400)
    // The first debounce window never fired — it was reset by the
    // second edit — so status is still dirty at 800ms total elapsed.
    expect(draft.status.value).toBe('dirty')

    await vi.advanceTimersByTimeAsync(400)
    expect(draft.status.value).toBe('saved')
    expect(draft.answers['g1:0'].text).toBe('OI')
  })
})

describe('useInterviewDraft reconciliation across a round advance', () => {
  it('carries an answer forward under the new round’s question id', () => {
    const draft = useInterviewDraft('wf-1')
    const round1: InterviewQuestion[] = [{ id: 'g1:0', prompt: 'Auth?' }]
    draft.reconcile(round1)
    draft.setAnswer('g1:0', { state: 'answered', text: 'OIDC' })

    const round2: InterviewQuestion[] = [{ id: 'g2:0', prompt: 'Auth?' }]
    draft.reconcile(round2)

    expect(draft.answers['g1:0']).toBeUndefined()
    expect(draft.answers['g2:0']).toEqual({ state: 'answered', text: 'OIDC' })
  })

  it('drops an answer whose question is gone from the new round', () => {
    const draft = useInterviewDraft('wf-1')
    draft.reconcile([{ id: 'g1:0', prompt: 'Auth?' }])
    draft.setAnswer('g1:0', { state: 'answered', text: 'OIDC' })

    draft.reconcile([{ id: 'g2:0', prompt: 'A different question?' }])

    expect(Object.keys(draft.answers)).toEqual([])
  })

  it('is a no-op when reconciled again with an unchanged question set', () => {
    const draft = useInterviewDraft('wf-1')
    const questions: InterviewQuestion[] = [{ id: 'g1:0', prompt: 'Auth?' }]
    draft.reconcile(questions)
    draft.setAnswer('g1:0', { state: 'answered', text: 'OIDC' })

    draft.reconcile(questions)

    expect(draft.answers['g1:0']).toEqual({ state: 'answered', text: 'OIDC' })
  })
})
