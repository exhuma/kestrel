# Contract: Health HTTP/SSE API

Mirrors `backend/app/routers/notifications.py`'s shape exactly (list +
SSE stream + one mutating action that ticks the bus).

## `GET /api/health`

One-shot fetch of every registered entry's current state — used for the
initial render before the SSE stream's first frame arrives, and as a
fallback if `EventSource` isn't available.

**Response** `200`, `list[HealthOut]`:

```json
[
  {"name": "github", "state": "healthy", "checked_at": "2026-09-08T10:00:00"},
  {"name": "jira", "state": "unhealthy", "checked_at": "2026-09-08T10:00:00"},
  {"name": "gitlab", "state": "unknown", "checked_at": null}
]
```

Order is stable (registration order at bootstrap — data-model.md).

## `GET /api/health/events`

`text/event-stream`. Emits the full current list (same shape as the
plain `GET`) immediately on connect, and again every time any entry's
`state` changes (background cycle tick or a manual refresh completing).
Idle periods send the existing keepalive comment (`app/sse.py`,
`HEARTBEAT_SECONDS`).

## `POST /api/health/{name}/refresh`

Triggers an immediate recheck of the named entry (FR-004), deduped
against any check already in flight for that entry (FR-005,
research.md R7).

- `404` if `name` does not match any registered entry.
- `202` (accepted) otherwise — the response does not wait for the check
  to complete; the caller observes the result via the SSE stream (or a
  subsequent `GET /api/health`), the same "fire the action, watch the
  stream for the outcome" shape `POST /api/notifications/{id}/read`
  already establishes.

## Frontend types (`frontend/src/types/`)

New file mirroring `types/notifications.ts`:

```ts
export type HealthState = 'unknown' | 'healthy' | 'unhealthy'

export interface SourceHealth {
  name: string
  state: HealthState
  checked_at: string | null
}
```

Per Constitution Principle I (Contract Fidelity), this MUST stay in sync
with the backend's `HealthOut` schema field-for-field.
