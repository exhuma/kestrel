/**
 * Answer-model types for the interview workspace (feature 029, US3).
 *
 * Recovered from `3fc281c^:frontend/src/types/questionnaire.ts` per
 * research R5, then re-pointed at the current backend rather than restored
 * verbatim: a refinement round now emits a flat list of question strings
 * (`app/services/board/refinement.py::parse_refinement_round`), with no
 * `id`, `type`, `options` or `required` — every open question is required,
 * and `single_select`/`multi_select`/waiver/custom answers have no backend
 * counterpart any more. FR-023 keeps only the two escape hatches the issue
 * actually asks for.
 */

/** The four answer states FR-023 requires stay distinguishable.
 *  `unanswered` blocks submission (FR-026); the other three do not. */
export type AnswerState = 'answered' | 'unknown' | 'not-relevant' | 'unanswered'

/** One question's recorded answer. `text` is meaningful only when
 *  `state === 'answered'` — the escape hatches carry no text
 *  (data-model.md §2). */
export interface QuestionAnswer {
  state: AnswerState
  text: string
}

/** One question, scoped to the gate card it must be submitted through.
 *  `id` is stable only within one round: the backend hands back a new
 *  card id every round, so round-advance reconciliation (FR-025) keys on
 *  `prompt` text instead — see `lib/interview.ts`. */
export interface InterviewQuestion {
  id: string
  prompt: string
}

/** One persona's open interview gate: its question set plus the round
 *  state and the card id the combined answer is submitted against. */
export interface InterviewCard {
  cardId: string
  persona: string
  questions: InterviewQuestion[]
  round: number | null
  cap: number | null
}

/** The round indicator's state (FR-024, FR-027). `null`/`null` means "not
 *  a round-capped gate" — degrades to a single round rather than 0-of-0. */
export interface RoundState {
  current: number | null
  cap: number | null
}
