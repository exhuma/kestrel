# Implementation Plan: Source Health Checks

**Branch**: `014-source-health-checks` | **Date**: 2026-09-08 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/014-source-health-checks/spec.md`

## Summary

Surface, per configured task-source/code-host adapter (GitHub, Jira,
GitLab, Gitea, fixture), whether it is currently reachable and
authenticated — as a binary healthy/unhealthy indicator, never the
underlying technical cause. A new `check_health()` capability is added to
the existing `TaskSource`/`CodeHost` ports; a background poll cycle
(reusing the existing `PollSource` pattern) keeps status fresh, an
on-demand refresh action shortcuts the wait, and results are pushed to
the frontend over SSE (mirroring the existing notification-center
pattern) as a persistent per-source indicator in the app bar.

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript / Vue 3 (frontend) — existing stack, unchanged.

**Primary Dependencies**: FastAPI, httpx (via existing `GitHubClient`/`JiraClient`/`GitLabCodeHost` transports), Vuetify — no new dependency.

**Storage**: None (in-memory only — research.md R5).

**Testing**: pytest (backend), vitest (frontend) — existing suites, extended.

**Target Platform**: Existing loopback-bound single-process backend + SPA frontend.

**Project Type**: Web application (backend + frontend), matching the existing repo layout.

**Performance Goals**: A health cycle must not add perceptible load to workflow dispatch (SC-004); each adapter check is one cheap authenticated GET, checks run sequentially per cycle (research.md R6), bounded per-check by `health_check_timeout_seconds` (default 10s).

**Constraints**: No new external dependency; no new persistence; must not alter any existing port method's behavior (purely additive to `TaskSource`/`CodeHost`).

**Scale/Scope**: At most a handful of entries (one per configured adapter — today's bootstrap supports at most one GitHub + one Jira + one fixture profile simultaneously, so realistically 2-4 indicators).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Principle I (Contract Fidelity)**: New frontend type `SourceHealth`
  mirrors the backend `HealthOut` schema field-for-field (contracts/health-api.md).
  No existing type contract changes. **PASS**.
- **Principle II (Layered, Backend-Owned Architecture)**: All health
  logic (checking, dedup, state, timeout) lives in the backend
  (`services/health.py` + adapters); the frontend only renders pushed
  state and fires a refresh action — no client-side health logic.
  No raw DDL: this feature adds no database table at all. **PASS**.
- **Principle III (Test-First Discipline)**: New behavior (port
  capability, poll cycle, dedup, timeout, API routes, SSE stream,
  frontend indicator) ships with pytest + vitest coverage per the
  existing per-feature convention. **PASS** (enforced in Phase 2/3).
- **Principle IV (Deliberate Simplicity & Single-User Scope)**: No new
  dependency; reuses the existing `PollSource`/SSE-bus patterns instead
  of inventing new plumbing; explicitly rejects a generic dedup
  algorithm in favor of hand-curated bootstrap wiring, since today's
  system cannot even produce the case it would need to handle
  (research.md R6). **PASS**.
- **Principle V (Kit-Aligned Consistency & Observability)**: UI indicator
  uses Vuetify theme tokens (no hard-coded colors) for
  healthy/unhealthy/unknown states; health-check outcomes and failures
  are logged server-side (structured logging) for operator
  troubleshooting even though the UI itself stays detail-free. **PASS**.

No deviations requiring a Complexity Tracking entry or constitution
amendment.

## Project Structure

### Documentation (this feature)

```text
specs/014-source-health-checks/
├── plan.md                          # This file
├── research.md                      # Phase 0 output
├── data-model.md                    # Phase 1 output
├── quickstart.md                    # Phase 1 output
├── contracts/
│   ├── health-check-port.md         # TaskSource/CodeHost.check_health() contract
│   └── health-api.md                # REST + SSE contract
└── tasks.md                         # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── ports.py                     # + TaskSource.check_health / CodeHost.check_health
│   ├── config.py                    # + health_check_interval_seconds, health_check_timeout_seconds
│   ├── schemas.py                   # + HealthOut
│   ├── services/
│   │   ├── github.py                # GitHubTaskSource/GitHubCodeHost.check_health (GET /user)
│   │   ├── github_tasksource.py     # (same, if check_health lands here per current split)
│   │   ├── jira.py                  # JiraTaskSource.check_health (GET /myself)
│   │   ├── gitlab.py                # GitLabCodeHost.check_health (GET /user)
│   │   ├── fixture.py               # FixtureTaskSource.check_health (returns True, no I/O)
│   │   ├── health.py                # NEW: HealthState, SourceHealth, HealthStore, HealthPollService
│   │   ├── poll_source.py           # + health poll service registered in configured_poll_sources
│   │   └── workflows/bootstrap.py   # + hand-curated (label, check_fn) registration list
│   ├── storage/
│   │   └── health_bus.py            # NEW: keyless pub/sub tick, mirrors notification_bus.py
│   └── routers/
│       └── health.py                # NEW: GET /api/health, GET /api/health/events, POST /api/health/{name}/refresh
└── tests/
    ├── test_health_port.py          # NEW: per-adapter check_health() contract tests
    ├── test_health_store.py         # NEW
    ├── test_health_poll.py          # NEW: cycle, timeout, dedup, sequential isolation
    └── test_health_api.py           # NEW: routes + SSE

frontend/
├── src/
│   ├── types/health.ts              # NEW: SourceHealth, HealthState
│   ├── composables/useSourceHealth.ts  # NEW: mirrors useNotifications.ts (SSE + refresh action)
│   ├── components/SourceHealthIndicator.vue  # NEW: per-source app-bar dot/icon
│   └── App.vue                      # + <SourceHealthIndicator> in the app bar
└── tests/
    ├── composables/useSourceHealth.test.ts   # NEW
    └── components/SourceHealthIndicator.test.ts  # NEW
```

**Structure Decision**: Existing `backend/` + `frontend/` layout, unchanged. New backend module `app/services/health.py` (service logic) + `app/routers/health.py` (HTTP/SSE surface) + `app/storage/health_bus.py` (pub/sub), following the exact separation `notifications.py`/`notification_bus.py`/`persistence/notification_store.py` already establish for a comparable "list + stream + one mutating action" feature — health simply has no persistence layer where notifications has a store. New frontend composable + component, wired into the existing `App.vue` app bar alongside the existing `useConnectivity` banner.

## Complexity Tracking

No Constitution Check violations — this section intentionally left empty.
