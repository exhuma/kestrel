# Implementation Plan: OIDC authentication & permission-based authorization

**Branch**: `011-oidc-authentication` | **Date**: 2026-08-31 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/011-oidc-authentication/spec.md`

## Summary

Kestrel gains an opt-in (`KESTREL_AUTH_ENABLED`, default `false`) authentication
and authorization layer: the FastAPI backend becomes a stateless OIDC resource
server validating bearer tokens against an operator-configured identity
provider's JWKS; the Vue SPA becomes the public OIDC client, performing
Authorization Code + PKCE. IdP roles (Keycloak realm and client roles alike)
are extracted through a pluggable, provider-keyed port and mapped, via an
operator-authored `config.toml` list, onto a fixed, app-owned permission
vocabulary — application code gates only on those permissions. Eight
consequential mutating actions (session start/resume/delete; workflow
approve/reject/respond/cleanup/rerun/delete) require the matching permission
when auth is enabled; everything else requires only a valid identity. No new
database tables or user provisioning — permissions are recomputed from token
claims on every request. Browser `EventSource` (used by all 4 live SSE
streams) can't carry an `Authorization` header, so those streams authenticate
via a short-lived, single-use, kestrel-minted connection ticket instead.
Disabled (the default), kestrel is unchanged.

## Technical Context

**Language/Version**: Python 3.12 (backend, `uv`-managed), TypeScript / Vue 3
(frontend, Vite/npm)

**Primary Dependencies**: `pyjwt[crypto]` (new, backend — JWKS/RS256 token
validation), `oidc-client-ts` (new, frontend — Authorization Code + PKCE);
reuses the existing FastAPI/Pydantic/SQLAlchemy stack and Vuetify UI

**Storage**: SQLite via SQLAlchemy 2.x / Alembic (existing) — **no schema
change**. Permissions are recomputed statelessly from token claims + config
on every request; no `User` table, no provisioning.

**Testing**: pytest (backend; `respx` or `pytest-httpserver` to mock the
JWKS endpoint — never a real IdP call in tests), vitest (frontend; mocked
`UserManager`)

**Target Platform**: Linux server (bundled Docker image) and the
run-from-source developer flow (`uv` / `vite`) — both MUST keep working
per the constitution's Run modes constraint

**Project Type**: Web application (FastAPI backend + Vue/Vuetify SPA)

**Performance Goals**: No new perf target. JWKS validation is
cached (`PyJWKClient`, refetches only on an unknown `kid`); negligible
overhead at kestrel's personal/small-team request volume.

**Constraints**: Opt-in — disabled is a byte-for-byte behavioral no-op.
Stateless — no new persisted state. `backend/app/auth/permissions.py` MUST
stay a leaf module (no `app.config` import) to satisfy the import-linter
layering contract. All new/changed modules MUST stay within `task quality`'s
structural limits (complexity ≤10, module ≤500 lines, etc. — see AGENTS.md).

**Scale/Scope**: One IdP initially (Keycloak), pluggable for more later; 8
permissions; a handful of trusted identities, not internet-scale multi-tenant
auth.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Contract Fidelity** — PASS. New backend response shapes
  (`GET /api/auth/config`, `GET /api/auth/permissions`) get matching
  TypeScript types under `frontend/src/types/`, per the existing
  business-object-typing convention. No existing type's shape changes.
- **II. Layered, Backend-Owned Architecture** — PASS. Permission enforcement
  lives entirely in backend dependencies (`require_permission`); the
  frontend's `usePermissions().can(...)` gating is UX-only, never the sole
  enforcer. No new tables, no `Base.metadata.create_all()`, no raw DDL — this
  feature is schema-free by design.
- **III. Test-First Discipline** — PASS (obligation carried into
  `/speckit.tasks`/implementation). Every new auth code path (token
  validation, role extraction, permission resolution, ticket issuance, the
  8 gated endpoints, the frontend reauth-loop guard) ships with a test
  first; no test hits a real IdP or a production database.
- **IV. Deliberate Simplicity & Single-Tenant Scope** — PASS. This feature
  *is* the one recorded, deliberate exception the v2.0.0 amendment
  authorizes — it stays inside that exception's stated bounds: off by
  default, no per-user data ownership, no new tables, permissions
  recomputed per-request. No further justification needed beyond the
  amendment already on this branch.
- **V. Kit-Aligned Consistency & Observability** — PASS. Built from
  `module-auth-oidc`/`-python`/`-vue` kit guidance (PKCE, JWKS caching,
  the reauth-loop-guard circuit breaker); UI additions (login/logout
  control, disabled-button states) source colors from the existing Vuetify
  theme, no hard-coded hex.

No violations. Nothing in this feature requires the Complexity Tracking
table — see the "Rejected simpler alternatives" subsection of `research.md`
for the specific simplifications already chosen (no user provisioning, no
dev-auth-bypass, no vue-router).

**Post-design re-check** (after Phase 1 — `data-model.md`, `contracts/`,
`quickstart.md`): unchanged, still PASS on all five principles. Phase 1
confirmed no new database table, no request/response shape change on any
existing endpoint (only new endpoints and new authorization checks on
existing ones), and no new frontend architectural concept beyond what
`research.md` already scoped (no router, no state-management library
change).

## Project Structure

### Documentation (this feature)

```text
specs/011-oidc-authentication/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/             # Phase 1 output
│   ├── auth-config.md
│   ├── auth-permissions.md
│   ├── auth-sse-ticket.md
│   └── permission-gated-endpoints.md
└── tasks.md              # Phase 2 output (/speckit-tasks — not this command)
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── auth/                       # NEW package
│   │   ├── __init__.py
│   │   ├── permissions.py          # leaf module: vocabulary + resolve_permissions()
│   │   ├── jwks.py                 # cached PyJWKClient via OIDC discovery
│   │   ├── roles.py                # RoleExtractor protocol + KeycloakRoleExtractor + registry
│   │   ├── identity.py             # AuthenticatedUser value object (never persisted)
│   │   ├── tickets.py              # SSE connection-ticket mint/validate
│   │   └── dependencies.py         # get_current_claims, require_permission(), opt-out short-circuit
│   ├── routers/
│   │   ├── auth.py                 # NEW: GET /api/auth/config, GET /api/auth/permissions,
│   │   │                           #      POST /api/auth/sse-ticket
│   │   ├── sessions.py             # MODIFIED: require_permission on start/resume/delete;
│   │   │                           #           ticket-auth on /events
│   │   ├── workflows.py            # MODIFIED: require_permission on the 6 gated actions;
│   │   │                           #           ticket-auth on /events
│   │   ├── notifications.py        # MODIFIED: ticket-auth on /events
│   │   └── identity.py             # UNCHANGED (oauth2-proxy passthrough, disabled-auth path only)
│   ├── config.py                   # MODIFIED: new Settings fields, _validate_role_mappings
│   ├── config_models.py            # MODIFIED: new RoleMapping model
│   └── main.py                     # MODIFIED: register app.routers.auth
└── tests/
    ├── test_auth_dependencies.py   # NEW
    ├── test_auth_roles.py          # NEW
    ├── test_auth_permissions.py    # NEW
    ├── test_auth_tickets.py        # NEW
    ├── test_auth_router.py         # NEW
    ├── test_sessions_router.py     # MODIFIED: permission-gated cases
    └── test_workflows_router.py    # MODIFIED: permission-gated cases

