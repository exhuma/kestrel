# Phase 0 Research: OIDC authentication & permission-based authorization

All technical unknowns below were resolved before this spec/plan existed, via
full codebase exploration (backend layering, the import-linter contract, the
existing `TaskSource`/`Backend` protocol+registry pattern, the frontend's
`api/index.ts` seams, absence of vue-router, the `EventSource`/SSE-auth gap)
and Quartermaster kit research (`module-auth-oidc`, `-python`, `-vue`,
`module-oidc-user-provisioning`, `module-runtime-config-spa`), captured in
`/home/claude/.claude/plans/we-need-to-deal-shimmering-quasar.md` and
validated by a dedicated design-review pass. No `NEEDS CLARIFICATION` markers
remain in the spec; this document records the resulting decisions in the
plan-template's Decision/Rationale/Alternatives format rather than
re-researching them.

## 1. OIDC flow strategy

**Decision**: "True OIDC" (Option A per `module-auth-oidc`) — the SPA
performs Authorization Code + PKCE directly against Keycloak's standard
discovery document; no backend token-exchange endpoint.

**Rationale**: Keycloak exposes a standard
`/.well-known/openid-configuration` document, so no upstream-normalization
adapter is needed. This keeps the backend a pure, stateless resource server.

**Alternatives considered**: Option B (a backend `/auth/exchange` endpoint
normalizing a non-OIDC provider like GitHub/Twitter) — rejected, Keycloak
is a real OIDC provider so the extra indirection buys nothing.

## 2. Backend token validation library

**Decision**: `pyjwt[crypto]` with a cached `PyJWKClient` resolved from the
IdP's discovery document.

**Rationale**: The project's kit conventions (`module-auth-oidc-python`,
`module-library-preferences`) standardize on `pyjwt`; `PyJWKClient` handles
unknown-`kid` refetching automatically, so no bespoke JWKS-cache-invalidation
logic is needed.

**Alternatives considered**: `python-jose`, `authlib` — rejected per kit
convention (one JWT library, not several).

## 3. Role extraction pluggability

**Decision**: A `RoleExtractor` `Protocol` + a per-provider registry keyed
by `KESTREL_OIDC_PROVIDER` (default `"keycloak"`), mirroring the existing
`TaskSource`/`Backend` protocol+registry pattern already in this codebase
(`backend/app/ports.py`, `backend/app/backends/registry.py`).

**Rationale**: The codebase already has a proven, structural-typing
(no ABC inheritance) pattern for "pick an adapter by a config-tagged type
string, fail fast on an unknown one." Reusing it means the OIDC feature
introduces zero new architectural idiom, and a second IdP later is one new
adapter file plus a registry entry.

**Alternatives considered**: A single hardcoded Keycloak-only extraction
function — rejected; the spec (FR-012) requires that adding another IdP not
require redesigning the permission model.

## 4. User provisioning

**Decision**: None. Permissions are recomputed from validated token claims
+ the `role_mappings` config on every request; no `User` table, no
`AuthIdentity` table, no lazy-provisioning-on-first-login flow.

**Rationale**: `module-oidc-user-provisioning`'s own scoping test is "a
resource server needs a local user row to own data and carry app-level
roles." Kestrel has neither: no per-user data exists anywhere in its schema
today, and this feature's app-level "roles" (permissions) are computed
per-request, not carried on a persisted row. Adding one would be exactly the
speculative generalization the constitution's Principle IV prohibits.

**Alternatives considered**: Adopting the kit's lazy-provisioning pattern
(a `users` + `auth_identities` table pair) — rejected; no present need, and
it would introduce the exact per-user-data-ownership the constitution
amendment explicitly says this feature must not introduce.

## 5. Runtime OIDC client configuration

**Decision**: A new `GET /api/auth/config` endpoint (`{enabled, authority,
client_id}`), fetched by the SPA at boot, rather than build-time
`VITE_OIDC_*` environment variables.

