/**
 * Deep-linking: open a specific run from a URL like `/?run=<id>`.
 *
 * Gate-notification comments (feature 002) carry such a link so a
 * maintainer lands directly on the run's active gate form. There is no
 * router; the run is opened by calling the workflows composable's
 * `select(id)`, which self-populates the detail view from a bare id.
 */

/** Extract the `run` query parameter from a URL search string, if present. */
export function runIdFromSearch(search: string): string | null {
  const id = new URLSearchParams(search).get('run')
  return id && id.trim() !== '' ? id : null
}

/**
 * If the search string names a run, select it. `select` is injected so this
 * stays pure and unit-testable (no window / composable coupling here).
 */
export function applyDeepLink(
  search: string,
  select: (id: string) => void,
): void {
  const id = runIdFromSearch(search)
  if (id) select(id)
}
