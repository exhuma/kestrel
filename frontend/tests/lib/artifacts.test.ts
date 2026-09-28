import { describe, it, expect } from 'vitest'
import { railItems } from '../../src/lib/artifacts'
import { workCardSummary } from '../support/board'
import type { WorkCardSummary } from '../../src/types/workflows'

const PIPELINE_ORDER = [
  'Original request',
  'Understanding check',
  'CAB-1 decision',
  'Interview rounds',
  'PRD',
  'Technical analysis',
  'Executive summary',
  'Pull request',
]

function artifact(id = 'art-1') {
  return { id, label: 'report', revision: 1 }
}

describe('railItems shape', () => {
  it('lists the whole durable set in pipeline order', () => {
    expect(railItems([]).map((i) => i.label)).toEqual(PIPELINE_ORDER)
  })

  it('shows the same set for a request that has produced nothing', () => {
    const items = railItems([])
    expect(items).toHaveLength(PIPELINE_ORDER.length)
    expect(items.every((i) => i.state === 'Not yet produced')).toBe(true)
    expect(items.every((i) => !i.available)).toBe(true)
  })

  it('keeps the set the same length once a request is under way', () => {
    const items = railItems([
      workCardSummary({ card_type: 'prd', state: 'done' }),
    ])
    expect(items).toHaveLength(PIPELINE_ORDER.length)
  })
})

describe('railItems availability', () => {
  it('marks an entry available only when there is content to open', () => {
    const items = railItems([
      workCardSummary({
        card_type: 'prd',
        state: 'done',
        latest_artifact: artifact('prd-art'),
      }),
      workCardSummary({ card_type: 'delivery', state: 'ready' }),
    ])
    const prd = items.find((i) => i.kind === 'prd')
    const pr = items.find((i) => i.kind === 'pull_request')
    expect(prd?.available).toBe(true)
    expect(prd?.artifactId).toBe('prd-art')
    expect(pr?.available).toBe(false)
    expect(pr?.artifactId).toBeNull()
  })

  it('never omits an unproduced artifact', () => {
    const labels = railItems([
      workCardSummary({ card_type: 'understanding_gate', state: 'done' }),
    ]).map((i) => i.label)
    expect(labels).toEqual(PIPELINE_ORDER)
  })
})

describe('railItems states', () => {
  it.each([
    ['awaiting_human', 'Awaiting your decision'],
    ['quarantined', 'Quarantined'],
    ['ready', 'In progress'],
    ['claimed', 'In progress'],
    ['failed', 'Failed'],
    ['cancelled', 'Cancelled'],
  ])('reports a %s card as %s', (state, expected) => {
    const items = railItems([
      workCardSummary({ card_type: 'prd', state: state as never }),
    ])
    expect(items.find((i) => i.kind === 'prd')?.state).toBe(expected)
  })

  it('states a resolved gate as its decision, not merely as produced', () => {
    const approved = railItems([
      workCardSummary({
        card_type: 'prd_gate',
        state: 'done',
        gate: {
          requested_decision: 'approve_prd',
          decision: 'approved',
          round: null,
          cap: null,
        },
      }),
    ])
    expect(approved.find((i) => i.kind === 'prd')?.state).toBe('Approved')

    const rejected = railItems([
      workCardSummary({
        card_type: 'prd_gate',
        state: 'done',
        gate: {
          requested_decision: 'approve_prd',
          decision: 'rejected',
          round: null,
          cap: null,
        },
      }),
    ])
    expect(rejected.find((i) => i.kind === 'prd')?.state).toBe('Rejected')
  })

  it('reports a done non-gate card as produced', () => {
    const items = railItems([
      workCardSummary({ card_type: 'analysis', state: 'done' }),
    ])
    expect(items.find((i) => i.kind === 'analysis')?.state).toBe('Produced')
  })
})

describe('railItems card matching', () => {
  it('prefers the gate card over its question set for the interview slot', () => {
    const items = railItems([
      workCardSummary({
        id: 'q',
        card_type: 'refinement',
        state: 'done',
        latest_artifact: artifact('questions'),
      }),
      workCardSummary({
        id: 'g',
        card_type: 'refinement_gate',
        state: 'awaiting_human',
        latest_artifact: artifact('gate-art'),
      }),
    ])
    const interview = items.find((i) => i.kind === 'interview')
    expect(interview?.state).toBe('Awaiting your decision')
    expect(interview?.artifactId).toBe('gate-art')
  })

  it('shows the latest of several rounds of the same kind', () => {
    const items = railItems([
      workCardSummary({
        id: 'r1',
        card_type: 'refinement_gate',
        state: 'done',
        latest_artifact: artifact('round-1'),
      }),
      workCardSummary({
        id: 'r2',
        card_type: 'refinement_gate',
        state: 'awaiting_human',
        latest_artifact: artifact('round-2'),
      }),
    ])
    expect(items.find((i) => i.kind === 'interview')?.artifactId).toBe(
      'round-2',
    )
  })

  it('ignores card kinds that back no rail entry', () => {
    const items = railItems([
      workCardSummary({ card_type: 'coordinator_review', state: 'ready' }),
    ])
    expect(items.every((i) => i.state === 'Not yet produced')).toBe(true)
  })
})

describe('railItems original request', () => {
  // Recorded deliberately: the original request lives on
  // `Workflow.task_body`, which the snapshot does not carry.
  it('still lists the original request as expected work', () => {
    const items = railItems([
      workCardSummary({ card_type: 'delivery', state: 'done' }),
    ])
    expect(items.find((i) => i.kind === 'request')?.state).toBe(
      'Not yet produced',
    )
  })
})

describe('railItems executive summary (feature 030)', () => {
  const gate = (overrides: Partial<WorkCardSummary> = {}) =>
    workCardSummary({
      card_type: 'decomposition_gate',
      state: 'awaiting_human',
      latest_artifact: {
        id: 'art-sum',
        label: 'executive_summary',
        revision: 1,
      },
      ...overrides,
    })

  it('is not produced before CAB-2 opens', () => {
    const items = railItems([
      workCardSummary({ card_type: 'estimation', state: 'claimed' }),
    ])
    expect(items.find((i) => i.kind === 'exec_summary')?.state).toBe(
      'Not yet produced',
    )
  })

  it('opens the CAB-2 gate card artifact', () => {
    const item = railItems([gate()]).find((i) => i.kind === 'exec_summary')
    expect(item?.available).toBe(true)
    expect(item?.artifactId).toBe('art-sum')
    expect(item?.state).toBe('Awaiting your decision')
  })

  it('leaves the gate out of technical analysis, which shows estimation', () => {
    const items = railItems([
      gate(),
      workCardSummary({ card_type: 'estimation', state: 'done' }),
    ])
    const analysis = items.find((i) => i.kind === 'analysis')
    expect(analysis?.state).toBe('Produced')
    expect(analysis?.artifactId).not.toBe('art-sum')
  })
})
