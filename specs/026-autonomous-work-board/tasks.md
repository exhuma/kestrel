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

## Phase 1: Setup

**Purpose**: Establish the file/configuration and dependency surface required
by the replacement board.

- [ ] T001 Create the default role folders, manifests, and prompts under
  `specialists/` for requester, pm, uiux, developer, infosec, dba, architect,
  ops, qa, coordinator, coder, verifier, and input-security.
- [ ] T002 Add the `specialists_root` file-only setting, input bounds, lease
  defaults, and board capacity settings in `backend/app/config.py` and
  `backend/config.toml.example`.
- [ ] T003 [P] Add `@vue-flow/core` and its lockfile entry in
  `frontend/package.json` and `frontend/package-lock.json`; document why it is
  lazy-loaded, read-only graph enhancement rather than board state authority.
- [ ] T004 [P] Add specialist-manifest fixtures and safe source/gate input
  fixtures in `backend/tests/fixtures/board/`.

---

## Phase 2: Foundational Board Domain

**Purpose**: Build the durable board primitives and policy that every story
uses. No task-source or UI behavior may depend on the legacy fixed driver after
this phase.

**⚠️ CRITICAL**: Complete this phase before story implementation.

- [ ] T005 [P] Write state, dependency, and cycle-rejection unit tests in
  `backend/tests/test_board_policy.py` from `data-model.md`.
- [ ] T006 [P] Write atomic claim, repository-write lease, stale-result, and
  lease-expiry recovery tests in `backend/tests/test_board_claims.py`.
- [ ] T007 [P] Write immutable artifact provenance and project-material
  selection tests in `backend/tests/test_board_artifacts.py`.
- [ ] T008 Define board enums, typed value objects, card action/result schemas,
  and pure dependency helpers in `backend/app/services/board/models.py` and
  `backend/app/services/board/policy.py` to satisfy T005.
- [ ] T009 Add board ORM rows, indexes, foreign keys, and SQLAlchemy mappings
  for workflows, cards, dependencies, attempts, leases, artifacts, gates,
  untrusted inputs, security reviews, actions, events, and projections in
  `backend/app/persistence/tables.py`.
- [ ] T010 Add Alembic board-schema creation revision in
  `backend/alembic/versions/` and migration tests in
  `backend/tests/test_migrations.py`.
- [ ] T011 Implement focused board persistence stores and transactional
  conditional claim/write-lease operations in
  `backend/app/persistence/board_store.py`,
  `backend/app/persistence/board_artifact_store.py`, and
  `backend/app/persistence/board_projection_store.py` to satisfy T006-T007.
- [ ] T012 Implement the board application service's workflow/card reads,
  revision increments, policy-mediated transitions, and safe event append in
  `backend/app/services/board/service.py`.
- [ ] T013 Adapt `backend/app/storage/workflow_bus.py` to publish committed
  board mutation ticks without embedding mutable payloads.
- [ ] T014 Replace the fixed step-to-backend configuration validation with
  capability-checked specialist/card routing in `backend/app/policy.py` and
  `backend/app/config.py`.
- [ ] T015 Implement strict specialist-root traversal, manifest parsing,
  prompt-file loading, role/default validation, and immutable roster snapshots
  in `backend/app/services/board/specialists.py`.
- [ ] T016 Add specialist loader and capability/permission validation tests in
  `backend/tests/test_board_specialists.py` for invalid manifests, root escape,
  missing defaults, unknown roles, and changed role definitions.
- [ ] T017 Compose board stores, service, roster loader, and existing backend/
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

- [ ] T018 [P] [US1] Add source-task intake and duplicate-content tests in
  `backend/tests/test_board_input_intake.py` for GitHub, Jira, and local task
  source bodies.
- [ ] T019 [P] [US1] Add feedback webhook/poll quarantine tests in
  `backend/tests/test_board_feedback_intake.py` proving suspect input cannot be
  persisted as ordinary feedback, translated, acknowledged, or dispatched.
- [ ] T020 [P] [US1] Add gate/questionnaire/direct-session input boundary tests
  in `backend/tests/test_board_human_input.py`.
- [ ] T021 [P] [US1] Add input-security specialist dispatch contract tests in
  `backend/tests/test_board_input_security.py` for no-tools, no-workspace,
  malformed-result, timeout, and fail-closed behavior.

### Implementation for User Story 1

- [ ] T022 [US1] Implement bounded input normalization, hashing, deterministic
  screening, constrained input-security classification, quarantine creation,
  and release/discard resolution in
  `backend/app/services/board/quarantine.py`.
- [ ] T023 [US1] Implement trust-separated prompt envelopes and constrained
  specialist result validation in `backend/app/services/board/dispatch.py`.
- [ ] T024 [US1] Replace source-task creation in
  `backend/app/services/ingestion.py` with canonical task fetch, protected
  input intake, and accepted-task board workflow creation.
- [ ] T025 [US1] Route webhook and polling feedback through protected intake in
  `backend/app/services/feedback/intake.py`,
  `backend/app/services/feedback/poll.py`, and
  `backend/app/services/feedback/github_events.py`; remove unsafe pre-screen
  acknowledgement and translation paths.