**Rationale**: Kestrel ships one Docker image reused across deployments
(`docs/qm-alignment.md` already records this exact reasoning for
`VITE_API_BASE=""` same-origin dispatch). OIDC authority/client_id are
genuinely per-deployment (the operator's own Keycloak realm) and don't have
that same escape hatch, so baking them into the image at build time would
break build-once-run-anywhere. The backend already serves dynamic,
request-time content, so a small runtime-config endpoint is simpler here
than standing up `module-runtime-config-spa`'s canonical
entrypoint-`envsubst`-into-`config.js` mechanism for one config blob — a
second, precedented instance of the same kind of deviation already on
record.

**Alternatives considered**: Build-time `VITE_OIDC_*` (the kit's literal
default) — rejected, breaks build-once. The full `module-runtime-config-spa`
mechanism (`window.__APP_CONFIG__` + entrypoint templating) — rejected as
disproportionate for one small, non-secret config blob when a simpler,
already-dynamic backend endpoint does the same job.

## 6. Authenticated Server-Sent Events

**Decision**: A short-lived (~30s), single-use, kestrel-minted connection
ticket (`POST /api/auth/sse-ticket`, itself authenticated normally),
appended as `?ticket=...` only on the four `/events`-suffixed routes.
Signed with an in-process HS256 secret generated at kestrel startup; a
bounded in-memory used-`jti` set enforces one-time use.

**Rationale**: Browser `EventSource` cannot set an `Authorization` header —
this is a hard platform limitation, not a design choice. The developer
explicitly flagged that kestrel intends to grow beyond single-user, ruling
out simply putting a long-lived access token in the URL (query strings leak
into server access logs and browser history). A short-lived, single-use
ticket bounds exposure to seconds and works identically across both
required run modes (same-origin packaged image; cross-origin
`vite dev` + `:8000` backend) with no cookie/`SameSite` complications an
httpOnly-cookie alternative would introduce in the cross-origin dev flow.
An in-process signing secret (vs. a persisted one) is sufficient because
tickets are meaningless after ~30s and connections don't need to survive a
backend restart mid-mint.

**Alternatives considered**: Raw access token as a query parameter —
rejected (long exposure window, explicitly flagged as a real trade-off, not
accepted). An httpOnly `SameSite` session cookie set by a dedicated
endpoint — rejected; correct for same-origin production but adds real
complexity (cross-origin cookie rules over plain `http://localhost` during
`vite dev`) that the ticket approach avoids entirely, for no offsetting
benefit at kestrel's scale. Rewriting all 4 `EventSource` call sites as
fetch-based `ReadableStream` readers — rejected as more invasive (rewrites
each composable's reconnect/backoff logic) for a problem the ticket
approach solves without touching that logic.

## 7. Frontend routing for the OIDC callback

**Decision**: Manual `window.location.pathname` handling in
`frontend/src/main.ts` for `/auth/callback`, not a new vue-router
integration.

**Rationale**: The frontend currently has zero router (confirmed by
exploration: no `vue-router` dependency, navigation is a local
`ref<'sessions'|'workflows'>` toggle in `App.vue`). The kit's default
two-route (`/auth/callback` + `/auth/logout` + `router.beforeEach` guard)
pattern assumes a router that would be introduced solely for this feature,
disproportionate for an app with exactly one meaningful page. The existing
`frontend/src/lib/deeplink.ts` already hand-parses `window.location.search`
for a `?run=<id>` deep link — the same manual-URL-handling idiom already
exists in this codebase and is extended, not invented.

**Alternatives considered**: Introducing `vue-router` — rejected per YAGNI
(constitution Principle IV); would add a new architectural concept (routes,
guards) for a single-page app that doesn't otherwise need one.

## 8. Permission vocabulary

**Decision**: Eight permissions, one per genuinely consequential mutating
action: `sessions:write` (start, resume), `sessions:delete`,
`workflows:approve`, `workflows:reject`, `workflows:respond` (reply/
answers/answers-draft), `workflows:cleanup`, `workflows:rerun`,
`workflows:delete`. Session `poll` and notification mark-read stay
just-authenticated (no dedicated permission).

**Rationale**: Validated against the actual router surface
(`backend/app/routers/sessions.py`, `.../workflows.py`) one-for-one.
`workflows:respond` is kept distinct from `workflows:reject` rather than
folded together — advancing a refine interview is semantically closer to
approving than rejecting, and reusing `reject` for a non-rejecting action
would be a mapping-file footgun for an operator reading `config.toml`.

**Alternatives considered**: A single `workflows:write` covering
approve/reject/respond/cleanup/rerun/delete — rejected as too coarse; an
operator plausibly wants to grant "answer refine questions" without also
granting "discard and restart a run's history." Per-endpoint permissions
(finer than per-action) — rejected as unnecessary granularity with no
identified use case.

## 9. Import-linter layering for `app/auth/permissions.py`

**Decision**: `backend/app/auth/permissions.py` is a leaf module with no
import of `app.config`; `Settings._validate_role_mappings` imports *from*
`permissions.py`, never the reverse.

**Rationale**: `backend/app/config.py` needs the permission vocabulary to
validate `role_mappings` at startup (mirroring the existing
`_validate_step_backends` fail-fast pattern). If `permissions.py` imported
`Settings` back, that would be an import cycle the repo's import-linter
contract (`app.routers -> app.services -> app.persistence`, downward only)
would catch — `permissions.py` sits outside that chain entirely and must
stay a true leaf, like `app/config.py` itself.

**Alternatives considered**: Defining the vocabulary inline in `config.py`
— rejected; couples the permission vocabulary (used by routers, the
frontend-facing `/api/auth/permissions` endpoint, and tests) to the
settings module for no reason, and forecloses `permissions.py` staying
reusable/leaf.

## Rejected simpler alternatives (Complexity Tracking context)

Per Principle IV, these were considered and explicitly rejected as
unnecessary for the feature as specified — recorded here so a future reader
doesn't wonder why they're absent:

- **`module-dev-auth-bypass`** (a dev-only HS256 bypass token mechanism) —
  not adopted. When auth is disabled entirely (the default), today's
  fully-open local-dev behavior already covers running without an IdP;
  backend tests mock the JWKS endpoint per `module-auth-oidc-python`'s own
  testing guidance rather than needing a bypass. Revisit only if manual QA
  against a real Keycloak becomes a real friction point.
- **vue-router** — see §7 above.
- **User provisioning / a `users` table** — see §4 above.
