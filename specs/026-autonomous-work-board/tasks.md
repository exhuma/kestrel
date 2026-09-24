# Tasks: Autonomous Work Board

**Input**: Design documents from `/specs/026-autonomous-work-board/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`,
`contracts/board-api.md`, and `quickstart.md`

**Tests**: Tests are required by the constitution for this behavior change.
Write each specified test first and verify it fails before implementing its
corresponding behavior. Frontend tests must mock HTTP and SSE boundaries.

**Organization**: Tasks are grouped by user story. Complete Phases 1 and 2
before beginning story phases.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel with other marked tasks after their stated
  prerequisites are complete.
- **[Story]**: Maps a task to a user story in `spec.md`.

## Status (2026-09-26, after Phase 10 clean break + T034 + T041 + T051 +
partial T067)

73/77 tasks fully verified `[x]` complete against actual code (not just
checked off — every one confirmed by reading/grepping the current source
or, for T034/T041/T051, by writing and passing new tests); **T067 is
additionally now partially done** (still `[ ]`, see its own note — gate
decisions project to the task source, the other four FR-033 kinds don't
yet). The old fixed six-step driver is fully removed (commits `33628b4`
backend, `3fc281c` frontend, `483dda2` docs); the board domain's data
model, intake/quarantine, gates/interventions, coordinator planning,
claim/lease bookkeeping + recovery, the read-only Board/Graph UI, the
automatic specialist claim→turn→accept dispatch loop (T034), a real
per-workflow git worktree with `coder` actually able to edit files
(T041), verifier-finding routing into remediation/escalation cards
(T051), **and now a resolved gate's decision posting back to its task
source (T067, partial)** are all solid and tested.

**4 tasks remain open** (T067 among them, partially). Each has a
`**NOT DONE**`/`**PARTIAL**` note in place with exact findings:

| Task | Phase | Gap |
| --- | --- | --- |
| **T067** | 9 (US7) | Partial — see its own note. `kind="gate"` projection is done and tested; `escalation`/`approved_artifact`/`child_work`/`delivery` are not. `write_back.py::post_projection` is the shared, tested mechanism any of these can reuse — the remaining work per kind is a new call site, not new infrastructure. |
| **T068** | 9 (US7) | No decomposition-to-child-cards publication at all. |
| **T069** | 9 (US7) | No rerun/cleanup using the projection ownership ledger. Also the natural place to add push/opening a change request (T041/T051's deferred delivery step, `kind="delivery"`) — a clean verification result creates no follow-up card today, so there is still no explicit "done, ship it" signal anywhere. |
| **T052** | 7 (US5) | CI-pipeline-specific evidence/repair cards — distinct from T051's verifier-finding routing, which is done. Lower priority now: local remediation already works without it. |

Suggested resume order: **finish T067 (escalation projection is the
cheapest next slice — same `write_back.py` infrastructure, two known call
sites) → T068 → T069 → T052**. See each task's note
below for specifics before starting.

## Phase 1: Setup

**Purpose**: Establish the file/configuration and dependency surface required
by the replacement board.

- [x] T001 Create the default role folders, manifests, and prompts under
  `specialists/` for requester, pm, uiux, developer, infosec, dba, architect,
  ops, qa, coordinator, coder, verifier, and input-security.
- [x] T002 Add the `specialists_root` file-only setting, input bounds, lease
  defaults, and board capacity settings in `backend/app/config.py` and
  `backend/config.toml.example`.
- [x] T003 [P] Add `@vue-flow/core` and its lockfile entry in
  `frontend/package.json` and `frontend/package-lock.json`; document why it is
  lazy-loaded, read-only graph enhancement rather than board state authority.
- [x] T004 [P] Add specialist-manifest fixtures and safe source/gate input
  fixtures in `backend/tests/fixtures/board/`.

---

## Phase 2: Foundational Board Domain

**Purpose**: Build the durable board primitives and policy that every story
uses. No task-source or UI behavior may depend on the legacy fixed driver after
this phase.

**⚠️ CRITICAL**: Complete this phase before story implementation.

- [x] T005 [P] Write state, dependency, and cycle-rejection unit tests in
  `backend/tests/test_board_policy.py` from `data-model.md`.
- [x] T006 [P] Write atomic claim, repository-write lease, stale-result, and
  lease-expiry recovery tests in `backend/tests/test_board_claims.py`.
- [x] T007 [P] Write immutable artifact provenance and project-material
  selection tests in `backend/tests/test_board_artifacts.py`.
- [x] T008 Define board enums, typed value objects, card action/result schemas,
  and pure dependency helpers in `backend/app/services/board/models.py` and
  `backend/app/services/board/policy.py` to satisfy T005.
- [x] T009 Add board ORM rows, indexes, foreign keys, and SQLAlchemy mappings
  for workflows, cards, dependencies, attempts, leases, artifacts, gates,
  untrusted inputs, security reviews, actions, events, and projections in
  `backend/app/persistence/tables.py`.
- [x] T010 Add Alembic board-schema creation revision in
  `backend/alembic/versions/` and migration tests in
  `backend/tests/test_migrations.py`.
- [x] T011 Implement focused board persistence stores and transactional
  conditional claim/write-lease operations in
  `backend/app/persistence/board_store.py`,
  `backend/app/persistence/board_artifact_store.py`, and
  `backend/app/persistence/board_projection_store.py` to satisfy T006-T007.
- [x] T012 Implement the board application service's workflow/card reads,
  revision increments, policy-mediated transitions, and safe event append in
  `backend/app/services/board/service.py`.
- [x] T013 Adapt `backend/app/storage/workflow_bus.py` to publish committed
  board mutation ticks without embedding mutable payloads.
- [x] T014 Replace the fixed step-to-backend configuration validation with
  capability-checked specialist/card routing in `backend/app/policy.py` and
  `backend/app/config.py`.
- [x] T015 Implement strict specialist-root traversal, manifest parsing,
  prompt-file loading, role/default validation, and immutable roster snapshots
  in `backend/app/services/board/specialists.py`.
- [x] T016 Add specialist loader and capability/permission validation tests in
  `backend/tests/test_board_specialists.py` for invalid manifests, root escape,
  missing defaults, unknown roles, and changed role definitions.
- [x] T017 Compose board stores, service, roster loader, and existing backend/
  task-source/code-host ports in `backend/app/services/workflows/bootstrap.py`.

**Checkpoint**: Board state, claims, artifacts, specialist definitions, and
policy are durable, capability checked, and testable without the old driver.

---

## Phase 3: User Story 1 - Safely Accept a Task for Autonomous Work (P1) 🎯 MVP

**Goal**: Ingest all source and human-gate input through a fail-closed security
boundary before it can trigger agent work, source writes, or external services.

**Independent Test**: A normal source task creates initial safe board work. A
suspect task, feedback item, or gate edit creates one quarantine review and
cannot trigger dispatch, acknowledgement, translation, source writes, or gate
progress until an operator release.

### Tests for User Story 1

- [x] T018 [P] [US1] Add source-task intake and duplicate-content tests in
  `backend/tests/test_board_input_intake.py` for GitHub, Jira, and local task
  source bodies.
- [x] T019 [P] [US1] Add feedback webhook/poll quarantine tests in
  `backend/tests/test_board_feedback_intake.py` proving suspect input cannot be
  persisted as ordinary feedback, translated, acknowledged, or dispatched.
- [x] T020 [P] [US1] Add gate/questionnaire/direct-session input boundary tests
  in `backend/tests/test_board_human_input.py`.
- [x] T021 [P] [US1] Add input-security specialist dispatch contract tests in
  `backend/tests/test_board_input_security.py` for no-tools, no-workspace,
  malformed-result, timeout, and fail-closed behavior.

### Implementation for User Story 1

- [x] T022 [US1] Implement bounded input normalization, hashing, deterministic
  screening, constrained input-security classification, quarantine creation,
  and release/discard resolution in
  `backend/app/services/board/quarantine.py`.
- [x] T023 [US1] Implement trust-separated prompt envelopes and constrained
  specialist result validation in `backend/app/services/board/dispatch.py`.
- [x] T024 [US1] Replace source-task creation in
  `backend/app/services/ingestion.py` with canonical task fetch, protected
  input intake, and accepted-task board workflow creation.
- [x] T025 [US1] Route webhook and polling feedback through protected intake in
  `backend/app/services/feedback/intake.py`,
  `backend/app/services/feedback/poll.py`, and
  `backend/app/services/feedback/github_events.py`; remove unsafe pre-screen
  acknowledgement and translation paths.
- [x] T026 [US1] Route workflow gate/questionnaire and direct session prompt
  bodies through protected intake in `backend/app/routers/workflows.py`,
  `backend/app/services/sessions.py`, and
  `backend/app/services/board/service.py`.
- [x] T027 [US1] Add safe security-review DTOs and release/discard intervention
  request shapes in `backend/app/schemas.py` and matching types in
  `frontend/src/types/workflows.ts`.

**Checkpoint**: Every external/gate input transport is fail-closed and
deduplicated. Direct operator prompts require recorded confirmation rather than
automatic quarantine.

---

## Phase 4: User Story 2 - Coordinate Independent Specialist Work (P1)

**Goal**: Enable event-driven coordinator planning and independent specialist
claims, while backend policy remains the only state-mutation authority.

**Independent Test**: Two ready read-only cards can be claimed concurrently;
only one writer can claim a repository; a conflicting output creates a
reconciliation card; invalid coordinator actions mutate nothing.

### Tests for User Story 2

- [x] T028 [P] [US2] Add coordinator action-schema, validation, replay, and
  forbidden-action tests in `backend/tests/test_board_coordinator.py`.
- [x] T029 [P] [US2] Add eligibility, parallel read-only dispatch, one-writer,
  no-ready-work, and dependency-wait tests in
  `backend/tests/test_board_scheduler.py`.
- [x] T030 [P] [US2] Add reconciliation card creation and conflicting-artifact
  tests in `backend/tests/test_board_reconciliation.py`.

### Implementation for User Story 2

- [x] T031 [US2] Implement bounded coordinator action parsing, action ledger,
  event claiming, and policy-delegated action application in
  `backend/app/services/board/coordinator.py`.
- [x] T032 [US2] Implement ready-card eligibility, atomic claims, heartbeats,
  read-only capacity, write leases, completion, and stale-result handling in
  `backend/app/services/board/claims.py`.
- [x] T033 [US2] Implement card-result acceptance, immutable artifact inputs,
  dependency updates, and reconciliation-card creation in
  `backend/app/services/board/artifacts.py`.
- [x] T034 [US2] **Done 2026-09-25.** `dispatch.py::dispatch_ready_work` (+
  `DispatchServices`, `_dispatch_one`) now runs one claim→turn→`claims
  .complete(new_state="review")`→`artifacts.submit_result` cycle per
  non-coordinator role. Wired into `bootstrap.py::_trigger_scheduling` (now
  `_wake_and_dispatch`): every committed board mutation wakes the
  coordinator, then tries dispatching each role in turn. Per-specialist
  errors (`SpecialistCapabilityError`, `ReadCapacityExceededError`,
  `CardTurnError`) are caught and logged individually so one role's failure
  never blocks the others; a card left `claimed` after a failure is picked
  up by the existing lease-expiry recovery sweep, not retried inline.
  Covered by `tests/test_board_scheduling.py::TestDispatchReadyWork` (4
  tests: happy path, coordinator exclusion, one-specialist-failure
  isolation, failed-turn-leaves-card-claimed). **Still limited**: every
  turn runs with `cwd=""` (T041 not done — no board git/workspace layer
  exists), so a `FILE_EDITS` specialist (e.g. `coder`) is claimed and
  dispatched correctly but has nowhere real to write; text-only roles work
  end-to-end today. T041 is now the most important remaining gap.
- [x] T035 [US2] Done via a different mechanism than described: `profiles.py`
  and `workflows/interview/` were deleted outright in Phase 10 rather than
  edited in place. The board domain never reused them — `specialists.py`'s
  `SpecialistRoster` (built in Phase 2, T015) is a wholly separate,
  file-backed roster that every board service already resolves roles
  through.

**Checkpoint**: Specialist work is selected from ready cards and all proposed
delegation, graph, and transition changes are policy validated.

---

## Phase 5: User Story 3 - Preserve Work Through Interruption and Recovery (P1)

**Goal**: Retain exact handoffs and safely recover claimed work after process
interruption without committing orchestration-only artifacts to target projects.

**Independent Test**: After restart during a claim, accepted artifacts remain
available, the attempt becomes interrupted, recovery follows retry policy, and
only explicitly project-material artifacts enter a delivered project change.

### Tests for User Story 3

- [x] T036 [P] [US3] Add restart/expiry/retry/reassign/escalate recovery tests
  in `backend/tests/test_board_recovery.py`.
- [x] T037 [P] [US3] Add durable artifact content-store, provenance, retention,
  and commit-exclusion tests in `backend/tests/test_board_artifact_content.py`.
- [x] T038 [P] [US3] Add duplicate/late external projection recovery tests in
  `backend/tests/test_board_projection_recovery.py`.

### Implementation for User Story 3

- [x] T039 [US3] Implement durable artifact content storage, immutable revision
  writes, provenance reads, and project-material selection in
  `backend/app/services/board/artifacts.py`.
- [x] T040 [US3] Implement startup and periodic claim/projection expiry recovery
  in `backend/app/services/board/recovery.py` and register it from
  `backend/app/main.py` or the existing lifespan composition root.
- [x] T041 [US3] **Done 2026-09-26, partial scope — see below.** New
  `app/services/board/workspace.py::WorkspaceService`: a per-repo shared
  bare mirror (`ensure_mirror`) plus one worktree per workflow cut from it
  on demand (`ensure_workspace`, idempotent — an existing worktree is
  reused unchanged, never reset, so it never clobbers a specialist's
  local commits). Wired into `dispatch.py`'s `_resolve_workspace`: a
  `read_only`/`write` card now gets a real, git-backed `cwd` instead of
  `""`, and a `write` card additionally runs with
  `permission_mode="acceptEdits"` (was hardcoded `"plan"` — read-only —
  for every card regardless of `workspace_permission`, a second bug this
  fixed alongside the missing workspace itself). If provisioning fails or
  no workspace/code-host is configured for a card that needs one, the
  dispatch aborts and leaves the card `claimed` for recovery rather than
  silently running a repo-blind turn. `coder`'s prompt now instructs it to
  commit its own work locally (kestrel does not commit on its behalf).
  Covered by `tests/test_board_workspace.py` (4 tests) and
  `tests/test_board_dispatch_workspace.py` (3 tests: write card gets
  `acceptEdits` + real cwd, no-workspace-configured leaves card claimed,
  read-only card gets a workspace but stays in `plan` mode).

  **Deliberately out of scope, matching the module's own docstring**: push,
  opening a change request, and any other "delivery" decision. A coder's
  commits stay local to its worktree; kestrel never pushes or publishes
  them automatically. This is intentional, not an oversight — delivery
  should wait for verification (T051/T052, still not done) to exist, so
  nothing unverified ever reaches a remote. `git.py`'s old
  `diff`/`diff_stat`/`remove_worktree`/`ensure_remote_branch` and any
  project-material commit *filtering* (this task's original literal ask)
  were not carried over either — there is no verify loop yet to make that
  filtering meaningful. Revisit when building T051/T052.
- [x] T042 [US3] Done via deletion: `workflows/driver/__init__.py` (and the
  whole `driver/` package) was removed outright in Phase 10.
  `board/recovery.py`'s startup + periodic sweep (registered in
  `app/main.py`'s lifespan) is the board's only recovery entry point now.

**Checkpoint**: Process loss produces recoverable durable state rather than a
terminal generic workflow failure.

---

## Phase 6: User Story 4 - Keep Human Approvals Visible and Authoritative (P1)

**Goal**: Preserve understanding, refinement, PRD, decomposition, and security
decisions as explicit, revisioned gate cards that control only dependent work.

**Independent Test**: Each gate blocks only its declared dependents; approval
records exact authority; rejection invalidates affected work; suspect human
input leaves its original gate unresolved.

### Tests for User Story 4

- [x] T043 [P] [US4] Add human-gate revision, decision provenance, PRD scope,
  and targeted invalidation tests in `backend/tests/test_board_gates.py`.
- [x] T044 [P] [US4] Add revisioned intervention conflict and stale-action tests
  in `backend/tests/test_board_interventions.py`.

### Implementation for User Story 4

- [x] T045 [US4] Implement revisioned human-gate cards, decision records,
  approved PRD authority, and targeted downstream invalidation in
  `backend/app/services/board/gates.py` and
  `backend/app/services/board/service.py`.
- [x] T046 [US4] Implement policy-mediated retry, cancel, reassign, resolve
  gate, release/discard quarantine, and coordinator-review interventions in
  `backend/app/services/board/interventions.py`.
- [x] T047 [US4] Done via deletion: `workflows/gate.py`, `workflows/reentry.py`,
  and `feedback/dispatch.py` were all removed outright in Phase 10.
  `board/gates.py` + `board/interventions.py` (T045/T046) already provide
  card-targeted gate resolution; nothing further needed replacing.

**Checkpoint**: Human approval remains the scope authority, with no global run
pause or fixed-step rewind.

---

## Phase 7: User Story 5 - Resolve Verification Findings at the Right
Authority (P2)

**Goal**: Keep implementation nonconformance in internal remediation while
moving ambiguity, conflict, infeasibility, and material risk to coordinator
review and, when necessary, a human gate.

**Independent Test**: A clear approved-PRD violation creates remediation work;
an ambiguous criterion creates coordinator review and cannot mutate the PRD.

### Tests for User Story 5

- [x] T048 [P] [US5] Add verifier finding classification and internal
remediation tests in `backend/tests/test_board_verifier_routing.py`.
- [x] T049 [P] [US5] Add ambiguity, conflict, infeasibility, and policy-risk
  escalation tests in `backend/tests/test_board_verifier_escalation.py`.

### Implementation for User Story 5

- [x] T050 [US5] Define the closed verifier finding/result schema and validate
  it in `backend/app/services/board/validation.py`.
- [x] T051 [US5] **Done 2026-09-26.** New
  `app/services/board/verification.py::route_verifier_result`: parses a
  completed `verification` card's turn result via `validation.py`'s
  `parse_verifier_result` (T050) and creates exactly one follow-up card
  per finding — `is_remediation` → a `coder`-eligible, `ready`
  `implementation` card (no dependency: new work, not a revision);
  `is_escalation`, or a result that fails to parse at all (fail closed) →
  a `coordinator_review` card, claimed by no specialist. Every card is
  created exclusively through `CoordinatorService.apply_actions`
  (`CreateCardAction`) — this module never touches the board store
  directly, preserving FR-006's "only the coordinator creates cards."
  Idempotent per verification attempt (`verification:<card.id>
  :<card.attempt_count>` trigger), reusing `apply_actions`'s own
  per-trigger dedup. Wired into `dispatch_ready.py`'s `_dispatch_one`
  (best-effort — a routing failure never undoes the verification card's
  own already-accepted result) and into `_resolve_workspace`: a
  `verification` card now dispatches with `permission_mode="acceptEdits"`
  despite being `read_only`, since it needs to actually run tests/checks
  (tool execution), which the previously-universal `"plan"` mode for
  non-write cards does not reliably support headlessly — a real card
  never edits/commits regardless of this mode; that boundary is enforced
  by its prompt and by `required_abilities` excluding `file_edits`, the
  same trust model the rest of this project already relies on (agent
  instructions + capability-based routing, not a runtime sandbox).
  `verifier`'s prompt now specifies the exact `<VERIFIER_FINDINGS>` output
  format. Covered by `tests/test_board_verification.py` (7 tests:
  remediation/escalation/mixed/clean/unparseable routing, idempotency,
  and one full `dispatch_ready_work` end-to-end integration test).
  `dispatch.py` was split into `dispatch.py` (classification + card/
  coordinator-turn primitives) and `dispatch_ready.py` (the ready-work
  loop) to stay under the 500-line module ceiling.

  **Deliberately still out of scope**: pushing/opening a change request
  once a `coder`'s remediation is verified clean. Nothing currently
  decides "verification passed, therefore deliver" — a clean verification
  result (empty findings) creates no follow-up card at all today, so the
  loop has no explicit "done, ship it" signal yet. That decision point is
  the natural place to finally add T041's deferred push/PR-open step.
- [ ] T052 [US5] **Still NOT DONE.** T051 covers a verifier's own
  findings (code review / local test run style) but nothing about a CI
  pipeline specifically: no CI-status polling, no CI-evidence card, no
  bounded CI-repair-attempt tracking (the old driver's
  `max_ci_repair_iterations` setting still exists in config but has no
  reader). Lower priority than it looked before T051 landed — a repo
  without CI can already get real, verified local remediation today.

**Checkpoint**: Verification preserves autonomous implementation repair without
allowing the verifier to extend approved scope.

---

## Phase 8: User Story 6 - Understand and Intervene in the Work Board (P2)

**Goal**: Give the operator a live, accessible Board/List control surface and a
read-only graph that explains dependencies, ownership, artifacts, and security
state.

**Independent Test**: With a workflow containing every card state, keyboard-only
operators can inspect and invoke every allowed intervention in List/Board; Graph
selects the same detail and does not allow state-changing drag interactions.

### Tests for User Story 6

- [x] T053 [P] [US6] Add board DTO serialization, safe quarantine-field, and
  snapshot SSE tests in `backend/tests/test_workflows_router.py`.
- [x] T054 [P] [US6] Add mirrored board contract and graph-projection tests in
  `frontend/tests/lib/boardGraph.test.ts` and
  `frontend/tests/types/workflows.test.ts`.
- [x] T055 [P] [US6] Add Board/List state grouping, safe review rendering,
  permitted action, keyboard focus, and narrow-layout tests in
  `frontend/tests/components/WorkBoard.test.ts`.
- [x] T056 [P] [US6] Add graph selection, filtering, and no-mutation interaction
  tests in `frontend/tests/components/WorkflowGraph.test.ts`.

### Implementation for User Story 6

- [x] T057 [US6] Replace fixed step schemas with board summary, detail, card,
  artifact, relation, gate, and intervention schemas in
  `backend/app/schemas.py`.
- [x] T058 [US6] Replace fixed-step routes with board collection/detail/card,
  revisioned intervention, and board snapshot SSE routes in
  `backend/app/routers/workflows.py`.
- [x] T059 [US6] Replace fixed workflow types and step constants with the
  mirrored board contract in `frontend/src/types/workflows.ts`.
- [x] T060 [US6] Adapt selected-workflow HTTP/SSE lifecycle, board revisions,
  stale action errors, and card interventions in
  `frontend/src/composables/useWorkflows.ts`.
- [x] T061 [US6] Implement accessible state-grouped Board/List, responsive card
  detail, security-review summary, safe confirmation dialogs, and live status
  announcements in `frontend/src/components/WorkBoard.vue`,
  `frontend/src/components/WorkCardDetail.vue`, and
  `frontend/src/components/WorkflowPanel.vue`.
- [x] T062 [US6] Implement deterministic card/relation-to-graph projection in
  `frontend/src/lib/boardGraph.ts`.
- [x] T063 [US6] Implement lazy-loaded, read-only Vue Flow graph selection,
  filters, fit/focus controls, and Vuetify-theme custom nodes in
  `frontend/src/components/WorkflowGraph.vue` and
  `frontend/src/components/WorkflowPanel.vue`.

**Checkpoint**: Board/List is a complete accessible control surface; Graph is a
read-only explanation/navigation enhancement sharing the same card detail.

---

## Phase 9: User Story 7 - Selectively Project External Milestones (P3)

**Goal**: Keep the internal board authoritative while publishing only
human-meaningful milestones with durable ownership and idempotency.

**Independent Test**: Claims and retries generate no source updates; gates,
blockers, approved artifacts, child tasks, and delivery each project once;
public cleanup only sees recorded Kestrel-owned resources.

### Tests for User Story 7

- [x] T064 [P] [US7] Add projection eligibility, idempotency, retry, and
  no-routine-update tests in `backend/tests/test_board_projections.py`.
- [x] T065 [P] [US7] Add public/private visibility and cleanup-ownership tests
  in `backend/tests/test_board_projection_cleanup.py`.

### Implementation for User Story 7

- [x] T066 [US7] Implement projection planning, durable idempotency records,
  Kestrel-owned external artifact ledger, and retry handling in
  `backend/app/services/board/projections.py`.
- [ ] T067 [US7] **PARTIAL (2026-09-26): gate projection done, the other
  four FR-033 milestone kinds are not.** New
  `app/services/board/write_back.py::post_projection`: plans (via
  `projections.py`, T066), posts via `TaskSource.post_comment()`, and
  resolves (`complete`/`fail`) exactly one projection — idempotent by
  key, a post failure recorded as retryable rather than raised. Wired for
  **`kind="gate"` only**: `routers/board.py`'s `apply_board_intervention`
  calls `bootstrap.py::schedule_gate_projection` (fire-and-forget,
  mirrors `_trigger_scheduling`'s own pattern) after a `resolve_gate`
  intervention succeeds, which resolves the workflow's `TaskSource` via
  `get_task_source_registry()` and posts `"Gate {decision}: {title}"`.
  Covered by `tests/test_board_write_back.py` (3 tests: post-and-complete,
  idempotent re-post, failure-is-retryable-not-raised); the
  `bootstrap.py`/router wiring itself is intentionally untested directly,
  matching this codebase's existing convention for `_trigger_scheduling`
  (no dedicated test either) — trusted by code review plus the full app
  import/startup check.

  **Not done**: `kind="escalation"` (a `coordinator_review` card is
  created in two places — `verification.py` T051 and
  `interventions.py::_request_coordinator_review` — neither posts a
  projection yet); `kind="approved_artifact"`; `kind="child_work"`
  (belongs with T068); `kind="delivery"` (belongs with T069/the push-a-
  verified-coder's-work gap noted under T041/T051). `lifecycle.py` stays
  deleted with no replacement; `notifications.py` still produces nothing.
- [ ] T068 [US7] **NOT DONE.** `workflows/driver/technical_analysis.py` was
  deleted in Phase 10 with no board-domain replacement; `task_scheduler.py`
  survives only as pure branch-selection helpers
  (`integration_branch`/`ScheduledTask`) consulted by `ingestion.py` for an
  *already-linked* child — nothing in the board domain decomposes a task
  and coordinator-creates child cards/tickets yet. Depends on T034/T041
  (something has to actually do the decomposition work first).
- [ ] T069 [US7] **NOT DONE, no equivalent exists.** `workflows/reset.py`
  (rerun) was deleted outright in Phase 10 with no replacement — confirmed
  via the constitution's amendment 1.5.0→1.5.1 ("rerun action... removed").
  There is no cleanup action either. Both would need the projection
  ownership ledger (T066) as their foundation once (re)built.

**Checkpoint**: Task sources carry approvals, material blockers, artifacts,
child work, and delivery outcomes without becoming a noisy board mirror.

---

## Phase 10: Clean Break, Documentation, and Quality

**Purpose**: Remove obsolete fixed-workflow behavior, complete operator
documentation, and prove end-to-end behavior.

- [x] T070 Delete obsolete fixed driver modules under
  `backend/app/services/workflows/driver/` and remove their imports/tests after
  equivalent board coverage is passing.
- [x] T071 Remove legacy workflow-step models, stores, review/gate fields, and
  fixed profile registry in `backend/app/models_workflow.py`,
  `backend/app/persistence/workflow_store.py`, and `backend/app/profiles.py`.
- [x] T072 Create a final Alembic clean-break revision in
  `backend/alembic/versions/` that drops legacy fixed-workflow tables and
  preserves only semantically valid retained records/FKs.
- [x] T073 [P] Update system context, task-source setup guides, configuration
  reference, and operator security guidance in `docs/architecture.md`,
  `docs/setup-github-workflow.md`, `docs/setup-jira-workflow.md`,
  `docs/setup-local-tasks.md`, and `docs/configuration.md`.
- [x] T074 [P] Update `README.md`, `config.toml.example`, and container/source
  startup documentation for specialist roots, board recovery, direct-prompt
  confirmation, and security review operation.
- [x] T075 Update `.specify/memory/constitution.md` only if implementation
  introduces a binding trust, access, or cleanup behavior beyond the existing
  recorded constraints; otherwise document explicit no-amendment confirmation
  in the feature completion notes.
- [x] T076 Run every scenario in
  `specs/026-autonomous-work-board/quickstart.md`, recording outcomes in
  `specs/026-autonomous-work-board/quickstart.md` or follow-up defects.
- [x] T077 Run `task quality` from the repository root and resolve all findings
  without suppressions or quality-threshold changes.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)** begins immediately.
- **Foundational (Phase 2)** depends on Setup and blocks every user story.
- **US1** depends on Foundational and is the recommended MVP: safe accepted
  task intake is required before autonomous scheduling.
- **US2** depends on Foundational and US1 because coordinator dispatch must
  consume only accepted/released input.
- **US3** depends on Foundational and may begin with US2 once claim semantics
  exist.
- **US4** depends on US1 and Foundational; it may proceed alongside US2/US3.
- **US5** depends on US2, US3, and US4 because verifier routing produces cards,
  durable evidence, and scope-bound escalations.
- **US6** depends on Foundational, US1 safe DTOs, and US4 interventions. It may
  begin once stable board read/intervention contracts are implemented.
- **US7** depends on US2, US3, and US4 because it projects coordinator-approved
  milestones and ownership records.
- **Clean Break/Polish (Phase 10)** depends on all selected story phases.

### Parallel Opportunities

- T003 and T004 can run in parallel after T001/T002 design decisions are known.
- T005, T006, and T007 are independent test-first foundation work.
- T018-T021, T028-T030, T036-T038, T043-T044, T048-T049, T053-T056, and
  T064-T065 can each run in parallel within their story phase.
- US3 and US4 can proceed in parallel once US1 and board claim/gate primitives
  are available.
- Board/List work (T061) and graph projection/graph component work (T062-T063)
  can split after T059-T060 establish the frontend contract.
- Documentation tasks T073 and T074 can run in parallel after behavior settles.

## Parallel Example: User Story 6

```text
Task: "Add board DTO/SSE tests in backend/tests/test_workflows_router.py"
Task: "Add graph projection tests in frontend/tests/lib/boardGraph.test.ts"
Task: "Add Board/List accessibility tests in
frontend/tests/components/WorkBoard.test.ts"
Task: "Add graph selection tests in
frontend/tests/components/WorkflowGraph.test.ts"
```

## Implementation Strategy

### MVP First

1. Complete Setup and Foundational phases.
2. Complete US1 through T027.
3. Verify source/gate input quarantine and explicit release/discard behavior.
4. Stop and validate before enabling autonomous specialist execution.

### Incremental Delivery

1. Add US2 for safe autonomous card delegation.
2. Add US3 and US4 for recoverable execution and human scope authority.
3. Add US5 for verifier authority boundaries.
4. Add US6 for complete operator visibility and intervention.
5. Add US7 for selective source projection.
6. Remove the old driver only after equivalent board behavior and tests pass.
