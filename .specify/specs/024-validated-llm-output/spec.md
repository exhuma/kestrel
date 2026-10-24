# Feature Specification: Validated LLM Output

**Feature Branch**: `024-validated-llm-output`

**Created**: 2026-09-17

**Status**: Draft

**Input**: User description: "Retry invalid required LLM output up to five
total attempts. Never expose an empty PRD."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Receive Valid Requirements (Priority: P1)

As a requester, I receive a complete requirements document for review, never
an empty or malformed document.

**Why this priority**: Requirements are the workflow's approval boundary and
must be usable before work can continue.

**Independent Test**: Simulate empty writer output followed by valid corrected
output and verify the requester receives only the nonempty document.

**Acceptance Scenarios**:

1. **Given** invalid requirements output, **When** a correction succeeds within
   five total attempts, **Then** the workflow presents the corrected nonempty
   document for approval.
2. **Given** five invalid requirements outputs, **When** the retry limit is
   reached, **Then** the workflow fails without presenting or publishing a
   requirements document.

---

### User Story 2 - Recover Required Analysis (Priority: P2)

As a requester, I receive a complete technical analysis and actionable task
proposal even when a less-capable model initially returns malformed output.

**Why this priority**: Analysis and task proposals define the work passed to
implementation and must not silently degrade into fabricated or empty content.

**Independent Test**: Simulate malformed analysis output followed by valid
output and verify the corrected proposal is the one presented for approval.

**Acceptance Scenarios**:

1. **Given** invalid required analysis output, **When** correction succeeds
   within five total attempts, **Then** only the valid analysis is retained.
2. **Given** five invalid required analysis outputs, **When** the retry limit is
   reached, **Then** no child tasks are published.

---

### User Story 3 - See Safe Revision Results (Priority: P3)

As a requester, I can request changes without a malformed response or blank
change summary crashing the workflow.

**Why this priority**: A failed revision loses the user's requested correction
and forces recovery work.

**Independent Test**: Request a revision that has blank changed lines and
verify the workflow posts a valid concise summary.

**Acceptance Scenarios**:

1. **Given** a revision whose textual difference includes blank lines, **When**
   Kestrel posts its summary, **Then** it posts a valid summary rather than
   failing.

### Edge Cases

- A tagged required response whose content is empty or whitespace-only is
  invalid.
- A required response missing its required tag or schema is invalid.
- A valid rejection verdict remains a normal rejection rather than a malformed
  output retry.
- Optional enrichment output remains best-effort and does not consume retries.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Kestrel MUST validate every required LLM artifact before storing,
  approving, publishing, or using it downstream.
- **FR-002**: Kestrel MUST request correction after invalid required output, up
  to five total attempts including the initial request.
- **FR-003**: Kestrel MUST fail the current workflow step with an actionable
  reason after five invalid attempts.
- **FR-004**: Kestrel MUST never present, approve, publish, or use an empty
  requirements document.
- **FR-005**: Kestrel MUST validate required requirements, technical analysis,
  task proposal, design, and verification outputs before they influence the
  workflow.
- **FR-006**: Kestrel MUST retain existing deterministic safe fallbacks for
  optional enrichment and question-pool reconciliation.
- **FR-007**: Kestrel MUST produce a valid change summary when a revision adds
  only blank lines or includes blank changed lines.

### Key Entities

- **Required artifact**: An LLM result that gates workflow progress or creates
  downstream work and therefore needs validation.
- **Correction attempt**: A bounded retry that includes the validation failure
  and asks the model to return the required result format.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of requirements documents presented for approval contain
  non-whitespace content.
- **SC-002**: Every invalid required response results in either a corrected
  valid artifact or a failed workflow within five total attempts.
- **SC-003**: No malformed required output causes an unhandled workflow crash.
- **SC-004**: Valid first-attempt output completes without an additional model
  request.

## Assumptions

- The initial request counts as attempt one, leaving at most four corrective
  requests.
- Existing transient-run recovery remains authoritative for process termination
  during an in-flight model request.
- A valid explicit verification rejection represents evidence about the change
  and must not be retried as a formatting failure.
