import { ref } from 'vue'
import { api } from '../api'
import type { AuthPermissions } from '../types/auth'

/** See the backend's ALL_PERMISSIONS_SENTINEL (app.auth.permissions). */
const ALL_PERMISSIONS_SENTINEL = '*'

const permissions = ref<Set<string>>(new Set())
let registered = false

// Global permissions signal, fetched once regardless of how many components
// call this composable — the single source of truth for which mutating
// controls to show enabled (constitution Principle II: the backend is the
// real enforcer, this is UX-only). Before the fetch resolves (and if it
// fails), `can()` defaults to false — the safe default is "no", never
// "yes" while we don't yet know.
export function usePermissions() {
  if (!registered) {
    registered = true
    void api
      .get<AuthPermissions>('/api/auth/permissions')
      .then((p) => {
        permissions.value = new Set(p.permissions)
      })
      .catch(() => {
        // Backend unreachable — permissions stay empty (safe default).
      })
  }

  function can(permission: string): boolean {
    return (
      permissions.value.has(ALL_PERMISSIONS_SENTINEL) ||
      permissions.value.has(permission)
    )
  }

  return { can }
}
