# Feature Specification: Feedback Intake

**Feature Branch**: `013-feedback-intake`

**Created**: 2026-09-07

**Status**: Draft

**Input**: User description: "Feedback intake: pick up human feedback left on
the originating task-source ticket and on the PR/MR kestrel opened, and fold
it back into the right point of the pipeline instead of only accepting input
through kestrel's own web UI."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Redirect a parked run from the ticket (Priority: P1)

A requester or reviewer left feedback as a ticket comment while a run is
parked waiting for a human decision (e.g. the understanding-checkpoint or the
requirements-document gate). Today the only way to act on that is to open
kestrel's own web UI and use its reject/amend control. This story lets that
same feedback, left where the human already is (the ticket), redirect the run
without requiring a trip to kestrel's UI.

**Why this priority**: Smallest, lowest-risk slice — reuses the existing
reject-with-feedback mechanism unchanged, touches no git/branch logic, and
delivers the core value ("kestrel listens where I already am") on its own.

**Independent Test**: Park a run at a gate, leave a marked comment on its
ticket with corrective feedback, and confirm the run re-parks with revised
content reflecting that feedback — with no kestrel UI interaction at all.

**Acceptance Scenarios**:

1. **Given** a run parked awaiting approval of its current step, **When** a
   human leaves a ticket comment containing the trigger marker and corrective
   feedback, **Then** the run treats it exactly as a reject-with-feedback
   decision: the step is revised and the run re-parks awaiting approval again.
2. **Given** a ticket comment without the trigger marker, **When** it is
   left on a parked run's ticket, **Then** kestrel takes no action and the run
   stays parked unchanged.
3. **Given** a marked ticket comment already acted on once, **When** it is
   observed again on a later check (e.g. after a restart), **Then** it is not
   applied a second time.

---

### User Story 2 - Steer an actively-working run from the ticket (Priority: P2)

Feedback may arrive while the run has no open gate — it is mid-way through an
autonomous phase (answering its own interview questions, analyzing, coding,
verifying). This story ensures that feedback is not lost, without forcing
kestrel to interrupt work already in progress.

**Why this priority**: Extends Story 1 to the phases with no gate to hang the
feedback on. Meaningful value (feedback is never silently dropped) with
still-contained risk — no interruption semantics, no branch/PR work.

**Independent Test**: Leave a marked ticket comment while a run is in an
autonomous phase, confirm it is not applied immediately (an in-progress step
is not interrupted), and confirm it is applied at that step's next natural
boundary.

**Acceptance Scenarios**:

1. **Given** a run in an autonomous, non-gated phase, **When** a marked ticket
   comment arrives, **Then** the currently in-progress unit of work completes
   undisturbed, and the feedback is applied at the next round or step
   boundary.
2. **Given** feedback queued this way, **When** the run reaches a natural
   boundary, **Then** the feedback is consumed exactly once and reflected in
   what that step produces next.

---

### User Story 3 - Amend the same pull/merge request from review feedback (Priority: P3)

A reviewer requests changes on the pull/merge request kestrel opened. This
story lets that feedback result in new commits on the **same** request,
keeping the review conversation intact, rather than a disconnected new
change.

**Why this priority**: Delivers the other half of the ask (review feedback,
not just ticket feedback) but requires resuming an existing branch and
therefore carries materially more implementation risk than Stories 1-2 — it
depends on them existing first (the same triage-and-redirect concept, now
also picking which pipeline step to resume at) but adds its own new
mechanics.

**Independent Test**: Open a change request, leave marked review feedback on
it, and confirm new commits land on that same request rather than a new one
being opened, with the resulting work addressing the feedback.

**Acceptance Scenarios**:

1. **Given** an open pull/merge request kestrel opened, **When** a reviewer
   leaves marked feedback requesting a change, **Then** kestrel resumes work
   on that request's existing branch and pushes new commits to it — no
   second request is opened for the same underlying change.
2. **Given** review feedback that only concerns the implementation, **When**
   it is picked up, **Then** kestrel re-enters at the implementation step
   without re-opening the approved requirements or design.
3. **Given** review feedback that calls the overall approach into question,
   **When** it is picked up, **Then** kestrel re-enters at whichever earlier
   step (up to and including the original requirements conversation) the
   feedback actually concerns, and a human is asked to re-approve if that
   step normally requires it.
