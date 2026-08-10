---

description: "Task list for feature 008-fixture-task-source"
---

# Tasks: Fixture Task Source & Rerun

**Input**: Design documents from `.specify/specs/008-fixture-task-source/`
(`plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`)

**Tests**: **REQUIRED, not optional.** Constitution Principle III (Test-First
Discipline, NON-NEGOTIABLE) mandates tests for every behavior change in this
repo. Every story phase below writes tests before the implementation that
makes them pass. Per the existing repo convention (`test_github_ports.py`,
`test_jira_ports.py`), `FixtureTaskSource`/`FixturePollService` tests use
real temp-directory file I/O rather than mocks (there is no external
subprocess/network boundary to fake) — they must never write outside a
pytest `tmp_path`.

**Organization**: Tasks are grouped by user story (US1/US2/US3, priorities
P1/P2/P1 from `spec.md`) so each story is independently implementable,
testable, and deliverable per `quickstart.md`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no unmet dependency on an incomplete task)
- **[Story]**: US1, US2, or US3 — omitted for Setup/Foundational/Polish tasks
- All file paths are relative to the repository root (`/home/claude/workspace/kestrel`)

## Path Conventions

Existing FastAPI backend layout (`backend/app/{routers,services,persistence}`,
`backend/tests/`) plus the existing Vue frontend (`frontend/src/`,
`frontend/tests/`) — unchanged by this feature. No Alembic migration and no
new frontend component (see `research.md` §3 and `plan.md`'s Project
Structure).

---

## Phase 1: Setup

**Purpose**: Confirm the environment is ready. No new dependency is
introduced by this feature (see `plan.md` Technical Context) — this phase
is intentionally small.

- [X] T001 [P] Confirm the backend dev environment is ready: `cd backend && uv sync && uv run pytest --collect-only` succeeds with no collection errors
- [X] T002 [P] Confirm the frontend dev environment is ready: `cd frontend && npm install && npm run type-check` succeeds with no errors

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The `visibility()` capability and the rerun-refusal mechanism
every user story depends on. No observable behavior yet — nothing returns
`"private"` and nothing calls `rerun()` until User Story 1/2 give it teeth.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T003 Add `visibility() -> Literal["public", "private"]` to the `TaskSource` Protocol in `backend/app/ports.py`, directly beside the existing `supports_time_spent()` (same "static per-source capability" doc language), per `data-model.md`'s `TaskSource` protocol table
- [X] T004 [P] Implement `GitHubTaskSource.visibility() -> "public"` in `backend/app/services/github.py` (depends on T003)
- [X] T005 [P] Implement `JiraTaskSource.visibility() -> "public"` in `backend/app/services/jira.py` (depends on T003)
- [X] T006 [P] Add `RerunNotAllowedError` to `backend/app/services/exceptions.py`, per `data-model.md`
- [X] T007 Register a `RerunNotAllowedError` → HTTP 403 exception handler in `backend/app/main.py` (`{"detail": "rerun is not available for this workflow's task source"}`), per `research.md` §4 (depends on T006)
- [X] T008 Record the Principle I constitution amendment in `.specify/memory/constitution.md`'s "Access model" section: every `TaskSource` declares `visibility()`; GitHub/Jira are `"public"`; rerun is permitted only when `"private"`; existing delete/cleanup were already safe and this doesn't change that. Follow the exact style of the existing 1.2.0 (webhook HMAC) and 1.3.0 (`hooks_dir`) deviation bullets; add a Sync Impact Report entry and bump to 1.4.0 — per `research.md` §7 (depends on T003)

**Checkpoint**: The visibility mechanism and its refusal exception exist and
are constitutionally recorded. Nothing user-visible has changed yet.

---

## Phase 3: User Story 1 - Run a disposable task through the pipeline (Priority: P1) 🎯 MVP

**Goal**: A local, file-backed task flows through the full
refine→design→code→verify pipeline with zero requests to any external
tracker on that task's behalf.

**Independent Test**: Define a fixture task file pointing at a real test
repository, let kestrel pick it up on its next scheduled check, and confirm
a run starts and proceeds exactly as any other source's run would — per
`quickstart.md` Scenario 1.

### Tests for User Story 1

> **NOTE**: Write these tests FIRST; confirm they FAIL before starting the
> matching implementation task.

