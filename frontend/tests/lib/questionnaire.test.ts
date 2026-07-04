import { describe, it, expect } from 'vitest'
import {
  allRequiredAnswered,
  groupByProfile,
  parseInterview,
  parseQuestionnaire,
} from '../../src/lib/questionnaire'
import type { Question, Questionnaire } from '../../src/types/questionnaire'

function q(partial: Partial<Question> & { id: string }): Question {
  return {
    prompt: '', why: '', type: 'free_text', required: true, options: [],
    audience: '', waiver_label: 'Unknown / N/A', ...partial,
  }
}

const single = q({
  id: 'q1', prompt: 'Which auth?', type: 'single_select',
  options: [{ value: 'oidc', label: 'OIDC' }], audience: 'developer',
})

describe('parseInterview / parseQuestionnaire', () => {
  it('parses a bare questionnaire with an empty draft', () => {
    const text = JSON.stringify({ questions: [single], profiles: [] })
    const env = parseInterview(text)
    expect(env?.questionnaire.questions[0].id).toBe('q1')
    expect(env?.draft_answers).toEqual({})
    expect(parseQuestionnaire(text)?.questions[0].id).toBe('q1')
  })

  it('unwraps the enveloped form and restores the draft', () => {
    const text = JSON.stringify({
      questionnaire: { questions: [single], profiles: [] },
      draft_answers: { q1: 'oidc' },
    })
    const env = parseInterview(text)
    expect(env?.questionnaire.questions[0].id).toBe('q1')
    expect(env?.draft_answers).toEqual({ q1: 'oidc' })
  })

  it('returns null for prose and null input', () => {
    expect(parseInterview('just prose')).toBeNull()
    expect(parseInterview(null)).toBeNull()
  })
})

describe('allRequiredAnswered with waivers', () => {
  const questionnaire: Questionnaire = { questions: [single], profiles: [] }

  it('is false until answered', () => {
    expect(allRequiredAnswered(questionnaire, {})).toBe(false)
    expect(allRequiredAnswered(questionnaire, { q1: 'oidc' })).toBe(true)
  })

  it('counts a waiver with a reason as answered', () => {
    expect(
      allRequiredAnswered(questionnaire, {
        q1: { waived: true, reason: 'Accepted' },
      }),
    ).toBe(true)
  })

  it('rejects a waiver without a reason', () => {
    expect(
      allRequiredAnswered(questionnaire, { q1: { waived: true, reason: '' } }),
    ).toBe(false)
  })
})

describe('groupByProfile', () => {
  const questionnaire: Questionnaire = {
    questions: [
      q({ id: 'developer:q1', audience: 'developer' }),
      q({ id: 'infosec:q1', audience: 'infosec' }),
      q({ id: 'infosec:q2', audience: 'infosec' }),
    ],
    profiles: [
      { id: 'developer', label: 'Developer', badge: 'agent' },
      { id: 'infosec', label: 'InfoSec', badge: 'warn' },
    ],
  }

  it('groups questions by audience with metadata and answered counts', () => {
    const groups = groupByProfile(questionnaire, {
      'infosec:q1': { waived: true, reason: 'risk accepted' },
    })
    expect(groups.map((g) => g.profile.id)).toEqual(['developer', 'infosec'])
    expect(groups[1].profile.label).toBe('InfoSec')
    expect(groups[1].profile.badge).toBe('warn')
    expect(groups[1].questions).toHaveLength(2)
    expect(groups[1].answered).toBe(1) // the waived one counts
    expect(groups[0].answered).toBe(0)
  })

  it('synthesises a group for an audience without metadata', () => {
    const groups = groupByProfile(
      { questions: [q({ id: 'x', audience: 'observability' })], profiles: [] },
      {},
    )
    expect(groups[0].profile.label).toBe('Observability')
    expect(groups[0].profile.badge).toBe('sys')
  })
})
