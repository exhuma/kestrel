import { describe, it, expect } from 'vitest'
import {
  PHASE_ORDER,
  STAGE_ORDER,
  attentionOf,
  groupByStage,
  phasePosition,
} from '../../src/lib/stages'
import { boardWorkflowSummary as summary } from '../support/board'

describe('STAGE_ORDER / PHASE_ORDER', () => {
  it('lists the six stages in FR-001 order, then Cancelled (040)', () => {
    expect(STAGE_ORDER).toEqual([
      'Intake & alignment',
      'Discovery',
      'Definition',
      'Planning',
      'Build & deliver',
      'Done',
      'Cancelled',
    ])
  })

  it('lists the ten phases in sequence order', () => {
    expect(PHASE_ORDER).toHaveLength(10)
    expect(PHASE_ORDER[0]).toBe('Intake')
    expect(PHASE_ORDER.at(-1)).toBe('Delivery')
  })
})

describe('phasePosition', () => {
  it('returns a 1-based ordinal for a known phase', () => {
    expect(phasePosition('Intake')).toEqual({ ordinal: 1, isTerminal: false })
    expect(phasePosition('Delivery')).toEqual({
      ordinal: 10,
      isTerminal: false,
    })
  })

  it('returns a null ordinal for an unrecognised phase', () => {
    expect(phasePosition('some-future-phase').ordinal).toBeNull()
  })

  it('marks the synthetic done phase terminal, with no ordinal', () => {
    expect(phasePosition('done')).toEqual({ ordinal: null, isTerminal: true })
  })

  it('marks the synthetic cancelled phase terminal too (feature 040)', () => {
    expect(phasePosition('cancelled')).toEqual({
      ordinal: null,
      isTerminal: true,
    })
  })
})

describe('attentionOf precedence', () => {
  it('ranks quarantined above every other treatment', () => {
    const s = summary({
      state_counts: { quarantined: 1 },
      cap_exhausted: true,
      action_required_count: 1,
      outcome: 'failed',
    })
    expect(attentionOf(s)).toBe('quarantined')
  })

  it('ranks cap-reached above your-move and done', () => {
    const s = summary({
      cap_exhausted: true,
      action_required_count: 1,
      outcome: 'done',
    })
    expect(attentionOf(s)).toBe('cap-reached')
  })

  it('ranks your-move above done', () => {
    const s = summary({ action_required_count: 1, outcome: 'done' })
    expect(attentionOf(s)).toBe('your-move')
  })

  it("reports done from the server's outcome, never from the phase", () => {
    expect(attentionOf(summary({ outcome: 'done' }))).toBe('done')
    // Feature 040: a "done" phase string alone does not make it done.
    expect(attentionOf(summary({ phase: 'done' }))).toBe('none')
  })

  it('reports a failed request as failed, above cap-reached and your-move', () => {
    const s = summary({
      outcome: 'failed',
      cap_exhausted: true,
      action_required_count: 1,
    })
    expect(attentionOf(s)).toBe('failed')
  })

  it('reports a cancelled request as cancelled, never done', () => {
    expect(attentionOf(summary({ outcome: 'cancelled' }))).toBe('cancelled')
  })

  it('reports none otherwise', () => {
    expect(attentionOf(summary())).toBe('none')
  })
})

function requestIds(column: { requests: { summary: { id: string } }[] }) {
  return column.requests.map((r) => r.summary.id)
}

describe('groupByStage', () => {
  it('places each request in its stage column', () => {
    const columns = groupByStage([
      summary({ id: 'a', stage: 'Intake & alignment' }),
      summary({ id: 'b', stage: 'Discovery' }),
    ])
    const intake = columns.find((c) => c.stage === 'Intake & alignment')!
    const discovery = columns.find((c) => c.stage === 'Discovery')!
    expect(requestIds(intake)).toEqual(['a'])
    expect(requestIds(discovery)).toEqual(['b'])
  })

  it('returns every known stage, even when empty', () => {
    const columns = groupByStage([])
    expect(columns.map((c) => c.stage)).toEqual(STAGE_ORDER)
  })

  it('lists every request as its own card, never nested', () => {
    const columns = groupByStage([
      summary({ id: 'a', stage: 'Build & deliver' }),
      summary({ id: 'b', stage: 'Build & deliver' }),
    ])
    const build = columns.find((c) => c.stage === 'Build & deliver')!
    expect(requestIds(build)).toEqual(['a', 'b'])
  })

  it('places an unrecognised stage in a trailing column instead of dropping it', () => {
    const columns = groupByStage([
      summary({ id: 'x', stage: 'Some Future Stage' }),
    ])
    const trailing = columns.find((c) => c.stage === 'Other')!
    expect(requestIds(trailing)).toEqual(['x'])
  })
})
