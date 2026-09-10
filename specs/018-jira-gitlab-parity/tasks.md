# Tasks: Jira GitLab Production Parity

**Input**: `specs/018-jira-gitlab-parity/spec.md` and `plan.md`

**Tests**: Required by Constitution Principle III. Write each behavior test
before its implementation and confirm it fails for the intended reason.

## Phase 1: Baseline And Contracts

- [ ] T001 Confirm existing backend/frontend tests pass and record the
  production parity gap against current Jira and GitLab adapters.
- [ ] T002 Define the source-safe feedback cursor contract in
  `backend/app/ports.py` and feedback models; preserve adapter opacity.
- [ ] T003 Add failing cursor-boundary and durable dedup tests in
  `backend/tests/test_feedback_poll.py`.
- [ ] T004 Add an Alembic migration and store tests for any changed persisted
  cursor representation in `backend/app/persistence/` and `backend/tests/`.

## Phase 2: Jira External Feedback And Runnable Children

**Goal**: Jira matches the shared external-feedback and child-work contract.

- [ ] T005 [US1] Add failing Jira tests for active tokenized gate decisions,
  stale responses, and acknowledgement fallback in
  `backend/tests/test_jira*.py`.
- [ ] T006 [US1] Implement Jira feedback mapping and acknowledgement required
  by `FeedbackSource` in `backend/app/services/jira.py`.
- [ ] T007 [US4] Add failing tests for self-contained native Jira child
  creation, later qualification, and exactly-one child workflow in
  `backend/tests/test_jira*.py` and `test_workflow_gap_analysis.py`.
- [ ] T008 [US4] Preserve child repository context and eligibility through
  `backend/app/services/jira.py`, `jira_poll.py`, and workflow publication.

## Phase 3: GitLab MR Feedback Completeness

**Goal**: Every eligible GitLab MR feedback surface reaches shared intake.

- [ ] T009 [US2] Add failing GitLab adapter tests for paginated conversation
  notes, review summaries, inline discussions, system filtering, and stable
  identities in `backend/tests/test_gitlab_code_host.py`.
- [ ] T010 [US2] Implement paginated MR conversation and review-summary reads
  in `backend/app/services/gitlab.py`.
- [ ] T011 [US2] Implement inline discussion feedback mapping and native
  acknowledgement in `backend/app/services/gitlab.py`.
- [ ] T012 [US2] Compose all GitLab MR signals in source order without changing
  the safe no-op behavior for unsupported Gitea/Forgejo review APIs.

## Phase 4: Cursor-Safe Intake

**Goal**: Polling cannot lose feedback at timestamp or pagination boundaries.

- [ ] T013 [US3] Add failing tests for equal timestamps, page shifts, retries,
  malformed cursors, and failure before cursor advancement in
  `backend/tests/test_feedback_poll.py`.
- [ ] T014 [US3] Implement source-safe cursor comparison and safe fallback in
  `backend/app/services/feedback/` and
  `backend/app/persistence/feedback_store.py`.
- [ ] T015 [US3] Update composed feedback polling to advance only after every
  retrieved item has reached durable intake in
  `backend/app/services/feedback/poll.py`.
- [ ] T016 [US3] Add adapter contract tests proving GitLab pagination and Jira
  feedback obey the new cursor contract in `backend/tests/`.

## Phase 5: Verification And Documentation

- [x] T017 [P] Document Jira/GitLab feedback coverage, MR limitations, cursor
  recovery, and runnable Jira children in `docs/architecture.md` and setup
  guides.
- [ ] T018 Run targeted pytest suites, full backend/frontend tests, and
  `task quality`; resolve every failure without suppressions.

## Dependencies

- T001-T004 complete before source adapters adopt the new cursor contract.
- T005-T008 and T009-T012 may proceed in parallel after T002-T004.
- T013-T016 require the adapter behavior from T005-T012.
- T017-T018 require all implementation tasks.
