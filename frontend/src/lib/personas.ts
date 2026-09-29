/**
 * Narrative-feed view model (feature 029, US2): turning one `BoardEvent`
 * into an attributed, toned, human-readable row.
 *
 * Pure and display-only. The vocabulary below mirrors the literals the
 * backend actually appends (`app/services/board/`) — `workflow.created`,
 * `card.*`, `gate.*`, `intervention.*`, `coordinator.*`, `refinement.*`
 * and `dev_reset.*`. An event type not listed here renders its own name
 * rather than being dropped: the feed's job is to carry the whole story,
 * including the parts this module has not been taught yet.
 */
import type { BoardEvent } from '../types/workflows'

/** Attribution, honestly (FR-013).
 *
 *  A tagged union rather than `string | null` so the neutral case cannot
 *  be rendered as an empty name or silently given an arbitrary one.
 *  `BoardEvent.specialist` is a **read-time derivation from the card's
 *  eligible role, not a recorded actor** (`backend/app/schemas.py`) —
 *  feature 026 never recorded who actually acted. */
export type PersonaLabel =
  | { kind: 'specialist'; name: string }
  | { kind: 'system' }
  | { kind: 'operator' }

export type FeedTone = 'info' | 'success' | 'warning' | 'error'

export interface FeedEntry {
  event: BoardEvent
  persona: PersonaLabel
  tone: FeedTone
  summary: string
  timestamp: string
}

/** Event types the operator causes. Attribution comes from the event type
 *  and never from `specialist`: a gate the operator resolved still carries
 *  the gate card's eligible role, so trusting that field would credit the
 *  operator's own decision to a specialist. */
const OPERATOR_EVENTS: ReadonlySet<string> = new Set([
  'gate.approved',
  'gate.rejected',
  'gate.rejected_dependent_cancelled',
  'intervention.retry',
  'intervention.cancel',
  'intervention.reassign',
  'manual_task.completed',
  'dev_reset.cleanup',
  'dev_reset.rerun',
])

const TONES: Readonly<Record<string, FeedTone>> = {
  'workflow.created': 'info',
  'card.dependency_met': 'info',
  'card.result_accepted': 'success',
  'refinement.satisfied': 'success',
  'gate.approved': 'success',
  // A rejection is a legitimate decision, not a malfunction — warning, not
  // error, so genuine failures stay distinguishable from normal outcomes.
  'gate.rejected': 'warning',
  'gate.rejected_dependent_cancelled': 'warning',
  'intervention.retry': 'warning',
  'intervention.cancel': 'warning',
  'intervention.reassign': 'info',
  'manual_task.completed': 'success',
  'screening.passed': 'success',
  'screening.quarantined': 'warning',
  'screening.released': 'info',
  'coordinator.transition_card': 'info',
  'card.recovery_retry': 'warning',
  'card.recovery_escalated': 'error',
  'dev_reset.cleanup': 'warning',
  'dev_reset.rerun': 'warning',
}

const SUMMARIES: Readonly<Record<string, string>> = {
  'workflow.created': 'Request ingested',
  'card.dependency_met': 'Dependency met — work can start',
  'card.result_accepted': 'Result accepted',
  'refinement.satisfied': 'Interview complete — no further round needed',
  'gate.approved': 'You approved this gate',
  'gate.rejected': 'You rejected this gate',
  'gate.rejected_dependent_cancelled':
    'Dependent work cancelled by that rejection',
  'intervention.retry': 'You retried this card',
  'intervention.cancel': 'You cancelled this card',
  'intervention.reassign': 'You returned this card to the queue',
  'manual_task.completed': 'You marked a manual task done',
  'screening.passed': 'Input screened: safe to work on',
  'screening.quarantined': 'Input quarantined for your review',
  'screening.released': 'You released the quarantined input',
  'coordinator.transition_card': 'Coordinator moved this card on',
  'card.recovery_retry': 'Recovery retried a stalled card',
  'card.recovery_escalated': 'Recovery escalated a failed card',
  'dev_reset.cleanup': 'Developer reset: workflow cleaned up',
  'dev_reset.rerun': 'Developer reset: workflow rerun',
}

export function personaOf(event: BoardEvent): PersonaLabel {
  if (OPERATOR_EVENTS.has(event.event_type)) return { kind: 'operator' }
  const name = event.specialist?.label
  return name ? { kind: 'specialist', name } : { kind: 'system' }
}

export function toneOf(event: BoardEvent): FeedTone {
  return TONES[event.event_type] ?? 'info'
}

/** A human sentence for the event, falling back to its raw type so an
 *  unknown event still says what it was. */
export function summaryOf(event: BoardEvent): string {
  return SUMMARIES[event.event_type] ?? event.event_type
}

/** The display name for a persona. The neutral case is named
 *  deliberately — never an empty string. */
export function personaName(persona: PersonaLabel): string {
  if (persona.kind === 'specialist') return persona.name
  return persona.kind === 'operator' ? 'You' : 'System'
}

/** First letter for the avatar, so the neutral case still gets a mark. */
export function personaInitial(persona: PersonaLabel): string {
  return personaName(persona).charAt(0).toUpperCase()
}

function formatTimestamp(iso: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString('en-GB')
}

export function toFeedEntry(event: BoardEvent): FeedEntry {
  return {
    event,
    persona: personaOf(event),
    tone: toneOf(event),
    summary: summaryOf(event),
    timestamp: formatTimestamp(event.created_at),
  }
}

/** Oldest first (FR-012) — the order the endpoint already returns, made
 *  explicit so the feed does not depend on it silently. */
export function toFeedEntries(events: BoardEvent[]): FeedEntry[] {
  return events.map(toFeedEntry)
}
