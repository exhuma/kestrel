# Feature Specification: Autonomous Work Board

**Feature Branch**: `026-autonomous-work-board`

**Created**: 2026-09-24

**Status**: Draft

**Input**: Replace Kestrel's fixed workflow with an internal, event-driven
work board where configurable specialist agents independently claim eligible
work. The coordinator manages the business process within enforced policy.
The board must support durable recovery, safe human input, selective external
updates, and graph plus board visualization.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Safely accept a task for autonomous work (Priority: P1)

An operator submits or labels a task in a configured task source. Kestrel
records it as a work board item, examines the task content before any agent
acts on it, and either begins the approved discovery work or presents a clear
security review for suspect content. A legitimate task progresses without the
operator manually selecting every specialist.

**Why this priority**: Safe ingestion and policy-governed autonomous work are
the foundation for every later specialist, board, and delivery capability.

**Independent Test**: Ingest one normal task and one task containing an unsafe
instruction pattern. Confirm the normal task creates eligible work, while the
suspect task cannot invoke an agent or publish any external update until the
operator explicitly resolves its security review.

**Acceptance Scenarios**:

1. **Given** a task from any configured source that passes input safety policy,
   **When** Kestrel ingests it, **Then** it creates a workflow and its initial
   work cards without requiring a fixed predefined sequence of steps.
2. **Given** a task containing content classified as suspect, **When** Kestrel
   receives it, **Then** Kestrel records a quarantined security review and
   prevents agent dispatch, translation, acknowledgement, and source writes
   based on that content.
3. **Given** a quarantined task, **When** the operator releases it after
   reviewing the security finding, **Then** Kestrel records the release
   decision and may create eligible work from the released content.
4. **Given** a quarantined task, **When** the operator discards it, **Then**
   Kestrel records the decision, performs no task-source mutation, and does
   not offer the task for agent work.

---

### User Story 2 - Coordinate independent specialist work (Priority: P1)

An operator watches Kestrel turn an accepted task into independently owned
work cards. The coordinator reacts to meaningful work events, delegates only
to configured eligible specialists, and creates reconciliation work when
specialist findings conflict. Specialists can read and analyze in parallel,
while Kestrel prevents conflicting writes to one repository.

**Why this priority**: This replaces the strict driver with the requested
office-like model of independently operating specialists and policy-bound
coordination.

**Independent Test**: Seed a workflow with two independent read-only cards,
one repository-writing card, and one dependent card. Verify that eligible
read-only cards may run together, only one writer can claim the repository,
and the dependent card remains unavailable until its inputs are complete.

**Acceptance Scenarios**:

1. **Given** a workflow with completed prerequisites, **When** an eligible
   specialist has capacity, **Then** it can claim its ready card without a
   coordinator session remaining continuously active.
2. **Given** two independent read-only cards, **When** both become ready,
   **Then** Kestrel can run them concurrently within configured resource caps.
3. **Given** a card requiring repository writes, **When** another writer holds
   that repository's work lease, **Then** the new card remains waiting for its
   dependency/resource and cannot modify the repository.
4. **Given** two valid specialist outputs that conflict, **When** the
   coordinator receives them, **Then** it creates a reconciliation card rather
   than silently replacing either output or advancing affected work.
5. **Given** a specialist proposes follow-up work, **When** the proposal is
   accepted by policy, **Then** only the coordinator creates the downstream
   card or external child task.

---

### User Story 3 - Preserve work through interruption and recovery
(Priority: P1)

An operator can interrupt Kestrel at any point and restart it without losing
the work necessary to understand, resume, retry, or safely escalate the
workflow. Specialists leave durable handoff artifacts whenever later work or
recovery needs their output. Project-material artifacts are included in the
project change; orchestration-only artifacts are not.

**Why this priority**: Interruptibility and recovery are an existing project
principle and become more important when work is independently scheduled.

**Independent Test**: Interrupt a workflow with a claimed card, a completed
analysis artifact, and a pending dependent card. Restart Kestrel and verify
that the completed artifact remains available, the abandoned claim follows the
retry policy, and no orchestration-only artifact is included in project work.

**Acceptance Scenarios**:

1. **Given** a card whose output is needed after completion or restart,
   **When** the card completes, **Then** its accepted output is retained as an
   immutable, versioned handoff artifact with producer and input provenance.
2. **Given** a process restart while a specialist holds a card, **When** its
   claim lease expires, **Then** Kestrel records the interrupted attempt and
   retries, reassigns, or escalates the card according to its bounded policy.
