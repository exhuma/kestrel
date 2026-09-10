# Tasks: Task-Source Feedback

## Phase 1: Foundation

- [x] T001 Add explicit task-source approval commands in
  `backend/app/services/feedback/marker.py`.
- [x] T002 Apply explicit gate decisions in
  `backend/app/services/feedback/dispatch.py`.
- [x] T003 Preserve same-timestamp Jira comments in
  `backend/app/services/jira.py`.
- [x] T004 Add response instructions to
  `backend/app/notifications.py`.

## Phase 2: External Gate Decisions

**Goal**: External comments drive non-questionnaire gates.

- [x] T005 [US1] Add durable review-request revisions and tokens in
  `backend/app/persistence/`.
- [x] T006 [US1] Create review-request rendering and delta-summary helpers in
  `backend/app/services/feedback/`.
- [x] T007 [US1] Match and classify tokenized external gate responses in
  `backend/app/services/feedback/`.
- [x] T008 [US1] Add review-request and gate-response tests in
  `backend/tests/test_feedback_*.py`.

## Phase 3: Approved Decomposition

**Goal**: Publish only approved child tasks.

- [x] T009 [US2] Add the decomposition approval state in
  `backend/app/services/workflows/driver/gap_analysis.py`.
- [x] T010 [US2] Persist pending decomposition candidates in
  `backend/app/persistence/`.
- [x] T011 [US2] Publish the approved candidate and record child links in
  `backend/app/services/workflows/driver/gap_analysis.py`.
- [x] T012 [US2] Test decomposition approval, revision, rejection, and
  publication in `backend/tests/test_workflow_gap_analysis.py`.

## Phase 4: Child Re-adoption

**Goal**: Route feedback and reopening of every published child task.

- [x] T013 [US3] Add child-task lineage and source-state persistence in
  `backend/app/persistence/`.
- [x] T014 [US3] Add source-native reopen observations in `backend/app/ports.py`
  and task-source adapters.
- [x] T015 [US3] Start a linked successor for a validated reopen in
  `backend/app/services/ingestion.py`.
- [x] T016 [US3] Cover GitHub, Jira, and fixture re-adoption in
  `backend/tests/test_*ingestion*.py`.

## Phase 5: Translation And Retirement

**Goal**: Make feedback visible across languages and monitoring bounded.

- [x] T017 [US4] Add OpenAI-compatible translation configuration and adapter in
  `backend/app/config*.py` and `backend/app/services/translation/`.
- [x] T018 [US4] Translate accepted non-English feedback in
  `backend/app/services/feedback/`.
- [x] T019 [US5] Add closed-child retention observations and one-time notices in
  `backend/app/services/feedback/`.
- [x] T020 [US5] Test translation failure isolation and retirement behavior in
  `backend/tests/test_*feedback*.py`.

## Phase 6: Polish

- [x] T021 Update `docs/architecture.md`, `docs/feedback-intake.md`, and source
  setup guides.
- [ ] T022 Run all relevant backend/frontend tests and `task quality`.

## Dependencies

- T005-T008 complete before externally classified normal-language decisions.
- T009-T012 complete before child tasks are published from this feature.
- T013-T016 depend on approved child-link publication.
- T017-T020 can follow the feedback-source foundation independently.
