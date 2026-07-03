import type {
  InterviewEnvelope,
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

function isMissing(value: unknown): boolean {
  return (
    value === undefined || value === null || value === '' ||
    (Array.isArray(value) && value.length === 0)
  )
}

/** True once a single question is answered or validly waived. */
export function isAnswered(
  question: Question,
  answers: Record<string, unknown>,
): boolean {
  const value = answers[question.id]
  if (isWaiver(value)) return waiverReason(value).length > 0
  return !isMissing(value)
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
