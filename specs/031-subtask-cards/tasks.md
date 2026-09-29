# Tasks: Sub-tasks as cards inside the parent workflow

**Input**: Design documents from `specs/031-subtask-cards/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/board-api-delta.md

**Tests**: required. Constitution Principle III makes them non-negotiable, so
each story's tests are written with or before its code. The scenarios are
listed in quickstart.md.

**Order note**: US1 and US2 are both P1. US2 depends on US1, because it
verifies and delivers the cards that US1 creates. US3 depends on US1 for the
manual cards. US4 (clean break) comes last: it deletes code that US1 makes
unreachable. Commit after each phase, and each commit must pass `task quality`
and both test suites (plan "Suggested commit slices").

## Phase 1: Setup

- [x] T001 Confirm a clean baseline: `task quality`, backend `uv run pytest -q` (note the 2 known failures in `test_claude_backend.py`, which are not ours) and frontend `npm test` / `npm run build`

## Phase 2: Foundational (blocks all stories)

- [x] T002 Create backend/alembic/versions/0033_subtask_cards.py: add a nullable `board_card.task_node_id` (Text) only. Drops come in T041. Add `BoardCardRow.task_node_id` in backend/app/persistence/board_tables.py; add `WorkCard.task_node_id: str | None = None` (docstring) in backend/app/models_board.py; persist and map it in `create_card` / `_row_to_card` in backend/app/persistence/board_store.py
- [x] T003 [P] Migration and store tests: upgrade adds the nullable column and a card round-trips `task_node_id` (in backend/tests/test_migrations.py and backend/tests/test_board_service.py)
- [x] T004 Add `CardKind.MANUAL_TASK = "manual_task"` (docstring comment) in backend/app/models_board.py; map it to "Build" in backend/app/services/board/phases.py; add it to `_CODE_ONLY_CARD_KINDS` in backend/app/services/board/coordinator.py (R8)
- [x] T005 Add the policy edge `waiting_dependency → awaiting_human` in backend/app/services/board/policy.py, and make `advance_ready_dependents` in backend/app/services/board/dependents.py move a `manual_task` card to `awaiting_human` (every other kind still goes to `ready`) (R4)
- [x] T006 [P] Tests: the new edge is legal; the cascade sends a manual card to `awaiting_human` and an implementation card to `ready`; the coordinator cannot create a `manual_task` (backend/tests/test_board_policy.py, a dependents test, backend/tests/test_board_coordinator.py)
- [x] T007 Strict prerequisite validation in `load_candidate` (strict mode) in backend/app/services/board/candidate.py: an unknown id, a self-reference or a cycle raises `DecompositionResultError` (R11). Tests go in backend/tests/test_board_candidate.py

## Phase 3: User Story 1 — Approved tasks become the request's own work (P1) 🎯 MVP

**Goal**: approving CAB-2 creates implementation + verification cards per
coding task and a manual card per manual task in the same workflow, wired by
prerequisites and carrying the approved text. It creates no ticket, and posts
one breakdown comment.

**Independent test**: approve CAB-2 on a candidate with a prerequisite
chain, a manual task and a legacy (id-less) variant. Check the card set, the
edges, the initial states, the `task_spec` artifacts, idempotency, one
comment, and zero `create_subtask` calls.

- [x] T008 [US1] Create backend/app/services/board/materialise.py:
  - `materialise_decomposition(gate_card, store, artifacts, gate_record)` reads the target `cab2_proposal` (`load_candidate(strict=False)`), assigns `t<n>` ids to id-less tasks, and is a no-op when the workflow already has any card with a `task_node_id`;
  - it creates `impl(t)` + `ver(t)` for coding tasks and `man(t)` for manual tasks, and the relations `ver(t)`→`impl(t)` and head(t)→head(p) for each prerequisite *p*, dropping an unknown prerequisite with a warning;
  - initial states are `ready` / `awaiting_human` when a card has no dependency and `waiting_dependency` otherwise;
  - it writes one `task_spec` reference artifact (`operator_approved`) per `impl`/`man` card, rendered by a pure `render_task_spec(task, titles_by_id)`. That function carries over the estimate section from the old `_estimate_section` in decomposition.py (data-model.md).
- [x] T009 [US1] Call `materialise_decomposition` from the approval path of `GatesService.resolve` in backend/app/services/board/gates.py, only for `decomposition_gate`, before `advance_ready_dependents`. Keep gates.py under 500 lines with a single hook method
- [x] T010 [US1] Tests in backend/tests/test_board_materialise.py for every row of the quickstart "materialisation" scenarios:
  - card kinds, roles, permissions, titles and `task_node_id`;
  - edges, including a manual prerequisite, and initial states;
  - `task_spec` content (body, estimate, trust);
  - idempotency, the legacy candidate, the unknown prerequisite, and a candidate with only manual tasks.
- [x] T011 [US1] Envelope: in `_extra_context_for` in backend/app/services/board/dispatch_ready.py, a card with a `task_node_id` gets "Approved task:" followed by the `task_spec` of that node's `implementation` or `manual_task` card, looked up via `ArtifactsService.latest_content_for_card`. Keep the branch count within limits, extracting a helper into materialise.py if needed. Test it in backend/tests/test_board_dispatch_ready.py (or the existing dispatch test module)
- [x] T012 [US1] Coordinator guard in backend/app/services/board/coordinator.py: `_validate_transition` rejects any transition of a card whose `task_node_id` is set (FR-005). Add `CreateCardAction.task_node_id: str | None = None` and persist it in `_apply_one`, making sure the coordinator-output parser never populates it. Test in backend/tests/test_board_coordinator.py: the transition is rejected, and the coordinator can still create its own implementation card
- [x] T013 [US1] Replace publishing with the breakdown comment:
  - in backend/app/services/board/bootstrap.py, rename `schedule_decomposition_publish` → `schedule_breakdown_projection`, which posts one `approved_artifact` projection with the key `approved_artifact:<gate card id>` and a body from `render_breakdown(candidate)` in materialise.py (titles + classification, candidate order);
  - update the call site in backend/app/routers/board.py;
  - remove `publish_decomposition`, `published_body`, `_markers_for` and `_estimate_section` from backend/app/services/board/decomposition.py;
  - remove `"child_work"` from backend/app/services/board/projections.py and the comments in backend/app/persistence/board_tables.py / backend/app/models_board_records.py.
- [x] T014 [US1] Tests: `render_breakdown` output; one projection per approval (a repeat is idempotent); `create_subtask` never called. Replace the publish tests in backend/tests/test_board_decomposition.py and add them to the bootstrap/projection tests
- [x] T015 [P] [US1] Coordinator prompt: add one sentence to backend/specialists/coordinator/prompt.md saying that approved decomposition tasks arrive with their own implementation and verification cards, which must not be duplicated or changed. Add `manual_task` to the card-kind vocabulary in backend/specialists/README.md

## Phase 4: User Story 2 — One request, one pull request (P1)

**Goal**: each task's verification loops through capped remediation, and the
workflow delivers once, after every coding task is cleanly verified.

**Independent test**: scripted verifier results across three tasks. There
is no delivery until the last clean verification, then exactly one; the cap
escalates; a CI repair re-delivers into the same change request.

- [x] T016 [US2] Create backend/app/services/board/verification_rounds.py:
  - `round_of(task_node_id, cards)`;
  - `tagged_follow_ups(card, findings, cap)`, which returns the action batches for a tagged verification card: remediation actions tagged with the node, then a separate re-verification action that depends on the remediation card ids. At the cap it returns one "Verification cap reached: <title>" `coordinator_review` instead. Escalations are handled as today, tagged (R6, data-model.md table).
- [x] T017 [US2] Wire it into `route_verifier_result` in backend/app/services/board/verification.py:
  - a card with a `task_node_id` uses the tagged path, with two `apply_actions` calls under the triggers `verification:<id>:<n>` and `reverification:<id>:<n>`;
  - an untagged card is routed exactly as today;
  - pass the cap through `DispatchServices.verify_round_cap` (backend/app/services/board/dispatch_ready.py), wired from `Settings.max_verify_iterations` in backend/app/services/board/bootstrap.py.
- [x] T018 [US2] Tests in backend/tests/test_board_verification_rounds.py: clean → nothing; findings below the cap → tagged remediation + one re-verification depending on all of them; at the cap → one tagged cap escalation and no remediation; escalations are tagged; an untagged card behaves as before
- [x] T019 [US2] Create backend/app/services/board/delivery_readiness.py with a pure `delivery_due(cards, relations) -> bool` (the two conditions of R7; manual cards ignored) and `delivery_trigger(cards) -> str` (a digest of the done implementation ids)
- [x] T020 [US2] In backend/app/services/board/dispatch_delivery.py, gate `_request_delivery` (still called by a clean verification) on `delivery_due`, with the trigger `delivery:<digest>` (R7 as revised during implementation)
- [x] T021 [US2] Tests in backend/tests/test_board_delivery_readiness.py (pure):
  - open, failed or unverified approved work → false; all clean → true;
  - a manual card open → still true;
  - coordinator work without edges → true, as before;
  - the digest is stable, and changes when a new implementation card is done.

  Update the existing delivery tests (dispatch_delivery/ci_poll):
  - exactly one delivery per distinct set;
  - a CI repair plus a clean re-verification → a second delivery that updates the same change request;
  - single-task workflows unchanged.

## Phase 5: User Story 3 — Manual tasks are visible, counted and waited on (P2)

**Goal**: the operator sees, counts and completes manual cards. They block
dependents and completion, but not delivery.

**Independent test**: a mixed decomposition. The stage-board chip count is
right; "Mark done" unblocks a dependent coding card; the request is not Done
while a manual card is open.

- [x] T022 [US3] Add `CardAction.COMPLETE_MANUAL_TASK = "complete_manual_task"` in backend/app/models_board.py and to the `BoardInterventionIn.action` literal in backend/app/schemas.py. In backend/app/services/board/interventions.py:
  - `_complete_manual_task`: only for `manual_task` in `awaiting_human`, else `InvalidInterventionError`. It transitions to `done` with the event `manual_task.completed`, then calls `advance_ready_dependents`, which needs `BoardStore`; the service already holds it;
  - `allowed_actions_for` offers `complete_manual_task` for that case and stops offering `resolve_gate` for `manual_task`.
- [x] T023 [US3] Tests in backend/tests/test_board_interventions.py and the router tests:
  - completing a manual card makes a waiting dependent `ready`;
  - wrong kind or state → 422; a stale revision → 409;
  - no specialist can ever claim a manual card (backend/tests/test_board_claims.py);
  - the phase is not `done` while a manual card is open (backend/tests/test_board_phases.py or equivalent).
- [x] T024 [US3] Listing count (Principle I, one commit with T026): add `open_manual_task_count: int = 0` to `WorkflowSummaryOut` in backend/app/schemas.py, filled in `workflow_summary` in backend/app/routers/board_views.py. Test in backend/tests/test_board_views.py
- [x] T025 [P] [US3] Create frontend/src/components/cockpit/ManualTaskList.vue: a `v-list` of the snapshot's `manual_task` cards showing title and state; "Read task" opens `ArtifactDialog` on `latest_artifact`; "Mark done" is shown only when `allowed_actions` includes `complete_manual_task` and calls `applyIntervention(card.id, 'complete_manual_task')` (frontend/src/composables/useBoard.ts). Render nothing when there are no manual cards. Mount it in frontend/src/views/RequestCockpitView.vue
- [x] T026 [US3] Frontend types and board chip:
  - add `open_manual_task_count: number` to `BoardWorkflowSummary`, and `'complete_manual_task'` to `CardAction`, in frontend/src/types/workflows.ts;
  - add `ACTION_LABELS.complete_manual_task = 'Mark done'` in frontend/src/components/WorkCardDetail.vue;
  - add a "N manual task(s) assigned to you" `v-chip` in frontend/src/components/board/RequestCard.vue, only when the count is > 0;
  - make `manual_task.completed` an operator event in frontend/src/lib/personas.ts;
  - update the factory in frontend/tests/support/board.ts.
- [x] T027 [P] [US3] Frontend tests: frontend/tests/components/cockpit/ManualTaskList.test.ts (list, read, mark done with the revision, hidden action, empty) and frontend/tests/components/board/RequestCard.test.ts (chip at 2, singular at 1, absent at 0)

## Phase 6: User Story 4 — The child-ticket machinery is gone (P3)

**Goal**: no second model of "a sub-task" remains. Legacy data upgrades
cleanly, and marked tickets ingest as ordinary requests.

**Independent test**: upgrade a DB with child links and a
`skip_decomposition` workflow. It lists as ordinary, and a marked body
ingests normally.

- [x] T028 [US4] Remove `parent_workflow_id` (Principle I, one commit):
  - drop it from `WorkflowSummaryOut` in backend/app/schemas.py and from `workflow_summary` / `_BoardListDeps` in backend/app/routers/board_views.py and backend/app/routers/board.py;
  - drop it from `BoardWorkflowSummary` in frontend/src/types/workflows.ts;
  - remove `partitionByParentage`, `children` and the nesting from frontend/src/lib/stages.ts, and the children list from frontend/src/components/board/RequestSubItems.vue and RequestCard.vue.
- [x] T029 [P] [US4] Update the frontend tests: frontend/tests/lib/stages.test.ts (drop the nesting tests; one card per request), RequestSubItems.test.ts, RequestCard.test.ts, frontend/tests/views/StageBoardView.test.ts, frontend/tests/composables/useBoard.test.ts, frontend/tests/support/board.ts
- [x] T030 [US4] Delete the ingestion child machinery in backend/app/services/ingestion.py:
  - `_scheduled_child`, the `child_tasks` parameter, `observe_child_source_state`, `observe_missing_child_source_tasks`, `observe_child_retrigger`, `maybe_start_reopened_successor`, `start_successor_run`, the `has_manual_sentinel` skip, and `skip_decomposition=` at intake;
  - remove their callers in backend/app/services/jira_poll.py, backend/app/services/local_task_poll.py, backend/app/services/reconcile.py and backend/app/routers/github_webhook.py.
- [x] T031 [US4] Delete backend/app/persistence/child_task_store.py, `ChildTaskLinkRow` in backend/app/persistence/tables.py, backend/app/services/task_scheduler.py, and the `child_task_store` wiring in backend/app/services/board/bootstrap.py / backend/app/routers/board.py
- [x] T032 [US4] Delete `SubtaskSentinel`, `ManualTaskSentinel`, `SUBTASK_SENTINEL` and `MANUAL_SENTINEL` in backend/app/markers.py, and `has_subtask_sentinel`, `has_manual_sentinel` and `append_subtask_sentinel` in backend/app/services/task_source_utils.py. Update the `create_subtask` docstring in backend/app/ports.py; the method itself is kept (FR-018)
- [x] T033 [US4] Remove `skip_decomposition`:
  - from `Workflow` (backend/app/models_board.py), `AcceptedTaskIntake` (backend/app/models_board_records.py), `BoardWorkflowRow` (backend/app/persistence/board_tables.py), backend/app/persistence/board_store.py and backend/app/services/board/service.py;
  - the exemptions in backend/app/services/board/gates.py (three) and backend/app/services/board/coordinator.py (two), with their docstrings;
  - the related comments in backend/app/config.py.
- [x] T034 [US4] Remove `child_task_closure_retention_days` from backend/app/config.py (the field and `_CONFIG_FILE_FIELDS`) and from config.toml.example. Update the backend/app/services/board/dev_reset.py docstring
- [x] T035 [US4] Extend backend/alembic/versions/0033_subtask_cards.py to drop `board_workflow.skip_decomposition` and the `child_task_link` table (batch mode). Downgrade re-creates both, and the docstring states that rows are not restored
- [x] T036 [US4] Backend test clean-up:
  - delete backend/tests/test_child_task_store.py and backend/tests/test_task_scheduler.py;
  - remove the sentinel tests from backend/tests/test_markers.py;
  - remove the skip_decomposition tests from test_board_gates.py, test_board_gates_prd.py, test_board_coordinator.py, test_board_coordinator_prd.py, test_board_input_intake.py and test_board_service.py;
  - remove the child tests and fixtures from test_board_api_additions.py, test_board_views.py, test_board_router_views.py, test_board_claims.py, test_ingestion_service.py and test_reconcile.py;
  - keep the `create_subtask` adapter tests.
- [x] T037 [US4] New tests:
  - migration 0033 upgrades a DB containing `child_task_link` rows and a `skip_decomposition=1` workflow, and downgrades back (backend/tests/test_migrations.py);
  - a body with `<!-- kestrel:subtask -->` or `<!-- kestrel:manual -->` ingests as an ordinary request that gets its understanding gate (backend/tests/test_ingestion_service.py or test_board_input_intake.py).

## Phase 7: Polish & cross-cutting

- [x] T038 [P] Amend specs/026-autonomous-work-board/contracts/board-api.md per contracts/board-api-delta.md: remove `parent_workflow_id`; add `open_manual_task_count`, the `manual_task` kind and the `complete_manual_task` action; replace the child_work write-back with the breakdown comment. Land it with T024/T028 if possible
- [ ] T039 [P] Add a "Superseded (child tickets) by feature 031" note at the top of specs/012-task-decomposition-pipeline/spec.md, with User Story 3's publish half, FR-011, FR-013, FR-014 and FR-015 listed as reversed (FR-022)
- [ ] T040 [P] Update docs/architecture.md: one workflow → one branch → one PR; decomposition materialises cards; manual tasks; the capped verification loop; per-task tickets lost for now (backlog #63/#64/#65)
- [ ] T041 Run the full gate: `task quality`, backend `uv run pytest -q`, and frontend `npx prettier --check`, `npm test` and `npm run build`. Walk the quickstart manual scenario where feasible
- [ ] T042 Mark the spec Status "Implemented", tick the tasks, and comment on GitHub #54 and Vikunja 708 with the commits

## Dependencies & execution order

- Phase 1 → Phase 2 → US1 → US2 → US3 → US4 → Polish.
- US3's backend half (T022–T024) needs only US1; it can run in parallel with
  US2 if done by a different hand. The frontend half (T025–T027) needs T024.
- US4 must come after US1 (publishing must already be unreachable) and after
  US3's T026 (the frontend types are touched by both).
- T035 finishes the migration T002 started. Both are the same file, and the
  drop must land in the same commit as T031–T033.

## Parallel opportunities

- Phase 2: T003 and T006 alongside the next implementation task.
- US1: T015 (prompt/README) at any time.
- US3: T025/T027 (frontend) alongside T023 (backend tests) once T024's field exists.
- US4: T029 (frontend tests) alongside T030–T034 (backend deletions).
- Polish: T038, T039 and T040 are independent documents.

## Implementation strategy

**MVP = Phase 2 + US1.** Approving CAB-2 then keeps the work inside the
request, which is the reversal itself, and no more child tickets are created.
US2 is needed before the result is *useful* (one PR). US3 completes #51's
intent. US4 is the deletion that keeps a single sub-task model in the
code.
