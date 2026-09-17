# Tasks: Validated LLM Output

**Input**: Design documents from `.specify/specs/024-validated-llm-output/`

## Phase 1: Foundation

- [ ] T001 Add strict required-artifact validators and a five-total-attempt
  correction helper in `backend/app/services/workflows/validation.py`.
- [ ] T002 [P] Add unit tests for validation, retry bounds, and correction
  prompts in `backend/tests/test_workflow_validation.py`.

## Phase 2: User Story 1 - Receive Valid Requirements (Priority: P1)

**Goal**: Never present, approve, or publish an empty or malformed PRD.

**Independent Test**: Empty or missing refined output is corrected; five
invalid responses fail without parking a refine approval gate.

- [ ] T003 [US1] Add failing writer-output retry and exhaustion regressions in
  `backend/tests/test_workflow_gate.py`.
- [ ] T004 [US1] Route initial and revision PRD writers through strict
  validation in `backend/app/services/workflows/interview/__init__.py`.
- [ ] T005 [US1] Reject empty refine approval deliverables in
  `backend/app/services/workflows/service.py`.

## Phase 3: User Story 2 - Recover Required Analysis (Priority: P2)

**Goal**: Never retain or publish malformed technical analysis or task output.

**Independent Test**: Invalid analysis is corrected before its proposal is
parked; five failures publish no child task.

- [ ] T006 [US2] Add invalid and corrected analysis output regressions in
  `backend/tests/test_workflow_gap_analysis.py`.
- [ ] T007 [US2] Validate and retry technical analysis and task proposal output
  in `backend/app/services/workflows/driver/gap_analysis.py`.
- [ ] T008 [P] [US2] Add required design and verifier retry regressions in
  `backend/tests/test_workflow_driver.py` and
  `backend/tests/test_workflow_driver_code_verify.py`.
- [ ] T009 [US2] Validate and retry design contracts in
  `backend/app/services/workflows/driver/__init__.py`.
- [ ] T010 [US2] Validate and retry malformed verification verdicts in
  `backend/app/services/workflows/driver/code_verify.py`.

## Phase 4: User Story 3 - Safe Revision Results (Priority: P3)

**Goal**: Blank-line changes never crash review-summary rendering.

**Independent Test**: Blank-only and mixed blank/nonblank diffs create valid
summaries.

- [ ] T011 [US3] Add blank-line delta-summary regressions in
  `backend/tests/test_task_source_notifier.py`.
- [ ] T012 [US3] Filter empty changed lines in
  `backend/app/review_requests.py`.

## Phase 5: Polish

- [ ] T013 Update strict-output requirements in
  `backend/app/services/workflows/prompts.py`.
- [ ] T014 Run focused tests, the full backend suite, and `task quality`.

## Dependencies & Execution Order

- T001 and T002 block all workflow-boundary changes.
- T003-T005 establish the critical PRD guarantee first.
- T006-T010 then extend the shared safety net to analysis, design, and verify.
- T011-T012 are independent after T001 and may run in parallel with T006-T010.
- T013-T014 follow all implementation tasks.