- [X] T009 [P] [US1] Write `backend/tests/test_fixture_task_source.py` covering `FixtureTaskSource`: `get_task` re-reads a temp `fixtures_dir` file live on every call (no caching); `post_comment`/`attach`/`publish_refined` write only to local files (assert no network call is attempted); `deep_link_ref` returns the file path (or `""` if missing); `transition()` returns `False`; `supports_time_spent()` returns `False`; `visibility()` returns `"private"` — per `contracts/fixture-task-file.md` (fails until T012)
- [X] T010 [P] [US1] Write `backend/tests/test_fixture_poll.py` covering `FixturePollService`: `list_work_items()` returns one `WorkItem(source="fixture-issue", ref="fixture:<slug>", ...)` per file in a temp `fixtures_dir`; a second `run_forever()` pass over the same file does not start a duplicate run (dedup via the existing `task_ref`/`has_run` mechanism) — per `data-model.md`'s `FixturePollService` table (fails until T013)

### Implementation for User Story 1

- [X] T011 [US1] Extend `TaskSourceConfig` in `backend/app/config_models.py`: `type: Literal["github", "jira", "fixture"]`, add `fixtures_dir: str = ""`, extend `_check_required` with the fixture branch requiring `fixtures_dir` — per `data-model.md` (depends on Foundational)
- [X] T012 [US1] Create `backend/app/services/fixture.py` with `FixtureTaskSource`, implementing every `TaskSource` method per `contracts/fixture-task-file.md` and `data-model.md` (depends on T003, T011; makes T009 pass)
- [X] T013 [US1] Create `backend/app/services/fixture_poll.py` with `FixturePollService` implementing `PollSource` (`name`, `list_work_items()`, `run_forever()`), calling `ingestion.maybe_start_run(source="fixture-issue", task_ref=..., code_repo=..., base_branch=...)` per `data-model.md`'s `FixturePollService` table (depends on T011, T012; makes T010 pass)
- [X] T014 [US1] Register `FixturePollService` alongside the existing GitHub/Jira poll services in `configured_poll_sources()`, `backend/app/services/poll_source.py` (depends on T013)
- [X] T015 [US1] Wire a `FixtureTaskSource` instance and a reused `GitHubCodeHost`/`GitLabCodeHost` into `sources["fixture-issue"]`/`code_hosts["fixture-issue"]` inside `get_workflow_service()`, `backend/app/services/workflows/bootstrap.py`, following the existing `jira_sources` wiring block exactly (depends on T012)
- [X] T016 [US1] Document a `[[task_sources]]` fixture entry (with inline comments, reusing the existing `code_host`/`code_host_base_url`/`code_host_token_env` fields) in `config.toml.example`, matching the existing github/jira examples, per `quickstart.md` prerequisites (depends on T011)

**Checkpoint**: A configured fixture task runs end-to-end through the
pipeline with zero requests to GitHub/Jira — `quickstart.md` Scenario 1
passes. This is the MVP: kestrel can now be tested/retried against a
disposable task without touching a real tracker.

---

## Phase 4: User Story 2 - Instantly restart a disposable run (Priority: P2)

**Goal**: Discard a fixture-sourced run's in-progress work and immediately
start a fresh run for the same task, without waiting for the next scheduled
check.

**Independent Test**: With a fixture-sourced run in any state, trigger
rerun and confirm a new run starts immediately with the prior run's branch
and session state discarded — per `quickstart.md` Scenario 2. Depends on
User Story 1 (needs a fixture-sourced run to rerun).

### Tests for User Story 2

> **NOTE**: Write these tests FIRST; confirm they FAIL before starting the
> matching implementation task.

- [X] T017 [P] [US2] Write `backend/tests/test_workflow_rerun.py::test_rerun_success_for_private_source`: given a fixture-sourced run, `WorkflowService.rerun()` abandons it, force-deletes its branch (local + remote), clears its dismissal, and immediately triggers a new run for the same `task_ref` (assert `ingestion.maybe_start_run` is awaited synchronously, not deferred to the next poll) — per `contracts/rerun-endpoint.md` (fails until T020)
- [X] T018 [P] [US2] Write frontend test coverage for `rerun(id)` alongside the existing `cleanup()` test in the `useWorkflows` composable spec: POSTs `/api/workflows/{id}/rerun`, clears `current` if it was the target, refreshes the workflow list — per `contracts/rerun-endpoint.md` (fails until T023)

