/**
 * The board card's state bar: a request's cards by state, as one
 * colour-coded row. Read left to right from finished work, through work
 * under way and waiting, to problems.
 */
import type { CardState } from '../types/workflows'

/** Every card state, in the order the bar shows them. */
export const STATE_BAR_ORDER: readonly CardState[] = [
  'done',
  'review',
  'claimed',
  'ready',
  'waiting_dependency',
  'awaiting_human',
  'quarantined',
  'failed',
  'cancelled',
]

/** Theme colour per state. */
export const STATE_BAR_COLOR: Readonly<Record<CardState, string>> = {
  done: 'success',
  review: 'primary',
  claimed: 'primary',
  ready: 'info',
  waiting_dependency: 'grey',
  awaiting_human: 'warning',
  quarantined: 'error',
  failed: 'error',
  cancelled: 'grey-darken-1',
}

const LABEL: Readonly<Partial<Record<CardState, string>>> = {
  waiting_dependency: 'waiting',
  awaiting_human: 'awaiting you',
}

/** One segment of the bar: a state with cards in it. */
export interface StateSegment {
  state: CardState
  count: number
  color: string
  /** "3 done", "1 waiting". */
  label: string
}

/** The words for a state. */
export function stateLabel(state: CardState): string {
  return LABEL[state] ?? state.replace(/_/g, ' ')
}

/** The bar's segments: every state with a card, in bar order. */
export function stateSegments(
  counts: Partial<Record<CardState, number>>,
): StateSegment[] {
  return STATE_BAR_ORDER.filter((state) => (counts[state] ?? 0) > 0).map(
    (state) => {
      const count = counts[state] ?? 0
      return {
        state,
        count,
        color: STATE_BAR_COLOR[state],
        label: `${count} ${stateLabel(state)}`,
      }
    },
  )
}
