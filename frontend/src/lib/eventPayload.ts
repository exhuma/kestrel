/**
 * What a board event's payload has to say to the operator (feature 043,
 * FR-001/FR-002).
 *
 * The backend always sends the payload as a JSON string, almost always
 * `{}`. The only non-empty shape it emits today is `{"detail": "…"}`,
 * a short, safe reason (`record_problem`, `retries.detail_of`). Anything
 * else is shown as labelled values so a new shape still reads, and raw
 * JSON is never shown.
 */

export type PayloadView =
  | { kind: 'detail'; detail: string; fields: [string, string][] }
  | { kind: 'fields'; fields: [string, string][] }

function parseObject(raw: string): Record<string, unknown> | null {
  try {
    const value: unknown = JSON.parse(raw)
    if (value === null || typeof value !== 'object' || Array.isArray(value)) {
      return null
    }
    return value as Record<string, unknown>
  } catch {
    return null
  }
}

function asText(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value)
}

/** `null` when there is nothing worth showing: empty, `{}`, unreadable,
 *  or not an object. */
export function parsePayload(
  raw: string | null | undefined,
): PayloadView | null {
  const object = raw ? parseObject(raw) : null
  if (!object) return null
  const { detail, ...rest } = object
  const fields = Object.entries(rest).map(([key, value]): [string, string] => [
    key,
    asText(value),
  ])
  if (typeof detail === 'string' && detail.trim() !== '') {
    return { kind: 'detail', detail, fields }
  }
  if (detail !== undefined && typeof detail !== 'string') {
    fields.unshift(['detail', asText(detail)])
  }
  return fields.length > 0 ? { kind: 'fields', fields } : null
}
