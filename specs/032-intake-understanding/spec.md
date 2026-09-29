# Feature Specification: Visible screening and a real understanding step

**Feature Branch**: `work`

**Created**: 2026-09-29

**Status**: Implemented (2026-09-29)

**Input**: GitHub #67 (the understanding gate has no restatement to confirm)
and #68 (ingest: screening is invisible until classification finishes). Both
were found while reviewing Vikunja 710 against opencode + qwen. The developer
approved both proposed designs on 2026-09-29.

## Context

When kestrel picks up a request, two things happen before any real work:

1. **Screening.** The input-security specialist classifies the ticket body.
   Unsafe content is quarantined.
2. **Understanding.** The operator confirms that kestrel understood the
   request.

Both currently fail the operator:

- Screening happens before the request exists on the board. For as long as the
  classification takes (30 s by default, often longer with a local model), the
  board shows nothing at all, even though the model is busy.
- The understanding gate asks "Confirm this request was understood correctly",
  but nothing ever writes an understanding. Spec 012 had one (User Story 1);
  the board rewrite (spec 026) dropped it. The operator is asked to confirm
  something that isn't there.

### Decisions settled before this spec (2026-09-29, with the developer)

- **The request appears first.** Kestrel creates the request on the board as
  soon as it picks the ticket up, showing "Screening input…" while
  classification runs. It then either continues or quarantines, in place.
- **The pm writes the understanding.** A short restatement, written before the
  gate, which the gate shows. A rejection with a correction triggers a
  redraft, capped the same way PRD rejections are (feature 028).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See a new request the moment it is picked up (Priority: P1)

A ticket is labelled for kestrel. On the next poll, a card for it appears on the
stage board in Intake, reading "Screening input…", before the model has
answered. When screening passes, the card moves on. When it fails, the same
card shows the quarantine and the reason.

**Why this priority**: an invisible system looks broken. This is the first
thing an operator sees.

**Independent Test**: point kestrel at a model that takes 30 s to answer.
Within one poll the request is listed, in Intake, with a screening card in
progress. After the answer it is either quarantined in place or moved on,
and there is still exactly one entry for the ticket.

**Acceptance Scenarios**:

1. **Given** a qualifying ticket, **When** kestrel picks it up, **Then** the
   request is listed immediately with an in-progress "Screening input…" card,
   before classification has finished.
2. **Given** screening finds the content safe, **When** it finishes, **Then**
   the screening card is done, the request shows the ticket's real title, and
   the understanding step starts.
3. **Given** screening quarantines the content, **When** it finishes, **Then**
   the same request shows a quarantine card with its reason. No second entry
   is created for the ticket.
4. **Given** a quarantined request, **When** the operator releases it,
   **Then** the request continues from the understanding step. **When** the
   operator discards it instead, **Then** the request ends.
5. **Given** kestrel restarts while a request is still screening, **When** it
   polls again, **Then** screening is retried for that request instead of
   leaving it stuck.
6. **Given** the request is listed but not yet screened, **When** anyone looks
   at it, **Then** it shows only the ticket reference as its title, never
   unscreened ticket content.

---

### User Story 2 - Confirm an understanding that is actually there (Priority: P1)

After screening, the pm writes a short restatement of the request: what is
being asked, for whom, and what "done" looks like. The cockpit's decision
banner shows that restatement with Approve and Reject. The operator approves
and the request moves on, or rejects with a correction and gets a redraft
that takes the correction into account.

**Why this priority**: the gate exists to catch a misunderstanding before any
effort is spent. Without a restatement it cannot do that.

**Independent Test**: approve screening on a ticket. A pm card writes a
restatement; the understanding gate shows it. Reject it with a correction;
a new restatement is written that received the correction. Reject past the
cap; the request escalates for review instead of redrafting again.

**Acceptance Scenarios**:

1. **Given** screening passed, **When** the request continues, **Then** a pm
   card writes the restatement, and only then does the understanding gate
   open.
