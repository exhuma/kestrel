/**
 * The cockpit's work list (feature 034, US3): every card of a request,
 * grouped by where it stands, and for work that ended without being done,
 * why it ended.
 *
 * Pure and display-only. The server decides every card's state and records
 * the event that moved it; this only groups what it sent and reads the
 * cause from the last event recorded against the card.
 */
import { summaryOf } from './personas'
import type { BoardEvent, CardState, WorkCardSummary } from '../types/workflows'

export interface WorkGroup {
  key: string
  label: string
  items: WorkItem[]
}

export interface WorkItem {
  card: WorkCardSummary
  /** Who the card is for, by role label; `null` for the operator's own
   *  cards and for system cards. */
  role: string | null
  /** For a cancelled or failed card: why it ended, if an event says. */
  endedBecause: string | null
}

/** Group order is reading order: what is moving, what is stuck on
 *  something, what is next, then what is over. */
const GROUPS: readonly { key: string; label: string; states: CardState[] }[] = [
  { key: 'active', label: 'In progress', states: ['claimed', 'review'] },
  {
    key: 'waiting',
    label: 'Waiting',
    states: ['awaiting_human', 'quarantined', 'waiting_dependency'],
  },
  { key: 'ready', label: 'Ready', states: ['ready'] },
  { key: 'failed', label: 'Failed', states: ['failed'] },
  { key: 'cancelled', label: 'Cancelled', states: ['cancelled'] },
  { key: 'done', label: 'Done', states: ['done'] },
]

const ENDINGS = new Set<CardState>(['cancelled', 'failed'])

/** The cause, worded for a card that ended — the feed's summaries are
 *  worded for the moment it happened, and some read oddly after it. */
const ENDED_BECAUSE: Readonly<Record<string, string>> = {
  'intervention.cancel': 'You cancelled it',
  'gate.rejected_dependent_cancelled':
    'Cancelled because you rejected a gate it depended on',
  'coordinator.transition_card': 'The coordinator ended it',
  'card.recovery_escalated': 'Recovery gave up on it',
}

export function workGroups(
  cards: WorkCardSummary[],
  events: BoardEvent[],
): WorkGroup[] {
  const lastEvent = new Map<string, BoardEvent>()
  for (const event of events) {
    if (event.card_id) lastEvent.set(event.card_id, event)
  }
  return GROUPS.map((group) => ({
    key: group.key,
    label: group.label,
    items: cards
      .filter((card) => group.states.includes(card.state))
      .map((card) => toItem(card, lastEvent.get(card.id))),
  })).filter((group) => group.items.length > 0)
}

function toItem(card: WorkCardSummary, event: BoardEvent | undefined) {
  return {
    card,
    role: card.eligible_roles[0]?.label ?? null,
    endedBecause: ENDINGS.has(card.state) ? endedBecause(event) : null,
  }
}

function endedBecause(event: BoardEvent | undefined): string | null {
  if (!event) return null
  return ENDED_BECAUSE[event.event_type] ?? summaryOf(event)
}
