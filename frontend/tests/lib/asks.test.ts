import { describe, it, expect } from 'vitest'
import { pendingAsk, pendingAsks } from '../../src/lib/asks'
import { workCardSummary } from '../support/board'
import type { WorkCardSummary } from '../../src/types/workflows'

function gateCard(
  requested: string,
  overrides: Partial<WorkCardSummary> = {},
): WorkCardSummary {
  return workCardSummary({
    state: 'awaiting_human',
    allowed_actions: ['resolve_gate'],
    gate: {
      requested_decision: requested,
      decision: null,
      round: null,
      cap: null,
    },
    ...overrides,
  })
}

describe('pendingAsk when nothing is wanted', () => {
  it('returns nothing for a request with no cards', () => {
    expect(pendingAsk([])).toBeNull()
  })

  it('returns nothing for a card that is merely in progress', () => {
    expect(pendingAsk([workCardSummary({ state: 'claimed' })])).toBeNull()
  })

  it('returns nothing for a gate the operator may not resolve', () => {
    const card = gateCard('approve_prd', { allowed_actions: [] })
    expect(pendingAsk([card])).toBeNull()
  })

  it('returns nothing for an already-resolved gate', () => {
    const card = workCardSummary({
      state: 'done',
      allowed_actions: [],
      gate: {
        requested_decision: 'approve_prd',
        decision: 'approved',
        round: null,
        cap: null,
      },
    })
    expect(pendingAsk([card])).toBeNull()
  })
})

describe('pendingAsk classification', () => {
  it.each([
    ['confirm_understanding', 'approval'],
    ['approve_strategic_fit', 'approval'],
    ['approve_prd', 'approval'],
    ['approve_decomposition', 'approval'],
    ['answer', 'interview'],
  ])('classifies a %s gate as %s', (requested, kind) => {
    expect(pendingAsk([gateCard(requested)])?.kind).toBe(kind)
  })

  it('states each gate in the operator’s terms, not the API’s', () => {
    expect(pendingAsk([gateCard('approve_prd')])?.title).toBe(
      'Sign off the PRD',
    )
    expect(pendingAsk([gateCard('approve_decomposition')])?.title).toContain(
      'CAB-2',
    )
  })

  it('falls back to the card title for a decision it does not know', () => {
    const card = gateCard('approve_something_new', { title: 'A new gate' })
    expect(pendingAsk([card])?.title).toBe('A new gate')
  })

  it('requires written feedback only for a PRD rejection', () => {
    expect(
      pendingAsk([gateCard('approve_prd')])?.requiresRejectionFeedback,
    ).toBe(true)
    expect(
      pendingAsk([gateCard('confirm_understanding')])
        ?.requiresRejectionFeedback,
    ).toBe(false)
  })
})

describe('pendingAsk precedence', () => {
  const quarantined = workCardSummary({
    id: 'q',
    state: 'quarantined',
    security_review_id: 'sr-1',
  })

  it('recognises quarantined content as an ask', () => {
    const ask = pendingAsk([quarantined])
    expect(ask?.kind).toBe('quarantine')
    expect(ask?.title).toContain('quarantine')
  })

  it('ignores a quarantined card with no review to resolve', () => {
    const card = workCardSummary({
      state: 'quarantined',
      security_review_id: null,
    })
    expect(pendingAsk([card])).toBeNull()
  })

  it('puts quarantine ahead of any decision', () => {
    const ask = pendingAsk([gateCard('approve_prd', { id: 'g' }), quarantined])
    expect(ask?.kind).toBe('quarantine')
  })

  it('states exactly one ask even when several are outstanding', () => {
    const cards = [
      gateCard('approve_prd', { id: 'g1' }),
      gateCard('answer', { id: 'g2' }),
    ]
    expect(pendingAsks(cards)).toHaveLength(2)
    expect(pendingAsk(cards)?.card.id).toBe('g1')
  })
})
