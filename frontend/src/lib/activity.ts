/**
 * Phrasing a request's activity (feature 033). The backend decides which
 * of the six states a request is in; this only puts it into words, and
 * decides the display-only 5-minute "queued too long" warning.
 */
import type { RequestActivity } from '../types/workflows'

/** Queued work older than this is flagged: nobody has picked it up. */
export const QUEUED_WARNING_MS = 5 * 60 * 1000

export type ActivityTone = 'info' | 'error' | 'warning' | 'success' | 'default'

export interface ActivityView {
  text: string
  tone: ActivityTone
  /** Something is running right now: show a live indicator. */
  busy: boolean
}

const STALLED_TEXT: Readonly<Record<string, string>> = {
  interrupted_screening:
    'Stalled: screening was interrupted. It is retried on the next poll.',
  interrupted_claim: 'was interrupted. It is retried when its claim expires.',
  nothing_ready: 'Stalled: nothing is running, ready, or waiting for you.',
}

/** "just now", "4 min", "1 h 5 min" since *since*, or '' if unknown. */
export function elapsed(since: string | null, now: number): string {
  if (!since) return ''
  const minutes = Math.floor((now - Date.parse(since)) / 60000)
  if (!Number.isFinite(minutes) || minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min`
  const rest = minutes % 60
  return rest
    ? `${Math.floor(minutes / 60)} h ${rest} min`
    : `${minutes / 60} h`
}

function quote(subject: string | null): string {
  return subject ? `“${subject}”` : 'its work'
}

function working(a: RequestActivity): string {
  if (a.actor === 'screening') return 'Screening input…'
  if (a.actor === 'coordinator') return 'The coordinator is planning…'
  const who = a.actor ?? 'An agent'
  return a.subject
    ? `${who} is working on ${quote(a.subject)}`
    : `${who} is working…`
}

function problem(a: RequestActivity): string {
  if (a.detail) return `Problem: ${a.detail}. It will be retried.`
  return `Problem: ${quote(a.subject)} failed. Retry or cancel it.`
}

function stalled(a: RequestActivity): string {
  const text = STALLED_TEXT[a.reason ?? 'nothing_ready']
  return a.reason === 'interrupted_claim'
    ? `Stalled: ${quote(a.subject)} ${text}`
    : text
}

function queued(a: RequestActivity, late: boolean): string {
  const who = a.actor ? ` for ${a.actor}` : ''
  const text = `Queued${who}: ${quote(a.subject)}`
  return late ? `${text}. Nobody has picked it up yet.` : text
}

type Phrase = (
  a: RequestActivity,
  late: boolean,
) => Omit<ActivityView, 'text'> & {
  text: string
}

const PHRASES: Readonly<Record<RequestActivity['state'], Phrase>> = {
  working: (a) => ({ text: working(a), tone: 'info', busy: true }),
  problem: (a) => ({ text: problem(a), tone: 'error', busy: false }),
  waiting: (a) => ({
    text: `Waiting for you: ${a.subject ?? 'a decision'}`,
    tone: 'warning',
    busy: false,
  }),
  queued: (a, late) => ({
    text: queued(a, late),
    tone: late ? 'warning' : 'default',
    busy: false,
  }),
  done: () => ({ text: 'Done', tone: 'success', busy: false }),
  stalled: (a) => ({ text: stalled(a), tone: 'error', busy: false }),
}

function isLate(a: RequestActivity, now: number): boolean {
  if (a.state !== 'queued' || a.since === null) return false
  return now - Date.parse(a.since) > QUEUED_WARNING_MS
}

/** One line, a tone, and whether to show a live indicator. */
export function describeActivity(
  a: RequestActivity,
  now: number,
): ActivityView {
  const view = PHRASES[a.state](a, isLate(a, now))
  const age = a.state === 'done' ? '' : elapsed(a.since, now)
  return age ? { ...view, text: `${view.text} · ${age}` } : view
}
