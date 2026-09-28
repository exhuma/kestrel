/**
 * What one request wants from the operator right now (feature 029, US2,
 * FR-016) — the cockpit action banner's model.
 *
 * Pure: it reads the states and `allowed_actions` the backend already
 * decided and never infers a permission the server did not grant.
 * At most one ask is returned, because FR-016 requires the pending
 * decision to be stated exactly once.
 */
import type { WorkCardSummary } from '../types/workflows'

export type AskKind =
  /** Answer-shaped: a question set, which belongs on the interview
   *  surface and never inside the cockpit (FR-017). */
  | 'interview'
  /** An approve/reject decision the operator can take here. */
  | 'approval'
  /** Untrusted content held at intake, released or discarded. */
  | 'quarantine'

export interface PendingAsk {
  kind: AskKind
  card: WorkCardSummary
  /** What is being asked, in the operator's terms. */
  title: string
  /** Whether a rejection needs written feedback — a `prd_gate` rejection
   *  carries the reason the redraft works from. */
  requiresRejectionFeedback: boolean
}

/** Gate wording, keyed by the decision the backend asked for
 *  (`app/services/board/`: the five `requested_decision` literals). */
const GATE_TITLES: Readonly<Record<string, string>> = {
  confirm_understanding: 'Confirm this request was understood correctly',
  approve_strategic_fit: 'Decide whether this is a strategic fit (CAB-1)',
  approve_prd: 'Sign off the PRD',
  approve_decomposition: 'Approve the proposed breakdown (CAB-2)',
  answer: 'Answer the interview questions',
}

function isGateAsk(card: WorkCardSummary): boolean {
  return card.gate !== null && card.allowed_actions.includes('resolve_gate')
}

function isQuarantineAsk(card: WorkCardSummary): boolean {
  return card.state === 'quarantined' && card.security_review_id !== null
}

function toGateAsk(card: WorkCardSummary): PendingAsk {
  const requested = card.gate?.requested_decision ?? ''
  return {
    kind: requested === 'answer' ? 'interview' : 'approval',
    card,
    title: GATE_TITLES[requested] ?? card.title,
    requiresRejectionFeedback: requested === 'approve_prd',
  }
}

function toQuarantineAsk(card: WorkCardSummary): PendingAsk {
  return {
    kind: 'quarantine',
    card,
    title: 'Review quarantined content before it is trusted',
    requiresRejectionFeedback: false,
  }
}

/** Every outstanding ask, quarantine first: untrusted content outranks
 *  any decision, because until it is resolved the request may not be what
 *  it appears to be. */
export function pendingAsks(cards: WorkCardSummary[]): PendingAsk[] {
  const quarantine = cards.filter(isQuarantineAsk).map(toQuarantineAsk)
  const gates = cards.filter(isGateAsk).map(toGateAsk)
  return [...quarantine, ...gates]
}

/** The single ask to state prominently, or `null` when the request wants
 *  nothing — in which case the banner renders nothing at all (FR-016),
 *  rather than an empty or disabled prompt. */
export function pendingAsk(cards: WorkCardSummary[]): PendingAsk | null {
  return pendingAsks(cards)[0] ?? null
}
