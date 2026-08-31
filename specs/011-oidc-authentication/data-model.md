# Phase 1 Data Model: OIDC authentication & permission-based authorization

This feature is deliberately schema-free (see `research.md` §4 and §9,
constitution Principle IV) — none of the entities below are persisted to the
database. They are either request-scoped value objects (recomputed every
call) or operator-authored configuration (loaded once at process startup,
same lifecycle as the rest of `Settings`).

## Settings additions (`backend/app/config.py`, env-sourced)

| Field | Type | Default | Notes |
|---|---|---|---|
| `auth_enabled` | `bool` | `False` | `KESTREL_AUTH_ENABLED`. Master opt-in switch. |
| `oidc_authority` | `str` | `""` | `KESTREL_OIDC_AUTHORITY`. IdP issuer base URL; discovery doc at `{authority}/.well-known/openid-configuration`. |
| `oidc_audience` | `str` | `""` | `KESTREL_OIDC_AUDIENCE`. Validated against the token's `aud` claim. |
| `oidc_issuer` | `str` | `""` | `KESTREL_OIDC_ISSUER`. Validated against `iss`; defaults to `oidc_authority` when unset. |
| `oidc_client_id` | `str` | `""` | `KESTREL_OIDC_CLIENT_ID`. Which client's `resource_access` branch to read for client-role extraction; defaults to `oidc_audience` when unset. Distinct knob from `oidc_audience` (see `research.md` — same value in kestrel's single-SPA-client setup today, conceptually different purpose). |
| `oidc_provider` | `str` | `"keycloak"` | `KESTREL_OIDC_PROVIDER`. Selects the `RoleExtractor` implementation via the provider registry. |

**Validation** (model-validator, mirrors `_warn_incomplete_ingestion_config`):
when `auth_enabled=True`, warn (not fail) if `oidc_authority`,
`oidc_audience`, or `oidc_client_id` (after defaulting) is empty — a
misconfigured-but-enabled auth setup should be loud, not silently permissive
or a hard startup crash.

## RoleMapping (`backend/app/config_models.py`, file-only via `config.toml`)

```toml
[[role_mappings]]
role = "kestrel-operator"                 # IdP role name (realm or, namespaced, client)
permissions = ["sessions:write", "workflows:approve", "workflows:respond"]

[[role_mappings]]
role = "kestrel-admin"
permissions = [
  "sessions:write", "sessions:delete",
  "workflows:approve", "workflows:reject", "workflows:respond",
  "workflows:cleanup", "workflows:rerun", "workflows:delete",
]
```

| Field | Type | Notes |
|---|---|---|
| `role` | `str` | An IdP role name as reported in claims. A realm role is used as-is (e.g. `"kestrel-admin"`); a client role is namespaced by the extractor as `f"{client_id}:{role}"` (e.g. `"kestrel-spa:approver"`) before mapping lookup — the operator writes the mapping using that same namespaced form for a client role. |
| `permissions` | `list[str]` | Each entry MUST be one of the fixed permission-vocabulary strings (§ below). Validated at startup — an unknown string fails fast (`Settings._validate_role_mappings`, mirrors `_validate_step_backends`). |

**Lifecycle**: loaded once from `config.toml` at process startup, same as
`task_sources`/`backends` (`_FILE_ONLY_FIELDS`). A changed mapping requires
a restart to take effect (constitution Run modes / existing `config.toml`
convention: "Read once at startup — restart after editing").

**Multiple mappings for the same role**: not a distinct case to handle —
`role_mappings` is a list; an operator lists a role once. A signed-in
user's effective permission set is the union of every mapping whose `role`
appears in their extracted role set.

## Permission vocabulary (`backend/app/auth/permissions.py`, fixed constants)

| Permission | Gates |
|---|---|
| `sessions:write` | `POST /api/sessions` (start), `POST /api/sessions/{id}/resume` |
| `sessions:delete` | `DELETE /api/sessions/{id}` (abandon) |
| `workflows:approve` | `POST /api/workflows/{id}/approve` |
| `workflows:reject` | `POST /api/workflows/{id}/reject` |
| `workflows:respond` | `POST /api/workflows/{id}/reply`, `/answers`, `/answers/draft` |
| `workflows:cleanup` | `POST /api/workflows/{id}/cleanup` |
| `workflows:rerun` | `POST /api/workflows/{id}/rerun` |
| `workflows:delete` | `DELETE /api/workflows/{id}` (abandon) |

Not app-defined-permission-gated (just-authenticated when auth is enabled,
open when disabled): `POST /api/sessions/{id}/poll`,
`POST /api/notifications/{id}/read`, every `GET` (list/detail) route, and
the four `/events` SSE routes (which use the ticket mechanism below instead
of the standard bearer-token dependency).

This vocabulary is closed and application-owned — it is never derived from
IdP data, only mapped to from it.

## AuthenticatedUser (`backend/app/auth/identity.py`, request-scoped value object)

| Field | Type | Source |
|---|---|---|
| `sub` | `str` | Token `sub` claim |
| `email` | `str \| None` | Token `email` claim |
| `preferred_username` | `str \| None` | Token `preferred_username` claim |
| `permissions` | `frozenset[str]` | `resolve_permissions(roles, settings.role_mappings)`, where `roles` comes from the configured `RoleExtractor` |

**Not persisted.** Constructed fresh by `get_current_claims`/
`require_permission(...)` on every request from the validated token; there
is no row anywhere this object is written to. Two requests from the same
person produce two independently-constructed, field-equal instances.

**Opt-out identity**: when `auth_enabled=False`, dependencies short-circuit
to a stand-in `AuthenticatedUser` whose `permissions` is "everything" (or
the dependency is bypassed entirely) — no claims validation occurs, no
request is ever rejected on auth grounds.

## Connection ticket (`backend/app/auth/tickets.py`, in-memory + wire format)

| Field | Type | Notes |
|---|---|---|
| `sub` | `str` | Copied from the minting request's `AuthenticatedUser.sub` |
| `permissions` | `frozenset[str]` | Copied at mint time — the ticket carries a snapshot, not a live lookup |
| `exp` | `int` (unix ts) | Mint time + ~30s |
| `jti` | `str` | Random nonce; the one-time-use key |

Signed as a compact HS256 token using an in-process secret generated once at
kestrel startup (not persisted, not shared across processes — acceptable
because a ticket's ~30s lifetime never needs to survive a restart).
Transported as `?ticket=<value>` on the four `/events` routes only.

**One-time use**: `jti` is recorded in a bounded, TTL-cleaned in-memory set
on first successful validation (consistent with the existing
`SessionRegistry`/`WorkflowRegistry` in-memory-state pattern); a replayed
`jti` is rejected even if `exp` hasn't passed. Once an SSE connection is
established, the ticket is no longer needed — the stream stays open without
re-validation, unchanged from today's behavior.

## Relationships

```text
Settings.role_mappings (config.toml, list[RoleMapping])
        │
        │  resolve_permissions(roles, role_mappings)
        ▼
IdP token claims ──RoleExtractor──▶ roles: set[str] ──▶ permissions: frozenset[str]
        │                                                        │
        └──────────────────────────────────────────────▶ AuthenticatedUser (request-scoped)
                                                                   │
                                                    POST /api/auth/sse-ticket
                                                                   ▼
                                                        ConnectionTicket (~30s, one-time)
```

No entity here has a foreign key, a migration, or a lifecycle independent
of "one HTTP request" (`AuthenticatedUser`) or "one SSE connection attempt"
(`ConnectionTicket`) except `Settings.role_mappings`, which lives exactly as
long as the process does.
