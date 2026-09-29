/**
 * Pure grouping and parsing for the interview workspace (feature 029,
 * US3, FR-021, FR-045): which cards are open interview gates, which
 * persona each belongs to, and the question set inside each one's
 * artifact.
 */
import type { WorkCardSummary } from '../types/workflows'
import type { InterviewCard, RoundState } from '../types/interview'

/** A card is an open, answerable interview gate when its `requested_
 *  decision` is `'answer'` and no decision has been recorded yet — the
 *  same test `lib/asks.ts::isGateAsk` uses, narrowed to the interview
 *  kind (FR-016/FR-017's `'interview'` ask). */
export function isOpenInterviewCard(card: WorkCardSummary): boolean {
  return (
    card.gate?.requested_decision === 'answer' &&
    card.gate.decision === null &&
    card.allowed_actions.includes('resolve_gate')
  )
}

const TITLE_PERSONA = /^(\w+) interview\b/i

/** The persona a gate card's questions belong to (FR-021).
 *
 *  Derived from the card's title — the only signal the board API exposes
 *  for a `refinement_gate`, which itself carries no `eligible_roles`
 *  (`backend/app/services/board/refinement_rounds.py`'s module docstring:
 *  "a refinement_gate card itself carries no eligible_roles"). The title
 *  is `f"{persona} interview (...)"` by construction
 *  (`refinement.py::route_refinement_result`). A CAB-1 strategic-fit gate
 *  has no such prefix because it is always the requester's
 *  (`refinement.py::route_strategic_interview_result`), so anything that
 *  does not match falls back to `'requester'` rather than guessing a
 *  persona that was never offered. */
export function personaOf(card: WorkCardSummary): string {
  const match = TITLE_PERSONA.exec(card.title)
  return match ? match[1].toLowerCase() : 'requester'
}

/** One question as parsed: open (`options` null) or a choice question
 *  (feature 034). */
export interface ParsedQuestion {
  prompt: string
  options: string[] | null
  multiple: boolean
}

function parseQuestion(raw: unknown): ParsedQuestion | null {
  if (typeof raw === 'string') {
    return raw.trim() ? { prompt: raw, options: null, multiple: false } : null
  }
  if (typeof raw !== 'object' || raw === null) return null
  const q = raw as Record<string, unknown>
  const options = q.options
  if (typeof q.prompt !== 'string' || !q.prompt.trim()) return null
  if (!Array.isArray(options) || options.length < 2) return null
  if (!options.every((o) => typeof o === 'string' && o.trim())) return null
  return {
    prompt: q.prompt,
    options: options as string[],
    multiple: q.multiple === true,
  }
}

/** Parse an interview artifact's `{questions: [...], satisfied?: boolean}`
 *  content (`refinement.py`, normalised by `questions.py`): each question
 *  a plain string, or `{prompt, options, multiple}`. Returns `null` for
 *  anything unparseable or empty (FR-045) — callers surface that as
 *  "could not be read", never as an empty interview. */
export function parseQuestionSet(text: string | null): ParsedQuestion[] | null {
  if (!text) return null
  let data: unknown
  try {
    data = JSON.parse(text)
  } catch {
    return null
  }
  if (typeof data !== 'object' || data === null) return null
  const questions = (data as Record<string, unknown>).questions
  if (!Array.isArray(questions) || questions.length === 0) return null
  const parsed = questions.map(parseQuestion)
  if (parsed.some((q) => q === null)) return null
  return parsed as ParsedQuestion[]
}

/** Build one `InterviewCard` per open gate whose artifact content parsed.
 *  Cards whose content failed to parse are reported separately
 *  (FR-045) rather than silently dropped from the interview. */
export function buildInterviewCards(
  cards: WorkCardSummary[],
  contentByCardId: Record<string, string | null>,
): { cards: InterviewCard[]; unreadable: WorkCardSummary[] } {
  const open = cards.filter(isOpenInterviewCard)
  const result: InterviewCard[] = []
  const unreadable: WorkCardSummary[] = []
  for (const card of open) {
    const raw = parseQuestionSet(contentByCardId[card.id] ?? null)
    if (!raw) {
      unreadable.push(card)
      continue
    }
    result.push({
      cardId: card.id,
      persona: personaOf(card),
      questions: raw.map((q, i) => ({
        id: `${card.id}:${i}`,
        prompt: q.prompt,
        ...(q.options ? { options: q.options, multiple: q.multiple } : {}),
      })),
      round: card.gate?.round ?? null,
      cap: card.gate?.cap ?? null,
    })
  }
  return { cards: result, unreadable }
}

/** The round/cap to show in the shared indicator (FR-024, FR-027): every
 *  persona interviewed in one round shares the same cap and, barring one
 *  persona lagging behind, the same round number, so the first
 *  round-capped gate's state stands for the surface. `null`/`null`
 *  degrades to a single round rather than a false 0-of-0. */
export function deriveRoundState(cards: InterviewCard[]): RoundState {
  const capped = cards.find((c) => c.cap !== null)
  return capped
    ? { current: capped.round, cap: capped.cap }
    : { current: null, cap: null }
}