4. **Given** the request being commented on has already been merged or
   closed, **When** feedback arrives on it, **Then** kestrel does not attempt
   to push more commits to a request that can no longer receive them.

---

### User Story 4 - Pick up feedback after a run has already finished (Priority: P4)

A run reached a finished state (delivered, escalated, or decomposed) before
feedback arrived — e.g. someone reviews the shipped result days later and
has a correction. Today that ticket can never start a new run at all, so this
feedback is currently invisible forever.

**Why this priority**: Completes the story but is the least urgent slice —
it depends on Story 3's resume mechanics for the common "there's still an
open request to continue" case, and adds its own handling for the cases
where there is nothing left to resume.

**Independent Test**: Let a run reach a finished state, leave marked
feedback on its ticket or request afterward, and confirm the existing run
picks back up (when there's something to resume) or a new, clearly-linked
run starts (when there is not) — never a second, disconnected, unlinked run
for the same ticket.

**Acceptance Scenarios**:

1. **Given** a finished run whose request is still open, **When** marked
   feedback arrives, **Then** that same run resumes rather than a new one
   being started.
2. **Given** a finished run whose request is merged, closed, or never
   existed, **When** marked feedback arrives, **Then** a new run starts that
   is clearly recorded as continuing from the original.
3. **Given** a run that ended because its work was split into follow-up
   tasks, **When** feedback arrives saying the split was wrong or incomplete,
   **Then** kestrel publishes a correction as an additional or amended
   follow-up task rather than repeating the entire split from scratch and
   risking duplicates of what was already published.
4. **Given** a run that ended because it could not complete the work and gave
   up, **When** feedback arrives with guidance, **Then** kestrel retries the
   affected work with that guidance, starting from the last point it has a
   usable foundation to build on.

---

### Edge Cases

- A comment is edited after the fact to add the trigger marker, once kestrel
  has already looked past it — it is not picked up retroactively.
- Two marked comments arrive in quick succession before the first has been
  fully applied — both are recorded, neither is lost, and they are not
  applied out of order.
- Feedback carries the trigger marker but is ambiguous or unrelated to
  anything actionable (e.g. a question, not an instruction) — kestrel still
  attempts to act on it as feedback rather than silently discarding it, since
  there is no reliable way to distinguish "unclear feedback" from "off-topic
  aside" without acting on it.
- Feedback arrives for a run that is, at that exact moment, already being
  driven by kestrel's own in-progress work (a race between new feedback and
  work already underway) — the feedback is not lost, but it is not allowed to
  disrupt or duplicate that in-progress work either.
- A comment or reaction kestrel itself posts must never be mistaken for human
  feedback and re-trigger kestrel against itself.
- The task source or code host cannot support reacting to a comment (no such
  capability exists there) — kestrel still processes the feedback; only the
  acknowledgment is skipped.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Kestrel MUST be able to read comments left on a run's
  originating ticket, not only post them.
- **FR-002**: Kestrel MUST be able to read review feedback left on a
  pull/merge request it opened, not only open the request.
- **FR-003**: Kestrel MUST only act on feedback that carries an explicit,
  configurable trigger marker; feedback without it MUST be ignored entirely
  (never recorded as processed, never acted on).
- **FR-004**: Kestrel MUST never act on the same piece of feedback more than
  once, including across a restart.
- **FR-005**: Kestrel MUST never treat its own comments, or any comment
  posted by an identity it recognizes as itself, as human feedback.
- **FR-006**: When a run is parked awaiting a human decision and marked
  feedback arrives on its ticket, kestrel MUST apply it exactly as it would
  apply the same feedback typed into its own reject-with-amendment control —
  it MUST NOT be treated as an approval; approving a parked run remains an
  action only kestrel's own interface can take.
- **FR-007**: When a run has no open decision point and marked feedback
  arrives, kestrel MUST hold that feedback and apply it at the next point the
  run would naturally pause between units of work, without interrupting work
  already in progress at the moment the feedback arrived.
- **FR-008**: When marked review feedback arrives on an open pull/merge
  request, kestrel MUST resume work on that same request's existing branch
  and MUST NOT open a second request for the same underlying change.
- **FR-009**: Kestrel MUST determine which point of its process a piece of
  review feedback actually concerns (e.g. an implementation detail vs. the
  underlying approach) and resume from that point, rather than always
  restarting from the same fixed step.
