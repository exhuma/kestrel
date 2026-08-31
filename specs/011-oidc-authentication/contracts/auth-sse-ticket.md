# Contract: `POST /api/auth/sse-ticket`

Mints the short-lived, single-use credential the four SSE (`/events`)
streams use in place of an `Authorization` header, which browser
`EventSource` cannot set. See `research.md` §6 and `data-model.md`'s
Connection ticket section for the full rationale and shape.

## Request

`POST /api/auth/sse-ticket`, no body. Requires a valid
`Authorization: Bearer <token>` header when `auth_enabled=True` — this
endpoint is called via the normal authenticated `fetch`-based `api` client,
**not** via `EventSource`.

When `auth_enabled=False`: this endpoint is not needed and the frontend
never calls it (the four `EventSource` URLs are used unmodified, exactly as
today).

## Response — 200 OK

```json
{ "ticket": "eyJhbGciOiJIUzI1NiIs..." }
```

A compact, HS256-signed, opaque string. The frontend appends it verbatim:
`?ticket=<value>`.

## Response — 401 Unauthorized

Same shape as any other protected endpoint, when the caller's own bearer
token is missing/invalid.

## Ticket validation contract (consumed by the four `/events` routes)

| Check | Failure behavior |
|---|---|
| Signature valid (HS256, server's in-process secret) | Reject connection (`401`/close before streaming starts) |
| `exp` not passed (~30s from mint) | Reject |
| `jti` not previously seen | Reject (one-time use — replay of a URL captured from logs/history fails) |

On success: the connection's effective identity/permissions are those
embedded in the ticket at mint time (a snapshot — the ticket is not
re-resolved against live role mappings). The stream then behaves exactly as
it does today; no further ticket/token validation occurs for the life of
that one connection.

## Test cases

- Mint → immediately use → stream opens normally.
- Reused ticket (same `jti` twice) → second use rejected.
- Expired ticket (used after ~30s) → rejected.
- Tampered ticket (signature invalid) → rejected.
- Minting itself requires the caller's own valid bearer token when auth is
  enabled; an unauthenticated mint attempt gets 401, same as any other
  authenticated endpoint.