frontend/
├── src/
│   ├── auth/                       # NEW
│   │   ├── oidc.ts                 # lazy UserManager, fail-loud on bad config
│   │   └── reauthGuard.ts          # circuit-breaker for the 401 seam
│   ├── composables/
│   │   ├── usePermissions.ts       # NEW: can(permission) -> boolean
│   │   ├── useSessions.ts          # MODIFIED: ticket-fetch before EventSource
│   │   ├── useWorkflows.ts         # MODIFIED: ticket-fetch before EventSource (2 streams)
│   │   └── useNotifications.ts     # MODIFIED: ticket-fetch before EventSource
│   ├── components/
│   │   ├── WorkflowPanel.vue       # MODIFIED: usePermissions() gating on mutating buttons
│   │   ├── SessionPanel.vue        # MODIFIED: usePermissions() gating on mutating buttons
│   │   └── IdentityBadge.vue       # MODIFIED: login/logout controls when auth enabled
│   ├── api/index.ts                # MODIFIED: wire setTokenProvider/setUnauthorizedHandler
│   │                                #           (existing, currently-unused seams)
│   └── main.ts                     # MODIFIED: manual /auth/callback handling (no vue-router)
└── tests/
    ├── auth/oidc.test.ts           # NEW
    ├── auth/reauthGuard.test.ts    # NEW
    ├── composables/usePermissions.test.ts  # NEW
    └── (existing composable/component test files extended for gating + ticket-fetch)
```

**Structure Decision**: Web application (Option 2) — existing `backend/`
(FastAPI, routers → services → storage) and `frontend/` (Vue 3/Vuetify SPA)
split. This feature adds one new backend package (`backend/app/auth/`) as a
peer to the existing `backends/`/`persistence/`/`services/` packages, one
new backend router, and one new frontend module (`frontend/src/auth/`) as a
peer to `frontend/src/composables/`. No new top-level project or directory
is introduced.

## Complexity Tracking

*No Constitution Check violations — table intentionally empty.*
