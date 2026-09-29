import { describe, expect, it } from 'vitest'
import { workGroups } from '../../src/lib/workList'
import { boardEvent, workCardSummary } from '../support/board'

const pm = { id: 'pm', label: 'Project Manager' }

describe('workGroups', () => {
  it('groups cards in reading order and drops empty groups', () => {
    const groups = workGroups(
      [
        workCardSummary({ id: 'a', state: 'done' }),
        workCardSummary({ id: 'b', state: 'claimed' }),
        workCardSummary({ id: 'c', state: 'cancelled' }),
      ],
      [],
    )
    expect(groups.map((g) => g.key)).toEqual(['active', 'cancelled', 'done'])
  })

  it('says why a cancelled card ended, from its last event', () => {
    const [group] = workGroups(
      [workCardSummary({ id: 'c', state: 'cancelled', eligible_roles: [pm] })],
      [
        boardEvent({ card_id: 'c', event_type: 'card.dependency_met' }),
        boardEvent({
          card_id: 'c',
          event_type: 'gate.rejected_dependent_cancelled',
        }),
        boardEvent({ card_id: 'other', event_type: 'intervention.cancel' }),
      ],
    )
    expect(group.items[0]).toMatchObject({
      role: 'Project Manager',
      endedBecause: 'Cancelled because you rejected a gate it depended on',
    })
  })

  it('falls back to the feed summary, and to nothing without an event', () => {
    const groups = workGroups(
      [
        workCardSummary({ id: 'f', state: 'failed' }),
        workCardSummary({ id: 'x', state: 'cancelled' }),
      ],
      [boardEvent({ card_id: 'f', event_type: 'card.turn_failed' })],
    )
    const reasons = groups.flatMap((g) => g.items).map((i) => i.endedBecause)
    expect(reasons).toEqual([
      'A turn on this card failed; it will be retried',
      null,
    ])
  })

  it('gives no ending to work that did not end', () => {
    const [group] = workGroups(
      [workCardSummary({ id: 'd', state: 'done' })],
      [boardEvent({ card_id: 'd', event_type: 'intervention.cancel' })],
    )
    expect(group.items[0].endedBecause).toBeNull()
  })
})
