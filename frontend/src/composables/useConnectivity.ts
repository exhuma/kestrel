import { ref } from 'vue'
import { API_BASE, api, setConnectivityHandler } from '../api'

const reachable = ref(true)
let registered = false
let retryTimer: ReturnType<typeof setInterval> | null = null

// Probe a cheap, side-effect-free health endpoint while unreachable, so the
// banner clears itself once the backend comes back. The app otherwise has no
// periodic polling left (push, not poll), so nothing else would ever retry.
function probe(): void {
  void api.get('/livez').catch(() => {
    // The connectivity handler (registered below) already updated
    // `reachable`; a failed probe needs no further handling here.
  })
}

function startRetry(): void {
  if (retryTimer) return
  retryTimer = setInterval(probe, 5000)
}

function stopRetry(): void {
  if (retryTimer) {
    clearInterval(retryTimer)
    retryTimer = null
  }
}

// Global backend-reachability signal, shown as a persistent banner instead
// of failing silently (every api.get/post/put/delete call feeds this, via
// the connectivity handler registered once below).
export function useConnectivity() {
  if (!registered) {
    registered = true
    setConnectivityHandler((ok) => {
      reachable.value = ok
      if (ok) stopRetry()
      else startRetry()
    })
  }
  return { reachable, apiBase: API_BASE }
}