3. **Given** a durable artifact that is material to the target project,
   **When** the responsible work is delivered, **Then** the artifact is
   included with the project change when its card marks it as project material.
4. **Given** a durable artifact used only to coordinate agents, **When** code
   is committed or delivered, **Then** it is retained for workflow recovery but
   is excluded from the project change.

---

### User Story 4 - Keep existing human approvals visible and authoritative
(Priority: P1)

An operator sees understanding, refinement input, PRD approval, decomposition
approval, and security review as explicit cards waiting for human action. The
operator can approve, reject, request changes, answer questions, release
quarantined input, or discard it. A gate decision only unblocks the work it
authorizes and remains traceable afterwards.

**Why this priority**: The new workflow must preserve the current human
control points rather than allowing autonomy to bypass scope authority.

**Independent Test**: Drive a workflow through each gate type. Verify that
dependent work cannot be claimed before the decision, that an approval leaves
a durable revision record, and that a rejection invalidates only affected
downstream work.

**Acceptance Scenarios**:

1. **Given** work requiring requester approval, **When** its review artifact
   is ready, **Then** Kestrel creates an `awaiting_human` gate card with the
   decision, artifact revision, and affected work clearly identified.
2. **Given** an unresolved human gate, **When** another card depends on it,
   **Then** the dependent card is shown as waiting on that gate and cannot be
   claimed.
3. **Given** an approved PRD, **When** later work proposes a material scope
   change, **Then** Kestrel does not treat the proposal as approved scope until
   the required human decision is recorded.
4. **Given** an operator submits an edit, answer, or change request containing
   suspect content, **When** Kestrel receives it, **Then** the original gate
   remains unresolved and the input follows the security review process.

---

### User Story 5 - Resolve verification findings at the right authority
(Priority: P2)

The verifier can return ordinary implementation defects to the code and
verification loop without bothering the operator. When it finds an ambiguity,
contradiction, infeasible requirement, or material risk that needs a business
decision, it asks the coordinator to create the appropriate review or human
gate instead.

**Why this priority**: This keeps autonomous implementation effective while
protecting the human-approved requirements boundary.

**Independent Test**: Submit one verification result showing a clear PRD
violation and one showing an ambiguous acceptance criterion. Confirm the first
creates internal remediation work and the second creates coordinator review
without silently changing the PRD.

**Acceptance Scenarios**:

1. **Given** a verifier finding that implementation does not meet an approved
   requirement, **When** the finding is validated, **Then** Kestrel creates or
   reopens internal remediation work without opening a human gate by default.
2. **Given** a verifier finding that requirements are ambiguous, contradictory,
   infeasible, or materially risky, **When** the finding is validated, **Then**
   the verifier sends a structured escalation to the coordinator and does not
   modify requirements or open a human gate itself.
3. **Given** a coordinator escalation that requires requester input, **When**
   it is accepted by policy, **Then** Kestrel creates a human gate and blocks
   only work dependent on its outcome.

---

### User Story 6 - Understand and intervene in the work board (Priority: P2)

An operator can inspect the same workflow as a clear board and as an
interactive dependency graph. They can see ownership, current activity,
waiting reasons, security state, dependencies, artifacts, and the history of
decisions. They can retry, cancel, reassign eligible work, resolve a gate, or
request coordinator review without dragging cards through unauthorized states.

**Why this priority**: The board is the operator's primary mental model for
emergent collaboration and must remain understandable as work fans out.

**Independent Test**: Open a workflow with ready, claimed, dependency-waiting,
human-waiting, quarantined, and completed cards. Use both board and graph views
to locate a card, inspect its blocker/artifacts, and perform one authorized
intervention; verify an unauthorized state change is unavailable.

**Acceptance Scenarios**:

1. **Given** a workflow with cards in several states, **When** an operator
   opens its board, **Then** cards are grouped by their universal state and
   clearly distinguish dependency waiting, human waiting, and quarantine.
2. **Given** a workflow with card dependencies, **When** an operator opens its
   graph view, **Then** cards and their dependency or reconciliation relations
   are visible, selectable, and updated as workflow state changes.
3. **Given** a selected card, **When** the operator opens its detail view,
   **Then** they can see its role, claim/lease, inputs, artifacts, attempts,
   waiting reason, and event history without exposing unsafe raw content.
