import { ref } from 'vue'
import { api } from '../api'
import type { Identity } from '../types/identity'

const identity = ref<Identity | null>(null)
let registered = false

// Global identity signal, fetched once regardless of how many components
// call this composable. A failed fetch (or an all-null response) just
// leaves `identity` at null — no oauth2-proxy in front (e.g. local dev) is
// a normal state, not a failure to surface.
export function useIdentity() {
  if (!registered) {
    registered = true
    void api
      .get<Identity>('/api/identity')
      .then((i) => {
        identity.value = i
      })
      .catch(() => {
        // Backend unreachable or no proxy headers — identity stays null.
      })
  }
  return { identity }
}
