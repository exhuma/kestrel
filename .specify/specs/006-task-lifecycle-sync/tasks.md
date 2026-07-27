---

description: "Task list for feature 006-task-lifecycle-sync"
---

# Tasks: Task-Source Lifecycle Sync, Time Tracking, and Operator Hooks

**Input**: Design documents from `.specify/specs/006-task-lifecycle-sync/`
(`plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`)

**Tests**: **REQUIRED, not optional.** Constitution Principle III (Test-First
Discipline, NON-NEGOTIABLE) mandates tests for every behavior change in this repo.
Every story phase below writes tests before the implementation that makes them pass.
Per Principle III and the existing repo convention, `HookRunner` tests mock
`asyncio.create_subprocess_exec` — no test ever spawns a real executable or shells out
to a live GitHub/Jira API (fake HTTP transport, matching `test_github_ports.py`'s
existing convention).

**Organization**: Tasks are grouped by user story (US1/US2/US3, priorities P1/P2/P3
from `spec.md`) so each story is independently implementable, testable, and
deliverable per `quickstart.md`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no unmet dependency on an incomplete task)
- **[Story]**: US1, US2, or US3 — omitted for Setup/Foundational/Polish tasks
- All file paths are relative to the repository root (`/home/claude/workspace/kestrel`)

## Path Conventions

Existing FastAPI backend layout (`backend/app/{routers,services,persistence}`,
`backend/tests/`) — unchanged by this feature; no frontend paths appear below since
this feature is backend-only per the spec's clarified scope.

---

## Phase 1: Setup

**Purpose**: Confirm the environment is ready. No new dependencies are introduced by
this feature (subprocess invocation is stdlib `asyncio`, matching the existing
`services/runner.py`/`services/git.py` pattern) — this phase is intentionally small.

- [X] T001 Confirm the backend dev environment is ready: `cd backend && uv sync`, `uv run pytest --collect-only` succeeds with no collection errors, `uv run alembic current` runs cleanly against a fresh SQLite DB

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The lifecycle-dispatch scaffolding every user story hangs off. No
observable behavior yet — `LifecycleTransitioner` exists and is wired in, but no
`TaskSource` implementation gives it anything to do until User Story 1.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T002 Add the `LifecycleEvent` dataclass and `TaskSource.transition()` /
  `supports_time_spent()` Protocol methods to `backend/app/ports.py`, per
  `contracts/task-source-protocol.md`
- [X] T003 [P] Add the new lifecycle/hooks config fields to `TaskSourceConfig` in
  `backend/app/config_models.py` — `hooks_dir`, `in_progress_label`, `failed_label`,
  `escalated_label`, `rejected_label`, `transition_start`, `transition_done`,
  `transition_failed`, `transition_escalated`, `transition_rejected`,
  `time_spent_field` — all optional, per `data-model.md`'s `TaskSourceConfig` table
  (no `_check_required` changes needed)
- [X] T004 Create `backend/app/services/lifecycle.py` with `LifecycleTransitioner`
  (a `Notifier`-shaped class: synchronous `notify(run) -> None` entry point that
  derives `LifecycleEvent.kind` from `run.status` via the single exclusive mapping in
  `contracts/task-source-protocol.md`'s Invariant table, and schedules async work via
  `loop.create_task` exactly like `TaskSourceNotifier._post`,
  `backend/app/notifications.py:171-198`) and a `render_footer(event, *,
  include_status, include_time)` stub (depends on T002)
- [X] T005 Wire `LifecycleTransitioner` into the `CompositeNotifier` list built in
  `get_workflow_service()` in `backend/app/services/workflows.py:2321-2325`, and add
  an `_is_lifecycle_event(status)` predicate (mirrors `notifications.py`'s
  `_is_notifiable`) so `LifecycleTransitioner.notify()` only acts on `"cloning"`
  (start), `"done"`, `"failed"`, `"escalated"`, `"rejected"` (depends on T004)
- [X] T006 [P] Write the `kind`-exclusivity invariant test in
  `backend/tests/test_lifecycle_transitioner.py`: for every terminal `run.status`,
  assert the built `LifecycleEvent.kind` matches exactly and a
  failed/escalated/rejected run never yields `kind="done"` (depends on T004)

**Checkpoint**: Dispatcher scaffolding exists and its core correctness invariant is
proven by test. Nothing user-visible happens yet — User Story 1 gives it teeth.

---

## Phase 3: User Story 1 - Ticket reflects run status automatically (Priority: P1) 🎯 MVP

