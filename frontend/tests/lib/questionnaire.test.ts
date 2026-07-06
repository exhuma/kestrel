import { describe, it, expect } from 'vitest'
import {
  allRequiredAnswered,
  createPendingInterviewParser,
  groupByProfile,
  isCustom,
  noteOf,
  parseInterview,
  parseQuestionnaire,
  primaryValue,
} from '../../src/lib/questionnaire'
import type { Question, Questionnaire } from '../../src/types/questionnaire'

function q(partial: Partial<Question> & { id: string }): Question {
  return {
    prompt: '',
    why: '',
    type: 'free_text',
    required: true,
    options: [],
    audience: '',
    waiver_label: 'Unknown / N/A',
    ...partial,
  }
}

const single = q({
  id: 'q1',
  prompt: 'Which auth?',
  type: 'single_select',
  options: [{ value: 'oidc', label: 'OIDC' }],
  audience: 'developer',
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

  it('carries generation issues (with severity) through the envelope', () => {
    const issue = {
      profile: 'infosec',
      label: 'InfoSec',
      reason: 'no response',
      severity: 'soft',
    }
    const text = JSON.stringify({
      questionnaire: { questions: [single], profiles: [], issues: [issue] },
      draft_answers: {},
    })
    expect(parseInterview(text)?.questionnaire.issues).toEqual([issue])
  })

  it('defaults issues to an empty array when absent', () => {
    const text = JSON.stringify({ questions: [single], profiles: [] })
    expect(parseInterview(text)?.questionnaire.issues).toEqual([])
  })

  it('coerces an option-less select to free text, leaving others untouched', () => {
    const text = JSON.stringify({
      questions: [
        q({ id: 's1', type: 'single_select', options: [] }),
        q({ id: 's2', type: 'multi_select', options: [] }),
        single,
      ],
      profiles: [],
    })
    const qs = parseInterview(text)!.questionnaire.questions
    expect(qs.map((x) => x.type)).toEqual([
      'free_text',
      'free_text',
      'single_select',
    ])
    // The bare-questionnaire path coerces identically.
    expect(parseQuestionnaire(text)!.questions[0].type).toBe('free_text')
  })
})

describe('createPendingInterviewParser', () => {
  const text = JSON.stringify({ questions: [single], profiles: [] })

  it('returns the same reference for repeated calls at the same round', () => {
    const parse = createPendingInterviewParser()
    const first = parse('wf-1', { deliverable: text, refine_round: 1 })
    // A structurally-equal but distinct `step` object, as a fresh SSE
    // frame would produce — the round hasn't changed, so this must not
    // be treated as new data.
    const second = parse('wf-1', { deliverable: text, refine_round: 1 })
    expect(first).not.toBeNull()
    expect(second).toBe(first)
  })

  it('returns a new reference once the round advances', () => {
    const parse = createPendingInterviewParser()
    const first = parse('wf-1', { deliverable: text, refine_round: 1 })
    const second = parse('wf-1', { deliverable: text, refine_round: 2 })
    expect(second).not.toBe(first)
    expect(second?.round).toBe(2)
  })

  it('does not confuse the same round across different workflows', () => {
    const parse = createPendingInterviewParser()
    const first = parse('wf-1', { deliverable: text, refine_round: 1 })
    const second = parse('wf-2', { deliverable: text, refine_round: 1 })
    expect(second).not.toBe(first)
  })

  it('returns null once the step disappears', () => {
    const parse = createPendingInterviewParser()
    parse('wf-1', { deliverable: text, refine_round: 1 })
    expect(parse('wf-1', null)).toBeNull()
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

describe('custom corrections and noted answers', () => {
  const questionnaire: Questionnaire = { questions: [single], profiles: [] }

  it('isCustom guards a {custom} marker', () => {
    expect(isCustom({ custom: 'nope' })).toBe(true)
    expect(isCustom({ waived: true, reason: 'x' })).toBe(false)
    expect(isCustom('oidc')).toBe(false)
  })

  it('counts a custom correction with text as answered', () => {
    expect(
      allRequiredAnswered(questionnaire, { q1: { custom: 'It is a CLI' } }),
    ).toBe(true)
    expect(allRequiredAnswered(questionnaire, { q1: { custom: '  ' } })).toBe(
      false,
    )
  })

  it('unwraps a noted answer for its primary value and note', () => {
    const answers = { q1: { value: 'oidc', note: 'SSO only' } }
    expect(primaryValue('q1', answers)).toBe('oidc')
    expect(noteOf('q1', answers)).toBe('SSO only')
    // A noted answer still satisfies the completeness gate by its value.
    expect(allRequiredAnswered(questionnaire, answers)).toBe(true)
  })

  it('does not count a bare note (no value) as answered', () => {
    expect(
      allRequiredAnswered(questionnaire, { q1: { value: null, note: 'hmm' } }),
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
