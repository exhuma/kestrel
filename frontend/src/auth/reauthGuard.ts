/**
 * The reauth-loop-guard circuit breaker.
 *
 * A 401 usually means the session expired, and one redirect to the IdP
 * fixes it. But a token can be cryptographically valid yet still rejected
 * by the resource server (wrong `aud`/`iss`, insufficient scope) — in that
 * case re-authenticating returns the *same* rejected token, so a bare
 * "401 -> signinRedirect" handler loops forever (worse with
 * `automaticSilentRenew`, which silently refetches the same bad token).
 *
 * Bounded to one redirect per failure episode via a `sessionStorage`
 * counter (it must survive the full-page redirect round-trip), reset on
 * the next successful response.
 */
import { ref } from 'vue'

const ATTEMPT_KEY = 'kestrel.reauthAttempts'

/** Surfaced by the app shell as a blocking dialog. */
export const authError = ref<string | null>(null)

// Collapses the burst of parallel 401s one page load can produce. Resets
// on every fresh page load, which is when a new attempt is wanted.
let redirectInFlight = false

function attempts(): number {
  return Number(sessionStorage.getItem(ATTEMPT_KEY) ?? '0')
}

/**
 * Handle a 401: redirect once per failure episode, then stop.
 *
 * @param signinRedirect - Triggers the IdP redirect; injected so this stays
 *   testable without a real `UserManager`.
 */
export function handleUnauthorized(signinRedirect: () => void): void {
  if (redirectInFlight) return
  if (attempts() >= 1) {
    // A fresh token was still rejected -> stop, do not redirect again.
    sessionStorage.removeItem(ATTEMPT_KEY)
    authError.value =
      'Your session could not be authenticated (this can happen when ' +
      'the server and identity provider are misconfigured together). ' +
      'Try signing in again, or contact the operator if it persists.'
    return
  }
  sessionStorage.setItem(ATTEMPT_KEY, String(attempts() + 1))
  redirectInFlight = true
  signinRedirect()
}

/** Wire to a success seam on the api client (called on any 2xx). */
export function notifyAuthSuccess(): void {
  sessionStorage.removeItem(ATTEMPT_KEY)
}