**Goal**: Native "in progress"/"done"/failure-terminal status reaches the ticket
(GitHub labels, Jira configured transitions), with a comment-footer fallback wherever
the native attempt doesn't succeed — never conflating a failure terminal with "done".

**Independent Test**: `quickstart.md` §2, steps 1-3 and 7-8 (label appears on start,
is removed and replaced with a distinct failure label on a failing run — no time
tracking or hooks required for this story to be fully meaningful).

### Tests for User Story 1

> Write these tests FIRST; confirm they fail before starting the implementation tasks below.

- [X] T007 [P] [US1] Write `GitHubTaskSource.transition()`/`supports_time_spent()`
  tests (fake HTTP transport, no live GitHub calls) in `backend/tests/test_github_ports.py`
  — correct label add/remove per `event.kind`, correct `bool` return when a label
  field is configured vs. emptied, `supports_time_spent()` always `False`
- [X] T008 [P] [US1] Write `JiraTaskSource.transition()`/`supports_time_spent()` tests
  (fake HTTP transport) — `transition_issue`
  called only when the matching `transition_*` field is non-empty, a
  configured-but-failing call (mocked 4xx/5xx) returns `False` without raising,
  `supports_time_spent()` matches whether `time_spent_field` is set. **Deviation**:
  added to the existing `backend/tests/test_jira_client.py` (which already covers
  `JiraTaskSource`) instead of a new `test_jira_ports.py`, matching this repo's
  existing one-file-per-adapter test convention.
- [X] T009 [P] [US1] Write `render_footer()` tests (status-only / neither, since
  time-related cases land in User Story 2) in
  `backend/tests/test_lifecycle_transitioner.py`

### Implementation for User Story 1

- [X] T010 [P] [US1] Implement `GitHubClient.add_label` and a label-remove method,
  plus `GitHubTaskSource.transition()` / `supports_time_spent()`, in
  `backend/app/services/github.py` per `research.md` §3 (start → add
  `in_progress_label`; done → remove it only, never force-close the issue; failure
  terminals → remove it and add the matching terminal label) (depends on T002, T003;
  makes T007 pass)
- [X] T011 [P] [US1] Implement `JiraClient.transition_issue(key, transition_id)` and
  `JiraTaskSource.transition()` / `supports_time_spent()` (time-write logic deferred
  to User Story 2 — for now `supports_time_spent()` reflects whether
  `time_spent_field` is configured, but nothing writes to it yet) in
  `backend/app/services/jira.py` (depends on T002, T003; makes T008 pass)
- [X] T012 [P] [US1] Implement `render_footer()`'s status-line logic in
  `backend/app/services/lifecycle.py` (time-line logic deferred to User Story 2)
  (depends on T004; makes T009 pass)
- [X] T013 [US1] Complete `LifecycleTransitioner.notify()` in
  `backend/app/services/lifecycle.py`: call `source.transition(ref, event)`, then post
  the footer via `TaskSource.post_comment` for whatever the native attempt didn't
  cover (status only, at this point in the build) (depends on T010, T011, T012)
- [X] T014 [US1] Integration test in `backend/tests/test_lifecycle_transitioner.py`:
  drive a fake-sourced run through `start → done` and `start → failed`, assert the
  correct native label/transition calls happened and the footer carries exactly the
  status line the fake source didn't natively apply (depends on T013)

**Checkpoint**: User Story 1 is fully functional and independently testable per
`quickstart.md` §2 (steps 1-3, 7-8) — a ticket now reflects real run status, with no
dependency on time tracking or hooks.

---

## Phase 4: User Story 2 - Accurate time-spent reporting (Priority: P2)

**Goal**: A 3-state active/wait clock on `WorkflowRun`, persisted, reported to a
native Jira field when configured and via the footer otherwise — independent of
whether the operator has configured hooks.

**Independent Test**: `quickstart.md` §2, steps 4-6 (a run with a deliberate approval
pause reports wait time approximating that pause, and active time excluding it).

### Tests for User Story 2

> Write these tests FIRST; confirm they fail before starting the implementation tasks below.

- [X] T015 [P] [US2] Write `_set_clock` accumulation tests in
  `backend/tests/test_active_time.py` — active→waiting→active→terminal across
  multiple gate rounds, asserting `active_seconds`/`wait_seconds` accumulate
  independently and correctly (not a naive `done_at - created_at` split), per
  `data-model.md`'s state machine

### Implementation for User Story 2

- [X] T016 [P] [US2] Add `active_seconds`, `wait_seconds`, `clock_state`,
  `clock_since` fields to `WorkflowRun` in `backend/app/models_workflow.py`, per
  `data-model.md`
