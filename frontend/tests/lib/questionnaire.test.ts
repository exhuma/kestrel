import { describe, it, expect } from 'vitest'
import {
  allRequiredAnswered,
  parseQuestionnaire,
} from '../../src/lib/questionnaire'
import type { Questionnaire } from '../../src/types/questionnaire'

describe('parseQuestionnaire', () => {
  it('parses a valid questionnaire', () => {
    const text = JSON.stringify({
      questions: [
        {
          id: 'q1', prompt: 'Which auth?', why: '', type: 'single_select',
          required: true, options: [{ value: 'oidc', label: 'OIDC' }],
        },
      ],
    })
    const q = parseQuestionnaire(text)
    expect(q?.questions[0].id).toBe('q1')
  })

  it('returns null for plain prose', () => {
    expect(parseQuestionnaire('Which auth flow do you want?')).toBeNull()
  })

  it('returns null for null input', () => {
    expect(parseQuestionnaire(null)).toBeNull()
  })

  it('returns null when questions is missing', () => {
    expect(parseQuestionnaire(JSON.stringify({ foo: 'bar' }))).toBeNull()
  })
})

describe('allRequiredAnswered', () => {
  const questionnaire: Questionnaire = {
    questions: [
      {
        id: 'q1', prompt: 'Which auth?', why: '', type: 'single_select',
        required: true, options: [{ value: 'oidc', label: 'OIDC' }],
      },
      {
        id: 'q2', prompt: 'Anything else?', why: '', type: 'free_text',
        required: false, options: [],
      },
    ],
  }

  it('is false until the required question is answered', () => {
    expect(allRequiredAnswered(questionnaire, {})).toBe(false)
    expect(allRequiredAnswered(questionnaire, { q1: 'oidc' })).toBe(true)
  })

  it('ignores optional questions entirely', () => {
    expect(
      allRequiredAnswered(questionnaire, { q1: 'oidc', q2: '' }),
    ).toBe(true)
  })

  it('treats an empty array as missing (multi_select)', () => {
    const q: Questionnaire = {
      questions: [
        {
          id: 'm', prompt: 'Which?', why: '', type: 'multi_select',
          required: true, options: [{ value: 'a', label: 'A' }],
        },
      ],
    }
    expect(allRequiredAnswered(q, { m: [] })).toBe(false)
    expect(allRequiredAnswered(q, { m: ['a'] })).toBe(true)
  })
})