- **FR-010**: If resuming review feedback would re-open a point in the
  process that normally requires a human decision, kestrel MUST require that
  decision again rather than proceeding autonomously past it.
- **FR-011**: When marked feedback arrives on a ticket whose run already
  finished, kestrel MUST resume that same run when what it produced (e.g. its
  request) is still in a state that can be added to, and MUST start a new,
  clearly-linked run when it is not.
- **FR-012**: A finished run that ended because it gave up MUST be retryable
  with feedback-supplied guidance rather than starting over with no memory of
  why it failed.
- **FR-013**: A finished run that ended because its work was split into
  follow-up tasks MUST NOT re-run that split from scratch in response to
  feedback about it; it MUST instead produce a correction that does not
  duplicate what was already published.
- **FR-014**: Kestrel MUST acknowledge that it has picked up a piece of
  feedback using the lightest-weight signal the ticket/request source
  supports (e.g. a reaction), and MUST NOT post a comment purely to say
  feedback was received.
- **FR-015**: Kestrel MUST post at most one comment when feedback-driven work
  actually lands (e.g. new commits pushed, a revised document produced) —
  picking up feedback and later re-picking-up further feedback on the same
  underlying decision MUST NOT accumulate additional comments beyond what
  the existing approval-gate notification behavior already produces.
- **FR-016**: Where a ticket or request source has no way to acknowledge a
  comment at all, kestrel MUST still process the feedback normally and simply
  omit the acknowledgment, rather than treating the absence of that
  capability as a failure.

### Key Entities

- **Feedback item**: One piece of human input picked up from a ticket
  comment or a review, carrying who left it, what it said, where it came
  from, and whether it has been acted on yet. Persists independently of any
  single run, since it may need to outlive the run it eventually affects (a
  run that finishes, or one that has not been created yet).
- **Feedback cursor**: Per ticket and per pull/merge request, how far
  kestrel has already looked — so the same comment is never picked up twice
  and a restart does not miss what arrived while kestrel was down.
- **Change request identity**: The durable identity of a pull/merge request
  kestrel opened (beyond just its link), sufficient to look up its current
  state and read feedback left on it, and to connect it back to the run that
  opened it.
- **Run lineage**: When a new run is started because feedback arrived on a
  ticket whose prior run can no longer be added to, the connection back to
  that prior run, so the two are never mistaken for unrelated activity on the
  same ticket.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A human can redirect a parked run using only a ticket comment,
  with no visit to kestrel's own interface required.
- **SC-002**: Feedback left while kestrel is actively working is never lost —
  100% of marked feedback is eventually applied — and never interrupts work
  already underway at the moment it arrives.
- **SC-003**: Review feedback results in new work appearing on the same
  pull/merge request in the overwhelming majority of cases where that
  request is still open; a second, disconnected request for the same
  underlying change is never opened while the first is still open.
- **SC-004**: Across any number of feedback rounds on the same run, the
  number of comments kestrel posts stays proportional to genuinely new
  decisions raised, not to the number of feedback messages it received.
- **SC-005**: Kestrel never reacts to a comment or reaction it posted itself.
- **SC-006**: Feedback lacking the trigger marker never starts, alters, or
  redirects any run, verified across every supported ticket and request
  source.
- **SC-007**: A ticket whose run already finished can still receive
  actionable feedback — such a ticket is never permanently unreachable the
  way it is today.

## Assumptions

- The trigger marker is a configurable token (a sensible default is
  provided) rather than a fixed string, since different teams/organizations
  may already use similar conventions for other tools.
- Not every ticket or request source can acknowledge a comment (e.g. react to
  it); where that capability doesn't exist, kestrel degrades to no
  acknowledgment rather than substituting a comment, since a substitute
  comment would reintroduce the noise this feature is explicit about
  avoiding.
- "Resuming" a finished run never rewrites or discards any history a human
  or reviewer can already see (matching the project's existing append-only
  posture toward externally-visible ticket/request history) — it only adds
  to it or starts something new and clearly linked.
- Feedback that cannot be confidently classified is still acted on as
  feedback (see Edge Cases) rather than silently dropped, on the reasoning
  that a visible, wrong-ish attempt is more correctable than silence.
- This feature covers the ticket/request sources kestrel already integrates
  with; a source with no way to read comments/reviews at all is out of scope
  until such a way exists.
