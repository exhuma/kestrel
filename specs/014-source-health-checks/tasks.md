# Tasks: Source Health Checks

**Input**: Design documents from `specs/014-source-health-checks/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/,
quickstart.md (all present)

**Tests**: Included as first-class tasks — Constitution III ("Test-First
Discipline (NON-NEGOTIABLE)") requires every behaviour change to ship with
tests; not optional for this project.

**Organization**: Grouped by user story (spec.md P1-P2). US2 (manual
refresh) reuses US1's check function and store, so it is sequenced after
US1 rather than being independent, but is still independently testable
and demoable once its own phase lands.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no unresolved dependency)
- **[Story]**: Maps a task to US1/US2 from spec.md

---

## Phase 1: Setup

- [X] T001 Confirm the backend (`uv sync`, from `backend/`) and frontend
      (`npm ci`, from `frontend/`) toolchains are current and the existing
      full test suites (`pytest`, `npm test`) pass clean before any
      change, as the regression baseline for this feature.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The port capability, every adapter's implementation of it,
and the in-memory state/pub-sub shape every user story depends on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T002 [P] `async def check_health(self) -> bool` added to both
      `TaskSource` and `CodeHost` protocols in `backend/app/ports.py`
      (contracts/health-check-port.md).
- [X] T003 [P] Config settings `health_check_interval_seconds` (default
      `60`) and `health_check_timeout_seconds` (default `10`) in
      `backend/app/config.py`, alongside the existing
      `poll_interval_seconds` (research.md R3).
- [X] T004 `HealthState` enum, `SourceHealth` record, and `HealthStore`
      (`list_all`, `set`) in new `backend/app/services/health.py`
      (data-model.md). Depends on T002.
- [X] T005 [P] `HealthBus` (keyless pub/sub tick) in new
      `backend/app/storage/health_bus.py`, mirroring
      `backend/app/storage/notification_bus.py`.
- [X] T006 [P] `HealthOut` Pydantic schema (`name`, `state`,
      `checked_at`) in `backend/app/schemas.py` (contracts/health-api.md).
- [X] T007 [P] `GitHubClient.check_health()` (`GET /user`) plus
      `GitHubTaskSource.check_health()` / `GitHubCodeHost.check_health()`
      delegating to it, in `backend/app/services/github.py` /
      `backend/app/services/github_tasksource.py` (research.md R2).
      Never raises — any exception from the request is caught and
      becomes `False`. Depends on T002.
- [X] T008 [P] `JiraTaskSource.check_health()` (`GET /myself`) in
      `backend/app/services/jira.py`. Never raises. Depends on T002.
- [X] T009 [P] `GitLabCodeHost.check_health()` (`GET /user`; same
      endpoint shape covers the `is_gitea=True` case) in
      `backend/app/services/gitlab.py`. Never raises. Depends on T002.
- [X] T010 [P] `FixtureTaskSource.check_health()` returning `True`
      unconditionally, with no I/O (FR-012), in
      `backend/app/services/fixture.py`. Depends on T002.
- [X] T011 [P] Foundational tests: `HealthStore.set`/`list_all` state
      transitions and stable ordering in
      `backend/tests/test_health_store.py`. Depends on T004.
- [X] T012 [P] Foundational tests: per-adapter `check_health()` contract
      — success returns `True`; an HTTP error, a connection failure, and
      (where relevant) a malformed response each return `False` without
      raising — in `backend/tests/test_health_port.py`, covering GitHub,
      Jira, GitLab, and fixture (contracts/health-check-port.md).
      Depends on T007-T010.

**Checkpoint**: Port capability, every adapter's implementation, the
in-memory store, and the pub/sub bus exist; no poll cycle or HTTP surface
yet.

---

## Phase 3: User Story 1 - See integration health at a glance (Priority: P1) 🎯 MVP

**Goal**: Every configured source's health is checked automatically on a
recurring background cycle and shown as a persistent, always-visible
app-bar indicator.

**Independent Test**: quickstart.md Scenarios 1, 2, 4, 5.

### Tests for User Story 1 ⚠️

- [X] T013 [P] [US1] `HealthPollService.run_cycle()` checks every
      registered entry sequentially and updates `HealthStore` accordingly,
      in `backend/tests/test_health_poll.py`.
- [X] T014 [P] [US1] A hanging check is bounded by
      `health_check_timeout_seconds`, reported unhealthy, and does not
      delay the remaining entries' checks in the same cycle (research.md
      R3, spec.md edge case) — `backend/tests/test_health_poll.py`.
- [X] T015 [P] [US1] Bootstrap registers exactly one entry for a GitHub
      profile (task-source + code-host share one connection) but
      independent entries for Jira's task source and its configured
      GitLab code host (FR-010, research.md R6) —
      `backend/tests/test_health_poll.py` (or a bootstrap-focused test
      module if that reads more clearly once bootstrap.py is written).
- [X] T016 [P] [US1] `GET /api/health` returns every registered entry,
      each starting in the `unknown` state before any cycle has run
      (FR-009); `GET /api/health/events` streams the current snapshot
      immediately on connect and a fresh snapshot after a bus tick — in
      `backend/tests/test_health_api.py`.
- [X] T017 [P] [US1] `useSourceHealth` composable connects to
      `/api/health/events` and exposes the pushed list reactively, in
      `frontend/tests/composables/useSourceHealth.test.ts` (HTTP/SSE
      mocked per Constitution III).
- [X] T018 [P] [US1] `SourceHealthIndicator` renders the correct
      icon/tone for `unknown`/`healthy`/`unhealthy` per entry, using
      Vuetify theme tokens only, in
      `frontend/tests/components/SourceHealthIndicator.test.ts`.

### Implementation for User Story 1

- [X] T019 [US1] `HealthPollService` in `backend/app/services/health.py`:
      holds the hand-curated `list[tuple[str, Callable[[], Awaitable[bool]]]]`
      passed in at construction; `run_cycle()` runs each entry's check
      sequentially wrapped in `asyncio.wait_for(..., health_check_timeout_seconds)`,
      writes the result to `HealthStore`, and publishes one `HealthBus`
      tick per cycle (research.md R3). Depends on T004, T005.
- [X] T020 [US1] `PollSource` conformance on `HealthPollService`: `name`
      property, `list_work_items()` returning `[]` (no dry-run listing —
      mirrors `FeedbackPollService`), `run_forever()` running an initial
      cycle immediately then every `health_check_interval_seconds`.
      Depends on T019.
- [X] T021 [US1] Bootstrap wiring: build the hand-curated `(label,
      check_fn)` list from the already-constructed adapters in
      `backend/app/services/workflows/bootstrap.py` (or a small dedicated
      `get_health_poll_service()` factory next to it) — one `"github"`
      entry backed by the shared `GitHubClient` when a GitHub profile is
      configured, one `"jira"` and (when its code host is GitLab/Gitea) a
      separate `"gitlab"`/`"gitea"` entry, one `"fixture"` entry.
      Depends on T007-T010, T019.
- [X] T022 [US1] Register the health poll service in
      `backend/app/services/poll_source.py::configured_poll_sources()`,
      appended whenever any source is configured — no `main.py` change
      needed, since its lifespan already starts/cancels every
      `configured_poll_sources()` entry uniformly. Depends on T021.
- [X] T023 [US1] `backend/app/routers/health.py`: `GET /api/health`
      (list) and `GET /api/health/events` (SSE stream via `HealthBus` +
      `app/sse.py`, mirroring `routers/notifications.py`). Depends on
      T004-T006.
- [X] T024 [US1] Register the health router in `backend/app/main.py`.
      Depends on T023.
- [X] T025 [P] [US1] `frontend/src/types/health.ts`: `HealthState`,
      `SourceHealth` (contracts/health-api.md — must mirror `HealthOut`
      field-for-field per Constitution I).
- [X] T026 [US1] `frontend/src/composables/useSourceHealth.ts`: opens an
      `EventSource` on `/api/health/events`, exposes the current list
      reactively (mirrors `useNotifications.ts`'s `start`/`stop`/push
      shape). Depends on T025.
- [X] T027 [US1] `frontend/src/components/SourceHealthIndicator.vue`:
      one dot/icon per entry with a tooltip naming the source and its
      state (never the underlying cause — FR-002), Vuetify theme tokens
      only. Depends on T026.
- [X] T028 [US1] Wire `<SourceHealthIndicator>` into the app bar in
      `frontend/src/App.vue`, alongside the existing connectivity
      indicator. Depends on T027.

**Checkpoint**: User Story 1 is fully functional and independently
demoable — every configured source's health is visible from any page,
kept fresh by the background cycle alone.

---

## Phase 4: User Story 2 - Manually refresh a source's health (Priority: P2)

**Goal**: An operator can force an immediate recheck of one source
instead of waiting for the next background cycle.

**Independent Test**: quickstart.md Scenario 3.

### Tests for User Story 2 ⚠️

- [X] T029 [P] [US2] `POST /api/health/{name}/refresh` triggers an
      immediate check for that entry and the result reaches
      `GET /api/health` / the SSE stream, in
      `backend/tests/test_health_api.py`.
- [X] T030 [P] [US2] A refresh request for a name with a check already in
      flight (the background cycle's own run, or a concurrent refresh)
      does not start a second concurrent check (FR-005, research.md R7)
      — in `backend/tests/test_health_poll.py`.
- [X] T031 [P] [US2] `POST /api/health/{name}/refresh` for an unregistered
      name returns `404` — in `backend/tests/test_health_api.py`.
- [X] T032 [P] [US2] `useSourceHealth`'s `refresh(name)` action posts to
      the endpoint and relies on the SSE push for the result (no local
      state mutation) — in
      `frontend/tests/composables/useSourceHealth.test.ts`.
- [X] T033 [P] [US2] `SourceHealthIndicator` exposes a refresh control
      per entry that disables itself while that entry's check is in
      flight — in `frontend/tests/components/SourceHealthIndicator.test.ts`.

### Implementation for User Story 2

- [X] T034 [US2] `HealthPollService.refresh(name) -> bool` (`False` when
      `name` is unknown): guarded by a per-entry `asyncio.Lock` so it
      reuses and deduplicates against the same in-flight check the
      background cycle would run, then ticks `HealthBus` once done
      (research.md R7). Depends on T019.
- [X] T035 [US2] `POST /api/health/{name}/refresh` in
      `backend/app/routers/health.py`: `404` on an unknown name, `202`
      otherwise (fire-and-forget — the caller observes the outcome via
      SSE). Depends on T023, T034.
- [X] T036 [US2] `useSourceHealth.ts`: add the `refresh(name)` action.
      Depends on T026.
- [X] T037 [US2] `SourceHealthIndicator.vue`: add the per-entry refresh
      control, disabled/spinner while in flight (derived from whether
      the entry's `checked_at` has advanced since the click, or a local
      "pending" flag cleared by the next SSE frame for that entry).
      Depends on T027, T036.

**Checkpoint**: Both user stories are functional together — automatic
background checks plus an on-demand shortcut.

---

## Phase 5: Polish & Cross-Cutting Concerns

- [X] T038 [P] Document the health-check capability (what "healthy" means
      per adapter, the no-persistence choice, the app-bar placement) in
      `docs/architecture.md`.
- [X] T039 [P] Document `health_check_interval_seconds` /
      `health_check_timeout_seconds` in `config.toml.example` and
      `docs/configuration.md`, alongside the existing
      `poll_interval_seconds` entry.
- [X] T040 Run quickstart.md Scenarios 1-5 manually end-to-end (at least
      one non-fixture source configured) and record any deviation.
- [X] T041 Full verification: `uv run pytest` (backend), `task quality`,
      `npm run lint` / `npm run format:check` / `npm test` / `npm run
      build` (frontend) all green.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS both user
  stories.
- **User Story 1 (Phase 3)**: Depends on Foundational only.
- **User Story 2 (Phase 4)**: Depends on Foundational **and** US1's
  `HealthPollService`/`HealthStore`/API surface (it adds one action and
  one lock to already-existing objects, not a parallel implementation).
- **Polish (Phase 5)**: Depends on both user stories.

### Parallel Opportunities

- All `[P]`-marked Foundational tasks (T002, T003, T005-T012 pairwise
  where files differ) can run in parallel once their own direct
  dependency (T002 for the adapters) is done.
- All `[P]`-marked US1 tests (T013-T018) can run in parallel; T025
  ([P]) can start alongside backend US1 tasks since it touches only a
  new frontend types file.
- All `[P]`-marked US2 tests (T029-T033) can run in parallel.

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 (Setup) + Phase 2 (Foundational).
2. Complete Phase 3 (US1) — automatic background health visible in the
   app bar is the entire value proposition on its own.
3. **STOP and VALIDATE**: quickstart.md Scenarios 1, 2, 4, 5.
4. Phase 4 (US2) is a pure enhancement on top — safe to ship US1 alone
   first if desired.

### Incremental Delivery

1. Setup + Foundational → nothing user-visible yet.
2. US1 → deployable: every configured source's health is visible and
   self-updating.
3. US2 → deployable: adds the manual-refresh shortcut on top.
4. Polish → docs + full verification gate.
