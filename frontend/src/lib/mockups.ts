/**
 * Answer-dict key carrying the optional feedback for a mockup.
 *
 * Mirrors the backend `mockup_key` (`app/mockups.py`): mockup feedback
 * rides the same `answers` map as question answers, under a `mockup:<name>`
 * key the backend validator recognises.
 */
export function mockupKey(name: string): string {
  return `mockup:${name}`
}
