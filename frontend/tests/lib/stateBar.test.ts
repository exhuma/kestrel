import { describe, it, expect } from 'vitest'
import {
  STATE_BAR_COLOR,
  STATE_BAR_ORDER,
  stateLabel,
  stateSegments,
} from '../../src/lib/stateBar'
import { CARD_STATES } from '../../src/types/workflows'

describe('stateSegments', () => {
  it('orders states from finished work to problems, skipping empty ones', () => {
    const segments = stateSegments({ failed: 1, ready: 0, done: 3, claimed: 2 })
    expect(segments.map((s) => s.state)).toEqual(['done', 'claimed', 'failed'])
  })

  it('labels each segment with its count', () => {
    const segments = stateSegments({ waiting_dependency: 2, done: 1 })
    expect(segments.map((s) => s.label)).toEqual(['1 done', '2 waiting'])
  })

  it('is empty when no card has a state', () => {
    expect(stateSegments({})).toEqual([])
  })
})

describe('state bar vocabulary', () => {
  it('orders, colours and labels every card state', () => {
    expect([...STATE_BAR_ORDER].sort()).toEqual([...CARD_STATES].sort())
    for (const state of CARD_STATES) {
      expect(STATE_BAR_COLOR[state]).toBeTruthy()
      expect(stateLabel(state)).not.toContain('_')
    }
  })
})
