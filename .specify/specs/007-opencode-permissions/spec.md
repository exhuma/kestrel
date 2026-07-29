# Feature Specification: OpenCode Permission Compatibility

**Feature Branch**: `007-opencode-permissions`

**Created**: 2026-07-29

**Status**: Draft

**Input**: User description: "Update Kestrel for OpenCode 1.18.7 permission
replies and make errors that prevent useful work visible."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Complete an editing turn (Priority: P1)

An operator using a current OpenCode server can run a coding workflow that
receives and answers tool-permission requests, allowing the agent to finish
its work without manual interaction.

**Why this priority**: An unanswered permission request prevents all coding
work from completing.

**Independent Test**: A simulated editable turn that requests edit permission
receives an approval through the server's current permission-reply contract.

**Acceptance Scenarios**:

1. **Given** an editable OpenCode turn asks for edit permission, **When**
   Kestrel handles the request, **Then** it sends a one-time approval scoped to
   that session.
2. **Given** a read-only turn asks for edit permission, **When** Kestrel
   handles the request, **Then** it sends a rejection scoped to that session.

---

### User Story 2 - Diagnose blocked agent work (Priority: P2)

An operator can identify a permission-handling failure from Kestrel's logs
instead of seeing an indefinitely running agent with no diagnostic evidence.

**Why this priority**: Visible errors reduce recovery time when an external
server changes or becomes unavailable.

**Independent Test**: A simulated permission-reply failure produces a recorded
error and causes the affected turn to fail rather than wait indefinitely.

**Acceptance Scenarios**:

1. **Given** Kestrel cannot reply to an OpenCode permission request, **When**
   the reply fails, **Then** the turn finishes with an error describing the
   permission-handling failure.
2. **Given** the OpenCode event stream fails before any permission is needed,
   **When** the turn continues, **Then** Kestrel records a diagnostic error.

### Edge Cases

- A permission request with no identifier is ignored because it cannot be
  answered safely.
- Permission requests for other sessions are not answered by the active turn.
- Cancellation remains a normal control-flow outcome and is not reported as a
  permission failure.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Kestrel MUST reply to an OpenCode permission request through the
  session-scoped permission endpoint used by OpenCode 1.18.7.
- **FR-002**: Kestrel MUST send `once` for an allowed request and `reject` for
  a denied request using the current request body contract.
- **FR-003**: Kestrel MUST preserve its read-only policy by rejecting edits on
  read-only turns.
- **FR-004**: Kestrel MUST make failures of the permission event stream or a
  permission reply visible to operators and fail the affected turn.
- **FR-005**: Kestrel MUST not turn task cancellation into a reported failure.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every supported permission request in an editable test turn is
  answered exactly once using the current server contract.
- **SC-002**: Every simulated permission reply failure causes the affected
  workflow turn to finish with a visible error within its configured timeout.
- **SC-003**: All existing OpenCode backend tests and new compatibility tests
  pass.

## Assumptions

- OpenCode 1.18.7 is the compatibility target for this change.
- A failed permission channel means the agent cannot safely make progress, so
  failing the turn is preferable to continuing silently.
- Kestrel retains unattended one-time approval for tools it allows.
