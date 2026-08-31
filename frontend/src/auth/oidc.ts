/**
 * OIDC bootstrap: fetch the backend's runtime auth config, and — when
 * enabled — construct the `oidc-client-ts` `UserManager` and wire it into
 * the api client's existing (previously unused) `TokenProvider` seam.
 *
 * Runtime, not build-time, config (see `contracts/auth-config.md`): kestrel
 * ships one Docker image reused across deployments, and a specific Keycloak
 * realm/client baked in at build time would break that model.
 *
 * No vue-router: this app has exactly one meaningful page, so the
 * `/auth/callback` redirect target is handled manually in `main.ts` (see
 * `src/lib/deeplink.ts` for the same manual-URL-parsing idiom already used
 * here), not via router guards.
 */
import { UserManager, WebStorageStateStore, type User } from 'oidc-client-ts'
import { api, setTokenProvider } from '../api'
import type { AuthConfig } from '../types/auth'

export interface AuthState {
  enabled: boolean
  userManager: UserManager | null
}

let authState: AuthState | null = null
let cachedUser: User | null = null

function wireTokenProvider(userManager: UserManager): void {
  setTokenProvider({ getToken: () => cachedUser?.access_token ?? null })
  userManager.events.addUserLoaded((user) => {
    cachedUser = user
  })
  userManager.events.addUserUnloaded(() => {
    cachedUser = null
  })
}

/**
 * Resolve auth state once (subsequent calls return the cached result).
 *
 * @throws {Error} When `enabled: true` but the authority/client_id the
 *   backend reports is empty — a misconfigured-but-enabled setup must fail
 *   loudly, never silently degrade to "auth looks off".
 */
export async function initAuth(): Promise<AuthState> {
  if (authState) return authState

  const config = await api.get<AuthConfig>('/api/auth/config')
  if (!config.enabled) {
    authState = { enabled: false, userManager: null }
    return authState
  }
  if (!config.authority || !config.client_id) {
    throw new Error(
      'Authentication is enabled but misconfigured on the server ' +
        '(missing OIDC authority or client id). Contact the operator.',
    )
  }

  const userManager = new UserManager({
    authority: config.authority,
    client_id: config.client_id,
    redirect_uri: `${window.location.origin}/auth/callback`,
    post_logout_redirect_uri: window.location.origin,
    scope: 'openid email profile',
    response_type: 'code',
    automaticSilentRenew: true,
    // sessionStorage: survives a page reload within the tab (a long dev
    // session is common) without persisting indefinitely like localStorage
    // would (smaller XSS-persistence window). Documented trade-off — see
    // docs/auth.md.
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
  })
  wireTokenProvider(userManager)
  cachedUser = await userManager.getUser()

  authState = { enabled: true, userManager }
  return authState
}
