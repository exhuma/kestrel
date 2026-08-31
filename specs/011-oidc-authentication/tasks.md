# Tasks: OIDC authentication & permission-based authorization

**Input**: Design documents from `/specs/011-oidc-authentication/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/,
quickstart.md (all present)

**Tests**: Included and REQUIRED — constitution Principle III (Test-First
Discipline) is NON-NEGOTIABLE for this project. Every implementation task
below has a corresponding test task ordered before it; write the test,
confirm it fails, then implement.

**Organization**: Tasks are grouped by user story (spec.md's US1/US2/US3) so
each can be implemented, tested, and demoed independently. Backend precedes
frontend within each phase, per the plan's stated order.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an
  incomplete task)
- **[Story]**: US1 / US2 / US3, or absent for Setup/Foundational/Polish
- File paths are exact, per `plan.md`'s Project Structure section

---

## Phase 1: Setup

**Purpose**: Dependencies and package scaffolding, nothing behavioral yet.

- [X] T001 [P] Add `pyjwt[crypto]` to `backend/pyproject.toml` runtime deps
      and `respx` to its dev deps; run `uv sync` (or `uv add pyjwt[crypto]`
      / `uv add --dev respx`) so `backend/uv.lock` is updated
- [X] T002 [P] Add `oidc-client-ts` to `frontend/package.json`; run
      `npm install`
- [X] T003 [P] Create the empty `backend/app/auth/` package:
      `backend/app/auth/__init__.py`
- [X] T004 [P] Create the empty `frontend/src/auth/` directory (no file
      yet — populated in Phase 2)

**Checkpoint**: Dependencies installed, package scaffolding exists.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The authentication/authorization framework every user story
sits on top of — config, token validation, role extraction, permission
resolution, the opt-out short-circuit, and the frontend's OIDC client
bootstrap. No story-specific gating happens yet; this phase's own
observable behavior is limited to `GET /api/auth/config` and (with auth
disabled) zero change to anything else.

**⚠️ CRITICAL**: No user story work may begin until this phase is complete.

### Tests for Foundational (write first, confirm they fail)

- [X] T005 [P] Test `resolve_permissions()` and the fixed permission
      vocabulary in `backend/tests/test_auth_permissions.py`: role→permission
      mapping resolution (union across multiple matched mappings), and that
      `Settings._validate_role_mappings` fails fast at startup on a
      permission string outside the vocabulary
- [X] T006 [P] Test `RoleExtractor`/`KeycloakRoleExtractor` in
      `backend/tests/test_auth_roles.py`: realm-role extraction, client-role
      extraction with `f"{client_id}:{role}"` namespacing, and the provider
      registry raising on an unknown `oidc_provider`
- [X] T007 [P] Test the JWKS client and `get_current_claims`/opt-out
      short-circuit in `backend/tests/test_auth_dependencies.py`: mock the
      JWKS endpoint (`respx`); cases — valid token, expired token, wrong
      `aud`, wrong `iss`, tampered signature, and `auth_enabled=False`
      passing every case through untouched
- [X] T008 [P] Test `GET /api/auth/config` in
      `backend/tests/test_auth_router.py`: disabled → `{"enabled": false,
      "authority": "", "client_id": ""}`; enabled → populated from
      `Settings`; no `Authorization` header required either way (per
      `contracts/auth-config.md`)
- [X] T009 [P] Test the new `oidc.ts` bootstrap in
      `frontend/tests/auth/oidc.test.ts`: `enabled: false` → no-op
      `UserManager` stand-in constructed, app can mount immediately;
      `enabled: true` with a populated authority/client_id → a real
      `UserManager` is constructed; `enabled: true` with an empty
      authority/client_id → throws/surfaces a hard error (fail-loud, per
      `contracts/auth-config.md`)

### Implementation for Foundational

- [X] T010 [P] Add `RoleMapping` model (`role: str`, `permissions:
      list[str]`) to `backend/app/config_models.py`
- [X] T011 [P] Create `backend/app/auth/permissions.py`: the fixed
      permission-vocabulary constants from `data-model.md` (`sessions:write`,
      `sessions:delete`, `workflows:approve`, `workflows:reject`,
      `workflows:respond`, `workflows:cleanup`, `workflows:rerun`,
      `workflows:delete`) and `resolve_permissions(roles: set[str],
      mappings: list[RoleMapping]) -> frozenset[str]`. **Leaf module — MUST
      NOT import `app.config`** (see `research.md` §9 / `plan.md`'s import-
      linter constraint)
- [X] T012 In `backend/app/config.py`: add `auth_enabled`, `oidc_authority`,
      `oidc_audience`, `oidc_issuer`, `oidc_client_id`, `oidc_provider`
      fields (see `data-model.md`'s Settings table for defaults); add
      `role_mappings: list[RoleMapping] = []` to `_FILE_ONLY_FIELDS` and
      `_apply_config_file`; add a `_validate_role_mappings` after-validator
      (mirrors `_validate_step_backends`) importing the vocabulary from
      `app.auth.permissions` and failing fast on an unknown permission
      string; add the auth-incomplete-config warning validator (mirrors
      `_warn_incomplete_ingestion_config`) — depends on T010, T011 (T005
      must be failing before this task, T005 must pass after)
- [X] T013 [P] Create `backend/app/auth/jwks.py`: `get_jwks_client(authority:
      str) -> jwt.PyJWKClient`, `lru_cache`d, resolving
      `{authority}/.well-known/openid-configuration` — depends on T001
- [X] T014 [P] Create `backend/app/auth/roles.py`: `RoleExtractor` Protocol,
      `KeycloakRoleExtractor` (realm + namespaced client roles per
      `data-model.md`), and a provider registry keyed by `oidc_provider` —
      makes T006 pass
- [X] T015 [P] Create `backend/app/auth/identity.py`: the `AuthenticatedUser`
      value object (`sub`, `email`, `preferred_username`, `permissions:
      frozenset[str]`), never persisted — depends on T011
- [X] T016 Create `backend/app/auth/dependencies.py`: `get_current_claims`
      (validates `exp`/`nbf`/`aud`/`iss` via T013's JWKS client),
      `require_permission(perm: str)` dependency factory, an
      authenticated-only dependency, all short-circuiting to "everything
      allowed" when `auth_enabled=False` — makes T007 pass; depends on
      T012, T013, T014, T015
- [X] T017 Create `backend/app/routers/auth.py` with `GET /api/auth/config`
      only (per `contracts/auth-config.md`); register it in
      `backend/app/main.py` — makes T008 pass; depends on T012
- [X] T018 [P] Add `AuthConfig`/`AuthPermissions` TypeScript interfaces to
      `frontend/src/types/` (per constitution Principle I — every backend
      JSON shape gets a mirrored frontend type), matching
      `contracts/auth-config.md` and `contracts/auth-permissions.md`
- [X] T019 Create `frontend/src/auth/oidc.ts`: fetches `GET /api/auth/config`
      at boot; lazy `UserManager` built only when `enabled: true`; no-op
      stand-in otherwise; throws on missing authority/client_id when
      enabled — makes T009 pass; depends on T018
- [X] T020 In `frontend/src/api/index.ts`: wire `setTokenProvider()` to read
      `oidc.ts`'s current user's access token (existing, currently-unused
      seam) — depends on T019

**Checkpoint**: `GET /api/auth/config` works; token validation, role
extraction, and permission resolution are all correct and tested in
isolation; the frontend can tell whether auth is on. **No route's
authorization behavior has changed yet** — that starts in Phase 3.

---

## Phase 3: User Story 1 - Operator gates kestrel behind sign-in (Priority: P1) 🎯 MVP

**Goal**: With auth enabled, every visitor must sign in via the IdP before
reaching any part of kestrel — read-only views, live-updating streams, and
the app shell alike. With auth disabled (default), nothing changes.

**Independent Test**: Toggle the feature off → confirm zero behavior
change. Toggle it on → confirm an unauthenticated visitor is redirected to
sign in before seeing anything, and a signed-in visitor reaches kestrel's
normal (still fully-capable, since US2 hasn't landed yet) views, including
live-updating ones.

### Tests for User Story 1

- [X] T021 [P] [US1] Test SSE connection tickets in
      `backend/tests/test_auth_tickets.py`: mint → validate succeeds once;
      replay of the same `jti` is rejected; expired ticket rejected;
      tampered signature rejected (per `contracts/auth-sse-ticket.md`)
- [X] T022 [P] [US1] Extend `backend/tests/test_sessions_router.py`: with
      auth enabled, `GET /api/sessions`, `POST /api/sessions/{id}/poll`
      require only authentication (any valid identity, no permission
      check); with auth disabled, unchanged
- [X] T023 [P] [US1] Extend `backend/tests/test_workflows_router.py`
      (or create if list/detail/poll cases aren't yet covered): same
      authenticated-only assertions for `GET /api/workflows`,
      `/{id}`, `POST /{id}/poll`
- [X] T024 [P] [US1] Extend `backend/tests/` for `notifications.py`
      (`GET /api/notifications`, `POST /{id}/read`): same
      authenticated-only assertions
- [X] T025 [P] [US1] Test the ticket-gated `/events` routes (all four) in
      the relevant router test files: valid ticket → stream opens; missing/
      invalid/reused/expired ticket → connection refused; auth disabled →
      unchanged (no ticket required)
- [X] T026 [P] [US1] Test `POST /api/auth/sse-ticket` in
      `backend/tests/test_auth_router.py`: requires the caller's own valid
      bearer token when auth is enabled; returns a ticket; 401 when
      unauthenticated
- [X] T027 [P] [US1] Test the reauth-loop-guard circuit breaker in
      `frontend/tests/auth/reauthGuard.test.ts`: a single 401 (genuine
      expiry) triggers exactly one redirect and clears on the next success;
      a second consecutive 401 (structurally-rejected token) trips the
      breaker and surfaces `authError` instead of redirecting again
- [X] T028 [P] [US1] Test the `/auth/callback` bootstrap path in
      `frontend/tests/` (e.g. a `main.ts`-adjacent test or an
      `oidc.test.ts` addition): pathname `/auth/callback` triggers
      `signinRedirectCallback()` and redirects to the stored `returnTo`
      (or `/`) before the main app mounts
- [X] T029 [P] [US1] Extend `frontend/tests/composables/useSessions.test.ts`,
      `useWorkflows.test.ts`, `useNotifications.test.ts`: when auth is
      enabled, a ticket is fetched via `POST /api/auth/sse-ticket` and
      appended as `?ticket=...` before each `EventSource` is constructed;
      when disabled, the URL is unchanged

### Implementation for User Story 1

- [X] T030 [P] [US1] Create `backend/app/auth/tickets.py`: mint (HS256,
      in-process startup secret, `sub` + `permissions` + `exp` (~30s) +
      `jti`) and validate (signature, expiry, one-time use via a bounded
      in-memory used-`jti` set) — makes T021 pass; depends on T015
- [X] T031 [US1] Add `POST /api/auth/sse-ticket` to
      `backend/app/routers/auth.py` (per `contracts/auth-sse-ticket.md`) —
      makes T026 pass; depends on T030
- [X] T032 [US1] Apply the authenticated-only dependency (T016) to
      `GET /api/sessions`, `POST /api/sessions/{id}/poll` in
      `backend/app/routers/sessions.py` — makes T022 pass
- [X] T033 [US1] Apply the authenticated-only dependency to
      `GET /api/workflows`, `GET /api/workflows/{id}`,
      `POST /api/workflows/{id}/poll` in
      `backend/app/routers/workflows.py` — makes T023 pass
- [X] T034 [US1] Apply the authenticated-only dependency to
      `GET /api/notifications`, `POST /api/notifications/{id}/read` in
      `backend/app/routers/notifications.py` — makes T024 pass
- [X] T035 [US1] Add the ticket-validation dependency (from T030) to the
      four `/events` routes: `GET /api/sessions/{id}/events`
      (`sessions.py`), `GET /api/workflows/events` and
      `GET /api/workflows/{id}/events` (`workflows.py`),
      `GET /api/notifications/events` (`notifications.py`) — makes T025
      pass
- [X] T036 [P] [US1] Create `frontend/src/auth/reauthGuard.ts`: the
      `sessionStorage`-counter circuit breaker (`handleUnauthorized`,
      `notifyAuthSuccess`, `authError` ref) — makes T027 pass
- [X] T037 [US1] In `frontend/src/api/index.ts`: wire
      `setUnauthorizedHandler(reauthGuard.handleUnauthorized)` and a
      success-seam call to `reauthGuard.notifyAuthSuccess` on every 2xx —
      depends on T036
- [X] T038 [US1] In `frontend/src/main.ts`: before mounting `App.vue`,
      resolve `oidc.ts`'s config; if disabled, mount immediately
      (unchanged today); if enabled and `pathname === '/auth/callback'`,
      run the callback flow and redirect (mirrors the existing
      `applyDeepLink` manual-URL-parsing idiom in this file); otherwise
      check for a valid non-expired user and `signinRedirect()` if absent —
      makes T028 pass; depends on T019, T037
- [X] T039 [P] [US1] In `frontend/src/composables/useSessions.ts`: before
      constructing the session-detail `EventSource`, fetch a ticket via
      `POST /api/auth/sse-ticket` (through the authenticated `api` client)
      when auth is enabled, append `?ticket=...`; unchanged when disabled —
      part of what makes T029 pass; depends on T020
- [X] T040 [P] [US1] Same ticket-fetch wiring in
      `frontend/src/composables/useWorkflows.ts` for both its
      `EventSource` call sites (list + detail) — part of what makes T029
      pass; depends on T020
- [X] T041 [P] [US1] Same ticket-fetch wiring in
      `frontend/src/composables/useNotifications.ts` — part of what makes
      T029 pass; depends on T020
- [X] T042 [US1] Extend `frontend/src/components/IdentityBadge.vue`: add
      login/logout controls (`userManager.signinRedirect()` /
      `signoutRedirect()`) visible when auth is enabled, in the existing
      `v-app-bar` right-hand cluster in `frontend/src/App.vue`

**Checkpoint**: With auth enabled, sign-in is required everywhere,
including live views; every signed-in user can still do everything (no
permission differentiation yet — that's US2). With auth disabled, byte-for-
byte unchanged. This alone is a demoable, independently valuable increment.

---

## Phase 4: User Story 2 - Signed-in users are limited to what they're permitted to do (Priority: P2)

**Goal**: A signed-in user without a given permission is refused the
matching mutating action and sees it as unavailable beforehand; a user with
the permission can perform it.

**Independent Test**: Sign in as two configured identities — one granted a
permission, one not — and confirm the corresponding action succeeds for one
and is refused for the other, for every gated action.

### Tests for User Story 2

- [X] T043 [P] [US2] Extend `backend/tests/test_sessions_router.py`: with
      auth enabled, `POST /api/sessions`, `POST /api/sessions/{id}/resume`
      require `sessions:write` (200 with it, 403 without, 401 with no
      token); `DELETE /api/sessions/{id}` requires `sessions:delete`
- [X] T044 [P] [US2] Extend `backend/tests/test_workflows_router.py`: each
      of `POST /{id}/approve` (`workflows:approve`), `/reject`
      (`workflows:reject`), `/reply` `/answers` `/answers/draft`
      (`workflows:respond`), `/cleanup` (`workflows:cleanup`), `/rerun`
      (`workflows:rerun`), `DELETE /{id}` (`workflows:delete`) — 200 with
      the matching permission, 403 without, and confirm a 403 performs no
      side effect (per `contracts/permission-gated-endpoints.md`)
- [X] T045 [P] [US2] Test `GET /api/auth/permissions` in
      `backend/tests/test_auth_router.py`: auth disabled → the `"*"`
      sentinel shape; auth enabled + valid token + mapped permissions →
      exact list; auth enabled + zero mapped roles → `"permissions": []`
      (not an error); auth enabled + invalid token → 401 (per
      `contracts/auth-permissions.md`)
- [X] T046 [P] [US2] Test `usePermissions.ts` in
      `frontend/tests/composables/usePermissions.test.ts`: fetches once,
      `can(permission)` reflects the fetched set; auth disabled → `can()`
      always true (sentinel handling)
- [X] T047 [P] [US2] Extend `frontend/tests/components/` for
      `WorkflowPanel.vue` and `SessionPanel.vue`: each mutating button
      renders disabled when `usePermissions().can(...)` is false for its
      permission, enabled when true

### Implementation for User Story 2

- [X] T048 [US2] Apply `require_permission("sessions:write")` to
      `POST /api/sessions` and `POST /api/sessions/{id}/resume`,
      `require_permission("sessions:delete")` to
      `DELETE /api/sessions/{id}` in `backend/app/routers/sessions.py` —
      makes T043 pass
- [X] T049 [US2] Apply the matching `require_permission(...)` (per
      `data-model.md`'s vocabulary table) to `POST /{id}/approve`,
      `/reject`, `/reply`, `/answers`, `/answers/draft`, `/cleanup`,
      `/rerun`, and `DELETE /{id}` in `backend/app/routers/workflows.py` —
      makes T044 pass
- [X] T050 [US2] Add `GET /api/auth/permissions` to
      `backend/app/routers/auth.py` (per `contracts/auth-permissions.md`,
      including the disabled-auth `"*"` sentinel response) — makes T045
      pass; depends on T016
- [X] T051 [P] [US2] Create `frontend/src/composables/usePermissions.ts`
      (module-singleton pattern, matching `useIdentity.ts`): fetches
      `GET /api/auth/permissions` once, exposes `can(permission: string):
      boolean`, treating the `"*"` sentinel as always-true — makes T046
      pass; depends on T018
- [X] T052 [P] [US2] Gate `WorkflowPanel.vue`'s mutating buttons
      (`onCleanup`, `onRerun`, `onDelete`, `onApprove`, `onReject`,
      `onReply`/answers) via `usePermissions().can(...)` — makes half of
      T047 pass; depends on T051
- [X] T053 [P] [US2] Gate `SessionPanel.vue`'s mutating buttons (`onStart`,
      `onResume`, `onDelete`) via `usePermissions().can(...)` — makes the
      other half of T047 pass; depends on T051

**Checkpoint**: Both US1 and US2 work together — sign-in is required, and
which mutating actions a signed-in user may perform is now genuinely
differentiated by their granted permissions, enforced backend-side with
UX-only frontend gating (constitution Principle II).

---

## Phase 5: User Story 3 - Operator maps their own roles to kestrel's permissions (Priority: P3)

**Goal**: An operator decides which of their IdP's role names — realm-wide
or client-specific — grant which kestrel permission, entirely through
`config.toml`, no code change.

**Independent Test**: Change only the role-to-permission configuration and
confirm a signed-in user's allowed actions change accordingly on the next
restart, for a role defined at either the realm or the client level.

**Note**: The mapping *mechanism* (config loading, validation, realm/
client-role extraction, permission resolution) was already built and
tested in Phase 2 (T005, T006, T010–T012, T014). This phase proves it
end-to-end against the now-gated endpoints from US2, and gives the operator
the documentation and example needed to use it.

### Tests for User Story 3

- [ ] T054 [P] [US3] Integration test in `backend/tests/test_auth_roles.py`
      (or a new `backend/tests/test_auth_integration.py`): a user whose
      token carries a **realm** role mapped in `config.toml` to
      `workflows:cleanup` can call `POST /api/workflows/{id}/cleanup`
      (200); a user without that role mapping cannot (403)
- [ ] T055 [P] [US3] Same integration test shape for a **client** role
      (namespaced `f"{client_id}:{role}"` in the mapping) granting
      `sessions:delete` — confirms client-role mapping works identically
      to realm-role mapping
- [ ] T056 [P] [US3] Test that changing `role_mappings` between two
      `Settings()` construction calls (simulating a restart with an edited
      `config.toml`) changes `resolve_permissions()`'s output for the same
      role set — confirms FR-005/SC-002 without needing a real process
      restart in the test

### Implementation for User Story 3

- [ ] T057 [P] [US3] Add a commented-out, documented `[[role_mappings]]`
      example block to `config.toml.example` (per `data-model.md`'s
      example, showing both a realm-role and a namespaced client-role
      entry)
- [ ] T058 [P] [US3] Write `docs/auth.md` (new): Keycloak public-client
      setup (PKCE, redirect URIs), realm vs. client role creation, the
      `[[role_mappings]]` format and permission vocabulary, **the
      audience-mapper gotcha** (Keycloak access tokens don't carry the
      requesting client as `aud` by default — needs an explicit audience
      mapper, or `oidc_audience` validation fails for every token), the
      SSE-ticket mechanism and its short exposure window, and the explicit
      statement that task-ingestion permissions are the source's
      responsibility, not kestrel's (per spec FR-014)

**Checkpoint**: All three user stories work together and are independently
verifiable per `quickstart.md`'s steps 1–7.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation catch-up recorded as pending in the constitution
amendment's Sync Impact Report, plus whole-feature verification.

- [ ] T059 [P] Update `docs/configuration.md`: add the new
      `KESTREL_AUTH_ENABLED`/`KESTREL_OIDC_*` environment variable rows and
      the `[[role_mappings]]` config.toml section, matching the existing
      table format
- [ ] T060 [P] Rewrite `docs/architecture.md`'s "Data & auth" section
      (currently states "Single-user, no auth… Multi-user/authn is out of
      scope") to describe the opt-in OIDC resource-server model
- [ ] T061 [P] Update `docs/qm-alignment.md`: move the four `module-auth-*`
      kits from "N/A" to "Applies", noting what was and wasn't adopted (no
      user provisioning, no dev-auth-bypass, no vue-router — see
      `research.md`'s Rejected Alternatives); record the
      `GET /api/auth/config` runtime-config deviation alongside the
      existing `VITE_API_BASE` entry
- [ ] T062 Run `cd backend && uv run pytest` — full suite green
- [ ] T063 Run `uvx ruff check backend` and the import-linter check (however
      `task quality` invokes it) — confirm `backend/app/auth/permissions.py`
      has no upward import (leaf-module constraint, T011)
- [ ] T064 Run `cd frontend && npm run test && npm run build` — full suite
      green
- [ ] T065 Run `task quality` end-to-end — confirm every new/changed module
      stays within the structural limits (complexity ≤10, module ≤500
      lines, etc.)
- [ ] T066 Execute `quickstart.md` steps 1–7 end-to-end against a real
      Keycloak instance (or a disposable `docker run
      quay.io/keycloak/keycloak start-dev`) — the feature's actual
      acceptance bar

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational only
- **User Story 2 (Phase 4)**: Depends on Foundational; **also depends on
  User Story 1** per the spec's own stated priority reasoning ("sign-in
  must exist first") — specifically, US2's gated endpoints need the
  authenticated-only wiring US1 establishes on the same router files
  (T032–T034 touch the same files as T048–T049)
- **User Story 3 (Phase 5)**: Depends on Foundational (the mapping
  mechanism) and User Story 2 (the gated endpoints it proves the mapping
  against) — its own new code is documentation/example only
- **Polish (Phase 6)**: Depends on all three user stories being complete

### Within Each Phase

- Tests MUST be written and confirmed failing before their corresponding
  implementation task
- Within Foundational: config/vocabulary (T010–T012) before the modules
  that consume them (T013–T017); backend before frontend
- Within US1: `tickets.py` (T030) before the SSE-ticket endpoint (T031)
  before wiring it into the 4 routers (T035); backend (T030–T035) before
  frontend (T036–T042)
- Within US2: backend permission-gating (T048–T050) before the frontend
  composable that reads resolved permissions (T051) before the components
  that use it (T052–T053)

### Parallel Opportunities

- All Setup tasks (T001–T004) in parallel
- Foundational: T005–T009 (tests) in parallel with each other; T010, T011,
  T013, T014, T015, T018 in parallel with each other (distinct files);
  T012 depends on T010+T011, T016 depends on T012–T015, T017 depends on
  T012, T019 depends on T018, T020 depends on T019
- US1: T021–T029 (tests) in parallel; T030, T036 in parallel; T039, T040,
  T041 in parallel (three different composable files)
- US2: T043–T047 (tests) in parallel; T052, T053 in parallel (different
  component files)
- US3: T054–T056 in parallel; T057, T058 in parallel
- Polish: T059, T060, T061 in parallel; T062–T066 sequential (each
  verifies the whole tree, no point parallelizing)

---

## Parallel Example: Foundational Phase

```bash
# Tests first, all independent:
Task: "Test resolve_permissions() and fail-fast validation in backend/tests/test_auth_permissions.py"
Task: "Test RoleExtractor/KeycloakRoleExtractor in backend/tests/test_auth_roles.py"
Task: "Test JWKS client and get_current_claims in backend/tests/test_auth_dependencies.py"
Task: "Test GET /api/auth/config in backend/tests/test_auth_router.py"
Task: "Test oidc.ts bootstrap in frontend/tests/auth/oidc.test.ts"

