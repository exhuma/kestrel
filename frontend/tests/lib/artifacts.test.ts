import { describe, it, expect } from 'vitest'
import { railItems, REQUEST_FRESHNESS_NOTE } from '../../src/lib/artifacts'
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
          target_artifact: null,
          persona: null,
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
          target_artifact: null,
          persona: null,
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

describe('railItems original request (feature 030)', () => {
  const request = (body?: string) =>
    railItems([], body).find((i) => i.kind === 'request')

  it('is not produced when the snapshot carries no body', () => {
    expect(request()?.state).toBe('Not yet produced')
    expect(request('   ')?.available).toBe(false)
  })

  it('opens the body directly, with the freshness note', () => {
    const item = request('Please add CSV export.')
    expect(item?.available).toBe(true)
    expect(item?.state).toBe('Produced')
    expect(item?.artifactId).toBeNull()
    expect(item?.directContent).toBe('Please add CSV export.')
    expect(item?.note).toBe(REQUEST_FRESHNESS_NOTE)
  })

  it('never carries direct content on an ordinary artifact entry', () => {
    const items = railItems([], 'body')
    const others = items.filter((i) => i.kind !== 'request')
    expect(others.every((i) => i.directContent === null)).toBe(true)
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

describe('railItems reviewed documents (feature 043)', () => {
  function gateOf(
    card_type: string,
    target: string | null,
    own: string | null = null,
  ) {
    return workCardSummary({
      card_type,
      state: 'done',
      latest_artifact: own ? artifact(own) : null,
      gate: {
        requested_decision: 'approve',
        decision: 'approved',
        round: null,
        cap: null,
        target_artifact: target ? artifact(target) : null,
        persona: null,
      },
    })
  }

  it.each([
    ['understanding', 'understanding_gate'],
    ['cab1', 'cab1_gate'],
    ['prd', 'prd_gate'],
  ])('opens the document the %s gate reviewed', (kind, cardType) => {
    const items = railItems([gateOf(cardType, 'reviewed', 'response')])
    const item = items.find((i) => i.kind === kind)
    expect(item?.artifactId).toBe('reviewed')
    expect(item?.available).toBe(true)
  })

  it('is openable when the operator approved without a note', () => {
    const items = railItems([gateOf('understanding_gate', 'restatement')])
    expect(items.find((i) => i.kind === 'understanding')?.available).toBe(true)
  })

  it('falls back to the gate card own artifact without a target', () => {
    const items = railItems([gateOf('prd_gate', null, 'response')])
    expect(items.find((i) => i.kind === 'prd')?.artifactId).toBe('response')
  })

  it('keeps the interview answers, falling back to the questions', () => {
    const items = railItems([gateOf('refinement_gate', 'questions')])
    expect(items.find((i) => i.kind === 'interview')?.artifactId).toBe(
      'questions',
    )
  })
})

describe('railItems pull request link (feature 043)', () => {
  const delivery = workCardSummary({ card_type: 'delivery', state: 'done' })

  it('links to the change request once delivery recorded it', () => {
    const url = 'https://github.com/o/r/pull/7'
    const item = railItems([delivery], '', url).find(
      (i) => i.kind === 'pull_request',
    )
    expect(item?.href).toBe(url)
    expect(item?.available).toBe(true)
    expect(item?.artifactId).toBeNull()
  })

  it('is unavailable without a recorded URL', () => {
    const item = railItems([delivery]).find((i) => i.kind === 'pull_request')
    expect(item?.href).toBeNull()
    expect(item?.available).toBe(false)
    expect(item?.state).toBe('Produced')
  })
})
