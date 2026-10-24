# Feature Specification: Specific feedback replies

**Feature Branch**: `023-specific-feedback-replies`
**Created**: 2026-09-15
**Status**: Draft
**Input**: User description: "Only acknowledge when Kestrel has taken an
immediate visible action, using a natural, specific message."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See a meaningful immediate result (Priority: P1)

A requester responds to a Kestrel review on a comment-only task platform.
When Kestrel immediately accepts and acts on the response, the requester sees
a concise, natural reply that says what Kestrel did.

**Why this priority**: Comment-only platforms need a visible confirmation, but
the confirmation must communicate useful workflow state rather than create
noise.

**Independent Test**: Submit an accepted review decision through a comment-only
source and verify one reply describes the resulting immediate action.

**Acceptance Scenarios**:

1. **Given** a review awaiting approval, **When** the requester approves its
   active revision, **Then** Kestrel posts one reply stating that the workflow
   has advanced.
2. **Given** a review awaiting changes, **When** the requester requests changes
   for its active revision, **Then** Kestrel posts one reply stating that it is
   updating the review.
3. **Given** an unclassified response to an active review, **When** Kestrel
   needs the requester to select an allowed decision, **Then** it posts only
   that decision guidance and no separate acknowledgement.

---

### User Story 2 - Avoid acknowledgement noise (Priority: P2)

A requester leaves marked feedback while work is in progress or Kestrel must
continue processing asynchronously. The requester does not receive a generic
or premature acknowledgement comment.

**Why this priority**: Suppressing routine comments makes task discussions
readable and prevents a false impression that work has already completed.

**Independent Test**: Submit feedback to a running workflow and verify Kestrel
records it without posting a reply or reaction.

**Acceptance Scenarios**:

1. **Given** work is in progress, **When** marked feedback is queued for a
   later workflow boundary, **Then** Kestrel posts no acknowledgement.
2. **Given** feedback requires asynchronous revival or successor processing,
   **When** Kestrel begins that processing, **Then** it posts no
   acknowledgement before a visible result exists.
3. **Given** feedback is ignored or duplicated, **When** Kestrel receives it,
   **Then** it posts no acknowledgement.

---

### User Story 3 - Prefer non-comment signals (Priority: P3)

On a source that supports reactions, a requester receives a reaction after an
immediate visible action instead of an additional reply comment. If the
reaction cannot be added, Kestrel uses the same action-specific reply used on a
comment-only source.

**Why this priority**: Reactions provide confirmation without clutter while
still leaving a reliable fallback where reactions are unavailable.

**Independent Test**: Complete an immediate feedback action through a
reaction-capable source and verify a reaction is added; simulate its failure and
verify the action-specific reply is posted.

**Acceptance Scenarios**:

1. **Given** a source supports reactions, **When** Kestrel immediately acts on
   feedback, **Then** it adds a reaction and posts no acknowledgement comment.
2. **Given** that reaction cannot be added, **When** Kestrel immediately acts
   on feedback, **Then** it posts one natural, action-specific reply.

### Edge Cases

- An acknowledgement failure never reverses accepted feedback or blocks the
  workflow.
- A reply must not imply completion when Kestrel has only started a visible
  update.
- Fixed reply templates remain safe from Kestrel's feedback trigger marker.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST post a feedback acknowledgement only after it
  has taken an immediate, visible workflow action.
- **FR-002**: The system MUST NOT acknowledge feedback that is queued, ignored,
  duplicated, or still awaiting asynchronous processing.
- **FR-003**: Every acknowledgement reply MUST state the action Kestrel has
  just taken in brief, natural language; a fixed `Acknowledged` prefix is not
  required.
- **FR-004**: The system MUST prefer a reaction over an acknowledgement reply
  where the source supports reactions.
- **FR-005**: If a preferred reaction cannot be added, the system MUST use the
  applicable action-specific reply.
- **FR-006**: When Kestrel has already posted a specific reply for the same
  feedback, it MUST NOT add a second acknowledgement reply or reaction.
- **FR-007**: Failed acknowledgement delivery MUST NOT block feedback intake or
  the workflow action.

### Key Entities

- **Feedback dispatch result**: The immediate or deferred outcome of processing
  one accepted feedback item, used to decide whether confirmation is warranted.
- **Action-specific reply**: A short visible message that describes a completed
  immediate workflow action without implying uncompleted work is done.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of acknowledgement comments produced after an immediate
  feedback action describe that action.
- **SC-002**: 0 acknowledgement comments or reactions are produced for queued,
  ignored, duplicate, or asynchronous feedback processing.
- **SC-003**: Each accepted feedback item produces at most one confirmation
  signal, unless its workflow action independently requires a separate,
  substantive follow-up.

## Assumptions

- A reaction is an adequate low-noise acknowledgement on sources that support
  it.
- Existing substantive workflow replies remain authoritative and are not
  duplicated by this feature.
