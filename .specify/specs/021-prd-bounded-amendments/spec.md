# Feature Specification: PRD-Bounded Amendments

**Feature Branch**: `[021-prd-bounded-amendments]`
**Created**: 2026-09-14
**Status**: Draft

**Input**: Let technical analysis begin after PRD approval, but constrain
parent decomposition changes and child-task clarifications or amendments to
that accepted PRD. Refuse conflicting changes with a reason.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Amend proposed decomposition within approved scope
(Priority: P1)

After approving a PRD, a requester can ask to add, remove, or reshape proposed
follow-up tasks. Kestrel evaluates the request against the accepted PRD before
regenerating the technical analysis.

**Why this priority**: The PRD remains the go/no-go boundary while letting a
requester improve the technical breakdown before it is published.

**Independent Test**: Request a decomposition change that is consistent with
the accepted PRD, then verify the replacement candidate reflects the feedback
and remains available for approval.

**Acceptance Scenarios**:

1. **Given** a decomposition candidate for an approved PRD, **When** the
   requester asks for an in-scope task change, **Then** Kestrel regenerates the
   candidate using that request and presents the replacement for review.
2. **Given** a decomposition candidate, **When** the requester asks for work
   outside the accepted PRD, **Then** Kestrel refuses the request, explains the
   conflicting PRD boundary, and preserves the candidate unchanged.

---

### User Story 2 - Keep child-task amendments within parent scope (Priority: P2)

A requester can clarify or amend a published child task, but Kestrel only
reopens work when the requested change stays within the child task and the
parent's accepted PRD.

**Why this priority**: A child may need clarification as implementation
progresses, without allowing a local request to silently expand the approved
parent scope.

**Independent Test**: Send feedback to a published child requesting an
in-scope clarification and verify it resumes; send an out-of-scope request and
verify it receives a refusal without resuming work.

**Acceptance Scenarios**:

1. **Given** a published child task and its parent PRD, **When** feedback
   requests an in-scope clarification, **Then** Kestrel applies the existing
   feedback lifecycle to the child.
2. **Given** a published child task and its parent PRD, **When** feedback asks
   for a new outcome or contradicts an accepted constraint, **Then** Kestrel
   records and publishes a refusal without reopening the child workflow.

---

### User Story 3 - Explain scope refusals (Priority: P3)

A requester receives a clear reason whenever Kestrel cannot apply a requested
technical-analysis or child-task change because it conflicts with the accepted
PRD.

**Why this priority**: A silent refusal leaves requesters unsure whether their
feedback was lost and offers no path to revise scope deliberately.

**Independent Test**: Submit a conflicting request and verify its source task
receives a concise explanation that identifies the accepted PRD as the reason
and directs the requester to revise it first.

**Acceptance Scenarios**:

1. **Given** an out-of-scope change request, **When** Kestrel refuses it,
   **Then** the response states why the request conflicts with the approved
   PRD and that a PRD revision and approval are required.

### Edge Cases

- A malformed or inconclusive scope decision must not start an amendment.
- A parent candidate remains publishable after a refused amendment request.
- Duplicate delivery of the same feedback must not create multiple amendments
  or refusal messages.
- A child with no durable parent PRD relationship must not be reopened from
  feedback until scope can be verified.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Kestrel MUST start technical analysis once the requester has
  approved the PRD; no additional PRD approval is required to start it.
- **FR-002**: Kestrel MUST retain the exact accepted PRD as the scope authority
  for a parent decomposition and every child task it publishes.
- **FR-003**: Before changing a parent technical-analysis candidate, Kestrel
  MUST evaluate the request against the accepted PRD.
- **FR-004**: Before reopening or continuing a child task from feedback,
  Kestrel MUST evaluate the request against its accepted parent PRD.
- **FR-005**: Kestrel MUST apply an in-scope parent request to the replacement
  analysis candidate and retain normal review before publication.
- **FR-006**: Kestrel MUST allow existing child feedback handling only after an
  in-scope decision.
- **FR-007**: Kestrel MUST refuse an out-of-scope request without changing the
  parent candidate, publishing new tasks, or reopening child work.
- **FR-008**: Every refusal MUST be visible on the task source and identify the
  accepted PRD as the governing boundary, state the conflict reason, and direct
  the requester to revise and approve the PRD for expanded scope.
- **FR-009**: An unavailable, malformed, or inconclusive scope decision MUST
  fail closed and produce an explanatory refusal.
- **FR-010**: Scope decisions and their PRD authority MUST survive restart and
  must be traceable from each published child task.

### Key Entities

- **Accepted PRD**: The immutable requirements document that the requester has
  approved for a parent workflow.
- **Scope decision**: The allowed or refused outcome for a requested technical
  change, including an explanatory reason.
- **Parent amendment**: A requested change to a pending decomposition candidate.
- **Child amendment**: Feedback requesting clarification or changed technical
  work for a published child task.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of parent and child change requests are evaluated against an
  accepted PRD before Kestrel changes technical work.
- **SC-002**: 100% of refused requests leave the current candidate and child
  workflow state unchanged.
- **SC-003**: 100% of refusals include a requester-visible reason and a path to
  deliberate PRD revision.
- **SC-004**: No duplicate feedback delivery creates more than one amendment or
  refusal outcome.

## Assumptions

- Existing decomposition approval remains the review point for an amended
  parent candidate.
- The existing feedback marker and review-token controls remain the authority
  for feedback authenticity and deduplication.
- A scope review may use the existing technical-analysis agent capability, but
  it must produce a structured decision and fail closed on invalid output.
