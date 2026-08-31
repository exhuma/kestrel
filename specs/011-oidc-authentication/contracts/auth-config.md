# Contract: `GET /api/auth/config`

Runtime bootstrap endpoint the SPA calls once at page load to learn how (or
whether) to set up OIDC sign-in. See `research.md` §5 for why this is a
runtime endpoint rather than a build-time `VITE_OIDC_*` variable.

## Request

No parameters. No authentication required (it must be callable *before* the
visitor has signed in — this is how the frontend learns whether sign-in is
even needed).

## Response — 200 OK

```json
{
  "enabled": true,
  "authority": "https://keycloak.example.com/realms/kestrel",
  "client_id": "kestrel-spa"
}
```

| Field | Type | Notes |
|---|---|---|
| `enabled` | `bool` | Mirrors `Settings.auth_enabled`. |
| `authority` | `str` | `Settings.oidc_authority`. `""` when `enabled=false`. |
| `client_id` | `str` | `Settings.oidc_audience` (the public client id). `""` when `enabled=false`. |

No secret is ever present in this response — `client_id` is a public OIDC
client identifier, not a credential, and a public client never holds a
`client_secret` in the first place (PKCE replaces it).

## Frontend contract

- Called once at SPA boot (`frontend/src/auth/oidc.ts`), before anything
  else that depends on auth state.
- `enabled: false` (or the endpoint being unreachable, e.g. during very
  early local dev) → the app mounts exactly as it does today, no OIDC
  machinery constructed.
- `enabled: true` but `authority` or `client_id` empty → **fail loudly**
  (surface a blocking error), never silently degrade to "auth looks off"
  (per `module-runtime-config-spa`'s fail-loud rule and this feature's own
  design decision).

## Test cases

- `auth_enabled=False` → `{"enabled": false, "authority": "", "client_id": ""}`.
- `auth_enabled=True` with authority/audience configured → the three fields
  populated correctly from `Settings`.
- No `Authorization` header required — confirm a completely unauthenticated
  call still succeeds (this endpoint is never behind `require_permission`
  or even `get_current_claims`).
