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
  /** Content read straight off the snapshot rather than fetched by
   *  artifact id — only the original request, which is no artifact. */
  directContent: string | null
  /** Shown alongside direct content in place of a trust chip. */
  note: string | null
  /** An entry that opens elsewhere rather than in the dialog — the
   *  pull request on its code host (feature 043, FR-009). */
  href: string | null
}

/** The original request is screened once at intake and never again, so
 *  it must never be mistaken for the live ticket (feature 030, FR-022). */
export const REQUEST_FRESHNESS_NOTE =
  'Screened once at intake. Later edits to the source ticket are not reflected here.'

interface RailSlot {
  kind: string
  label: string
  icon: string
  /** The card kinds that produce this artifact, most significant first. */
  cardKinds: readonly string[]
  /** Read from the snapshot's `task_body` instead of from a card. */
  direct?: true
  /** A link to the change request instead of an artifact. */
  link?: true
  /** Which artifact a gate-backed slot opens first (feature 043,
   *  FR-006): `target` is the document the gate reviewed, `own` the
   *  gate card's own (the operator's answers, or the executive summary
   *  kestrel renders). Either falls back to the other. */
  source?: 'target' | 'own'
}

/** FR-014's durable set, in pipeline order.
 *
 * Two entries are not ordinary card artifacts (feature 030):
 *
 * - **Original request** is `Workflow.task_body`, carried on the snapshot.
 *   It is no artifact — intake writes none — so it is read directly.
 * - **Executive summary** is the CAB-2 gate's own artifact: kestrel
 *   renders it from the estimates and stores it on the
 *   `decomposition_gate` card, so it is that card's `latest_artifact`. The
 *   gate therefore belongs to this slot, not to "Technical analysis".
 */
const RAIL: readonly RailSlot[] = [
  {
    kind: 'request',
    label: 'Original request',
    icon: '$inboxArrowDown',
    cardKinds: [],
    direct: true,
  },
  {
    kind: 'understanding',
    label: 'Understanding check',
    icon: '$helpCircleOutline',
    cardKinds: ['understanding_gate'],
    source: 'target',
  },
  {
    kind: 'cab1',
    label: 'CAB-1 decision',
    icon: '$gavel',
    cardKinds: ['cab1_gate', 'strategic_interview_gate', 'strategic_interview'],
    source: 'target',
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
    source: 'target',
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
    link: true,
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

/** The artifact a slot opens for *card*, in the slot's preferred order. */
function artifactFor(slot: RailSlot, card: WorkCardSummary): string | null {
  const own = card.latest_artifact?.id ?? null
  const target = card.gate?.target_artifact?.id ?? null
  return slot.source === 'target' ? (target ?? own) : (own ?? target)
}

function toItem(
  slot: RailSlot,
  byKind: Map<string, WorkCardSummary[]>,
): ArtifactRailItem {
  const card = cardFor(slot, byKind)
  const artifactId = card ? artifactFor(slot, card) : null
  return {
    kind: slot.kind,
    label: slot.label,
    icon: slot.icon,
    state: card ? stateOf(card) : 'Not yet produced',
    available: artifactId !== null,
    artifactId,
    directContent: null,
    note: null,
    href: null,
  }
}

/** The pull request entry: a link once delivery recorded where the
 *  change request is; unavailable before, or for a delivery from before
 *  feature 043, which recorded only a number. */
function linkItem(
  slot: RailSlot,
  byKind: Map<string, WorkCardSummary[]>,
  href: string | null,
): ArtifactRailItem {
  return {
    ...toItem(slot, byKind),
    available: href !== null,
    artifactId: null,
    href,
  }
}

function directItem(slot: RailSlot, taskBody: string): ArtifactRailItem {
  const available = taskBody.trim() !== ''
  return {
    kind: slot.kind,
    label: slot.label,
    icon: slot.icon,
    state: available ? 'Produced' : 'Not yet produced',
    available,
    artifactId: null,
    directContent: available ? taskBody : null,
    note: available ? REQUEST_FRESHNESS_NOTE : null,
    href: null,
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
export function railItems(
  cards: WorkCardSummary[],
  taskBody = '',
  changeRequestUrl: string | null = null,
): ArtifactRailItem[] {
  const byKind = groupByKind(cards)
  return RAIL.map((slot) => {
    if (slot.direct) return directItem(slot, taskBody)
    if (slot.link) return linkItem(slot, byKind, changeRequestUrl)
    return toItem(slot, byKind)
  })
}
