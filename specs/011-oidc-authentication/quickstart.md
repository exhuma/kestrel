# Quickstart: validating OIDC authentication end-to-end

Proves the feature works against a real Keycloak instance, covering both the
disabled-by-default regression check and the enabled/permission-gated path.
See `contracts/` for the exact request/response shapes and `data-model.md`
for config field names.

## Prerequisites

- kestrel running from source (`task backend`, `task frontend`) or the
  Docker image, per `docs/getting-started.md`.
- A Keycloak instance (self-hosted, or a disposable `docker run
  quay.io/keycloak/keycloak start-dev` for validation) with:
  - A realm (e.g. `kestrel`).
  - A **public** client (no client secret) with:
    - Standard flow (Authorization Code) enabled, PKCE required (`S256`).
    - Redirect URI matching kestrel's SPA origin
      (`http://localhost:5173/auth/callback` for `vite dev`, or the
      packaged image's origin) — the audience-mapper gotcha in
      `docs/auth.md` applies here: add a client audience mapper so access
      tokens carry this client as `aud`, or every token will fail
      `oidc_audience` validation.
  - At least two realm or client roles, e.g. `kestrel-admin` (full access)
    and `kestrel-viewer` (no mapped permissions).
  - Two test users, one in each role above.

## Step 1 — confirm disabled is a no-op (regression check)

```bash
# KESTREL_AUTH_ENABLED unset/false
curl -s http://localhost:8000/api/auth/config
# → {"enabled": false, "authority": "", "client_id": ""}
```

Open the SPA — it loads directly, no sign-in prompt, every button behaves
exactly as before this feature existed. This must pass before touching Step
2 at all; a regression here is a hard stop.

## Step 2 — configure and enable

```bash
export KESTREL_AUTH_ENABLED=true
export KESTREL_OIDC_AUTHORITY=http://localhost:8080/realms/kestrel
export KESTREL_OIDC_AUDIENCE=kestrel-spa
export KESTREL_OIDC_CLIENT_ID=kestrel-spa   # same value here; see data-model.md
```

Add to `config.toml` (pointed at by `KESTREL_CONFIG_FILE`):

```toml
[[role_mappings]]
role = "kestrel-admin"
permissions = [
  "sessions:write", "sessions:delete",
  "workflows:approve", "workflows:reject", "workflows:respond",
  "workflows:cleanup", "workflows:rerun", "workflows:delete",
]
```

(Deliberately no mapping for `kestrel-viewer` — proves the "authenticated,
zero permissions, still view-only" edge case from the spec.)

Restart kestrel (config is read once at startup, per existing convention).

```bash
curl -s http://localhost:8000/api/auth/config
# → {"enabled": true, "authority": "http://localhost:8080/realms/kestrel", "client_id": "kestrel-spa"}
```

## Step 3 — sign-in gate (User Story 1)

Open the SPA in a private/incognito window. Expected: immediate redirect to
Keycloak's login page before any kestrel UI renders. Sign in as the
`kestrel-admin` test user → redirected back to kestrel, normal UI visible.

## Step 4 — permission gating (User Story 2)

Still signed in as `kestrel-admin`: trigger a workflow cleanup, a session
delete, an approve/reject — each should succeed exactly as it did with auth
disabled.

Sign out, sign back in as the `kestrel-viewer` test user (no role mapping):
expected —

- Session and workflow lists/history are visible.
- Every mutating button (cleanup, rerun, delete, approve, reject,
  start/resume a session) is visibly disabled.
- Manually replaying one of those requests with `curl` and the viewer's
  access token returns `403`, never a silent no-op or a `500`.

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST http://localhost:8000/api/workflows/<id>/cleanup \
  -H "Authorization: Bearer <viewer-token>"
# → 403
```

## Step 5 — live updates keep working (User Story 2, scenario 4)

While signed in as either user, leave a workflow's detail view open and
trigger an update from another session/tab. Expected: the view updates in
real time with no perceptible difference from the disabled-auth experience
— confirms the SSE connection-ticket mechanism
(`contracts/auth-sse-ticket.md`) is working, not silently falling back to a
broken/no-op stream.

```bash
# Confirm the ticket mechanism directly:
TOKEN=<admin-access-token>
TICKET=$(curl -s -X POST http://localhost:8000/api/auth/sse-ticket \
  -H "Authorization: Bearer $TOKEN" | jq -r .ticket)
curl -N "http://localhost:8000/api/workflows/events?ticket=$TICKET"
# → SSE stream opens; a second curl reusing the same $TICKET must fail (one-time use)
```

## Step 6 — role mapping is configuration-only (User Story 3)

Without changing any code, add a mapping for `kestrel-viewer` granting only
`workflows:respond`, restart kestrel, sign in as that user again: they can
now answer a refine-interview question but still cannot cleanup/rerun/
delete. Confirms FR-005/SC-002.

## Step 7 — the reauth-loop guard (edge case / FR-015)

Sign in normally, then invalidate the session in a way that's a genuine
audience/issuer mismatch rather than a normal expiry (e.g. temporarily
point `KESTREL_OIDC_AUDIENCE` at a different value and restart, keeping the
already-signed-in browser tab open). Expected: the SPA attempts exactly one
automatic re-authentication, then shows a clear error dialog rather than
looping. Confirms `frontend/src/auth/reauthGuard.ts`'s circuit breaker.

## Done

All seven steps passing is the end-to-end acceptance bar for this feature —
they map directly onto the spec's User Stories 1–3, the edge cases, and
Success Criteria SC-001 through SC-005.