4. **Given** a failed, claimed, or gated card, **When** the operator chooses an
   allowed intervention, **Then** Kestrel validates the action against policy,
   records it, and updates the board; arbitrary state dragging is unavailable.
5. **Given** an operator uses a keyboard or a narrow display, **When** viewing
   workflow state, **Then** an accessible list or board view provides the same
   essential status and intervention functions as the graph view.

---

### User Story 7 - Keep external task sources useful without mirroring the
entire board (Priority: P3)

An operator continues using GitHub, Jira, or local task sources for the
request, human-facing approvals, blockers, and delivery outcome. Kestrel keeps
fine-grained activity on its internal board and posts only meaningful
milestones, avoiding status noise and preserving public-source history rules.

**Why this priority**: The internal board improves control without requiring
operators to abandon their established task source.

**Independent Test**: Run a workflow that claims, retries, waits on a human
gate, escalates, and delivers. Confirm that the source receives gate,
blocker/escalation, approved-artifact, child-task, and delivery updates but no
comment for ordinary claims or retries.

**Acceptance Scenarios**:

1. **Given** an externally sourced workflow, **When** an ordinary card is
   claimed, retried, or completed internally, **Then** Kestrel does not create
   a task-source update solely for that internal transition.
2. **Given** a human gate, material blocker, approved externally relevant
   artifact, external child task, or delivery outcome, **When** it occurs,
   **Then** Kestrel projects the relevant milestone to the originating task
   source when that source supports it.
3. **Given** a public task source, **When** Kestrel projects board activity or
   cleans up workflow artifacts, **Then** it preserves forward-only task
   history and changes only Kestrel-owned, durably recorded artifacts.

---

### Edge Cases

- A task or feedback item arrives through both a webhook and polling. The
  security decision, quarantine, source projection, and work creation occur at
  most once for the source item.
- A source task changes after its initial safety assessment but before it is
  used in later work. The newly fetched content must not bypass safety policy.
- A security classifier is unavailable, malformed, or exceeds its budget. The
  affected external or gate input fails closed into review; it never proceeds
  as trusted input.
- A specialist definition is missing, malformed, has incompatible abilities, or
  is removed while work is waiting. Kestrel does not dispatch the affected card
  and presents an actionable blocked or failed state according to policy.
- A card claim expires after the specialist completed an external side effect
  but before recording completion. Recovery must avoid duplicate source writes
  and retain the attempt history for reconciliation.
- A coordinator plan is malformed or requests a forbidden card, transition,
  source update, write lease, or scope change. Kestrel rejects that action,
  records the reason, and does not mutate the workflow from the invalid plan.
- A workflow graph contains a cycle. Kestrel prevents the cycle from becoming
  runnable, identifies the involved cards, and requests reconciliation or
  operator intervention rather than waiting forever.
- A human gate is rejected after downstream read-only analysis has completed.
  Kestrel preserves the historical artifacts but invalidates outputs that no
  longer derive from approved scope before they can drive delivery.
- A graph is too dense for practical visual inspection. The board remains a
  complete, keyboard-operable alternative; graph navigation never becomes the
  only way to inspect or act on work.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST replace the fixed workflow-step progression with a
  workflow containing typed work cards and explicit dependency relationships.
- **FR-002**: System MUST use the card states `ready`, `claimed`,
  `waiting_dependency`, `awaiting_human`, `review`, `quarantined`, `done`,
  `failed`, and `cancelled`; state transitions MUST be policy validated and
  recorded.
- **FR-003**: System MUST treat `waiting_dependency`, `awaiting_human`, and
  `quarantined` as separately identifiable states in all operator-visible
  workflow views and interfaces.
- **FR-004**: System MUST provide an event-driven coordinator that reacts to
  task ingestion, card outcomes, incoming feedback, gate decisions, lease
  expiry, and absence of eligible work; it MUST produce bounded, structured
  actions rather than retain unbounded continuous authority.
- **FR-005**: System MUST validate every coordinator action against
  deterministic policy before it creates, transitions, cancels, reassigns, or
  projects work.
- **FR-006**: System MUST allow only the coordinator to create downstream
  cards and external child tasks. Specialists MAY submit structured proposals
  for that work.
- **FR-007**: System MUST load a named specialist roster from an operator-owned
  file tree. Each specialist definition MUST declare a stable identity, label,
  purpose, allowed card types, required abilities, model policy, workspace
  permission, retry limit, and prompt content or prompt-file references.
