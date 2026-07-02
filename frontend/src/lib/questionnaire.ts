import type { Questionnaire } from '../types/questionnaire'

/**
 * Parse a step deliverable as a structured questionnaire.
 *
 * Returns null for anything that isn't valid JSON shaped like a
 * questionnaire — free-text agent messages included — so callers
 * can fall back to the plain-text reply UI without special-casing.
 */
export function parseQuestionnaire(
  text: string | null,
): Questionnaire | null {
  if (!text) return null
  let data: unknown
  try {
    data = JSON.parse(text)
  } catch {
    return null
  }
  if (
    typeof data === 'object' && data !== null &&
    Array.isArray((data as Questionnaire).questions)
  ) {
    return data as Questionnaire
  }
  return null
}

function isMissing(value: unknown): boolean {
  return (
    value === undefined || value === null || value === '' ||
    (Array.isArray(value) && value.length === 0)
  )
}

/** Return true once every required question has a non-empty answer. */
export function allRequiredAnswered(
  questionnaire: Questionnaire,
  answers: Record<string, unknown>,
): boolean {
  return questionnaire.questions
    .filter((q) => q.required)
    .every((q) => !isMissing(answers[q.id]))
}
