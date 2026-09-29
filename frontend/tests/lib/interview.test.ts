import { describe, it, expect } from 'vitest'
import {
  buildInterviewCards,
  deriveRoundState,
  isOpenInterviewCard,
  parseQuestionSet,
  personaOf,
} from '../../src/lib/interview'
import { workCardSummary } from '../support/board'

function interviewGate(overrides: Parameters<typeof workCardSummary>[0] = {}) {
  return workCardSummary({
    id: 'gate-1',
    title: 'pm interview (2 questions)',
    state: 'awaiting_human',
    allowed_actions: ['resolve_gate'],
    gate: {
      requested_decision: 'answer',
      decision: null,
      round: 1,
      cap: 3,
      target_artifact: null,
    },
    ...overrides,
  })
}

describe('isOpenInterviewCard', () => {
  it('is true for an unresolved answer gate with resolve_gate allowed', () => {
    expect(isOpenInterviewCard(interviewGate())).toBe(true)
  })

  it('is false once a decision is recorded', () => {
    expect(
      isOpenInterviewCard(
        interviewGate({
          gate: {
            requested_decision: 'answer',
            decision: 'approved',
            round: 1,
            cap: 3,
            target_artifact: null,
          },
        }),
      ),
    ).toBe(false)
  })

  it('is false for a non-interview gate', () => {
    expect(
      isOpenInterviewCard(
        interviewGate({
          gate: {
            requested_decision: 'approve_prd',
            decision: null,
            round: null,
            cap: null,
            target_artifact: null,
          },
        }),
      ),
    ).toBe(false)
  })

  it('is false when the card no longer allows resolve_gate', () => {
    expect(isOpenInterviewCard(interviewGate({ allowed_actions: [] }))).toBe(
      false,
    )
  })
})

describe('personaOf', () => {
  it('reads the persona off a refinement_gate title', () => {
    expect(
      personaOf(interviewGate({ title: 'pm interview (2 questions)' })),
    ).toBe('pm')
    expect(
      personaOf(interviewGate({ title: 'uiux interview (1 question)' })),
    ).toBe('uiux')
  })

  it('falls back to requester for the CAB-1 strategic-fit title', () => {
    expect(
      personaOf(interviewGate({ title: 'Strategic fit (3 questions)' })),
    ).toBe('requester')
  })

  it('falls back to requester for any unrecognised title shape', () => {
    expect(personaOf(interviewGate({ title: 'Something else' }))).toBe(
      'requester',
    )
  })
})

describe('parseQuestionSet', () => {
  it('parses the plain {questions} shape', () => {
    expect(
      parseQuestionSet(JSON.stringify({ questions: ['A?', 'B?'] })),
    ).toEqual(['A?', 'B?'])
  })

  it('ignores the satisfied flag alongside the questions', () => {
    expect(
      parseQuestionSet(JSON.stringify({ questions: ['A?'], satisfied: false })),
    ).toEqual(['A?'])
  })

  it('returns null for null, prose, and malformed JSON', () => {
    expect(parseQuestionSet(null)).toBeNull()
    expect(parseQuestionSet('not json')).toBeNull()
    expect(parseQuestionSet('[]')).toBeNull()
  })

  it('returns null for an empty or non-string question list', () => {
    expect(parseQuestionSet(JSON.stringify({ questions: [] }))).toBeNull()
    expect(parseQuestionSet(JSON.stringify({ questions: [1, 2] }))).toBeNull()
  })

  it('returns null when a question is blank', () => {
    expect(
      parseQuestionSet(JSON.stringify({ questions: ['A?', '  '] })),
    ).toBeNull()
  })
})

describe('buildInterviewCards', () => {
  it('builds one card per open gate whose content parsed', () => {
    const cards = [
      interviewGate({ id: 'g1', title: 'pm interview (2 questions)' }),
      interviewGate({ id: 'g2', title: 'uiux interview (1 question)' }),
    ]
    const content = {
      g1: JSON.stringify({ questions: ['Q1', 'Q2'] }),
      g2: JSON.stringify({ questions: ['Q3'] }),
    }
    const { cards: built, unreadable } = buildInterviewCards(cards, content)
    expect(built).toHaveLength(2)
    expect(built[0]).toMatchObject({
      cardId: 'g1',
      persona: 'pm',
      round: 1,
      cap: 3,
    })
    expect(built[0].questions).toEqual([
      { id: 'g1:0', prompt: 'Q1' },
      { id: 'g1:1', prompt: 'Q2' },
    ])
    expect(unreadable).toHaveLength(0)
  })

  it('reports a card whose artifact did not parse as unreadable, not dropped silently', () => {
    const cards = [interviewGate({ id: 'g1' })]
    const { cards: built, unreadable } = buildInterviewCards(cards, {
      g1: 'not json',
    })
    expect(built).toHaveLength(0)
    expect(unreadable).toEqual([cards[0]])
  })

  it('reports a card with no fetched content yet as unreadable', () => {
    const cards = [interviewGate({ id: 'g1' })]
    const { unreadable } = buildInterviewCards(cards, {})
    expect(unreadable).toHaveLength(1)
  })

  it('ignores cards that are not open interview gates', () => {
    const cards = [
      workCardSummary({ id: 'other', card_type: 'implementation' }),
    ]
    const { cards: built, unreadable } = buildInterviewCards(cards, {})
    expect(built).toHaveLength(0)
    expect(unreadable).toHaveLength(0)
  })
})

describe('deriveRoundState', () => {
  it('takes the first round-capped card', () => {
    const state = deriveRoundState([
      { cardId: 'g1', persona: 'pm', questions: [], round: 2, cap: 3 },
    ])
    expect(state).toEqual({ current: 2, cap: 3 })
  })

  it('degrades to null/null with no round-capped card', () => {
    expect(
      deriveRoundState([
        { cardId: 'g1', persona: 'pm', questions: [], round: null, cap: null },
      ]),
    ).toEqual({ current: null, cap: null })
    expect(deriveRoundState([])).toEqual({ current: null, cap: null })
  })
})
