# Feature Specification: Task Decomposition Pipeline

**Feature Branch**: `012-task-decomposition-pipeline`

**Created**: 2026-09-02

**Status**: Draft

**Input**: User description: "Add a task-decomposition front end to kestrel's
ingestion pipeline: (1) an understanding-checkpoint where kestrel restates its
read of an ingested task and the requester confirms or amends it; (2) a
strictly non-technical, requestor-altitude, go/no-go PRD phase, replacing
today's undifferentiated refine interview; (3) a technical-analysis phase,
entered only after PRD approval, that produces an architecture/technical
decision record and decomposes the approved PRD into independent,
self-contained follow-up tasks published back to the task source as
subdivisions of the original ticket — without those follow-up tasks
themselves starting a new kestrel run. The original task's run ends once
decomposition is published; a follow-up task, when later triggered, skips
straight to technical design instead of repeating the front end."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Confirm kestrel's understanding before any deeper work (Priority: P1)

A requester submits a task (via GitHub issue, Jira ticket, or a local
fixture). Before kestrel asks any clarifying questions or starts drafting a
requirements document, it states back, in plain language, what it understood
the task to be — and the requester can either confirm that understanding or
correct it.

**Why this priority**: Every later phase (the PRD, the technical analysis, the
follow-up tasks) is built on top of kestrel's understanding of the original
ask. Catching a misunderstanding here, before any effort is spent, is the
cheapest possible place to catch it and prevents a chain of downstream work
built on a wrong premise.

**Independent Test**: Submit a task with a deliberately ambiguous or easily
misread request. Confirm kestrel produces a restatement, and that supplying a
correction changes what kestrel proceeds with. This delivers value even if
phases 2 and 3 below did not exist yet — it stops wrong-premise work at the
door for any task.

**Acceptance Scenarios**:

1. **Given** a newly ingested task, **When** kestrel begins working on it,
   **Then** the requester is shown a plain-language restatement of what
   kestrel understands the task to be, before any clarifying questions are
   asked.
2. **Given** a restatement that correctly captures the task, **When** the
   requester confirms it, **Then** kestrel proceeds to the next phase.
3. **Given** a restatement that misses or misstates something, **When** the
   requester supplies a correction, **Then** kestrel produces a revised
   restatement incorporating the correction and asks for confirmation again,
   repeating until the requester confirms.
4. **Given** an unconfirmed restatement, **When** no confirmation has been
   given, **Then** kestrel does not begin asking clarifying questions or
   drafting a requirements document.

---

### User Story 2 - Get a non-technical, go/no-go requirements document (Priority: P2)

Once the requester confirms kestrel's understanding, kestrel gathers the
information needed to produce a requirements document — but this document
stays at the altitude of "should this happen at all": the problem, the
desired outcome, who it's for, scope, and acceptance criteria, from the
requestor's point of view only. It deliberately excludes technical approach,
architecture, or implementation detail, so a non-technical decision-maker can
read it and decide whether to proceed. The requester can amend it before
approving it.

**Why this priority**: This is the actual go/no-go decision point — a human
decides whether the work should happen at all before any technical effort (or
technical framing) is spent on it. It depends on User Story 1 (the confirmed
understanding is its starting point) but is independently valuable: even
without decomposition into follow-up tasks (User Story 3), a clean go/no-go
document is useful for the requester's own decision-making and for handing
off to whoever does the technical work next.

**Independent Test**: Confirm an understanding (User Story 1), then verify
the resulting requirements document contains only business-level content —
problem, outcome, scope, acceptance criteria — and no architecture or
implementation language. Verify rejecting it with feedback produces a revised
document, and approving it lets the run proceed.

**Acceptance Scenarios**:

1. **Given** a confirmed understanding, **When** kestrel gathers clarifying
   information for the requirements document, **Then** every question asked
   is phrased at a non-technical, business/requestor level — no question
   probes implementation approach, architecture, or technical feasibility.
2. **Given** a completed requirements document, **When** the requester reads
   it, **Then** it describes only the requestor's needs (problem, desired
   outcome, scope, acceptance criteria) framed to support a go/no-go
   decision, with no implementation or architecture detail present.
3. **Given** a requirements document awaiting approval, **When** the
   requester rejects it with feedback, **Then** kestrel produces a revised
   document incorporating that feedback and presents it for approval again.
4. **Given** a requirements document awaiting approval, **When** the
   requester approves it, **Then** kestrel proceeds to technical analysis;
   **when** the requester instead withdraws the request, **Then** the run
   ends without further work.

---

### User Story 3 - Get independently implementable follow-up tasks instead of a black-box implementation (Priority: P3)

