/** The SPA's runtime OIDC bootstrap config, fetched at page load. */
export interface AuthConfig {
  enabled: boolean
  authority: string
  client_id: string
}

/**
 * The caller's resolved identity + permission set.
 *
 * `permissions` is `["*"]` (see the backend's `ALL_PERMISSIONS_SENTINEL`)
 * when auth is disabled, meaning "every permission" — treat its presence
 * as always-true rather than checking against a known vocabulary.
 */
export interface AuthPermissions {
  sub: string | null
  email: string | null
  preferred_username: string | null
  permissions: string[]
}