# Then, once T010/T011 land, these four are independent of each other:
Task: "Create backend/app/auth/jwks.py"
Task: "Create backend/app/auth/roles.py"
Task: "Create backend/app/auth/identity.py"
Task: "Add AuthConfig/AuthPermissions types to frontend/src/types/"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 (Setup) → Phase 2 (Foundational) → Phase 3 (US1)
2. **STOP and VALIDATE**: `quickstart.md` steps 1 and 3 (disabled no-op,
   sign-in gate) plus step 5 (live updates over the ticket mechanism)
3. This is already a real, demoable increment: kestrel requires sign-in,
   even though every signed-in user can still do everything

### Incremental Delivery

1. Setup + Foundational → foundation ready, `GET /api/auth/config` live
2. + US1 → sign-in required everywhere, including live views (MVP)
3. + US2 → mutating actions are permission-differentiated
4. + US3 → operator-documented, config-only role mapping proven end-to-end
5. + Polish → docs caught up, full quality/test gate green,
   `quickstart.md` fully executed

### Notes

- Commit after each task or logical group, per this repo's Conventional
  Commits convention (see recent `git log` for examples:
  `feat(auth): ...`, `test(auth): ...`, `docs(auth): ...`)
- Constitution Principle III is NON-NEGOTIABLE: do not skip a test task or
  reorder it after its implementation task
- Avoid same-file conflicts: `backend/app/routers/auth.py` is touched by
  T017 (Foundational), T031 (US1), and T050 (US2) — sequential, not
  parallel, across those three; `backend/app/routers/sessions.py` similarly
  by T032 (US1) and T048 (US2); `workflows.py` by T033 (US1) and T049
  (US2)
