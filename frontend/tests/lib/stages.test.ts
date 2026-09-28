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
  it('lists the six stages in FR-001 order', () => {
    expect(STAGE_ORDER).toEqual([
      'Intake & alignment',
      'Discovery',
      'Definition',
      'Planning',
      'Build & deliver',
      'Done',
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
})

describe('attentionOf precedence', () => {
  it('ranks quarantined above every other treatment', () => {
    const s = summary({
      state_counts: { quarantined: 1 },
      cap_exhausted: true,
      action_required_count: 1,
      phase: 'done',
    })
    expect(attentionOf(s)).toBe('quarantined')
  })

  it('ranks cap-reached above your-move and done', () => {
    const s = summary({
      cap_exhausted: true,
      action_required_count: 1,
      phase: 'done',
    })
    expect(attentionOf(s)).toBe('cap-reached')
  })

  it('ranks your-move above done', () => {
    const s = summary({ action_required_count: 1, phase: 'done' })
    expect(attentionOf(s)).toBe('your-move')
  })

  it('reports done when the phase is terminal and nothing else applies', () => {
    expect(attentionOf(summary({ phase: 'done' }))).toBe('done')
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

  it('nests a decomposition child inside its parent rather than listing it top-level', () => {
    const parent = summary({ id: 'parent', stage: 'Build & deliver' })
    const child = summary({
      id: 'child',
      parent_workflow_id: 'parent',
      stage: 'Intake & alignment',
    })
    const columns = groupByStage([parent, child])
    const buildColumn = columns.find((c) => c.stage === 'Build & deliver')!
    expect(buildColumn.requests).toHaveLength(1)
    expect(buildColumn.requests[0].children.map((c) => c.id)).toEqual(['child'])
    const intakeColumn = columns.find((c) => c.stage === 'Intake & alignment')!
    expect(intakeColumn.requests).toHaveLength(0)
  })

  it('falls back a child to top-level when its parent is absent from the listing', () => {
    const child = summary({
      id: 'child',
      parent_workflow_id: 'missing-parent',
      stage: 'Discovery',
    })
    const columns = groupByStage([child])
    const discovery = columns.find((c) => c.stage === 'Discovery')!
    expect(requestIds(discovery)).toEqual(['child'])
  })

  it('places an unrecognised stage in a trailing column instead of dropping it', () => {
    const columns = groupByStage([
      summary({ id: 'x', stage: 'Some Future Stage' }),
    ])
    const trailing = columns.find((c) => c.stage === 'Other')!
    expect(requestIds(trailing)).toEqual(['x'])
  })
})
