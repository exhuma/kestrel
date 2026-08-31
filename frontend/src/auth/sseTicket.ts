/**
 * Build an authenticated EventSource URL.
 *
 * Browser `EventSource` cannot set an `Authorization` header, so when auth
 * is enabled the four SSE streams (workflow list/detail, session detail,
 * notifications) authenticate via a short-lived, single-use connection
 * ticket instead — see `contracts/auth-sse-ticket.md`. Disabled, the URL
 * is returned unchanged.
 */
import { api, API_BASE } from '../api'
import { initAuth } from './oidc'

interface TicketResponse {
  ticket: string
}

/**
 * @param path - The API path (e.g. `/api/workflows/events`), without
 *   `API_BASE`.
 * @returns The full URL to open an `EventSource` against.
 */
export async function eventSourceUrl(path: string): Promise<string> {
  const auth = await initAuth()
  if (!auth.enabled) return `${API_BASE}${path}`
  const { ticket } = await api.post<TicketResponse>('/api/auth/sse-ticket')
  return `${API_BASE}${path}?ticket=${encodeURIComponent(ticket)}`
}