- [ ] T026 [US1] Route workflow gate/questionnaire and direct session prompt
  bodies through protected intake in `backend/app/routers/workflows.py`,
  `backend/app/services/sessions.py`, and
  `backend/app/services/board/service.py`.
- [ ] T027 [US1] Add safe security-review DTOs and release/discard intervention
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

- [ ] T028 [P] [US2] Add coordinator action-schema, validation, replay, and
  forbidden-action tests in `backend/tests/test_board_coordinator.py`.
- [ ] T029 [P] [US2] Add eligibility, parallel read-only dispatch, one-writer,
  no-ready-work, and dependency-wait tests in
  `backend/tests/test_board_scheduler.py`.
- [ ] T030 [P] [US2] Add reconciliation card creation and conflicting-artifact
  tests in `backend/tests/test_board_reconciliation.py`.

### Implementation for User Story 2

- [ ] T031 [US2] Implement bounded coordinator action parsing, action ledger,
  event claiming, and policy-delegated action application in
  `backend/app/services/board/coordinator.py`.
- [ ] T032 [US2] Implement ready-card eligibility, atomic claims, heartbeats,
  read-only capacity, write leases, completion, and stale-result handling in
  `backend/app/services/board/claims.py`.
- [ ] T033 [US2] Implement card-result acceptance, immutable artifact inputs,
  dependency updates, and reconciliation-card creation in
  `backend/app/services/board/artifacts.py`.
- [ ] T034 [US2] Implement event-driven specialist claiming and backend turn
  dispatch in `backend/app/services/board/dispatch.py` and trigger coordinator
  scheduling from `backend/app/services/board/service.py`.
- [ ] T035 [US2] Replace static profile lookup and generic role fallback in
  `backend/app/profiles.py` and fixed profile callers under
  `backend/app/services/workflows/interview/` with validated specialist roles.

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

- [ ] T036 [P] [US3] Add restart/expiry/retry/reassign/escalate recovery tests
  in `backend/tests/test_board_recovery.py`.
- [ ] T037 [P] [US3] Add durable artifact content-store, provenance, retention,
  and commit-exclusion tests in `backend/tests/test_board_artifact_content.py`.
- [ ] T038 [P] [US3] Add duplicate/late external projection recovery tests in
  `backend/tests/test_board_projection_recovery.py`.

### Implementation for User Story 3

- [ ] T039 [US3] Implement durable artifact content storage, immutable revision
  writes, provenance reads, and project-material selection in
  `backend/app/services/board/artifacts.py`.
- [ ] T040 [US3] Implement startup and periodic claim/projection expiry recovery
  in `backend/app/services/board/recovery.py` and register it from
  `backend/app/main.py` or the existing lifespan composition root.
- [ ] T041 [US3] Update `backend/app/services/git.py` and delivery handoff code
  to commit only project-material board artifacts and exclude orchestration-only
  content from target repositories.
- [ ] T042 [US3] Remove the fixed driver's mid-step restart failure behavior in
  `backend/app/services/workflows/driver/__init__.py` and replace its callers
  with board recovery entry points.

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

- [ ] T043 [P] [US4] Add human-gate revision, decision provenance, PRD scope,
  and targeted invalidation tests in `backend/tests/test_board_gates.py`.
- [ ] T044 [P] [US4] Add revisioned intervention conflict and stale-action tests
  in `backend/tests/test_board_interventions.py`.

### Implementation for User Story 4

- [ ] T045 [US4] Implement revisioned human-gate cards, decision records,
  approved PRD authority, and targeted downstream invalidation in
  `backend/app/services/board/gates.py` and
  `backend/app/services/board/service.py`.
- [ ] T046 [US4] Implement policy-mediated retry, cancel, reassign, resolve
  gate, release/discard quarantine, and coordinator-review interventions in
  `backend/app/services/board/interventions.py`.
- [ ] T047 [US4] Replace fixed gate control queues and positional re-entry in
  `backend/app/services/workflows/gate.py`,
  `backend/app/services/workflows/reentry.py`, and
  `backend/app/services/feedback/dispatch.py` with card-targeted board events.

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

- [ ] T048 [P] [US5] Add verifier finding classification and internal
remediation tests in `backend/tests/test_board_verifier_routing.py`.
- [ ] T049 [P] [US5] Add ambiguity, conflict, infeasibility, and policy-risk
  escalation tests in `backend/tests/test_board_verifier_escalation.py`.

### Implementation for User Story 5

- [ ] T050 [US5] Define the closed verifier finding/result schema and validate
  it in `backend/app/services/board/validation.py`.
- [ ] T051 [US5] Replace the fixed code/verify loop in
  `backend/app/services/workflows/driver/code_verify.py` with code, check,
  verify, remediation, and coordinator-escalation card behavior in
  `backend/app/services/board/verification.py`.
- [ ] T052 [US5] Replace fixed CI repair resumption in
  `backend/app/services/workflows/ci.py` with policy-bounded CI evidence and
  repair cards in `backend/app/services/board/verification.py`.

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