- **FR-008**: System MUST ship default definitions for the existing requester,
  project-management, UX, engineering, security, database, architecture,
  operations, and quality roles, plus coordinator, coder, verifier, and input
  security roles.
- **FR-009**: System MUST reject invalid specialist definitions before they can
  receive work, including definitions with missing required fields, unsupported
  card types, incompatible required abilities, or unsafe workspace permission.
- **FR-010**: System MUST permit independent eligible read-only cards to run in
  parallel within configured capacity limits.
- **FR-011**: System MUST ensure that no more than one write-capable card holds
  a repository/workspace write lease for the same repository at one time.
- **FR-012**: System MUST persist card claims, lease expiry, attempts, retries,
  ownership, and outcome history so restart recovery can retry, reassign, or
  escalate abandoned work without losing completed work.
- **FR-013**: System MUST retain an immutable, versioned handoff artifact when
  a card's output is needed for recovery, reassignment, reconciliation, or a
  downstream card.
- **FR-014**: System MUST record each handoff artifact's producing card, input
  artifact revisions, integrity identifier, trust classification, retention
  class, and whether it is material to the target project.
- **FR-015**: System MUST include a material artifact in project delivery only
  when its responsible work explicitly identifies it as material to the target
  project. Orchestration-only artifacts MUST remain available for recovery and
  MUST NOT be included in the project change.
- **FR-016**: System MUST preserve the existing understanding approval,
  refinement input, PRD approval, and decomposition approval decisions as
  explicit human-gate cards with revision and decision history.
- **FR-017**: System MUST retain the approved PRD as immutable scope authority.
  A later card MAY NOT expand or replace that scope without the required human
  decision.
- **FR-018**: System MUST treat task-source bodies, task-source feedback,
  review feedback, human-gate edits, questionnaire answers, local task files,
  and local feedback as untrusted input before they can influence an agent,
  workflow state, source update, or external model service.
- **FR-019**: System MUST assess untrusted external and human-gate input using
  deterministic boundary policy and the input-security specialist's structured
  classification. Neither prompts nor frontend validation alone may authorize
  input progression.
- **FR-020**: System MUST quarantine input that is suspect, exceeds permitted
  input bounds, cannot be classified safely, or receives a malformed security
  result. Quarantined input MUST NOT invoke an agent, translation, automatic
  acknowledgement, task-source write, gate decision, or workflow transition.
- **FR-021**: System MUST create an auditable security-review record for
  quarantined input containing the source identity, integrity identifier,
  classification category, policy version, timestamps, and resolution. It MUST
  deduplicate repeated delivery of the same source input.
- **FR-022**: System MUST allow the operator to release or discard quarantined
  input. Release MUST be a new recorded decision; discard MUST leave the
  original task or feedback unmodified.
- **FR-023**: System MUST present intentionally authored direct session prompts
  to the operator with an injection-risk warning and explicit confirmation
  instead of automatically quarantining them, while still applying input bounds
  and retaining a decision record.
- **FR-024**: System MUST keep human-originated or source-originated content
  clearly separated from governing specialist instructions whenever content is
  supplied to an agent. Untrusted content MUST NOT select a specialist,
  backend, permission level, repository, command, hook, or approval state.
- **FR-025**: System MUST not include full suspect input in logs, exceptions,
  notifications, or automated source replies. Operator review MUST use a safe
  rendering path and must not execute raw content as markup.
- **FR-026**: System MUST create a reconciliation card when valid specialist
  outputs conflict or fail a downstream acceptance contract. The coordinator
  MUST NOT silently overwrite a specialist output.
- **FR-027**: System MUST allow the verifier to create internal remediation
  work for implementation nonconformance or verification gaps within approved
  scope.
- **FR-028**: System MUST require the verifier to send ambiguity, requirement
  conflict, technical infeasibility, and material security/policy risk to the
  coordinator as a structured escalation. The verifier MUST NOT independently
  alter requirements or open a human gate.
- **FR-029**: System MUST route incoming feedback to the relevant cards and
  invalidate only downstream work that no longer has valid inputs or approved
  scope. It MUST NOT rely on a fixed set of workflow re-entry positions.
- **FR-030**: System MUST provide an operator board grouped by card state and a
  dependency graph view that shows cards, relationships, ownership, lease
  status, wait reasons, artifacts, security state, and live updates.
- **FR-031**: System MUST provide a keyboard-operable board/list alternative
  with the same essential status and permitted interventions as the graph view.