- [X] T017 [P] [US2] Add matching nullable/`server_default` columns to
  `WorkflowRunRow` in `backend/app/persistence/tables.py`, and map them in
  `WorkflowStore.save()` in `backend/app/persistence/workflow_store.py`, following the
  exact pattern of the existing `boundary` column
- [X] T018 [US2] Create Alembic migration
  `backend/alembic/versions/0012_run_lifecycle_time.py` adding the four columns
  (nullable/`server_default`, no backfill), following the pattern of
  `0011_workflow_run_boundary.py` (depends on T017)
- [X] T019 [P] [US2] Implement `_set_clock(run, state, now)` in new
  `backend/app/services/time_tracking.py` per `data-model.md`'s state machine
  (depends on T016; makes T015 pass)
- [X] T020 [US2] Add `_set_clock` call sites in `backend/app/services/workflows.py`
  per `data-model.md`'s call-site table: start (after `run.status = "cloning"`),
  gate-enter (each `awaiting_refine_input`/`awaiting_refine_approval` assignment),
  gate-leave (the refine gate resolution back into `"refining"`), and the centralized
  terminal-stop inside `_save()` (depends on T019)
- [X] T021 [US2] Populate `LifecycleEvent.active_seconds`/`wait_seconds` from
  `run.active_seconds`/`run.wait_seconds` in `LifecycleTransitioner`
  (`backend/app/services/lifecycle.py`); implement the Jira `time_spent_field` native
  write in `JiraTaskSource.transition()` (`backend/app/services/jira.py`); complete
  `render_footer()`'s time-line logic (wait time is always footer-only, per the
  clarified spec decision) (depends on T011, T012, T013, T016)
