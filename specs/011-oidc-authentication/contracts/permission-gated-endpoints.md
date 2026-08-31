# Contract: permission gating on existing endpoints

How `auth_enabled` and the permission vocabulary (`data-model.md`) change
the behavior of kestrel's existing mutating endpoints. No request/response
*shape* changes for any of these routes — only whether a given caller is
allowed to reach the handler at all.

## Gating tiers

| Tier | Applies when `auth_enabled=True` | Applies when `auth_enabled=False` |
|---|---|---|
| Open | No auth required | No auth required (unchanged) |
| Authenticated-only | Valid bearer token required; any authenticated identity passes | No auth required (unchanged) |
| Permission-gated | Valid bearer token **and** the matching permission required | No auth required (unchanged) |
| Ticket-gated (`/events` only) | A valid, unused, unexpired connection ticket required (see `auth-sse-ticket.md`) | No auth required (unchanged) |

## Endpoint → tier mapping

| Method & path | Tier | Permission (if gated) |
|---|---|---|
| `POST /api/sessions` | Permission-gated | `sessions:write` |
| `POST /api/sessions/{id}/resume` | Permission-gated | `sessions:write` |
| `DELETE /api/sessions/{id}` | Permission-gated | `sessions:delete` |
| `POST /api/sessions/{id}/poll` | Authenticated-only | — |
| `GET /api/sessions` | Authenticated-only | — |
| `GET /api/sessions/{id}/events` | Ticket-gated | — |
| `GET /api/backends` | Authenticated-only | — |
| `GET /api/workflows`, `/{id}` | Authenticated-only | — |
| `GET /api/workflows/events`, `/{id}/events` | Ticket-gated | — |
| `POST /api/workflows/{id}/poll` | Authenticated-only | — |
| `DELETE /api/workflows/{id}` | Permission-gated | `workflows:delete` |
| `POST /api/workflows/{id}/cleanup` | Permission-gated | `workflows:cleanup` |
| `POST /api/workflows/{id}/rerun` | Permission-gated | `workflows:rerun` |
| `POST /api/workflows/{id}/approve` | Permission-gated | `workflows:approve` |
| `POST /api/workflows/{id}/reject` | Permission-gated | `workflows:reject` |
| `POST /api/workflows/{id}/reply` | Permission-gated | `workflows:respond` |
| `POST /api/workflows/{id}/answers` | Permission-gated | `workflows:respond` |
| `POST /api/workflows/{id}/answers/draft` | Permission-gated | `workflows:respond` |
| `POST /api/notifications/{id}/read` | Authenticated-only | — |
| `GET /api/notifications` | Authenticated-only | — |
| `GET /api/notifications/events` | Ticket-gated | — |
| `GET /api/identity` | Open (unchanged) | Open (unchanged) |
| `POST /api/github/webhook` | Open (unchanged — HMAC-gated per constitution, unrelated to user auth) | Open (unchanged) |
| `GET /livez`, `/readyz`, `/healthz` | Open (unchanged) | Open (unchanged) |
| `GET /api/auth/config` | Open (must be reachable pre-login) | Open |
| `POST /api/auth/sse-ticket` | Authenticated-only | N/A (not called) |
| `GET /api/auth/permissions` | Authenticated-only (200 w/ sentinel when disabled) | Open, sentinel response |

## Failure responses (permission-gated / authenticated-only tiers, auth enabled)

| Condition | Status | Notes |
|---|---|---|
| No `Authorization` header | 401 | |
| Token fails validation (expired, wrong `aud`/`iss`, bad signature) | 401 | Never leaks the raw validation exception message to the client. |
| Valid token, missing the required permission | 403 | Distinguishes "who are you" (401) from "you can't do that" (403) — the frontend's reauth-loop guard must not treat a 403 as a re-authentication trigger (re-authenticating a valid-but-unpermitted user changes nothing). |

## Test cases (per gated endpoint, representative — full matrix in `tasks.md`)

- `auth_enabled=False` → every endpoint above behaves exactly as it does on
  `master` today, no `Authorization` header sent or required.
- `auth_enabled=True`, no token → permission-gated and authenticated-only
  routes 401; open routes still 200.
- `auth_enabled=True`, valid token, user has the exact required permission
  → 200/normal response, identical body shape to today.
- `auth_enabled=True`, valid token, user lacks the required permission →
  403, no side effect occurs (the action is not partially performed).
- `auth_enabled=True`, valid token, authenticated-only route, user has zero
  mapped permissions → 200 (view/refresh actions don't need a permission).
