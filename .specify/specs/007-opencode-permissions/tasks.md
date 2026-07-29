# Tasks: OpenCode Permission Compatibility

**Input**: Design documents in `.specify/specs/007-opencode-permissions/`

## Dependencies

- User Story 1 establishes the compatible permission protocol.
- User Story 2 depends on User Story 1 so reply failures can be surfaced by the
  same path.

## Phase 1: Setup

- [ ] T001 Review OpenCode 1.18.7 permission request and reply contracts in
  `backend/app/backends/opencode.py`

## Phase 2: Foundational

- [ ] T002 Add failing regression assertions for the session-scoped endpoint
  and `response` payload in `backend/tests/test_opencode_backend.py`

## Phase 3: User Story 1 - Complete an Editing Turn (Priority: P1)

**Goal**: Reply to editable and read-only permissions with the OpenCode 1.18.7
contract.

**Independent Test**: The focused adapter tests assert the request path and
payload for allowed and denied permission requests.

- [ ] T003 [US1] Send permission replies to the session-scoped OpenCode
  endpoint with the current body contract in `backend/app/backends/opencode.py`
- [ ] T004 [US1] Verify editable and read-only permission replies in
  `backend/tests/test_opencode_backend.py`

## Phase 4: User Story 2 - Diagnose Blocked Agent Work (Priority: P2)

**Goal**: Make permission-channel failures fail the active turn and appear in
Kestrel logs.

**Independent Test**: A simulated reply failure makes `run_turn` raise and a
background session records an error result.

- [ ] T005 [US2] Add failing tests for permission reply and event-stream
  failures in `backend/tests/test_opencode_backend.py`
- [ ] T006 [US2] Propagate permission-channel failures and log their causes in
  `backend/app/backends/opencode.py`
- [ ] T007 [US2] Verify cancellation remains non-error behavior in
  `backend/tests/test_opencode_backend.py`

## Phase 5: Validation

- [ ] T008 Run focused backend tests with `uv run pytest
  tests/test_opencode_backend.py` from `backend/`
- [ ] T009 Run `task quality` from the repository root

## Implementation Strategy

1. Complete the P1 protocol correction and focused tests.
2. Add the P2 failure propagation and diagnostics without changing normal
   cancellation.
3. Run the focused tests followed by the complete quality gate.
