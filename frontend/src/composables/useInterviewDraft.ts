/**
 * Draft answers for the interview workspace (feature 029, US3, FR-022,
 * FR-025): a module-level singleton keyed per workflow, so in-progress
 * answers survive leaving the `interview` route for the `cockpit` and
 * coming back — component-local state would not.
 *
 * There is no draft endpoint on the backend (the only write path is the
 * final `resolve_gate` submission), so "autosave" here means committing
 * into this singleton, not a network call — the debounce exists to turn
 * per-keystroke writes into an unambiguous idle/dirty/saving/saved signal
 * (FR-022) rather than to throttle a request that does not exist.
 *
 * The reconciliation logic itself (matching answers across a round
 * advance) is `lib/interviewAnswers.ts::reconcileAnswers`, ported from
 * `3fc281c^:frontend/src/components/QuestionnaireForm.vue` per research
 * R5 rather than rewritten; this module only owns *when* to call it and
 * the draft/status state machine around it.
 */
import { reactive, ref, type Ref } from 'vue'
import { debounce } from '../lib/debounce'
import { reconcileAnswers } from '../lib/interviewAnswers'
import type { InterviewQuestion, QuestionAnswer } from '../types/interview'

export type DraftStatus = 'idle' | 'dirty' | 'saving' | 'saved'

interface DraftEntry {
  answers: Record<string, QuestionAnswer>
  status: Ref<DraftStatus>
  lastQuestions: InterviewQuestion[]
  commit: () => void
}

const drafts = new Map<string, DraftEntry>()

function makeEntry(): DraftEntry {
  const status = ref<DraftStatus>('idle')
  async function settle(): Promise<void> {
    status.value = 'saving'
    await Promise.resolve()
    status.value = 'saved'
  }
  return {
    answers: reactive({}),
    status,
    lastQuestions: [],
    commit: debounce(() => void settle(), 800),
  }
}

function entryFor(workflowId: string): DraftEntry {
  let entry = drafts.get(workflowId)
  if (!entry) {
    entry = makeEntry()
    drafts.set(workflowId, entry)
  }
  return entry
}

export interface InterviewDraft {
  answers: Record<string, QuestionAnswer>
  status: Ref<DraftStatus>
  setAnswer: (questionId: string, answer: QuestionAnswer) => void
  /** Reconcile the draft against a freshly loaded question set. Safe to
   *  call on every load, including one that did not change: the merge is
   *  keyed on question identity (prompt text), so a genuinely-unchanged
   *  question set round-trips through the same ids and is a no-op. */
  reconcile: (questions: InterviewQuestion[]) => void
}

export function useInterviewDraft(workflowId: string): InterviewDraft {
  const entry = entryFor(workflowId)

  function setAnswer(questionId: string, answer: QuestionAnswer): void {
    entry.answers[questionId] = answer
    entry.status.value = 'dirty'
    entry.commit()
  }

  function reconcile(questions: InterviewQuestion[]): void {
    const merged = reconcileAnswers(
      entry.lastQuestions,
      entry.answers,
      questions,
    )
    for (const key of Object.keys(entry.answers)) delete entry.answers[key]
    Object.assign(entry.answers, merged)
    entry.lastQuestions = questions
  }

  return { answers: entry.answers, status: entry.status, setAnswer, reconcile }
}

/** Test-only escape hatch: the singleton must not leak draft state
 *  between test cases. */
export function __resetInterviewDrafts(): void {
  drafts.clear()
}
