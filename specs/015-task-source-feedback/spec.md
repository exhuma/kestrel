# Feature Specification: Task-Source Feedback

**Feature Branch**: `015-task-source-feedback`

**Created**: 2026-09-10

**Status**: Draft

**Input**: Make task sources the primary human-to-Kestrel channel for
understanding, PRD, decomposition, and child-task feedback.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Decide from the task source (Priority: P1)

A requester reviews Kestrel's understanding or published requirements document
where they already work. They reply in ordinary language to approve, reject, or
request changes without opening Kestrel.

**Why this priority**: The approval gates are currently the primary forced UI
dependency, which prevents hands-off use.

**Independent Test**: Post an understanding review request, reply with an
approval or change request, and observe the correct state transition.

**Acceptance Scenarios**:

1. **Given** an understanding or PRD awaits approval, **When** a requester
   responds to its active review request, **Then** Kestrel interprets and
   applies the response without UI interaction.
2. **Given** a requester asks for changes, **When** Kestrel revises an
   artifact, **Then** its reply lists only the concrete changes and links to
   the canonical updated artifact rather than repeating the whole artifact.
3. **Given** an unclear or stale response, **When** Kestrel receives it,
   **Then** it asks for clarification or ignores it without changing the gate.

---

### User Story 2 - Review decomposition before publication (Priority: P2)

A requester reviews technical analysis and proposed child tasks on the parent
task. No child task is published until the requester approves the proposal.

**Why this priority**: Preventing incorrect task fan-out is cheaper than
correcting several already-published tasks.

**Independent Test**: Produce a decomposition, request changes, approve the
revision, and verify that exactly the approved child tasks are published.

**Acceptance Scenarios**:

1. **Given** approved requirements, **When** Kestrel finishes analysis,
   **Then** it parks with a reviewable proposed decomposition.
2. **Given** an unapproved proposal, **When** it is reviewed, **Then** no
   child task has been published.
3. **Given** an approved proposal, **When** publication succeeds, **Then** all
   child tasks and the analysis are published and the parent run is decomposed.

---

### User Story 3 - Continue a published child task (Priority: P3)

A human can give feedback on every published child task during work and after
completion. Reopening a completed child task creates one linked new work run.

**Why this priority**: Follow-up tasks must remain correctable after delivery,
not just during their first execution.

**Independent Test**: Complete a child task, reopen it in its source, and
verify Kestrel creates one linked successor instead of silently ignoring it or
duplicating it.

**Acceptance Scenarios**:

1. **Given** a published child task, **When** a human leaves marked feedback,
   **Then** Kestrel acknowledges and routes it to the latest related run.
2. **Given** a completed child task is reopened and qualifies for work,
   **When** Kestrel detects that source lifecycle change, **Then** it creates
   exactly one linked successor run.
3. **Given** an unchanged completed task, **When** it is observed repeatedly,
   **Then** no extra run starts.

---

### User Story 4 - See accepted non-English feedback (Priority: P4)

A participant writes feedback in a language other than English. Kestrel keeps
the original feedback, processes it, and replies with an English translation
and a warning that automated translations may contain mistakes.

**Why this priority**: Shared task sources need a common language without
excluding contributors.

**Independent Test**: Leave non-English feedback and verify that the original
is retained and one disclaimer-bearing English translation is posted.

**Acceptance Scenarios**:

1. **Given** accepted non-English feedback, **When** translation succeeds,
   **Then** Kestrel posts one English translation with a warning.
2. **Given** translation fails, **When** processing continues, **Then** the
   original feedback is retained and workflow processing is not blocked.

---

### User Story 5 - Retire old closed child tasks (Priority: P5)

After a configurable six-month period from a child task's source closure,
Kestrel posts one retirement message and stops active monitoring. New work then
requires a newly created task.

**Why this priority**: Bounded monitoring keeps a long-lived task source from
accumulating unattended work indefinitely.

**Independent Test**: Advance a closed child past the configured cutoff and
verify one retirement post, no further monitoring, and normal ingestion for a
new task.

**Acceptance Scenarios**:

1. **Given** a closed child task reaches its retention cutoff, **When** a
   monitor cycle runs, **Then** Kestrel posts one retirement message.
2. **Given** a retired child task, **When** it later receives feedback or is
   reopened, **Then** Kestrel does not resume it automatically.

### Edge Cases

- Sources without native replies accept a marked task comment carrying the
  active review token.
- Multiple comments sharing one timestamp are never skipped.
- A webhook and a poll observation of one response cause only one action.
- An unavailable reaction mechanism falls back to a concise reply.
- Repeated saves of a terminal run do not extend the retention window.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Kestrel MUST use a dedicated feedback-monitoring boundary rather
  than coupling feedback reads to ticket and code-host responsibilities.
- **FR-002**: Every Kestrel-authored review post MUST state how to respond in
  one simple sentence and identify the current revision.
- **FR-003**: Kestrel MUST accept plain-language approval, rejection, and
  requested-change responses for understanding, PRD, and decomposition gates.
- **FR-004**: Kestrel MUST persist responses and apply each source item once.
- **FR-005**: Kestrel MUST leave the structured questionnaire in its UI flow.
- **FR-006**: Kestrel MUST create a decomposition approval gate before it
  publishes analysis or any proposed child task.
- **FR-007**: Kestrel MUST retain parent-child task identity and successor
  lineage for every published child task.
- **FR-008**: Kestrel MUST treat an eligible source-task reopen as an explicit,
  linked re-adoption event, never as ordinary duplicate ingestion.
- **FR-009**: Kestrel MUST acknowledge accepted feedback with a reaction where
  available, otherwise with a reply.
- **FR-010**: Kestrel MUST use an explicitly configured translation service for
  automated English translations and MUST retain original feedback.
- **FR-011**: Kestrel MUST stop active monitoring after a configurable closure
  retention period that defaults to six months and MUST post one notice.
- **FR-012**: Kestrel MUST use source-safe cursors so same-time comments are
  never missed.
- **FR-013**: Kestrel MUST not react to its own posts, acknowledgements, or
  translations.

### Key Entities

- **Feedback source**: A source-neutral channel that reads and acknowledges
  ticket and review feedback for a run.
- **Review request**: A revision-specific Kestrel post that asks for a decision.
- **Work graph**: The durable relationship between a parent run, child task,
  task generation, and linked successor runs.
- **Task observation**: The current source task lifecycle state used to detect
  closure, reopening, and retirement eligibility.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A requester completes every non-questionnaire decision gate from
  the task source without visiting Kestrel.
- **SC-002**: 100% of accepted feedback is acknowledged and acted on no more
  than once.
- **SC-003**: No child task is published before its decomposition is approved.
- **SC-004**: A re-opened child task creates exactly one linked successor run.
- **SC-005**: Each retired child task receives exactly one retirement message.

## Assumptions

- An agent-backed classifier decides normal-language gate responses.
- Translation uses a separately configured OpenAI-compatible service.
- Jira re-adoption is represented by qualifying-state exit and re-entry.
- Fixture sources use an explicit retrigger generation rather than file edits.
