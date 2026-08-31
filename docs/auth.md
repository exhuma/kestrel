# OIDC authentication & permission-based authorization

Kestrel can require sign-in through your own OpenID Connect identity
provider (Keycloak, initially) and gate its state-mutating actions behind
permissions your identities are granted. This is entirely **opt-in**:
`KESTREL_AUTH_ENABLED` defaults to `false`, and disabled kestrel behaves
exactly as it always has — unauthenticated, loopback-bound.

See the constitution's "Fourth recorded exception" (Access model,
`.specify/memory/constitution.md`) for the binding architecture this
document configures, and `specs/011-oidc-authentication/` for the full
spec/plan/research behind it.

## 1. Create a Keycloak client

In your Keycloak realm, create a client for kestrel's SPA:

- **Client type**: OpenID Connect, **public** (no client secret — the SPA
  authenticates via Authorization Code + PKCE, never holds a secret).
- **Standard flow** enabled; **PKCE method**: `S256` (required).
- **Valid redirect URIs**: kestrel's own origin plus `/auth/callback`, e.g.
  `https://kestrel.example.com/auth/callback` (and
  `http://localhost:5173/auth/callback` for the `vite dev` flow, if you use
  it against this realm).
- **Valid post logout redirect URIs**: kestrel's origin, e.g.
  `https://kestrel.example.com/`.

### The audience-mapper gotcha

Keycloak access tokens do **not** carry the requesting client as the `aud`
(audience) claim by default. Kestrel validates `aud` against
`KESTREL_OIDC_AUDIENCE` on every request — without an explicit mapper,
every token fails validation and every request 401s.

Fix: on the client, add a **Client scope → Mapper → Audience** mapper
("Included Client Audience" = this client), or add an audience mapper to a
default client scope shared by all clients. Confirm by decoding a token
(e.g. at [jwt.io](https://jwt.io)) and checking `aud` matches
`KESTREL_OIDC_AUDIENCE`.

## 2. Create realm and client roles

Keycloak reports two kinds of role kestrel can map:

- **Realm roles** — organization-wide (Realm settings → Realm roles).
- **Client roles** — scoped to this one client (Clients → your client →
  Roles).

Assign roles to users (or groups) as you normally would. Kestrel treats a
realm role name as-is and a client role name namespaced as
`<client_id>:<role>` — see step 4.

## 3. Configure kestrel

| Variable | Required | Purpose | Default |
| --- | --- | --- | --- |
| `KESTREL_AUTH_ENABLED` | No | Master opt-in switch | `false` |
| `KESTREL_OIDC_AUTHORITY` | Yes (if enabled) | Realm issuer base URL, e.g. `https://keycloak.example.com/realms/kestrel` | _(empty)_ |
| `KESTREL_OIDC_AUDIENCE` | Yes (if enabled) | The client id, validated against the token's `aud` | _(empty)_ |
| `KESTREL_OIDC_ISSUER` | No | Validated against `iss`; defaults to `KESTREL_OIDC_AUTHORITY` | _(unset)_ |
| `KESTREL_OIDC_CLIENT_ID` | No | Which client's roles to read for client-role extraction; defaults to `KESTREL_OIDC_AUDIENCE` | _(unset)_ |
| `KESTREL_OIDC_PROVIDER` | No | Selects the role-extraction adapter | `keycloak` |

`KESTREL_AUTH_ENABLED=true` with an incomplete authority/audience/client-id
doesn't crash startup — it logs a loud warning and every request is
rejected until configured, the same "misconfigured should be loud, not
silent" posture as the rest of kestrel's config surface.

## 4. Map roles to permissions

Application code never gates on Keycloak role names directly — only on a
fixed, kestrel-owned permission vocabulary. You map your roles onto it in
`config.toml` (see `config.toml.example` for a commented-out starting
point):

```toml
[[role_mappings]]
role = "kestrel-admin"                # a realm role
permissions = [
  "sessions:write", "sessions:delete",
  "workflows:approve", "workflows:reject", "workflows:respond",
  "workflows:cleanup", "workflows:rerun", "workflows:delete",
]

[[role_mappings]]
role = "kestrel-spa:approver"         # a client role, namespaced client_id:role
permissions = ["workflows:approve", "workflows:reject", "workflows:respond"]
```

The permission vocabulary is fixed and validated at startup — an unknown
string in `permissions` fails fast rather than silently granting nothing.
One permission gates one kind of consequential action:

| Permission | Gates |
| --- | --- |
| `sessions:write` | Start or resume a session |
| `sessions:delete` | Abandon a session |
| `workflows:approve` | Approve a gate |
| `workflows:reject` | Reject a gate (with or without feedback) |
| `workflows:respond` | Answer the refine interview (reply, submit/draft answers) |
| `workflows:cleanup` | Fully reset a workflow (drop local work, delete its branch) — the most destructive action |
| `workflows:rerun` | Discard a run and restart it (private/fixture-sourced runs only) |
| `workflows:delete` | Abandon a workflow |

Every other route (viewing sessions/workflows, polling, marking a
notification read) only requires a valid, authenticated identity — no
specific permission. A signed-in user with no role mapping at all is a
normal, expected state: they can view everything, mutate nothing.

Role mappings, like the rest of `config.toml`, are read once at startup —
restart kestrel after editing them.

## How sign-in works

When enabled, the SPA fetches `GET /api/auth/config` at page load (a
runtime, not build-time, config — kestrel ships one Docker image reused
across deployments) to learn the authority/client id, then performs
Authorization Code + PKCE directly against your IdP. The backend validates
each request's bearer token against your IdP's JWKS — it never
participates in the sign-in flow itself.

### Live views and the SSE-ticket mechanism

Browser `EventSource` (used by the workflow list/detail, session detail,
and notification live streams) cannot set an `Authorization` header. Those
four streams instead authenticate via a short-lived (~30 second),
single-use, kestrel-minted connection ticket: the SPA calls
`POST /api/auth/sse-ticket` (a normal, bearer-token-authenticated request)
immediately before opening each stream, and appends the returned ticket as
`?ticket=...`. The ticket is valid only to establish that one connection —
once open, the stream behaves exactly as it does with auth disabled. This
keeps a credential's exposure window to seconds instead of a token's full
lifetime, and needs no cookies or `SameSite` configuration, working the
same way whether kestrel is served same-origin (the packaged image) or the
SPA is on a different origin (the `vite dev` flow).

## Out of scope: task ingestion

Kestrel's permission model governs *who may act on a run once it
exists* — it does not, and will not, evaluate who may create or update a
ticket in an external tracker. Who can create a GitHub issue or file a Jira
RFC that kestrel picks up is entirely the responsibility of that source's
own access control: a GitHub label/repo allow-list, a scoped JQL query.
Document and enforce that boundary in Jira/GitHub itself, not here.
