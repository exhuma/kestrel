/**
 * The `/auth/callback` redirect target — handled manually since this app
 * has no vue-router (see `oidc.ts`). Pure helpers only; the actual
 * `userManager.signinRedirectCallback()` orchestration lives in `main.ts`,
 * mirroring how `lib/deeplink.ts`'s pure parsing is tested while its
 * caller in `main.ts` isn't.
 */
const CALLBACK_PATH = '/auth/callback'

/** Whether the current path is the OIDC redirect target. */
export function isAuthCallbackPath(pathname: string): boolean {
  return pathname === CALLBACK_PATH
}

/**
 * Where to send the browser after a successful callback: the path stashed
 * in `signinRedirect({ state })` before leaving for the IdP, or `/` when
 * absent/malformed.
 */
export function resolveReturnTo(state: unknown): string {
  return typeof state === 'string' && state !== '' ? state : '/'
}
