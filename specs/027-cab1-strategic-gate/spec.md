# Feature Specification: CAB-1 Strategic Fit Gate

**Feature Branch**: `027-cab1-strategic-gate`

**Created**: 2026-09-28

**Status**: Draft

**Input**: User description: "CAB-1: early human gate for strategic fit, before
pre-assessment (GitHub #47, epic #41, Vikunja task 709). An early, pure human
gate that asks one question only — why is this needed, and does it fit the
broader strategy? It is preceded by a distinct, light, turn-capped strategic
interview between kestrel and the original requester (non-technical,
low-detail), separate from the existing deeper refinement interviews that
follow gate approval and target additional, more technical audiences."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A reviewer decides whether new work is worth pursuing (Priority: P1)

A CAB-1 reviewer sees a short, plain-language case for why a newly
understood task matters and how it fits the broader strategy, and records an
approve or reject decision before kestrel invests any further effort in it.

**Why this priority**: This is the entire point of the feature — without a
strategic checkpoint, every understood task proceeds straight into detailed,
resource-consuming refinement regardless of whether it should happen at all.

**Independent Test**: Take a task through understanding and the strategic
interview, then approve or reject it at the CAB-1 gate, and confirm the
decision — not any coordinator judgment — determines whether the task
proceeds.

**Acceptance Scenarios**:

1. **Given** a task has passed understanding and completed its strategic
   interview, **When** a CAB-1 reviewer approves it, **Then** the task
   proceeds into refinement.
2. **Given** the same state, **When** a CAB-1 reviewer rejects it, **Then**
   the task does not proceed into refinement, and the rejection is recorded
   against the task.
3. **Given** CAB-1 is enabled for a deployment, **When** a task completes
   understanding, **Then** it does not reach refinement without an explicit
   CAB-1 decision.

---

### User Story 2 - The requester gives light strategic context (Priority: P2)

The person who originally asked for the work is asked a small number of
plain-language questions about why it matters, so their perspective is
available to the CAB-1 reviewer without putting them through a full
technical interview.

**Why this priority**: CAB-1 needs just enough context to make a go/no-go
call; a deep interview at this stage would waste the requester's time and
delay every task, including ones that will be rejected anyway.

**Independent Test**: Start the strategic interview for a task and verify it
asks a small, bounded set of non-technical questions, and that its answer is
what the CAB-1 reviewer sees before deciding.

**Acceptance Scenarios**:

1. **Given** a task has just passed understanding and CAB-1 is enabled,
   **When** the strategic interview starts, **Then** it asks a small,
   bounded number of questions in plain, non-technical language.
2. **Given** the requester has answered the strategic interview, **When**
   the CAB-1 gate becomes available for decision, **Then** the reviewer can
   see that answer as the basis for the decision.

---

### User Story 3 - A rejected task doesn't waste unrelated work (Priority: P2)

When a CAB-1 reviewer rejects a task, only the work that depended on that
decision is invalidated — everything already recorded about the task (its
understanding, the strategic interview, prior history) remains intact and
visible.

**Why this priority**: Matches the existing gate-rejection guarantee
elsewhere in the system (User Story 4 of the board feature); reviewers and
operators already rely on rejections being targeted, not destructive.

**Independent Test**: Reject a CAB-1 gate and confirm the task's prior
history stays queryable and nothing outside what depended on the gate is
altered.

**Acceptance Scenarios**:

1. **Given** a task at the CAB-1 gate, **When** a reviewer rejects it,
   **Then** only the work that depended on CAB-1 approval is invalidated.
2. **Given** a rejected CAB-1 gate, **When** the task's history is reviewed
   later, **Then** the understanding and strategic-interview records are
   still present and unchanged.

---

### User Story 4 - An operator can turn the gate on or off (Priority: P3)

An operator running a lightweight deployment can leave CAB-1 disabled, the
same way the existing optional PRD and decomposition gates can be left
disabled, so the extra review step is opt-in rather than forced.

**Why this priority**: Keeps the default experience unchanged for operators
who don't need a strategic checkpoint, consistent with how every other
optional gate in the system already behaves.

**Independent Test**: With CAB-1 left at its default setting, take a task
through understanding and confirm it proceeds to refinement exactly as it
does today, with no strategic interview or CAB-1 decision required.

**Acceptance Scenarios**:

1. **Given** CAB-1 is left at its default (off), **When** a task passes
   understanding, **Then** it proceeds directly to refinement as it does
   today.
2. **Given** an operator turns CAB-1 on, **When** a task passes
   understanding, **Then** the strategic interview and CAB-1 gate are
   required before refinement.

---

### Edge Cases

- What happens if the requester never answers the strategic interview? The
  task waits at that step the same way any other pending human interview
  waits today — no automatic timeout is introduced by this feature.
- What happens if an operator enables CAB-1 while tasks are already
  in-flight past understanding? Those tasks are unaffected — the gate only
  applies to tasks that have not yet completed the step it's inserted
  before.
- What happens if both CAB-1 and other optional gates (PRD, decomposition)
  are enabled at once? They compose the same way the existing optional
  gates already compose — CAB-1 adds one more step in the sequence without
  changing how the others are enforced.
- What happens when a CAB-1 reviewer rejects with no further explanation
  given? The rejection itself is sufficient; the task does not require a
  redraft-and-resubmit cycle the way an internal draft (e.g. a proposal
  document) might.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST let a human record an explicit approve or
  reject decision (the "CAB-1 decision") for a task's strategic fit, and
  MUST NOT let the task proceed into refinement without that decision when
  CAB-1 is enabled.
- **FR-002**: The CAB-1 decision MUST be preceded by a strategic interview
  that is a distinct step from the refinement interviews that follow gate
  approval — the two MUST be separately identifiable in the task's history.
- **FR-003**: The strategic interview MUST ask only a small, bounded number
  of questions, phrased in plain, non-technical language suitable for the
  person who originally requested the work.
- **FR-004**: The CAB-1 decision MUST evaluate only strategic fit and
  priority — the system MUST NOT require or present scope, feasibility, or
  cost analysis as part of it (that review happens later, after
  decomposition).
- **FR-005**: CAB-1 enforcement MUST be configurable per deployment and
  default to off, consistent with the system's other optional review gates.
- **FR-006**: The system MUST enforce the understanding → strategic
  interview → CAB-1 → refinement sequencing deterministically whenever CAB-1
  is enabled, without relying on case-by-case judgment.
- **FR-007**: Rejecting the CAB-1 decision MUST invalidate only the work
  that depended on it; all other recorded task history MUST remain intact
  and visible.
- **FR-008**: Once a task's CAB-1 decision is approved, its subsequent
  refinement step MUST be able to involve audiences or perspectives that are
  not part of the (lighter, non-technical) strategic interview.
- **FR-009**: The system MUST make a task's strategic-interview and CAB-1
  progress visible in the same status/progress view used for its other
  review stages.

### Key Entities

- **Strategic Interview**: A light, question-capped exchange between the
  system and the original requester, focused solely on why the work matters
  and how it fits the broader strategy. Distinct from the deeper refinement
  interviews that follow CAB-1 approval.
- **CAB-1 Decision**: The recorded human approve/reject outcome for a task's
  strategic fit, made after its Strategic Interview and before refinement.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: When CAB-1 is enabled, 100% of tasks reaching the review stage
  have a completed strategic interview before a CAB-1 decision can be
  recorded.
- **SC-002**: A CAB-1 reviewer can record a decision using only the
  strategic interview's answer, without needing to consult a full technical
  analysis.
- **SC-003**: The strategic interview's question count never exceeds its
  configured cap.
- **SC-004**: After a CAB-1 rejection, 100% of the task's prior recorded
  history (understanding, strategic interview) remains queryable and
  unchanged.
- **SC-005**: With CAB-1 left at its default (off), task flow through
  understanding and into refinement is unchanged from current behavior.

## Assumptions

- The "requester" answering the strategic interview is the same real-world
  person already represented later by the existing requester-facing
  refinement interview — the strategic interview just reaches them earlier,
  for a narrower purpose.
- CAB-1 is a single recorded human decision, not a multi-member vote or
  quorum process.
- CAB-1 rejection is terminal for the task's current path (matching how the
  system's other non-PRD gates already behave on rejection) rather than
  triggering an automatic redraft-and-resubmit cycle.
- Expanding the post-approval refinement step to actually reach new
  audiences (e.g. adding security- or design-focused review roles) is
  future work; this feature only needs to make that later expansion
  possible by keeping the strategic interview and the refinement interviews
  structurally distinct, not to build out new audiences itself.
- The later cost/scope/feasibility review that happens after decomposition
  (an existing, separately delivered feature) is unaffected by this feature
  and continues to own that part of the decision process.
- No new timeout/SLA behavior is introduced for a task waiting on a human
  at the strategic interview or CAB-1 decision — it waits the same way any
  other pending human step waits today.
