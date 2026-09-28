/**
 * The answer model itself (feature 029, US3): completeness gating
 * (FR-026), round-advance reconciliation (FR-025) and the submit-time
 * serialisation (FR-046) — split from `lib/interview.ts` (grouping and
 * parsing) per research R5's "port, then split" note, so neither file
 * grows toward the module-length cap carrying a concern the other owns.
 */
import type {
  AnswerState,
  InterviewQuestion,
  QuestionAnswer,
} from '../types/interview'

/** True once *answer* is a concrete answer, a waived "I don't know", or a
 *  "not relevant" — anything but nothing recorded at all. */
export function isAnswered(answer: QuestionAnswer | undefined): boolean {
  return answer !== undefined && answer.state !== 'unanswered'
}

/** FR-026: submission is refused while any question is neither answered
 *  nor waived. Every open question is required — the current backend has
 *  no "optional question" concept to hang an exemption off. */
export function allRequiredAnswered(
  questions: InterviewQuestion[],
  answers: Record<string, QuestionAnswer>,
): boolean {
  return questions.every((q) => isAnswered(answers[q.id]))
}

/** The questions still blocking submission, so they can be identified to
 *  the operator (FR-026) rather than just refusing silently. */
export function outstandingQuestions(
  questions: InterviewQuestion[],
  answers: Record<string, QuestionAnswer>,
): InterviewQuestion[] {
  return questions.filter((q) => !isAnswered(answers[q.id]))
}

/** Reconcile answers against a new round's questions by question
 *  *identity* — the prompt text, since the backend hands back a new card
 *  (and so a new question `id`) every round (FR-025). An answer whose
 *  question no longer exists is dropped rather than misattributed to
 *  whatever now occupies its old id. */
export function reconcileAnswers(
  oldQuestions: InterviewQuestion[],
  oldAnswers: Record<string, QuestionAnswer>,
  newQuestions: InterviewQuestion[],
): Record<string, QuestionAnswer> {
  const promptById = new Map(oldQuestions.map((q) => [q.id, q.prompt]))
  const byPrompt = new Map<string, QuestionAnswer>()
  for (const [id, answer] of Object.entries(oldAnswers)) {
    const prompt = promptById.get(id)
    if (prompt !== undefined) byPrompt.set(prompt, answer)
  }
  const merged: Record<string, QuestionAnswer> = {}
  for (const q of newQuestions) {
    const prior = byPrompt.get(q.prompt)
    if (prior) merged[q.id] = prior
  }
  return merged
}

/** Wording for the two escape hatches and the (unreachable at submit
 *  time, since FR-026 blocks it) unanswered case — kept distinguishable
 *  in the serialised text as FR-046 requires. See data-model.md §2 for
 *  the recorded format decision. */
const STATE_TEXT: Readonly<Record<Exclude<AnswerState, 'answered'>, string>> = {
  unknown: "(I don't know — let the PRD state an assumption.)",
  'not-relevant': '(Not relevant.)',
  unanswered: '(No answer was given.)',
}

function bodyOf(answer: QuestionAnswer | undefined): string {
  if (answer?.state === 'answered') return answer.text.trim()
  return STATE_TEXT[answer?.state ?? 'unanswered']
}

/** Serialise one persona's questions and answers into the single
 *  free-text `answer` field `resolve_gate` accepts (FR-046). Each
 *  question becomes a `Q:`/`A:` block; blocks are separated by a blank
 *  line so the format reads as plain text to both a human reviewing the
 *  artifact later and the `pm` agent drafting the next round or the PRD. */
export function serializeAnswers(
  questions: InterviewQuestion[],
  answers: Record<string, QuestionAnswer>,
): string {
  return questions
    .map((q) => `Q: ${q.prompt}\nA: ${bodyOf(answers[q.id])}`)
    .join('\n\n')
}
