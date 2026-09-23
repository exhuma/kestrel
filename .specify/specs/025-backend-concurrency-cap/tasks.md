# Tasks: Backend Concurrency Cap and Rate-Limit Backoff

**Feature**: 025-backend-concurrency-cap

## Phase 1: Setup

- [x] T001 Create feature specification and quality checklist in `.specify/specs/025-backend-concurrency-cap/`
- [x] T002 Create plan, research, data model, config contract, and quickstart artifacts in `.specify/specs/025-backend-concurrency-cap/`

## Phase 2: Foundational

- [x] T003 [P] Add `BackendLimiter` cancellation-safe semaphore wrapper in `backend/app/backends/limiter.py`
- [x] T004 [P] Add reusable HTTP 429 backoff policy in `backend/app/backends/rate_limit.py`
- [x] T005 Add validated backend throttle settings in `backend/app/config_models.py`

## Phase 3: User Story 1 - Global Per-Backend Cap

**Goal**: All workflow and ad-hoc turns sharing one backend ID share its cap.

**Independent test**: Concurrent calls through one limiter serialize at the

- [x] T006 [P] [US1] Add limiter serialization, parallelism, and cancellation tests in `backend/tests/test_backend_limiter.py`
- [x] T007 [US1] Inject one limiter per configured backend ID in `backend/app/backends/registry.py`
- [x] T008 [US1] Apply the shared cap to OpenCode turns in `backend/app/backends/opencode.py`
- [x] T009 [US1] Apply the shared cap to OpenAI-compatible turns in `backend/app/backends/openai_compat.py`
- [x] T010 [US1] Apply the shared cap to Claude CLI workflow and ad-hoc turns in `backend/app/backends/claude_cli.py` and `backend/app/services/runner.py`

## Phase 4: User Story 2 - Rate-Limit Backoff

**Goal**: OpenCode retries provider rate limits without retrying other errors.

**Independent test**: The rate-limit policy honors Retry-After, uses exponential
fallback, stops after the configured retry count, and passes through a 500.

- [x] T011 [P] [US2] Add rate-limit retry tests in `backend/tests/test_rate_limit.py`
- [x] T012 [US2] Invoke bounded rate-limit retry for OpenCode message POSTs in `backend/app/backends/opencode.py`

## Phase 5: User Story 3 - Configurable Operator Controls

**Goal**: Operators can tune and validate caps and retry behavior per backend.

**Independent test**: Defaults load without config and invalid values fail with

- [x] T013 [P] [US3] Add config default and validation tests in `backend/tests/test_backend_config.py`
- [x] T014 [US3] Document backend throttle keys in `config.toml.example`, `docs/backends.md`, and `docs/configuration.md`

## Phase 6: Verification

- [x] T015 Run focused backend tests from `backend/`
- [x] T016 Run `task quality` from the repository root

## Phase 7: Queue Visibility and Rate-Limit Observability

- [x] T017 Add queued/admitted limiter lifecycle callbacks in `backend/app/backends/limiter.py`
- [x] T018 Propagate queued status through backend adapters and workflow chips in `backend/app/backends/` and `backend/app/services/workflows/sessions.py`
- [x] T019 Add `zZz` queued-chip rendering and API type documentation in `frontend/src/components/RoundChips.vue`, `frontend/src/components/WorkflowPanel.vue`, and `frontend/src/types/workflows.ts`
- [x] T020 Log rate-limit retries and exhaustion in `backend/app/backends/rate_limit.py`
- [x] T021 Add queued-state and rate-limit logging regression tests in `backend/tests/` and `frontend/tests/components/RoundChips.test.ts`

## Phase 8: Child Workflow and Empty-Diagnostic Handling

- [x] T022 Seed persisted generated child tasks as already approved in `backend/app/services/workflows/driver/__init__.py`
- [x] T023 Preserve regular refine approval for unlinked sentinel-bearing tasks in `backend/app/services/workflows/driver/__init__.py`
- [x] T024 Record and log a useful fallback for blank OpenCode failures in `backend/app/backends/opencode.py`
- [x] T025 Add child bypass and empty-diagnostic tests in `backend/tests/test_workflow_driver.py` and `backend/tests/test_opencode_backend.py`

## Dependencies

- T003 through T005 precede T007 through T012.
- US1 and US2 depend on the foundational modules but are otherwise independent.
- US3 depends only on T005 and can be completed in parallel with US1/US2.

## Implementation Strategy

1. Deliver the shared limiter first so workflow fan-out cannot exceed the
   configured backend quota.
2. Add bounded retry for residual OpenCode provider rate limits.
3. Document the operator contract and run the repository quality gate.
