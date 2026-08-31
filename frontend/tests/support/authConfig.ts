// Shared helper for composable tests exercising an EventSource-opening
// function (start/select/startList/watchEvents/streamSession): those now
// call eventSourceUrl(), which resolves auth state via a GET
// /api/auth/config request before doing anything else. Most of those
// tests aren't about auth at all, so they just need that first request
// answered with "disabled" — this is the one place that response shape
// lives, rather than duplicated per test file.
import { vi } from 'vitest'

export function stubDisabledAuthConfig(): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({ enabled: false, authority: '', client_id: '' }),
          { status: 200 },
        ),
    ),
  )
}
