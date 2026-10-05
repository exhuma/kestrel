import { describe, it, expect } from 'vitest'
import {
  personaOf,
  personaName,
  personaInitial,
  toneOf,
  summaryOf,
  toFeedEntry,
  toFeedEntries,
} from '../../src/lib/personas'
import { boardEvent } from '../support/board'

describe('personaOf attribution', () => {
  it('names the specialist when the event carries an eligible role', () => {
    const persona = personaOf(
      boardEvent({
        event_type: 'card.result_accepted',
        specialist: { id: 'pm', label: 'Product manager' },
      }),
    )
    expect(persona).toEqual({ kind: 'specialist', name: 'Product manager' })
  })

  it('resolves a null specialist to the neutral system persona', () => {
    const persona = personaOf(
      boardEvent({ event_type: 'workflow.created', specialist: null }),
    )
    expect(persona).toEqual({ kind: 'system' })
  })

  it('attributes an operator-caused event to the operator', () => {
    const persona = personaOf(
      boardEvent({ event_type: 'gate.approved', specialist: null }),
    )
    expect(persona).toEqual({ kind: 'operator' })
  })

  it('credits the operator even when the gate card carries an eligible role', () => {
    // The gate a specialist was eligible for is still resolved by the
    // operator — `specialist` is a read-time derivation, not an actor.
    const persona = personaOf(
      boardEvent({
        event_type: 'gate.rejected',
        specialist: { id: 'pm', label: 'Product manager' },
      }),
    )
    expect(persona).toEqual({ kind: 'operator' })
  })

  it('treats an interview ending itself as the system, not the operator', () => {
    expect(
      personaOf(
        boardEvent({ event_type: 'refinement.satisfied', specialist: null }),
      ),
    ).toEqual({ kind: 'system' })
  })
})

describe('personaName never renders a blank attribution', () => {
  it.each([
    [
      { kind: 'specialist', name: 'Product manager' } as const,
      'Product manager',
    ],
    [{ kind: 'operator' } as const, 'You'],
    [{ kind: 'system' } as const, 'System'],
  ])('names %o', (persona, expected) => {
    expect(personaName(persona)).toBe(expected)
    expect(personaName(persona)).not.toBe('')
  })

  it('gives every persona an avatar initial', () => {
    expect(personaInitial({ kind: 'system' })).toBe('S')
    expect(personaInitial({ kind: 'operator' })).toBe('Y')
    expect(personaInitial({ kind: 'specialist', name: 'pm' })).toBe('P')
  })
})

describe('toneOf', () => {
  it.each([
    ['gate.approved', 'success'],
    ['card.result_accepted', 'success'],
    ['gate.rejected', 'warning'],
    ['card.recovery_escalated', 'error'],
    ['workflow.created', 'info'],
  ])('tones %s as %s', (type, expected) => {
    expect(toneOf(boardEvent({ event_type: type }))).toBe(expected)
  })

  it('falls back to info for an event type it has not been taught', () => {
    expect(toneOf(boardEvent({ event_type: 'something.new' }))).toBe('info')
  })
})

describe('summaryOf', () => {
  it('states known events in human words', () => {
    expect(summaryOf(boardEvent({ event_type: 'workflow.created' }))).toBe(
      'Request ingested',
    )
  })

  it('says a gate opening is a decision waiting, not a raw event type', () => {
    expect(summaryOf(boardEvent({ event_type: 'gate.opened' }))).toBe(
      'A decision is waiting for an answer',
    )
  })

  it('credits a gate opening to the system, not the operator', () => {
    expect(
      personaOf(boardEvent({ event_type: 'gate.opened', specialist: null })),
    ).toEqual({ kind: 'system' })
  })

  it('falls back to the raw event type rather than dropping the event', () => {
    expect(summaryOf(boardEvent({ event_type: 'something.new' }))).toBe(
      'something.new',
    )
  })
})

describe('toFeedEntry', () => {
  it('builds the whole row from one event', () => {
    const event = boardEvent({
      event_type: 'gate.approved',
      created_at: '2026-09-28T10:00:00Z',
    })
    const entry = toFeedEntry(event)
    expect(entry.persona).toEqual({ kind: 'operator' })
    expect(entry.tone).toBe('success')
    expect(entry.summary).toBe('You approved this gate')
    expect(entry.timestamp).not.toBe('')
  })

  it('renders an absent timestamp as empty rather than as an invalid date', () => {
    expect(toFeedEntry(boardEvent({ created_at: null })).timestamp).toBe('')
  })

  it('preserves the order it is given, oldest first', () => {
    const entries = toFeedEntries([
      boardEvent({ event_type: 'workflow.created' }),
      boardEvent({ event_type: 'gate.approved' }),
    ])
    expect(entries.map((e) => e.summary)).toEqual([
      'Request ingested',
      'You approved this gate',
    ])
  })
})

describe('a gate decided from the ticket (feature 046)', () => {
  const fromJira = JSON.stringify({
    detail: 'Rita Reporter decided via Jira',
    channel: 'jira',
    account_id: 'acc-reporter',
    display_name: 'Rita Reporter',
  })

  it('credits the person who replied, not the operator', () => {
    const event = boardEvent({ event_type: 'gate.approved', payload: fromJira })
    expect(personaOf(event)).toEqual({
      kind: 'person',
      name: 'Rita Reporter',
      channel: 'jira',
    })
    expect(personaName(personaOf(event))).toBe('Rita Reporter')
  })

  it('says who decided, via Jira, and what', () => {
    expect(
      summaryOf(boardEvent({ event_type: 'gate.approved', payload: fromJira })),
    ).toBe('Rita Reporter decided via Jira: approved')
    expect(
      summaryOf(boardEvent({ event_type: 'gate.rejected', payload: fromJira })),
    ).toBe('Rita Reporter decided via Jira: rejected')
  })

  it('never shows an empty name', () => {
    const payload = JSON.stringify({ channel: 'jira', display_name: ' ' })
    const event = boardEvent({ event_type: 'gate.approved', payload })
    expect(personaName(personaOf(event))).toBe('Someone')
  })

  it('keeps a UI decision as the operator', () => {
    const event = boardEvent({ event_type: 'gate.approved', payload: '{}' })
    expect(personaOf(event)).toEqual({ kind: 'operator' })
    expect(summaryOf(event)).toBe('You approved this gate')
  })

  it('ignores a channel on any other event', () => {
    const event = boardEvent({
      event_type: 'card.result_accepted',
      payload: fromJira,
      specialist: null,
    })
    expect(personaOf(event)).toEqual({ kind: 'system' })
  })
})
