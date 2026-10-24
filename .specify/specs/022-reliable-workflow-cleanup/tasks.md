---
description: "Task list for reliable workflow cleanup"
---

# Tasks: Reliable Workflow Cleanup

**Input**: Design documents in `.specify/specs/022-reliable-workflow-cleanup/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md,
contracts/workflow-cleanup.md, quickstart.md

**Tests**: Required by the constitution. Write behavior tests first and ensure
they fail before each implementation slice.

## Phase 1: Setup

**Purpose**: Establish the cleanup artifact vocabulary and migration boundary.

- [X] T001 Add failing artifact-store persistence tests in
  `backend/tests/test_workflow_artifact_store.py`
- [X] T002 Add failing cleanup reset and idempotency tests in
  `backend/tests/test_workflow_cleanup.py`
- [X] T003 Add an Alembic migration for workflow artifact records in
  `backend/alembic/versions/0025_workflow_artifacts.py`

---

## Phase 2: Foundational

**Purpose**: Make workflow-owned artifact records and provider-neutral cleanup
available to every workflow action.

- [X] T004 Implement the `WorkflowArtifact` domain model in
  `backend/app/models_workflow.py`
- [X] T005 Implement `WorkflowArtifactRow` in `backend/app/persistence/tables.py`
- [X] T006 Implement artifact recording, listing, finalization, and retry state
  in `backend/app/persistence/workflow_artifact_store.py`
- [X] T007 Extend `TaskSource` and `CodeHost` cleanup contracts in
  `backend/app/ports.py`
- [X] T008 Wire the artifact store into workflow construction in
  `backend/app/services/workflows/bootstrap.py` and
  `backend/app/services/workflows/service.py`

**Checkpoint**: Every future cleanup action has durable, workflow-scoped
ownership information.

---

## Phase 3: User Story 1 - Fully Reset a Workflow (Priority: P1) MVP

**Goal**: Remove all owned git, source, and code-host artifacts and return the
original task to polling eligibility.

**Independent Test**: Create a workflow with a workspace, local/remote branch,
published PRD, sub-tasks, comments, and change request; cleanup removes or
closes them and the next poll can create a fresh run.

- [ ] T009 [US1] Add failing source/code-host cleanup adapter tests in
  `backend/tests/test_workflow_cleanup.py`
- [X] T010 [US1] Add idempotent delete/close/comment/PRD operations to
  `backend/app/services/github.py` and
  `backend/app/services/github_tasksource.py`
- [X] T011 [US1] Add idempotent delete/close/comment/attachment/PRD operations
  to `backend/app/services/jira.py`
- [X] T012 [US1] Add reversible local-task artifact operations to
  `backend/app/services/local_task_source.py`
- [X] T013 [US1] Record source-body snapshots, PRD publication, comments,
  attachments, sub-tasks, branches, and change requests at creation sites in
  `backend/app/services/workflows/driver/`
- [X] T014 [US1] Implement ordered artifact cleanup and required-failure retry
  behavior in `backend/app/services/workflows/reset.py`
- [ ] T015 [US1] Update cleanup response semantics and tests in
  `backend/app/routers/workflows.py` and
  `backend/tests/test_workflows_router.py`
- [ ] T016 [US1] Remove stale child scheduling records after cleanup in
  `backend/app/persistence/child_task_store.py`

**Checkpoint**: Cleanup fully resets an owned workflow and a next poll accepts
the source task.

---

## Phase 4: User Story 2 - Recover From Partial External Cleanup (Priority: P2)

**Goal**: Cleanup retries safely after missing artifacts and preserves only
unresolved required failures.

**Independent Test**: Manually remove selected artifacts, trigger a required
provider failure and a best-effort comment failure, then retry cleanup.

- [ ] T017 [US2] Add missing-artifact, required-failure, and best-effort
  cleanup tests in `backend/tests/test_workflow_cleanup.py`
- [ ] T018 [US2] Classify provider failures and record bounded retry state in
  `backend/app/services/workflows/reset.py` and
  `backend/app/persistence/workflow_artifact_store.py`
- [ ] T019 [US2] Update cleanup confirmation/error feedback in
  `frontend/src/components/WorkflowPanel.vue`

**Checkpoint**: A cleanup retry is idempotent and gives actionable failures
without blocking a reset for comment-only failures.

---

## Phase 5: User Story 3 - Inspect Workflow Artifacts (Priority: P3)

**Goal**: Let operators see all current workflow-owned artifacts and their
cleanup state.

**Independent Test**: Open a workflow with multiple artifacts, validate the
detail response and dashboard list, then clean up an item and verify it drops
from the display.

- [ ] T020 [P] [US3] Add API schema and router tests for artifact detail in
  `backend/tests/test_workflows_router.py`
- [X] T021 [US3] Add artifact DTOs and detail hydration in
  `backend/app/schemas.py` and `backend/app/routers/workflows.py`
- [X] T022 [P] [US3] Add mirrored artifact types in
  `frontend/src/types/workflows.ts`
- [X] T023 [US3] Render an accessible workflow-artifact list in
  `frontend/src/components/WorkflowPanel.vue`
- [ ] T024 [US3] Add dashboard rendering tests in
  `frontend/src/components/WorkflowPanel.test.ts`

**Checkpoint**: Operators can inspect tracked artifacts and unresolved cleanup
failures in the workflow dashboard.

---

## Phase 6: Polish and Cross-Cutting Concerns

- [X] T025 Update cleanup ownership and retry behavior in
  `docs/architecture.md` and `README.md`
- [ ] T026 Run the end-to-end scenarios in
  `.specify/specs/022-reliable-workflow-cleanup/quickstart.md`
- [ ] T027 Run `task quality` from the repository root

---

## Dependencies & Execution Order

- Phase 1 precedes Phase 2.
- Phase 2 blocks all stories.
- US1 is the MVP and precedes US2 because it introduces cleanup execution.
- US3 may start after Phase 2, but its final dashboard integration follows US1
  so it can display the production artifact states.
- Polish follows all selected stories.

## Parallel Opportunities

- T001 and T002 may be authored in parallel.
- T004 and T005 can proceed in parallel after the migration shape is agreed.
- T010, T011, and T012 are independent adapter implementations.
- T020 and T022 can proceed in parallel after the artifact DTO shape is fixed.

## Implementation Strategy

1. Establish the durable record and cleanup interfaces.
2. Ship US1 first: record every current write and reset all owned artifacts.
3. Strengthen it with US2 retry and missing-resource behavior.
4. Expose the already durable state in the dashboard with US3.
5. Run the full quality gate and documented end-to-end validation.
