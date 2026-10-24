import { describe, expect, it } from 'vitest'
import { describeAwaiting, describeMoves } from '../../src/lib/awaiting'

describe('describeAwaiting', () => {
  it('phrases the actor and the ask', () => {
    expect(
      describeAwaiting({ actor: 'requester', ask: 'answer', role: null }),
    ).toBe('Requester: answer the interview')
    expect(
      describeAwaiting({
        actor: 'cab',
        ask: 'approve_decomposition',
        role: null,
      }),
    ).toBe('CAB: go / no-go')
  })

  it('shows an unknown ask as itself', () => {
    expect(
      describeAwaiting({ actor: 'operator', ask: 'mystery', role: null }),
    ).toBe('Operator: mystery')
  })
})

describe('describeMoves', () => {
  it('is empty when nothing waits', () => {
    expect(describeMoves([])).toBe('')
  })

  it('names the first move alone when it is the only one', () => {
    expect(describeMoves([{ actor: 'you', ask: 'do_task', role: null }])).toBe(
      'You: do the task',
    )
  })
})

describe('describeAwaiting for an interview (feature 038)', () => {
  it('names the profile whose human answers', () => {
    expect(
      describeAwaiting({
        actor: 'role',
        ask: 'answer',
        role: { id: 'dba', label: 'Database Specialist' },
      }),
    ).toBe('Database Specialist: answer the interview')
  })
})
