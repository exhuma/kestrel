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

/** Decisions whose rejection must say what is wrong: the redraft works
 *  from it (the PRD, feature 028; the understanding, feature 032). */
const REJECTION_NEEDS_FEEDBACK: ReadonlySet<string> = new Set([
  'approve_prd',
  'confirm_understanding',
])

/** The understanding is short and is itself the decision, so it is shown
 *  in place rather than behind "Read" (feature 032). */
export function inlineReading(ask: PendingAsk): string | null {
  const gate = ask.card.gate
  if (gate?.requested_decision !== 'confirm_understanding') return null
  return gate.target_artifact?.id ?? null
}

function toGateAsk(card: WorkCardSummary): PendingAsk {
  const requested = card.gate?.requested_decision ?? ''
  return {
    kind: requested === 'answer' ? 'interview' : 'approval',
    card,
    title: GATE_TITLES[requested] ?? card.title,
    requiresRejectionFeedback: REJECTION_NEEDS_FEEDBACK.has(requested),
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

/** What the operator can read before deciding an ask (#66). */
export interface AskReading {
  artifactId: string
  /** Names the thing, e.g. "the PRD" — the button reads "Read <label>". */
  label: string
}

/** Readings by requested decision. CAB-2's executive summary is the gate
 *  card's own artifact (feature 030); every other gate's content is its
 *  target, produced by another card. */
const READING_LABELS: Readonly<Record<string, string>> = {
  confirm_understanding: 'the understanding',
  approve_strategic_fit: 'the answers',
  approve_prd: 'the PRD',
  approve_decomposition: 'the executive summary',
}

export function readingFor(ask: PendingAsk): AskReading | null {
  const gate = ask.card.gate
  if (ask.kind !== 'approval' || !gate) return null
  const artifact =
    gate.requested_decision === 'approve_decomposition'
      ? ask.card.latest_artifact
      : gate.target_artifact
  if (!artifact) return null
  const label = READING_LABELS[gate.requested_decision] ?? 'what is asked'
  return { artifactId: artifact.id, label }
}
