# Feature Specification: Managed Agentic SDLC

**Feature Branch**: `[020-agentic-sdlc]`
**Created**: 2026-09-14
**Status**: Draft

**Input**: Run the complete technical delivery lifecycle inside Kestrel.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Approve requirements before design (Priority: P1)

An operator reviews and approves the generated PRD before Kestrel dispatches a
Designer Agent, so no design or code is based on unapproved requirements.

**Independent Test**: Start an ordinary task and verify its design agent cannot
start until the PRD gate has an approval decision.

**Acceptance Scenarios**:

1. **Given** an unapproved PRD, **When** the workflow continues, **Then** it
   remains at the PRD gate and the design step is not dispatched.
2. **Given** an approved PRD, **When** the workflow continues, **Then** Kestrel
   dispatches the Designer Agent with the approved PRD and repository context.

---

### User Story 2 - Use durable delivery contracts (Priority: P2)

An operator can inspect the accepted design, scoped acceptance scenarios, task
dependencies, and discovered local check commands from one workflow artifact
set, so subsequent agents share one stable technical contract.

**Independent Test**: Complete design for a child task and verify Kestrel writes
the design, acceptance, and check-contract artifacts before coding starts.

**Acceptance Scenarios**:

1. **Given** an approved PRD, **When** design completes, **Then** Kestrel stores
   readable scenarios with stable IDs and their automation disposition.
2. **Given** a code retry, **When** Kestrel reruns deterministic checks, **Then**
   it uses the recorded command contract rather than rediscovering commands.

---

### User Story 3 - Reach technical readiness through independent evidence
(Priority: P3)

An operator can see that a change is technically ready only after Kestrel has
recorded local check, behavioural-verification, and required-CI evidence.

**Independent Test**: Drive a change through a failed local check, failed
behavioural observation, failed required CI check, and eventual success.

**Acceptance Scenarios**:

1. **Given** a local deterministic check fails, **When** Kestrel receives its
   result, **Then** it returns the structured result to the Coder Agent.
2. **Given** HTTP or UI work has no matching observed evidence, **When** the
   Verifier Agent responds, **Then** Kestrel rejects it and returns to coding.
3. **Given** a required CI check fails, **When** Kestrel observes it, **Then** it
   recreates an isolated branch worktree and starts a bounded CI repair loop.
4. **Given** all required CI checks pass, **When** Kestrel records the result,
   **Then** it marks the run technically ready.

### Edge Cases

- A changed PRD, design, or acceptance contract after coding begins requires an
  explicit approved revision and restarts downstream work at design.
- A missing command, non-zero exit status, timeout, or malformed result cannot
  pass deterministic verification.
- A run that exhausts either repair budget records an escalation rather than
  continuing indefinitely.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Kestrel MUST dispatch Designer, Coder, and Verifier agents as
  managed workflow steps.
- **FR-002**: Kestrel MUST not dispatch design before the PRD approval gate is
  approved.
- **FR-003**: The Designer MUST create a versioned acceptance contract with
  stable scenario IDs, parent traceability, and an automation disposition.
- **FR-004**: The Coder MUST implement automated tests for scenarios marked
  automated.
- **FR-005**: Before coding, Kestrel MUST persist an agent-discovered command
  contract and use it unchanged for later local-check rounds.
- **FR-006**: Kestrel MUST execute contract commands and record structured,
  bounded results before behavioural verification.
- **FR-007**: Missing required HTTP or UI evidence MUST reject verification and
  return actionable feedback to the Coder.
- **FR-008**: Kestrel MUST represent a task dependency graph and schedule only
  tasks whose prerequisites are technically ready.
- **FR-009**: Kestrel MUST serialize code-changing work per repository and
  revalidate each task on the current feature integration branch.
- **FR-010**: Code hosts MUST expose required-CI status and bounded failure
  details through a source-neutral capability.
- **FR-011**: A required-CI failure MUST use a separate bounded repair budget
  and a fresh worktree from the change-request branch.
- **FR-012**: A required-CI success MUST mark the run technically ready.

### Key Entities

- **Acceptance contract**: Immutable, scoped, readable scenarios and their
  automation dispositions.
- **Command contract**: Discovered deterministic commands, working directories,
  timeouts, and rationale for one task run.
- **Check result**: Structured execution evidence for one command and round.
- **Task graph**: Child task IDs and prerequisite relationships.
- **Technical readiness**: The state reached after all local, behavioural, and
  required-CI evidence is passing.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of design dispatches follow an approved PRD.
- **SC-002**: 100% of coding rounds have a persisted local-check report.
- **SC-003**: 100% of HTTP/UI acceptances contain evidence for every declared
  boundary.
- **SC-004**: Every technically ready run has recorded passing local,
  behavioural, and required-CI evidence.

## Assumptions

- The current task source provides the existing PRD and decomposition gates.
- Required CI check information is available through the configured code host.
- The first delivery increment serializes code-changing work within a repository.