Once the go/no-go requirements document is approved, kestrel analyzes it
technically: it works out the architecture and technical decisions the work
requires, and breaks the work into a set of independent tasks. Each of those
tasks, along with a summary of the technical analysis and decisions, is
published back into the same tracker the original task came from, as
follow-up items tied to the original ticket. Each follow-up task is written
so it can be picked up and implemented on its own — by kestrel later, or by a
person — without needing to go back and read the original ticket, the
requirements document, the technical-analysis summary, or any other follow-up
task to understand what to do.

**Why this priority**: This is what turns a single, possibly large or
ambiguous request into a set of concretely actionable, independently
schedulable pieces of work — the payoff of running the first two phases at
all. It depends on both prior stories (it starts from the approved
requirements document) and is the most complex piece, hence lowest priority
to build first, but it is the reason the pipeline exists rather than kestrel
simply diving into an implementation blind.

**Independent Test**: Approve a requirements document (User Story 2), then
verify a technical-analysis summary and one or more follow-up tasks appear in
the originating tracker, each linked to the original ticket. Verify a
follow-up task's content alone (with no access to the original ticket or its
siblings) is sufficient to describe what needs to be built and why. Verify
the original task's run completes at this point rather than continuing into
implementation, and that the follow-up tasks did not themselves start new
runs.

**Acceptance Scenarios**:

1. **Given** an approved requirements document, **When** technical analysis
   runs, **Then** it produces a record of the architecture/technical
   decisions made and a set of one or more independent follow-up tasks
   covering the approved work.
2. **Given** a produced follow-up task, **When** it is read on its own, with
   no access to the original ticket, the requirements document, the
   technical-analysis summary, or any sibling follow-up task, **Then** it
   still contains everything needed to implement it — including any
   architecture decisions, shared interfaces/contracts with sibling tasks,
   and acceptance criteria relevant to it.
3. **Given** completed technical analysis, **When** its outputs are ready,
   **Then** the technical-analysis summary and every follow-up task are
   published back to the task source, linked to the original ticket, and the
   original task's run ends successfully without kestrel performing design,
   implementation, or verification work against the original ticket itself.
4. **Given** follow-up tasks have just been published to the task source,
   **When** kestrel's ingestion next runs, **Then** none of the newly
   published follow-up tasks is mistaken for a new, independent task request
   and no new run is started for any of them as a side effect of their
   creation.
5. **Given** a follow-up task is later, independently triggered the same way
   any task is triggered, **When** kestrel begins work on it, **Then** it
   starts directly at technical design rather than repeating the
   understanding-checkpoint or requirements-document phases.

---

### Edge Cases

- What happens if the requester never responds to the understanding
  restatement or the requirements document? The run parks awaiting that
  input, the same way today's approval gate parks a run, indefinitely, until
  the requester responds or the request is withdrawn.
- What happens if the requester rejects the understanding restatement (or the
  requirements document) with no corrective feedback at all? The run ends
  without further work, the same way an unqualified rejection ends a run
  today.
- What happens if technical analysis determines the approved work is a single
  indivisible unit that doesn't warrant splitting? It still produces at least
  one follow-up task (re-scoped technically) and a technical-analysis
  summary, so the "the original run always ends by publishing follow-up work"
  guarantee holds even in the degenerate one-task case.
- What happens if the task source a given ticket came from does not support
  publishing follow-up tasks at all? Every supported task source is required
  to support this; there is no degraded path where decomposition is skipped
  because the source can't accept it.
- What happens if a person or process manually edits or replies to a follow-up
  task before it is triggered? That is ordinary tracker activity on an
  as-yet-untriggered ticket; it does not start a run, the same as any other
  untriggered ticket sitting in the tracker.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Immediately after ingesting a task and before asking any
  clarifying questions, the system MUST produce a plain-language restatement
  of its understanding of the task and present it to the requester for
  confirmation.
- **FR-002**: The system MUST let the requester amend or correct the
  restated understanding, MUST produce a revised restatement incorporating
  each correction, and MUST repeat confirmation until the requester
  explicitly confirms it or withdraws the request.
- **FR-003**: The system MUST NOT begin gathering information for the
  requirements document (or ask any clarifying question) until the requester
  has explicitly confirmed the restated understanding.
- **FR-004**: While gathering information for the requirements document, the
  system MUST restrict itself to non-technical, requestor-altitude
  perspectives (e.g. the business owner/requester's own priorities and
  user-facing concerns) and MUST NOT surface questions about implementation
  approach, architecture, or technical feasibility during this phase.
- **FR-005**: The resulting requirements document MUST describe only the
  requestor's needs — the problem, desired outcome, scope, and acceptance
  criteria — framed to support a go/no-go decision, and MUST exclude
  implementation or architecture detail.
- **FR-006**: The system MUST let the requester reject the requirements
  document with feedback, producing a revised document that is presented for
  approval again, repeating until the requester approves it or withdraws the
  request.
- **FR-007**: The system MUST NOT begin technical analysis until the
  requester has explicitly approved the requirements document.