- **FR-032**: System MUST permit operators to retry, cancel, reassign eligible
  cards, resolve gates, and request coordinator review. System MUST reject
  manual transitions that violate policy and MUST NOT offer arbitrary card
  dragging as a state-change mechanism.
- **FR-033**: System MUST make the internal board authoritative for granular
  work state and project only human gates, material blockers/escalations,
  approved externally relevant artifacts, external child tasks, and delivery
  outcomes to task sources by default.
- **FR-034**: System MUST NOT project ordinary card claims, retries, or routine
  completions to the originating task source by default.
- **FR-035**: System MUST preserve existing public task-source constraints:
  public task history is forward-only, and cleanup may change only durable,
  Kestrel-owned artifacts while restoring an original task exactly where
  restoration is supported.
- **FR-036**: System MUST provide workflow, card, artifact, dependency, and
  event information through the same live-update experience used to monitor
  active work.
- **FR-037**: System MUST remove the fixed workflow driver and fixed six-step
  visualization as the operating model. This is a green-field replacement;
  existing development data does not require workflow-state migration.

### Key Entities

- **Workflow**: The internal record for one accepted task and all work,
  decisions, artifacts, and external projections that Kestrel owns for it.
- **Work Card**: A typed, policy-governed unit of work with dependencies,
  required inputs, acceptance contract, state, eligible roles, and outcome.
- **Specialist Definition**: An operator-owned role contract and prompt
  definition describing what a named specialist may do and what it requires.
- **Claim Lease**: A time-bounded, durable assignment of a card to one
  specialist, including attempt and recovery information.
- **Handoff Artifact**: An immutable version of card output retained for
  recovery or downstream work, with provenance, trust, and delivery metadata.
- **Human Gate**: A work card that requests a specific operator decision or
  answer and controls only its declared dependent work.
- **Security Review**: A quarantine record and gate for untrusted input whose
  safety assessment prevented normal processing.
- **Coordinator Action**: A structured proposed board change that takes effect
  only after deterministic policy validation.
- **External Projection**: A selected, human-meaningful update sent to the
  task source without mirroring the internal board's every transition.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A normal accepted task can reach an eligible specialist card
  without relying on a fixed ordered list of workflow stages.
- **SC-002**: In a workflow with at least two independent read-only cards and
  two writer candidates for one repository, both readers can be active while
  no more than one writer is active for that repository at any observed time.
- **SC-003**: After an interruption during active work, 100% of completed
  accepted artifacts, recorded gate decisions, and card attempt history remain
  available after restart; each abandoned claim reaches retry, reassignment, or
  escalation according to its configured limit.
- **SC-004**: In automated coverage of each supported input transport, 100% of
  suspect or unclassifiable external/gate inputs are prevented from reaching an
  agent, translator, automatic acknowledgement, task-source mutation, or
  workflow-advancing decision before an operator release.
- **SC-005**: An operator can identify a card's owner, current state, waiting
  reason, direct dependencies, and most recent artifact from either the board
  or detail view in no more than two selections.
- **SC-006**: An operator can resolve an existing human gate or security review
  through the board without editing external task-source state directly.
- **SC-007**: A verifier finding limited to implementation nonconformance
  creates internal remediation without an operator gate, while each simulated
  requirement ambiguity produces coordinator review before any requirement
  mutation.
- **SC-008**: For a workflow containing claims, retries, gates, one escalation,
  and delivery, the external task source receives updates only for gates,
  material blocker/escalation, approved relevant artifacts, child work, and
  delivery, with zero updates for routine claims and retries.
- **SC-009**: Keyboard-only users can inspect every card state and invoke every
  permitted intervention without relying on graph-canvas interaction.

## Assumptions

- Kestrel remains a single-user tool. The operator owns specialist definitions
  and is the sole authority for human-gate and security-release decisions.
- The replacement is green-field development. No production workflow state or
  legacy in-flight run requires migration.
- The existing task-source and code-host separation remains. Task sources are
  not required to expose a matching Kanban model.
- Existing source authentication, webhook authenticity, feedback deduplication,
  and Kestrel-owned cleanup guarantees remain in effect, but are not treated as
  prompt-injection protection.
- The initial specialist roster is file-based and named. Runtime-created roles
  and executable third-party specialist plugins are outside this feature.
- A graph visualization is read-only navigation and explanation. The board is
  the accessible, authoritative operator surface for status and intervention.
- Work-card type contracts define completion and artifact expectations. The
  detailed vocabulary may grow after this feature without changing the
  universal card states or coordinator authority boundary.