### Implementation for User Story 2

- [X] T019 [US2] Add `rerunnable: bool` to `WorkflowSummary` and `WorkflowDetail` in `backend/app/schemas.py`, per `data-model.md` (depends on T003)
- [X] T020 [US2] Implement `WorkflowService.rerun(workflow_id)` in `backend/app/services/workflows/service.py`: guard on `self._task_source(run).visibility() != "private"` raising `RerunNotAllowedError`; reuse `_abandon_common` plus `cleanup()`'s branch-delete-and-dismissal-clear logic; immediately call `ingestion.maybe_start_run(...)` with the captured `task_ref`/`code_repo`/`issue_number`/`base_branch`/`source`; return the new run id — per `data-model.md` and `contracts/rerun-endpoint.md` (depends on T006, T019; makes T017 pass)
- [X] T021 [US2] Add `POST /{workflow_id}/rerun` to `backend/app/routers/workflows.py` (returns `{"workflow_id": <new id>}`); compute `rerunnable` in `_detail()`/`_summaries()` as `service._task_source(run).visibility() == "private"` — per `contracts/rerun-endpoint.md` (depends on T020)
- [X] T022 [P] [US2] Add `rerunnable: boolean` to `WorkflowSummary`/`WorkflowDetail` in `frontend/src/types/workflows.ts`, mirroring the backend field (Constitution Principle I type contract) (depends on T019)
- [X] T023 [US2] Add `rerun(id): Promise<void>` to `frontend/src/composables/useWorkflows.ts`, mirroring `cleanup(id)` exactly — per `contracts/rerun-endpoint.md` (depends on T021, T022; makes T018 pass)
- [X] T024 [US2] Add a "Rerun" `v-btn` (`v-if="w.rerunnable"`, `@click.stop="onRerun(w.id)"`) to the sidebar `#append` slot in `frontend/src/components/WorkflowPanel.vue`, next to the existing Clean up/Abandon buttons (depends on T022, T023)

**Checkpoint**: Rerun works end-to-end for a fixture-sourced run, starting a
fresh run within seconds instead of waiting on the poll interval —
`quickstart.md` Scenario 2 passes.

---

## Phase 5: User Story 3 - Protect real tickets from history rewrites (Priority: P1)

**Goal**: Rerun is categorically unavailable — in the UI and if attempted
directly — for any run whose task source is GitHub or Jira; the existing
delete/cleanup actions remain provably unchanged.

**Independent Test**: With a GitHub- or Jira-sourced run, confirm no rerun
control is shown and a direct call is refused with no state change — per
`quickstart.md` Scenario 3.