- [ ] T053 [P] [US6] Add board DTO serialization, safe quarantine-field, and
  snapshot SSE tests in `backend/tests/test_workflows_router.py`.
- [ ] T054 [P] [US6] Add mirrored board contract and graph-projection tests in
  `frontend/tests/lib/boardGraph.test.ts` and
  `frontend/tests/types/workflows.test.ts`.
- [ ] T055 [P] [US6] Add Board/List state grouping, safe review rendering,
  permitted action, keyboard focus, and narrow-layout tests in
  `frontend/tests/components/WorkBoard.test.ts`.
- [ ] T056 [P] [US6] Add graph selection, filtering, and no-mutation interaction
  tests in `frontend/tests/components/WorkflowGraph.test.ts`.

### Implementation for User Story 6

- [ ] T057 [US6] Replace fixed step schemas with board summary, detail, card,
  artifact, relation, gate, and intervention schemas in
  `backend/app/schemas.py`.
- [ ] T058 [US6] Replace fixed-step routes with board collection/detail/card,
  revisioned intervention, and board snapshot SSE routes in
  `backend/app/routers/workflows.py`.
- [ ] T059 [US6] Replace fixed workflow types and step constants with the
  mirrored board contract in `frontend/src/types/workflows.ts`.
- [ ] T060 [US6] Adapt selected-workflow HTTP/SSE lifecycle, board revisions,
  stale action errors, and card interventions in
  `frontend/src/composables/useWorkflows.ts`.
- [ ] T061 [US6] Implement accessible state-grouped Board/List, responsive card
  detail, security-review summary, safe confirmation dialogs, and live status
  announcements in `frontend/src/components/WorkBoard.vue`,
  `frontend/src/components/WorkCardDetail.vue`, and
  `frontend/src/components/WorkflowPanel.vue`.
- [ ] T062 [US6] Implement deterministic card/relation-to-graph projection in
  `frontend/src/lib/boardGraph.ts`.
- [ ] T063 [US6] Implement lazy-loaded, read-only Vue Flow graph selection,
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

- [ ] T064 [P] [US7] Add projection eligibility, idempotency, retry, and
  no-routine-update tests in `backend/tests/test_board_projections.py`.
- [ ] T065 [P] [US7] Add public/private visibility and cleanup-ownership tests
  in `backend/tests/test_board_projection_cleanup.py`.

### Implementation for User Story 7

- [ ] T066 [US7] Implement projection planning, durable idempotency records,
  Kestrel-owned external artifact ledger, and retry handling in
  `backend/app/services/board/projections.py`.
- [ ] T067 [US7] Replace fixed workflow lifecycle/source notification behavior
  in `backend/app/notifications.py` and
  `backend/app/services/lifecycle.py` with allowed board milestone projections.
- [ ] T068 [US7] Replace fixed decomposition child publication and scheduling in
  `backend/app/services/workflows/driver/technical_analysis.py` and
  `backend/app/services/task_scheduler.py` with coordinator-created child cards
  and source projections.
- [ ] T069 [US7] Adapt cleanup and rerun policy in
  `backend/app/services/workflows/reset.py` to use the projection ownership
  ledger and preserve public forward-only constraints.

**Checkpoint**: Task sources carry approvals, material blockers, artifacts,
child work, and delivery outcomes without becoming a noisy board mirror.

---

## Phase 10: Clean Break, Documentation, and Quality

**Purpose**: Remove obsolete fixed-workflow behavior, complete operator
documentation, and prove end-to-end behavior.

- [ ] T070 Delete obsolete fixed driver modules under
  `backend/app/services/workflows/driver/` and remove their imports/tests after
  equivalent board coverage is passing.
- [ ] T071 Remove legacy workflow-step models, stores, review/gate fields, and
  fixed profile registry in `backend/app/models_workflow.py`,
  `backend/app/persistence/workflow_store.py`, and `backend/app/profiles.py`.
- [ ] T072 Create a final Alembic clean-break revision in
  `backend/alembic/versions/` that drops legacy fixed-workflow tables and
  preserves only semantically valid retained records/FKs.
- [ ] T073 [P] Update system context, task-source setup guides, configuration
  reference, and operator security guidance in `docs/architecture.md`,
  `docs/setup-github-workflow.md`, `docs/setup-jira-workflow.md`,
  `docs/setup-local-tasks.md`, and `docs/configuration.md`.
- [ ] T074 [P] Update `README.md`, `config.toml.example`, and container/source
  startup documentation for specialist roots, board recovery, direct-prompt
  confirmation, and security review operation.
- [ ] T075 Update `.specify/memory/constitution.md` only if implementation
  introduces a binding trust, access, or cleanup behavior beyond the existing
  recorded constraints; otherwise document explicit no-amendment confirmation
  in the feature completion notes.
- [ ] T076 Run every scenario in
  `specs/026-autonomous-work-board/quickstart.md`, recording outcomes in
  `specs/026-autonomous-work-board/quickstart.md` or follow-up defects.
- [ ] T077 Run `task quality` from the repository root and resolve all findings
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
