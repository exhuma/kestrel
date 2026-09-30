import { describe, it, expect } from 'vitest'
import { describeActivity, elapsed } from '../../src/lib/activity'
import type { RequestActivity } from '../../src/types/workflows'

const NOW = Date.parse('2026-09-29T10:10:00Z')

function activity(overrides: Partial<RequestActivity>): RequestActivity {
  return {
    state: 'working',
    actor: null,
    subject: null,
    detail: null,
    reason: null,
    since: '2026-09-29T10:08:00Z',
    tool: null,
    tool_calls: null,
    ...overrides,
  }
}

describe('describeActivity (feature 033)', () => {
  it('names who works on what, for how long, with a live indicator', () => {
    const view = describeActivity(
      activity({ actor: 'Project Manager', subject: 'Restate the request' }),
      NOW,
    )
    expect(view).toEqual({
      text: 'Project Manager is working on “Restate the request” · 2 min',
      tone: 'info',
      busy: true,
    })
  })

  it('names screening and the coordinator in their own words', () => {
    expect(describeActivity(activity({ actor: 'screening' }), NOW).text).toBe(
      'Screening input… · 2 min',
    )
    expect(
      describeActivity(activity({ actor: 'coordinator' }), NOW).text,
    ).toContain('The coordinator is planning…')
  })

  it('states a problem and never shows it as busy', () => {
    const view = describeActivity(
      activity({
        state: 'problem',
        detail: "the coordinator's turn timed out",
      }),
      NOW,
    )
    expect(view.tone).toBe('error')
    expect(view.busy).toBe(false)
    expect(view.text).toContain("Problem: the coordinator's turn timed out.")
  })
})

describe('describeActivity when nothing runs (feature 033)', () => {
  it('warns once queued work has waited over 5 minutes', () => {
    const fresh = describeActivity(
      activity({ state: 'queued', actor: 'Project Manager', subject: 'X' }),
      NOW,
    )
    const late = describeActivity(
      activity({
        state: 'queued',
        actor: 'Project Manager',
        subject: 'X',
        since: '2026-09-29T10:00:00Z',
      }),
      NOW,
    )
    expect(fresh.tone).toBe('default')
    expect(late.tone).toBe('warning')
    expect(late.text).toContain('Nobody has picked it up yet.')
  })

  it('explains a stall', () => {
    const view = describeActivity(
      activity({ state: 'stalled', reason: 'interrupted_claim', subject: 'X' }),
      NOW,
    )
    expect(view.tone).toBe('error')
    expect(view.text).toContain('Stalled: “X” was interrupted.')
  })

  it('shows done without an age', () => {
    expect(describeActivity(activity({ state: 'done' }), NOW).text).toBe('Done')
  })
})

describe('elapsed', () => {
  it('reads coarse durations', () => {
    expect(elapsed(null, NOW)).toBe('')
    expect(elapsed('2026-09-29T10:09:50Z', NOW)).toBe('just now')
    expect(elapsed('2026-09-29T09:05:00Z', NOW)).toBe('1 h 5 min')
  })
})

describe('describeActivity tool use (feature 036)', () => {
  it('shows the tool being called and how often', () => {
    const view = describeActivity(
      activity({
        actor: 'Project Manager',
        subject: 'Draft the PRD',
        tool: 'gitlab_list_project_issues',
        tool_calls: 40,
      }),
      NOW,
    )
    expect(view.text).toBe(
      'Project Manager is working on “Draft the PRD” · calling ' +
        'gitlab_list_project_issues (×40) · 2 min',
    )
  })

  it('leaves out the count for a single call', () => {
    const view = describeActivity(
      activity({ actor: 'Coder', tool: 'read', tool_calls: 1 }),
      NOW,
    )
    expect(view.text).toBe('Coder is working… · calling read · 2 min')
  })
})

describe('describeActivity for a cancelled request (feature 040)', () => {
  it('says it was cancelled, never done', () => {
    const view = describeActivity(activity({ state: 'cancelled' }), NOW)
    expect(view.text).toBe('Cancelled before it was finished')
    expect(view.busy).toBe(false)
  })
})
