/**
 * The cockpit's artifact rail (feature 029, US2, FR-014): the durable set
 * that survives the chatter, in pipeline order.
 *
 * The rail lists the **expected** artifacts, not just the ones that
 * exist — an entry a request has not reached yet renders as unavailable
 * rather than being omitted, so the rail shows the durable shape of the
 * work instead of only its current contents (data-model.md §2).
 *
 * Pure and display-only: it reads the card kinds the backend already
 * reports (`app/models_board.py:CardKind`) and never re-derives a phase
 * or a stage.
 */
import type { WorkCardSummary } from '../types/workflows'

/** Where a rail entry stands. Deliberately its own vocabulary rather than
 *  the card-state one: the rail answers "has this been produced, and can
 *  I read it", which is not the same question as "what is this card
 *  doing". */
export type ArtifactState =
  | 'Not yet produced'
  | 'In progress'
  | 'Awaiting your decision'
  | 'Quarantined'
  | 'Produced'
  | 'Approved'
  | 'Rejected'
  | 'Cancelled'
  | 'Failed'

export interface ArtifactRailItem {
  /** Stable key, independent of the label's wording. */
  kind: string
  label: string
  icon: string
  state: ArtifactState
  /** Whether there is content behind it to open. */
  available: boolean
  artifactId: string | null
}

interface RailSlot {
  kind: string
  label: string
  icon: string
  /** The card kinds that produce this artifact, most significant first. */
  cardKinds: readonly string[]
}

/** FR-014's durable set, in pipeline order.
 *
 * One entry still has no card kind behind it, and that is recorded rather
 * than papered over:
 *
 * - **Original request** lives on `Workflow.task_body` and is not carried
 *   by the board snapshot, so there is nothing to open. Exposing it would
 *   need a fifth DTO addition, which FR-039 puts off-limits without the
 *   developer's word.
 *
 * The **Executive summary** (feature 030) is the CAB-2 gate's own
 * artifact: kestrel renders it from the estimates and stores it on the
 * `decomposition_gate` card, so it is that card's `latest_artifact`. The
 * gate therefore belongs to this slot, not to "Technical analysis".
 */
const RAIL: readonly RailSlot[] = [
  {
    kind: 'request',
    label: 'Original request',
    icon: '$inboxArrowDown',
    cardKinds: [],
  },
  {
    kind: 'understanding',
    label: 'Understanding check',
    icon: '$helpCircleOutline',
    cardKinds: ['understanding_gate'],
  },
  {
    kind: 'cab1',
    label: 'CAB-1 decision',
    icon: '$gavel',
    cardKinds: ['cab1_gate', 'strategic_interview_gate', 'strategic_interview'],
  },
  {
    kind: 'interview',
    label: 'Interview rounds',
    icon: '$forumOutline',
    cardKinds: ['refinement_gate', 'refinement'],
  },
  {
    kind: 'prd',
    label: 'PRD',
    icon: '$fileDocumentOutline',
    cardKinds: ['prd_gate', 'prd'],
  },
  {
    kind: 'analysis',
    label: 'Technical analysis',
    icon: '$sitemapOutline',
    cardKinds: ['analysis', 'design', 'decomposition', 'estimation'],
  },
  {
    kind: 'exec_summary',
    label: 'Executive summary',
    icon: '$textBoxCheckOutline',
    cardKinds: ['decomposition_gate'],
  },
  {
    kind: 'pull_request',
    label: 'Pull request',
    icon: '$sourcePull',
    cardKinds: ['delivery'],
  },
]

const STATE_BY_CARD_STATE: Readonly<Record<string, ArtifactState>> = {
  awaiting_human: 'Awaiting your decision',
  quarantined: 'Quarantined',
  cancelled: 'Cancelled',
  failed: 'Failed',
  ready: 'In progress',
  claimed: 'In progress',
  waiting_dependency: 'In progress',
  review: 'In progress',
}

/** A resolved gate states its decision; anything else done has simply
 *  been produced. */
function doneState(card: WorkCardSummary): ArtifactState {
  if (card.gate?.decision === 'approved') return 'Approved'
  if (card.gate?.decision === 'rejected') return 'Rejected'
  return 'Produced'
}

function stateOf(card: WorkCardSummary): ArtifactState {
  if (card.state === 'done') return doneState(card)
  return STATE_BY_CARD_STATE[card.state] ?? 'In progress'
}

/** The card that best represents a slot: the first listed kind that the
 *  request actually has. Interview rounds and PRD redrafts produce
 *  several cards; the gate kind is listed first because that is the one
 *  carrying the operator-visible outcome. */
function cardFor(
  slot: RailSlot,
  byKind: Map<string, WorkCardSummary[]>,
): WorkCardSummary | null {
  for (const kind of slot.cardKinds) {
    const cards = byKind.get(kind)
    if (cards && cards.length > 0) return cards[cards.length - 1]
  }
  return null
}

function toItem(
  slot: RailSlot,
  byKind: Map<string, WorkCardSummary[]>,
): ArtifactRailItem {
  const card = cardFor(slot, byKind)
  return {
    kind: slot.kind,
    label: slot.label,
    icon: slot.icon,
    state: card ? stateOf(card) : 'Not yet produced',
    available: card?.latest_artifact != null,
    artifactId: card?.latest_artifact?.id ?? null,
  }
}

function groupByKind(cards: WorkCardSummary[]): Map<string, WorkCardSummary[]> {
  const byKind = new Map<string, WorkCardSummary[]>()
  for (const card of cards) {
    const group = byKind.get(card.card_type) ?? []
    group.push(card)
    byKind.set(card.card_type, group)
  }
  return byKind
}

/** The full durable set for one request, in pipeline order. Always the
 *  same length — a request that has produced nothing still shows what is
 *  coming. */
export function railItems(cards: WorkCardSummary[]): ArtifactRailItem[] {
  const byKind = groupByKind(cards)
  return RAIL.map((slot) => toItem(slot, byKind))
}