**Sequencing note**: Although this story shares priority P1 with User
Story 1, it is sequenced last because it *verifies* a mechanism
(`rerun()`'s guard, the `rerunnable` flag, the Rerun button) that must
already exist to be tested against. The guard itself is built defensively
as part of Foundational (T007) and User Story 2 (T020) — it is never
introduced as an afterthought — so this phase adds proof, not new
production code.

### Tests for User Story 3

> **NOTE**: These tests verify behavior that should already be correct by
> construction (T007, T020, T024). A failure here means the earlier task is
> incomplete — fix that task, not this phase.

- [X] T025 [P] [US3] Write `backend/tests/test_workflow_rerun.py::test_rerun_refused_for_public_source`: a GitHub-sourced and a Jira-sourced run each raise `RerunNotAllowedError` from `WorkflowService.rerun()`, with the run's branch, status, and dismissal state left completely unchanged — per `contracts/rerun-endpoint.md` Response 403
- [X] T026 [P] [US3] Write a `backend/tests/test_main.py` (or the existing exception-handler test module) case asserting `RerunNotAllowedError` maps to HTTP 403 with the documented `{"detail": "rerun is not available for this workflow's task source"}` body — per `contracts/rerun-endpoint.md`
- [X] T027 [P] [US3] Write a frontend test asserting the Rerun button is absent for a `WorkflowSummary`/`WorkflowDetail` with `rerunnable: false` (a GitHub/Jira-sourced run) and present when `true` — per `contracts/rerun-endpoint.md`
- [X] T028 [P] [US3] Write a backend regression test pinning today's already-safe behavior: `WorkflowService.delete()` and `.cleanup()` on a GitHub- and a Jira-sourced run never call any `TaskSource` write-back method (`post_comment`/`attach`/`publish_refined`/`transition`) — per spec FR-009, so this feature cannot silently regress that guarantee

### Implementation for User Story 3

None. The safety property under test is enforced by construction in T007
and T020, not by new code added in this phase.

**Checkpoint**: All negative-path and regression assertions pass —
`quickstart.md` Scenario 3 passes; 100% of GitHub/Jira-sourced runs never
expose or accept rerun (SC-003).

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation and final verification across all three stories.

- [X] T029 [P] Note the fixture task source and the `visibility()`/rerun axis in `docs/architecture.md`'s description of the `TaskSource`/`CodeHost` ports, alongside the existing GitHub/Jira description — closes the doc-drift flag pattern used by the 1.2.0/1.3.0 constitution amendments (`research.md` §7)
- [X] T030 [P] Run the full new/extended test set (`backend/tests/test_fixture_task_source.py`, `test_fixture_poll.py`, `test_workflow_rerun.py`, plus the extended frontend spec files) and confirm all pass
- [ ] T031 Walk through `quickstart.md` Scenarios 1–3 manually end-to-end against a real sandbox repository, confirming every "Expect" outcome
- [X] T032 Run `task quality` and fix any violation without adding a suppression, threshold change, or grandfather entry (per `AGENTS.md`) — this gate must pass before the feature is considered done

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately.
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories.
- **User Story 1 (Phase 3)**: Depends on Foundational only. Fully independent — the MVP.
- **User Story 2 (Phase 4)**: Depends on Foundational; in practice needs a
  fixture-sourced run to rerun, so it is exercised against User Story 1's
  output, though its own code changes don't literally import from US1's
  files.
- **User Story 3 (Phase 5)**: Depends on Foundational (T007) and User Story
  2 (T020, T024) — see the Sequencing note in Phase 5. This is the one
  place priority order (P1) and build order diverge, and it's called out
  explicitly rather than silently reordered.
- **Polish (Phase 6)**: Depends on all three user stories being complete.

### Within Each User Story

- Tests are written and confirmed failing before the implementation task
  that makes them pass (Constitution Principle III).
- Config/protocol extensions before the classes that implement them.
- Service-layer methods before the router endpoints that call them.
- Backend schema/type changes before the frontend code that consumes them.

### Parallel Opportunities

- T001/T002 (Setup) run in parallel.
- T004/T005/T006 (Foundational) run in parallel once T003 lands.
- T009/T010 (US1 tests) run in parallel.
- T017/T018 (US2 tests) run in parallel; T022 (frontend type) runs in
  parallel with T020 (backend service method) once T019 lands.
- T025/T026/T027/T028 (all US3 tests) run fully in parallel — no
  interdependency between them.
- T029/T030 (Polish) run in parallel.

---

## Parallel Example: User Story 1

```bash
# Launch both US1 tests together (after Foundational, before implementation):
Task: "Write backend/tests/test_fixture_task_source.py per contracts/fixture-task-file.md"
Task: "Write backend/tests/test_fixture_poll.py per data-model.md's FixturePollService table"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational (blocks everything — but is itself small: one protocol method, two one-line implementations, one exception, one handler, one constitution bullet).
3. Complete Phase 3: User Story 1.
4. **STOP and VALIDATE**: run `quickstart.md` Scenario 1 against a real sandbox repo.
5. This alone delivers the requested "retry workflow without polluting a real source" value — rerun (US2/US3) is additive on top.

### Incremental Delivery

1. Setup + Foundational → mechanism exists, nothing observable yet.
2. Add User Story 1 → validate Scenario 1 → usable for disposable-task testing (MVP).
3. Add User Story 2 → validate Scenario 2 → rerun works for fixture-sourced runs.
4. Add User Story 3 → validate Scenario 3 → the safety property is proven, not assumed.
5. Polish → docs, full test run, `task quality`.

---

## Notes

- [P] tasks touch different files with no unmet dependency on an incomplete task.
- [Story] label maps each task to its user story for traceability.
- Constitution Principle III requires tests to exist and fail first — do not
  skip the "write it, watch it fail" step even though the guard/mechanism
  they test is simple.
- No task in this list requires an Alembic migration (`research.md` §3).
- Total: 32 tasks — 2 Setup, 6 Foundational, 8 US1, 8 US2, 4 US3, 4 Polish.