2. **Given** the gate is open, **When** the operator looks at the cockpit,
   **Then** the banner shows the restatement itself, not just a link to it.
3. **Given** the operator rejects, **When** they do so, **Then** a correction
   is required, and a redraft is written with both the previous restatement
   and the correction in view.
4. **Given** the restatement has been redrafted `board_understanding_redraft_cap`
   times, **When** it is rejected again, **Then** no further redraft is made
   and a coordinator review is opened instead.
5. **Given** the pm's answer cannot be read as a restatement, **When** it
   arrives, **Then** a coordinator review is opened (fail closed) and no
   empty gate is shown.
6. **Given** the developer's dev reset is used, **When** a request is reset,
   **Then** it restarts at the understanding step with a fresh restatement.

### Edge Cases

- **A quarantine resolved for a legacy placeholder workflow** (created before
  this feature) keeps its old behaviour. The next poll screens the ticket
  again, now visibly.
- **A release whose ticket has since disappeared from the task source.** The
  request cannot continue. It is left with its released review, and the
  failure is logged.
- **Approving the understanding** continues exactly as before: CAB-1 or
  refinement, depending on configuration.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Picking up a qualifying ticket MUST create its request on the
  board before classification starts, with a single in-progress screening
  card.
- **FR-002**: Until screening passes, the request MUST show only the ticket
  reference as its title and MUST hold no ticket content.
- **FR-003**: When screening passes, the request MUST record the ticket's title
  and screened body, complete the screening card, and start the
  understanding step.
- **FR-004**: When screening fails, the quarantine MUST be attached to that
  same request, and the screening card MUST end. No separate placeholder
  entry may be created for a newly picked-up ticket.
- **FR-005**: Releasing an intake quarantine MUST continue the request as in
  FR-003, using a fresh canonical fetch of the ticket. Discarding it MUST
  end the request.
- **FR-006**: A request whose screening was interrupted (for example by a
  restart) MUST be screened again on the next poll.
- **FR-007**: The understanding step MUST start with a pm card that writes a
  restatement. The understanding gate MUST open only once a readable
  restatement exists, and MUST target it.
- **FR-008**: The cockpit MUST show the restatement inline with the decision.
- **FR-009**: Rejecting the understanding MUST require a correction. A
  rejection MUST produce a redraft whose context includes the previous
  restatement and the correction, up to `board_understanding_redraft_cap`
  redrafts (default 2). Past the cap it MUST open a coordinator review
  instead.
- **FR-010**: An unreadable restatement MUST open a coordinator review
  instead of a gate.
- **FR-011**: The coordinator MUST NOT be able to create the understanding
  card itself.
- **FR-012**: The dev reset MUST restart a request at the understanding step.

### Key Entities

- **Screening card**: the request's first card, a `security_review`, in
  progress while classification runs.
- **Understanding card** (new kind): the pm's restatement of the request.
- **Restatement**: the understanding card's result, which the understanding
  gate targets.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A picked-up ticket appears on the board within one poll,
  regardless of how long classification takes.
- **SC-002**: A ticket has exactly one board entry through screening,
  quarantine, release, and the rest of its life.
- **SC-003**: No understanding gate is ever opened without a restatement to
  show.
- **SC-004**: Repeated rejections of an understanding end in a coordinator
  review after at most `board_understanding_redraft_cap` redrafts.

## Assumptions

- The screening card is a system activity: no specialist claims it, and a
  restart is recovered by re-screening (FR-006), not by lease expiry.
- The pm is the right author for the restatement: it already scopes work,
  and it writes the PRD later, so it sees its own restatement become the
  baseline.
- The redraft cap is a new setting, because the PRD cap has a different
  default meaning (feature 028) and the two loops should be tunable
  separately.

## Out of scope

- Reworking quarantine for non-intake content (feedback, gate answers).
- Changing what happens after the understanding is approved.
