# Feature Specification: CAB Estimates

**Feature Branch**: `016-cab-estimates`

**Created**: 2026-09-17

**Status**: Draft

**Input**: Add task estimates, model recommendations, and mandatory CAB
publication to technical analysis.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Review an informed decomposition (Priority: P1)

A requester reviews a proposed technical decomposition and can see the delivery
effort, coding-agent token budget, and best-value coding-model recommendation
for every child task before approving publication.

**Why this priority**: The estimates are required for a decision before work is
created and scheduled.

**Independent Test**: Produce a decomposition with a discoverable coding-model
catalogue and verify every proposed child displays all three planning values.

**Acceptance Scenarios**:

1. **Given** approved requirements and a usable coding-model catalogue, **When**
   technical analysis creates a proposal, **Then** every child task has a
   positive effort estimate, a positive token estimate, and a model
   recommendation from that catalogue.
2. **Given** a coding backend whose model catalogue cannot be determined,
   **When** technical analysis creates a proposal, **Then** affected model
   recommendations are shown as unknown rather than guessed.

---

### User Story 2 - Make a CAB decision quickly (Priority: P1)

A CAB member reads the last comment on an approved parent task and receives the
minimum information needed to make a go/no-go decision without reviewing the
full technical analysis.

**Why this priority**: CAB review meetings contain many candidates and require
consistent, scannable decision records.

**Independent Test**: Approve a multi-child proposal and verify that the final
parent comment asks CAB to decide and contains the scope, totals, model allocation, and
only decision-relevant risks or dependencies.

**Acceptance Scenarios**:

1. **Given** an approved proposal with successful child publication, **When**
   the parent is completed, **Then** its detailed technical analysis comment is
   followed by a separate CAB summary comment.
2. **Given** the CAB summary comment cannot be published, **When** publication
   is attempted, **Then** the parent is not marked decomposed and the failure is
   visible for recovery.
3. **Given** a successful parent completion, **When** the comment timeline is
   inspected, **Then** no workflow-generated parent comment follows the CAB
   summary.

---

### User Story 3 - Operate heterogeneous model infrastructure (Priority: P2)

An operator can expose on-site and frontier coding models through configured
backends, allowing Kestrel to make recommendations only from confirmed,
cost-qualified choices.

**Why this priority**: The organization uses multiple model providers and must
not base a financial recommendation on a fixed vendor catalogue.

**Independent Test**: Query a configured backend's model catalogue and verify
available models are returned with their coding suitability and cost metadata;
unsupported discovery reports unknown.

**Acceptance Scenarios**:

1. **Given** a backend that supports model introspection, **When** its catalogue
   is requested, **Then** the available model identifiers and their planning
   metadata are returned.
2. **Given** a backend that does not support introspection or is unavailable,
   **When** its catalogue is requested, **Then** the result is unknown without
   exposing credentials or raw infrastructure errors.

### Edge Cases

- A valid backend catalogue can be empty; it is not the same as unknown.
- A model without cost or coding-quality metadata cannot be called the best
  monetary ROI and is not selected for a recommendation.
- A previously posted detailed analysis must not be duplicated when only the
  mandatory CAB publication is retried.
- A model inventory can change after approval; the approved proposal retains
  the catalogue used to validate its recommendations.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Every proposed child task MUST carry a positive effort estimate in
  man-days and a positive coding-agent token estimate.
- **FR-002**: Every proposed child task MUST carry either a backend-qualified
  coding-model recommendation or an explicit unknown recommendation.
- **FR-003**: A non-unknown recommendation MUST name a discovered, coding-capable
  model with sufficient cost and coding-quality metadata to compare ROI.
- **FR-004**: The system MUST retain estimates, recommendations, and the model
  catalogue used to validate them from proposal through publication and retry.
- **FR-005**: Published child tasks MUST visibly include their approved effort,
  token, and model-planning values.
- **FR-006**: The system MUST publish a detailed technical-analysis comment on
  the parent before publishing the separate CAB summary comment.
- **FR-007**: The CAB summary MUST be the final workflow-generated parent
  comment, explicitly request CAB review, and include only scope, material
  blockers or risks, child count, total effort, total token budget, and model
  allocation. It MUST NOT recommend a go/no-go outcome.
- **FR-008**: Failure to publish either mandatory parent comment MUST prevent
  decomposition completion and remain recoverable without duplicating completed
  publication work.
- **FR-009**: Every configured backend MUST expose a model-catalogue result as
  either available or unknown; unknown MUST not be reported as an empty list.
- **FR-010**: Catalogue data MUST provide each model's identifier, coding-agent
  capability, cost basis, and coding-quality tier or score when available.

### Key Entities

- **Model catalogue**: A backend-owned inventory of models and their planning
  metadata, with an explicit available or unknown state.
- **Model recommendation**: A backend-qualified, approved coding-model choice
  for one child task, or an explicit unknown state.
- **Delivery estimate**: The man-day and coding-agent-token budgets attached to
  one child task.
- **CAB summary**: The final, concise parent-task decision record that rolls up
  approved delivery estimates and decision-critical information.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of approved published child tasks display a positive
  man-day estimate and a positive coding-agent token estimate.
- **SC-002**: 100% of non-unknown model recommendations identify a confirmed
  coding-capable model with comparable cost and quality information.
- **SC-003**: 100% of successfully decomposed parent tasks end with one CAB
  summary comment posted after the detailed technical analysis.
- **SC-004**: CAB summaries present all required decision information in no more
  than 12 lines for decompositions of up to five child tasks.
- **SC-005**: 100% of unavailable or unsupported model-catalogue requests return
  an explicit unknown state without failing unrelated work.

## Assumptions

- Backend adapters own the discovery protocol and return identifiers in the
  syntax that their dispatch mechanism accepts.
- Cost and coding-quality metadata is supplied by backend introspection; Kestrel
  does not maintain a duplicate operator-managed pricing catalogue.
- A recommendation is planning advice and does not automatically override the
  configured backend/model policy when a child run starts.
- Mandatory parent-comment publication failures leave the run recoverable and
  must not create duplicate child tasks or duplicate successful comments.
