import type {
  CustomAnswer,
  GenerationIssue,
  InterviewEnvelope,
  NotedAnswer,
  PendingInterview,
  ProfileMeta,
  Question,
  Questionnaire,
  WaiverAnswer,
} from '../types/questionnaire'

function titleCase(id: string): string {
  return id
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

function normaliseQuestionnaire(obj: unknown): Questionnaire | null {
  if (typeof obj !== 'object' || obj === null) return null
  const o = obj as Record<string, unknown>
  if (!Array.isArray(o.questions)) return null
  return {
    questions: o.questions as Question[],
    profiles: Array.isArray(o.profiles) ? (o.profiles as ProfileMeta[]) : [],
    issues: Array.isArray(o.issues) ? (o.issues as GenerationIssue[]) : [],
  }
}

/**
 * Parse a step deliverable as a structured questionnaire.
 *
 * Accepts either a bare questionnaire or the interview envelope the
 * backend now stores; returns null for anything else (free-text agent
 * messages included) so callers can fall back gracefully.
 */
export function parseQuestionnaire(
  text: string | null,
): Questionnaire | null {
  return parseInterview(text)?.questionnaire ?? null
}

/**
 * Parse the interview envelope, unwrapping either the enveloped form
 * (`{ questionnaire, draft_answers }`) or a bare questionnaire.
 */
export function parseInterview(
  text: string | null,
): InterviewEnvelope | null {
  if (!text) return null
  let data: unknown
  try {
    data = JSON.parse(text)
  } catch {
    return null
  }
  if (typeof data !== 'object' || data === null) return null
  const obj = data as Record<string, unknown>
  if (obj.questionnaire && typeof obj.questionnaire === 'object') {
    const questionnaire = normaliseQuestionnaire(obj.questionnaire)
    if (!questionnaire) return null
    const draft = obj.draft_answers
    return {
      questionnaire,
      draft_answers:
        typeof draft === 'object' && draft !== null
          ? (draft as Record<string, unknown>)
          : {},
    }
  }
  const questionnaire = normaliseQuestionnaire(obj)
  if (!questionnaire) return null
  return { questionnaire, draft_answers: {} }
}

/**
 * Build a memoized parser from a step's (deliverable, refine_round) to a
 * PendingInterview, returning the *same* object reference when the round
 * hasn't changed. This stops an SSE tick that carries no real
 * questionnaire change from looking like "new data" to a downstream
 * reference-identity watcher.
 */
export function createPendingInterviewParser() {
  let lastKey: string | null = null
  let lastValue: PendingInterview | null = null
  return function parsePendingInterview(
    workflowId: string,
    step: { deliverable: string | null; refine_round: number } | null,
  ): PendingInterview | null {
    if (!step) {
      lastKey = null
      lastValue = null
      return null
    }
    const key = `${workflowId}:${step.refine_round}`
    if (key === lastKey) return lastValue
    const envelope = parseInterview(step.deliverable)
    lastValue = envelope ? { ...envelope, round: step.refine_round } : null
    lastKey = key
    return lastValue
  }
}

/** Type guard: a "cannot answer — recorded reason" answer. */
export function isWaiver(value: unknown): value is WaiverAnswer {
  return (
    typeof value === 'object' &&
    value !== null &&
    (value as { waived?: unknown }).waived === true
  )
}

function waiverReason(value: unknown): string {
  return isWaiver(value) ? String(value.reason ?? '').trim() : ''
}

/** Type guard: a "none of these fit — correct the agent" answer. */
export function isCustom(value: unknown): value is CustomAnswer {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as { custom?: unknown }).custom === 'string'
  )
}

function customText(value: unknown): string {
  return isCustom(value) ? value.custom.trim() : ''
}

/** Type guard: a concrete answer annotated with extra detail. */
function isNoted(value: unknown): value is NotedAnswer {
  return (
    typeof value === 'object' &&
    value !== null &&
    'value' in value &&
    !isWaiver(value) &&
    !isCustom(value)
  )
}

/** The concrete answer for a question, unwrapping any attached note. */
export function primaryValue(
  id: string,
  answers: Record<string, unknown>,
): unknown {
  const value = answers[id]
  if (isWaiver(value) || isCustom(value)) return undefined
  return isNoted(value) ? value.value : value
}

/** The "additional information" note attached to an answer ('' if none). */
export function noteOf(id: string, answers: Record<string, unknown>): string {
  const value = answers[id]
  return isNoted(value) && typeof value.note === 'string' ? value.note : ''
}

function isMissing(value: unknown): boolean {
  return (
    value === undefined || value === null || value === '' ||
    (Array.isArray(value) && value.length === 0)
  )
}

/** True once a single question is answered, corrected, or validly waived. */
export function isAnswered(
  question: Question,
  answers: Record<string, unknown>,
): boolean {
  const value = answers[question.id]
  if (isWaiver(value)) return waiverReason(value).length > 0
  if (isCustom(value)) return customText(value).length > 0
  return !isMissing(primaryValue(question.id, answers))
}

/**
 * Return true once every required question has a concrete answer or a
 * waiver with a reason. This mirrors the backend completeness gate.
 */
export function allRequiredAnswered(
  questionnaire: Questionnaire,
  answers: Record<string, unknown>,
): boolean {
  return questionnaire.questions
    .filter((q) => q.required)
    .every((q) => isAnswered(q, answers))
}

export interface ProfileGroup {
  profile: ProfileMeta
  questions: Question[]
  answered: number
}

/**
 * Group questions by their audience profile, preserving first-seen
 * order and attaching per-group answered counts for progress display.
 */
export function groupByProfile(
  questionnaire: Questionnaire,
  answers: Record<string, unknown>,
): ProfileGroup[] {
  const metaById = new Map(questionnaire.profiles.map((p) => [p.id, p]))
  const order: string[] = []
  const byId = new Map<string, Question[]>()
  for (const question of questionnaire.questions) {
    const key = question.audience || 'general'
    if (!byId.has(key)) {
      byId.set(key, [])
      order.push(key)
    }
    byId.get(key)!.push(question)
  }
  return order.map((id) => {
    const questions = byId.get(id)!
    return {
      profile:
        metaById.get(id) ??
        { id, label: id === 'general' ? 'General' : titleCase(id), badge: 'sys' },
      questions,
      answered: questions.filter((q) => isAnswered(q, answers)).length,
    }
  })
}