- **FR-008**: Upon approval of the requirements document, the system MUST
  perform a technical-analysis phase that produces (a) a record of the
  architecture/technical decisions made and (b) a decomposition of the
  approved work into one or more independent follow-up tasks.
- **FR-009**: The technical-analysis phase MUST produce at least one
  follow-up task even when the approved work is judged not to warrant
  splitting into multiple tasks.
- **FR-010**: Each follow-up task MUST be technically self-contained: it
  MUST contain, inline, every architecture decision, shared interface/
  contract detail, and acceptance criterion relevant to that task, without
  further access to the technical-analysis summary or any sibling follow-up
  task. It MUST NOT restate the requirements document's business framing
  (the problem, who it is for, why it matters) — that stays reachable via
  the task's link to its parent ticket, so the PRD stays high-altitude and
  the task stays low-altitude/technical, referencing the PRD instead of
  duplicating it (found redundant in manual testing: near-identical wording
  between a PRD and its sole decomposed task).
- **FR-011**: The system MUST publish each follow-up task back to the task
  source the original ticket came from, as a distinct item linked to (a
  subdivision of) the original ticket.
- **FR-012**: The system MUST publish the technical-analysis summary
  (decisions and rationale) back to the task source, associated with the
  original ticket, for human reference.
- **FR-013**: Publishing follow-up tasks MUST NOT itself start a new kestrel
  run for any of them; a follow-up task only starts a run when it is
  independently and explicitly triggered later, the same way any other task
  is triggered.
- **FR-014**: The original task's run MUST end successfully once the
  technical-analysis summary and all follow-up tasks have been published;
  the system MUST NOT perform technical design, implementation, or
  verification work against the original ticket itself.
- **FR-015**: When a follow-up task produced by technical analysis is later
  triggered, the system MUST recognize it as already scoped and technical,
  and MUST begin directly with technical design rather than repeating the
  understanding-checkpoint or requirements-document phases.
- **FR-016**: This understanding-checkpoint → requirements-document →
  technical-analysis sequence MUST apply uniformly to every ingested task,
  regardless of task source or task size.

### Key Entities

- **Understanding Statement**: kestrel's plain-language restatement of what
  it believes an ingested task is asking for; carries a confirmed/unconfirmed
  status and a history of requester corrections.
- **Requirements Document**: the business-altitude, go/no-go description of
  the requestor's needs — problem, desired outcome, scope, acceptance
  criteria — produced from the confirmed understanding; carries an
  approval status.
- **Technical-Analysis Summary**: the record of architecture/technical
  decisions made when breaking an approved requirements document down into
  follow-up tasks; associated with the original ticket.
- **Follow-up Task**: one independently implementable unit of work produced
  by technical analysis; self-contained, linked to the original ticket it
  was decomposed from, and to any sibling follow-up tasks it shares
  interfaces or decisions with.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For every ingested task, the requester sees kestrel's
  restated understanding and can confirm or correct it before any
  clarifying question is asked — with zero exceptions across all supported
  task sources.
- **SC-002**: Every requirements document produced is reviewed as
  containing no implementation or architecture content prior to approval —
  zero such documents pass this pipeline with technical detail present.
- **SC-003**: Every follow-up task published to a tracker can be understood
  and correctly implemented by a reader with no access to the original
  ticket, the requirements document, the technical-analysis summary, or
  sibling follow-up tasks.
- **SC-004**: Publishing follow-up tasks results in zero unintended,
  duplicate kestrel runs being started as a side effect of their creation,
  across every supported task source.
- **SC-005**: A triggered follow-up task reaches technical design without
  re-presenting the understanding-checkpoint or requirements-document
  questions already answered by its parent task.
- **SC-006**: An original task's run, once it enters technical analysis,
  always concludes by publishing a technical-analysis summary and at least
  one follow-up task — it never silently stalls or falls through to direct
  implementation of the original ticket.

## Assumptions

- The technical-analysis phase, like today's technical-design phase, runs
  autonomously once the requirements document is approved: it does not add a
  second human approval gate beyond the two now in the pipeline
  (understanding-checkpoint, requirements-document approval). If a
  human-reviewed technical-analysis gate turns out to be wanted, that is a
  follow-on decision, not assumed here.
- Every task source kestrel currently supports is expected to gain the
  ability to publish a follow-up task linked to a parent ticket; how each
  underlying tracker natively models "subdivision of a ticket" (e.g. a
  labelled child issue vs. a native sub-task type) is a source-specific
  detail, not a product-level decision.
- A rejection with no corrective feedback, at either the
  understanding-checkpoint or the requirements-document stage, ends the run
  the same way an unqualified rejection ends a run in the pipeline today.
- The mechanism that keeps a newly published follow-up task from being
  mistaken for a new, independent task request may differ per task source,
  as long as the guarantee (FR-013) holds for all of them.
