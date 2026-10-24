# Feature Specification: Jira GitLab Production Parity

**Feature Branch**: `018-jira-gitlab-parity`
**Created**: 2026-09-10
**Status**: Draft
**Input**: Bring Jira and GitLab production behavior to parity for external
feedback and gates, MR discussions and pagination, cursors, and child tasks.

## User Scenarios & Testing

### User Story 1 - Decide from Jira and GitLab (Priority: P1)

A requester can approve, reject, or request changes on an active Kestrel gate
from either a Jira ticket or its GitLab merge request, with the same outcome
and acknowledgement they receive from the existing supported source.

**Independent Test**: Submit each supported decision from Jira and from a
GitLab MR discussion, then verify the active gate changes exactly once.

**Acceptance Scenarios**:

1. **Given** an active gate, **When** a valid Jira or GitLab response targets
   it, **Then** Kestrel applies it and acknowledges the response once.
2. **Given** a stale, malformed, or Kestrel-authored response, **When** it is
   observed, **Then** the gate remains unchanged.

### User Story 2 - Review every GitLab MR signal (Priority: P2)

A requester can leave feedback in the MR conversation, a review summary, or
an inline diff discussion. Kestrel sees every eligible item even when the MR
has more results than one page.

**Independent Test**: Create multi-page MR feedback containing one comment of
each kind, then verify each is available to the related run exactly once.

**Acceptance Scenarios**:

1. **Given** paginated GitLab MR feedback, **When** Kestrel polls it, **Then**
   it reads every eligible page before advancing its cursor.
2. **Given** an inline discussion, **When** it contains marked feedback,
   **Then** Kestrel routes and acknowledges it like other MR feedback.

### User Story 3 - Preserve feedback at cursor boundaries (Priority: P3)

An operator can rely on polling without losing feedback when multiple source
items share a timestamp, pages shift while being read, or a poll repeats.

**Independent Test**: Poll a source with equal-time items and changing pages,
then poll again; every item is handled once and none is skipped.

**Acceptance Scenarios**:

1. **Given** multiple items at a cursor boundary, **When** a poll completes,
   **Then** all items after the prior durable cursor are considered.
2. **Given** a repeated item from overlap or retry, **When** it is observed,
   **Then** durable deduplication prevents a second action.

### User Story 4 - Run published Jira child tasks (Priority: P4)

After approved decomposition, each published Jira child task contains the
information and source state needed to be independently discovered and run.

**Independent Test**: Publish an approved Jira decomposition, qualify a child
task for work, and verify it starts one child workflow at the intended stage.

**Acceptance Scenarios**:

1. **Given** an approved Jira child candidate, **When** Kestrel publishes it,
   **Then** the child is native, self-contained, and linked to its parent.
2. **Given** a published qualifying child, **When** Jira polling discovers it,
   **Then** it starts exactly one runnable child workflow.

### Edge Cases

- GitLab system notes, deleted notes, and unsupported Gitea review endpoints
  do not create feedback.
- A GitLab API page that returns no new entries stops pagination safely.
- Cursor data that cannot be parsed fails safely without skipping later items.
- A Jira parent that cannot create native subtasks reports the failure without
  publishing a partial child set as successful.

## Requirements

### Functional Requirements

- **FR-001**: Jira and GitLab feedback MUST use the same active-review token,
  classification, acknowledgement, and exactly-once decision semantics.
- **FR-002**: GitLab MR polling MUST collect eligible conversation, review,
  and inline discussion feedback across all available pages.
- **FR-003**: Each GitLab feedback item MUST have a stable source-native
  identity suitable for durable deduplication and acknowledgement.
- **FR-004**: Cursor advancement MUST occur only after all retrieved items
  have been offered to durable intake.
- **FR-005**: Cursors MUST distinguish items sharing a creation timestamp or
  use safe overlap plus durable deduplication; they MUST never skip them.
- **FR-006**: Invalid, stale, or unsupported cursor values MUST fail safely
  and be observable without causing feedback loss.
- **FR-007**: Jira-published child tasks MUST be native children, preserve the
  approved self-contained body, and remain independently eligible for work.
- **FR-008**: Child-task discovery MUST not start duplicate workflows or cause
  parent decomposition publication to execute a child prematurely.

### Key Entities

- **Feedback cursor**: Durable per-run position used to resume source reads.
- **GitLab MR signal**: A reviewer-authored conversation, review, or inline
  discussion item associated with one merge request.
- **Runnable child task**: A published Jira child with its lineage, scoped
  work, repository context, and eligibility needed for independent execution.

## Success Criteria

- **SC-001**: 100% of valid Jira and GitLab gate decisions change only their
  active gate and are acknowledged once.
- **SC-002**: A multi-page MR with conversation, review, and inline feedback
  has 100% of its eligible items available to its related workflow.
- **SC-003**: A repeated poll containing equal-time feedback loses no item and
  triggers no duplicate workflow action.
- **SC-004**: Each qualifying published Jira child starts exactly one workflow
  that can proceed without further parent-task context.

## Assumptions

- GitLab review support applies to GitLab; Gitea and Forgejo retain their
  current safe no-op behavior until their APIs are separately supported.
- Existing durable feedback deduplication remains the final authority for
  exactly-once processing.
- Jira project workflow permissions permit creation and discovery of native
  child tasks for the configured source.
