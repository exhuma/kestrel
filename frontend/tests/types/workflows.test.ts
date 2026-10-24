import { describe, it, expect } from 'vitest'
import { CARD_STATES } from '../../src/types/workflows'

// The only runtime-checkable part of the board contract types (the rest
// are compile-time interfaces) — guards CARD_STATES against silent drift
// from board-api.md's CardState enumeration / app.models_board.CardState.
describe('board contract: CARD_STATES', () => {
  it('matches board-api.md CardState exactly', () => {
    expect(CARD_STATES).toEqual([
      'ready',
      'claimed',
      'waiting_dependency',
      'awaiting_human',
      'review',
      'quarantined',
      'done',
      'failed',
      'cancelled',
    ])
  })
})