- [X] T022 [US2] Integration test: drive a
  fake-sourced run through zero, one, and multiple approval gates through to
  completion; assert `active_seconds`/`wait_seconds` are correct and reported via the
  native Jira field (when configured) or the footer (depends on T020, T021).
  **Deviation**: added as `test_active_and_wait_seconds_accumulate_through_both_gates`
  in `backend/tests/test_workflow_service.py` (reusing its existing `_service`/
  `_FakeGitHub`/`_FakeRunner`/`_wait` fixtures — driving the full pipeline through a
  real `WorkflowService` needs that harness) rather than `test_active_time.py`, which
  holds only the pure `_set_clock` unit tests. Covers one input-gate round + one
  approval-gate round with a real (small, injected) delay at each, asserting
  `active_seconds`/`wait_seconds` are both positive and the clock is fully stopped
  (`clock_state is None`) once `done`. The native-Jira-field-write and footer-reporting
  paths are covered separately and already (T008/T021's `test_jira_client.py` cases,
  and `test_lifecycle_transitioner.py`'s footer tests) — duplicating a full pipeline
  run per source/config combination here would not add coverage beyond those.

**Checkpoint**: User Story 2 is fully functional and independently testable per
`quickstart.md` §2 (steps 4-6), layered on User Story 1 without modifying its
behavior.

---

## Phase 5: User Story 3 - Operator-defined custom actions per lifecycle event (Priority: P3)

**Goal**: A per-task-source `hooks_dir` mechanism, strictly additive to User Stories 1
and 2, giving operators an escape hatch for platform-specific actions kestrel can't
anticipate — with the required constitution amendment landed first, per Principle I.

**Independent Test**: `quickstart.md` §3 (a hook script observes every lifecycle
event's JSON payload and kestrel's own credentials; a hanging/failing hook never
blocks the run or kestrel's own native transition/footer).

- [X] T023 [US3] Amend the "Access model" bullet in Technology & Architecture
  Constraints in `.specify/memory/constitution.md` (currently lines 186-200),
  recording: kestrel now executes arbitrary operator-provided executables from a
  configured, per-task-source `hooks_dir` at defined lifecycle points; those
  executables inherit kestrel's full process environment, including every configured
  credential, by deliberate design; `hooks_dir` and its contents are a
  secret-equivalent trust boundary with no sandboxing beyond failure-isolation and
  startup audit logging. MINOR version bump (1.2.0 → 1.3.0), following the exact
  format of the 2026-07-21 webhook-HMAC amendment in the same file's SYNC IMPACT
  REPORT header. **Blocks the rest of this phase** — per Principle I, the capability
  must be recorded before it is relied upon.

### Tests for User Story 3

> Write these tests FIRST; confirm they fail before starting the implementation tasks below.

- [X] T024 [US3] Write `HookRunner` tests (subprocess mocked via `AsyncMock` on
  `asyncio.create_subprocess_exec` — never spawn a real executable) in
  `backend/tests/test_hooks.py`, per `contracts/hook-wire-format.md`'s test contract:
  success, non-zero exit, timeout at 30s, invalid stdout, the env-inheritance
  regression assertion (mocked call receives no explicit `env=` keyword), and
  `comment_posted` suppression semantics (depends on T023)

### Implementation for User Story 3

- [X] T025 [US3] Implement `HookRunner` in new `backend/app/services/hooks.py`:
  discovery (executable files directly inside `hooks_dir`, filename-sorted),
  invocation (`asyncio.create_subprocess_exec`, no `env=` override, JSON stdin via
  `communicate(input=...)`, `asyncio.wait_for(..., timeout=30)`), stdout parsing
  (`comment_posted`), and failure isolation/logging per `contracts/hook-wire-format.md`
  (depends on T023; makes T024 pass)
- [X] T026 [US3] Implement startup audit logging in `backend/app/services/hooks.py`:
  for each configured `hooks_dir`, log every executable file found (path;
  `WARNING` if group/world-writable, `INFO` otherwise), wired into app startup, using
  kestrel's existing structured-logging setup (depends on T025). Wired into
  `backend/app/main.py`'s `_lifespan()`, iterating `settings.task_sources` — matches
  that function's existing local-import style.
- [X] T027 [US3] Wire `HookRunner.run()` into `LifecycleTransitioner.notify()` in
  `backend/app/services/lifecycle.py` — invoke for every lifecycle event when the
  run's task source has `hooks_dir` configured; suppress only the footer's comment
  post when any invoked hook returns `comment_posted: true` (never suppress the
  native `transition()` attempt — additive, always both, per FR-009) (depends on
  T025, T013)
- [X] T028 [P] [US3] Write new `docs/hooks.md`: the hook wire format (linking
  `contracts/hook-wire-format.md`'s schema) and a prominent, unambiguous
  credential-exposure security warning per FR-012 (depends on T023)
- [X] T029 [P] [US3] Document the new `TaskSourceConfig` fields (from T003) in
  `config.toml.example`, alongside the existing `[[task_sources]]` documentation
  (depends on T023)
- [X] T030 [US3] Integration test in `backend/tests/test_hooks.py`: drive a
  fake-sourced run with a mocked hook configured for one task source, assert the hook
  fires for `start`/`done`/each failure kind, kestrel's own native transition and
  footer still fire alongside it, and a timing-out or failing hook never blocks the
  run or a second, well-behaved hook configured for the same source (depends on T026,
  T027)

**Checkpoint**: User Story 3 is fully functional and independently testable per
`quickstart.md` §3, layered on User Stories 1 and 2 without modifying their behavior.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Repo-wide quality gates and end-to-end validation across all three
stories together.

- [X] T031 [P] Run `task quality` (ruff/pylint/vulture/knip/import-linter/
  dependency-cruiser/eslint/jscpd per `AGENTS.md`) and fix any violations across all
  files touched by T002-T030 — no suppressions, no threshold edits (per `AGENTS.md`'s
  hard-constraint rule). Fixed one real finding introduced by this feature: vulture
  flagged `TaskSource` as an unused import in `lifecycle.py` (it's TYPE_CHECKING-only,
  referenced solely in a quoted forward-reference annotation vulture can't parse) —
  added it to `backend/.vulture_allowlist.py`, the project's sanctioned mechanism for
  exactly this class of false positive (not a suppression of a real issue). One
  pre-existing, unrelated failure remains and was left untouched: `tests/test_verify_loop.py`
  exceeds the 500-line pylint limit (635 lines) — confirmed via `git diff`/line-count
  against `HEAD` that this file was already at 635 lines before this feature touched
  anything; fixing it is out of this feature's scope.
- [X] T032 Run the full backend test suite (`cd backend && uv run pytest`) and confirm
  no regressions outside this feature's own new tests. 555 passed (498 pre-existing +
  57 new/extended across this feature), 0 failed, throughout every checkpoint.
- [X] T033 Run `quickstart.md` end-to-end validation in full: the automated-test
  section, the migration smoke test, the manual GitHub status/time walkthrough, and
  the manual hooks walkthrough. **Scope note**: this sandbox has no live GitHub/Jira
  credentials or repo access, so the literal "trigger a real GitHub issue" steps in
  §2 could not be run; that path is exercised instead by
  `test_active_and_wait_seconds_accumulate_through_both_gates` (T022) end-to-end
  through the real `WorkflowService` driver with a fake GitHub client. What *was* run
  for real (no mocks): the automated-test section (T032); the migration upgrade AND
  downgrade against fresh SQLite DBs; booting the real FastAPI app
  (`create_app`/`_lifespan`) with a configured `hooks_dir`, confirming the startup
  audit log fires and correctly flags a deliberately world-writable hook at
  `WARNING`; and a real (unmocked) `HookRunner.run()` subprocess invocation, verifying
  the hook received the exact wire-format JSON on stdin and could see
  `KESTREL_GITHUB_TOKEN` in its environment — direct proof of both the payload
  contract and the credential-inheritance design.
- [X] T034 [P] Add a pointer to the new lifecycle-sync/time-tracking/hooks behavior
  (linking `docs/hooks.md`) in `docs/setup-github-workflow.md` and
  `docs/setup-jira-workflow.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup — **BLOCKS all user stories**.
- **User Story 1 (Phase 3)**: Depends on Foundational only. No dependency on US2/US3.
- **User Story 2 (Phase 4)**: Depends on Foundational. Touches
  `services/lifecycle.py` and `services/jira.py` files US1 already edited (T021
  extends T011/T012/T013's work), so in practice implement after US1 — but US2's own
  *behavior* (the clock, its persistence) does not require US1's status-transition
  behavior to function, and US2 is independently testable per `quickstart.md` §2
  without any hook configured.
- **User Story 3 (Phase 5)**: Depends on Foundational (`LifecycleTransitioner` must
  exist) and on T013 (US1's `notify()` completion, which T027 extends). Fully additive
  — does not modify US1/US2 behavior, only adds a new dispatch alongside it.
- **Polish (Phase 6)**: Depends on all three user stories being complete.

### Within Each User Story

- Tests are written first and MUST fail before the implementation tasks that follow.
- Protocol/model additions before service implementations.
- Service implementations before the integration test that exercises them together.

### Parallel Opportunities

- Foundational: T003 [P] alongside T002; T006 [P] alongside T005 (both depend only on
  T004).
- US1: T007, T008, T009 [P] together (independent test files); T010, T011, T012 [P]
  together (independent implementation files, all depending only on Foundational).
- US2: T016, T017 [P] together; T019 [P] alongside T017/T018 (depends only on T016).
- US3: T028, T029 [P] together (independent doc files, both depend only on T023).
- Different user-story **phases** are not safe to parallelize against each other in
  practice, since US2 and US3 both extend files US1 already wrote (`lifecycle.py`,
  and for US3 also `notify()`'s body) — implement in priority order (US1 → US2 → US3)
  even though the design is conceptually additive.

---

## Parallel Example: User Story 1

```bash
# Tests together:
Task: "GitHubTaskSource.transition()/supports_time_spent() tests in backend/tests/test_github_ports.py"
Task: "JiraTaskSource.transition()/supports_time_spent() tests in backend/tests/test_jira_ports.py"
Task: "render_footer() status-only tests in backend/tests/test_lifecycle_transitioner.py"

# Implementation together (after Foundational, before T013):
Task: "GitHubClient.add_label + GitHubTaskSource.transition() in backend/app/services/github.py"
Task: "JiraClient.transition_issue + JiraTaskSource.transition() in backend/app/services/jira.py"
Task: "render_footer() status-line logic in backend/app/services/lifecycle.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational (blocks everything else).
3. Complete Phase 3: User Story 1.
4. **STOP and VALIDATE**: run `quickstart.md` §2 steps 1-3 and 7-8 against a real (or
   sandboxed) GitHub issue.
5. This alone already satisfies the feature's most-requested capability (spec SC-001,
   SC-002) without any time-tracking or hooks work.

### Incremental Delivery

1. Setup + Foundational → scaffolding ready, nothing observable yet.
2. + User Story 1 → tickets reflect real status → validate → this is the MVP.
3. + User Story 2 → time metrics reported → validate independently.
4. + User Story 3 → operator hooks available (after the constitution amendment lands)
   → validate independently.
5. + Polish → quality gates, full regression pass, docs.

---

## Notes

- Re-run `resolve_kits` per concrete step as each phase is reached (standing
  Quartermaster instruction — see `research.md` §12; this repo's kit pins live in
  `.quartermaster.toml`).
- Commit after each task or logical group, per the project's normal workflow.
- `T023` (the constitution amendment) is the one task in this list that is not a code
  change but is nonetheless a hard blocking prerequisite — do not skip or defer it
  past the rest of User Story 3.
- Avoid: same-file conflicts between tasks marked `[P]` in different stories (see
  the parallel-opportunities caveat above); cross-story dependencies beyond the ones
  explicitly named (T021, T027) that would break independent testability.
