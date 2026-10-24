import { describe, it, expect } from 'vitest'
import {
  allRequiredAnswered,
  isAnswered,
  outstandingQuestions,
  reconcileAnswers,
  serializeAnswers,
} from '../../src/lib/interviewAnswers'
import type {
  InterviewQuestion,
  QuestionAnswer,
} from '../../src/types/interview'

const q1: InterviewQuestion = { id: 'g1:0', prompt: 'Auth mechanism?' }
const q2: InterviewQuestion = { id: 'g1:1', prompt: 'Rate limit?' }

describe('isAnswered / allRequiredAnswered', () => {
  it('is false for every unanswered question', () => {
    expect(isAnswered(undefined)).toBe(false)
    expect(isAnswered({ state: 'unanswered', text: '' })).toBe(false)
    expect(allRequiredAnswered([q1, q2], {})).toBe(false)
  })

  it('is true for a concrete answer', () => {
    const answers: Record<string, QuestionAnswer> = {
      [q1.id]: { state: 'answered', text: 'OIDC' },
    }
    expect(isAnswered(answers[q1.id])).toBe(true)
  })

  it('counts unknown and not-relevant as satisfying the gate', () => {
    const answers: Record<string, QuestionAnswer> = {
      [q1.id]: { state: 'unknown', text: '' },
      [q2.id]: { state: 'not-relevant', text: '' },
    }
    expect(allRequiredAnswered([q1, q2], answers)).toBe(true)
  })

  it('is false while any one question remains unanswered', () => {
    const answers: Record<string, QuestionAnswer> = {
      [q1.id]: { state: 'answered', text: 'OIDC' },
    }
    expect(allRequiredAnswered([q1, q2], answers)).toBe(false)
  })
})

describe('outstandingQuestions', () => {
  it('identifies exactly the unanswered questions', () => {
    const answers: Record<string, QuestionAnswer> = {
      [q1.id]: { state: 'answered', text: 'OIDC' },
    }
    expect(outstandingQuestions([q1, q2], answers)).toEqual([q2])
  })

  it('is empty once every question is answered or waived', () => {
    const answers: Record<string, QuestionAnswer> = {
      [q1.id]: { state: 'answered', text: 'OIDC' },
      [q2.id]: { state: 'not-relevant', text: '' },
    }
    expect(outstandingQuestions([q1, q2], answers)).toEqual([])
  })
})

describe('reconcileAnswers', () => {
  it('carries an answer forward under the new round’s id, keyed on prompt text', () => {
    const oldQuestions: InterviewQuestion[] = [{ id: 'g1:0', prompt: 'Auth?' }]
    const oldAnswers: Record<string, QuestionAnswer> = {
      'g1:0': { state: 'answered', text: 'OIDC' },
    }
    const newQuestions: InterviewQuestion[] = [{ id: 'g2:0', prompt: 'Auth?' }]
    expect(reconcileAnswers(oldQuestions, oldAnswers, newQuestions)).toEqual({
      'g2:0': { state: 'answered', text: 'OIDC' },
    })
  })

  it('drops an answer whose question no longer exists', () => {
    const oldQuestions: InterviewQuestion[] = [{ id: 'g1:0', prompt: 'Auth?' }]
    const oldAnswers: Record<string, QuestionAnswer> = {
      'g1:0': { state: 'answered', text: 'OIDC' },
    }
    const newQuestions: InterviewQuestion[] = [
      { id: 'g2:0', prompt: 'A completely different question?' },
    ]
    expect(reconcileAnswers(oldQuestions, oldAnswers, newQuestions)).toEqual({})
  })

  it('is a no-op when the question set is genuinely unchanged', () => {
    const questions: InterviewQuestion[] = [q1, q2]
    const answers: Record<string, QuestionAnswer> = {
      [q1.id]: { state: 'answered', text: 'OIDC' },
      [q2.id]: { state: 'unknown', text: '' },
    }
    expect(reconcileAnswers(questions, answers, questions)).toEqual(answers)
  })

  it('does not misattribute a new question at a reused id to the old answer', () => {
    const oldQuestions: InterviewQuestion[] = [{ id: 'g1:0', prompt: 'Auth?' }]
    const oldAnswers: Record<string, QuestionAnswer> = {
      'g1:0': { state: 'answered', text: 'OIDC' },
    }
    // A fresh round starting again at index 0 for a new card id collides
    // with nothing here, but guards the id-based (not prompt-based) trap.
    const newQuestions: InterviewQuestion[] = [
      { id: 'g1:0', prompt: 'A totally different question?' },
    ]
    expect(reconcileAnswers(oldQuestions, oldAnswers, newQuestions)).toEqual({})
  })
})

describe('serializeAnswers', () => {
  it('names the picked options and the comment (feature 034)', () => {
    const choice = {
      id: 'c',
      prompt: 'Formats?',
      options: ['CSV', 'PDF'],
      multiple: true,
    }
    const answers: Record<string, QuestionAnswer> = {
      c: { state: 'answered', text: ' PDF later ', choices: ['CSV', 'PDF'] },
    }
    expect(serializeAnswers([choice], answers)).toBe(
      'Q: Formats?\nA: CSV, PDF\nComment: PDF later',
    )
  })

  it('renders a concrete answer plainly', () => {
    const answers: Record<string, QuestionAnswer> = {
      [q1.id]: { state: 'answered', text: '  OIDC, with PKCE  ' },
    }
    expect(serializeAnswers([q1], answers)).toBe(
      'Q: Auth mechanism?\nA: OIDC, with PKCE',
    )
  })

  it('distinguishes unknown, not-relevant and unanswered from each other and from empty text', () => {
    const questions: InterviewQuestion[] = [
      { id: 'a', prompt: 'Q-unknown' },
      { id: 'b', prompt: 'Q-not-relevant' },
      { id: 'c', prompt: 'Q-unanswered' },
    ]
    const answers: Record<string, QuestionAnswer> = {
      a: { state: 'unknown', text: '' },
      b: { state: 'not-relevant', text: '' },
    }
    const out = serializeAnswers(questions, answers)
    const blocks = out.split('\n\n')
    expect(blocks[0]).toContain("I don't know")
    expect(blocks[1]).toContain('Not relevant')
    expect(blocks[2]).toContain('No answer was given')
    // No two states render identically.
    expect(new Set(blocks).size).toBe(3)
  })

  it('joins multiple questions with a blank line between blocks', () => {
    const answers: Record<string, QuestionAnswer> = {
      [q1.id]: { state: 'answered', text: 'OIDC' },
      [q2.id]: { state: 'answered', text: '100 req/s' },
    }
    expect(serializeAnswers([q1, q2], answers)).toBe(
      'Q: Auth mechanism?\nA: OIDC\n\nQ: Rate limit?\nA: 100 req/s',
    )
  })
})
