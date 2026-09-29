/**
 * Who is expected to act, in words (feature 035). The server decides the
 * actor and the ask as codes (`app.services.board.awaiting`); this only
 * phrases them. An unknown code is shown as itself rather than dropped.
 */
import type { Awaiting } from '../types/workflows'

const ACTORS: Readonly<Record<Awaiting['actor'], string>> = {
  requester: 'Requester',
  cab: 'CAB',
  you: 'You',
  operator: 'Operator',
}

const ASKS: Readonly<Record<string, string>> = {
  confirm_understanding: 'confirm the understanding',
  answer: 'answer the interview',
  approve_strategic_fit: 'decide strategic fit',
  approve_prd: 'sign off the PRD',
  approve_decomposition: 'go / no-go',
  do_task: 'do the task',
  review_input: 'review the input',
  retry_or_cancel: 'retry or cancel',
  review: 'review',
}

export function actorLabel(awaiting: Awaiting): string {
  return ACTORS[awaiting.actor] ?? awaiting.actor
}

/** "CAB: decide strategic fit". */
export function describeAwaiting(awaiting: Awaiting): string {
  return `${actorLabel(awaiting)}: ${ASKS[awaiting.ask] ?? awaiting.ask}`
}

/** The first waiting move, and how many more: "CAB: decide strategic
 *  fit (+1 more)". Empty when nothing waits on a human. */
export function describeMoves(awaiting: Awaiting[]): string {
  const [first, ...rest] = awaiting
  if (!first) return ''
  const more = rest.length > 0 ? ` (+${rest.length} more)` : ''
  return `${describeAwaiting(first)}${more}`
}
