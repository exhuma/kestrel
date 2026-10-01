# Feature Specification: Review feedback on a pull/merge request comes back to the board

**Feature Branch**: `work`

**Created**: 2026-09-30

**Status**: Draft

**Input**: "The system needs to be able to process feedback from a
pull-request … in a portable way so it works both on GitHub and GitLab.
One option I see is to treat PR feedback in the same way as the verifier
feedback is processed."

## Context

Kestrel delivers finished work as a draft pull request (GitHub) or merge
request (GitLab) and polls that request's required CI. It no longer reads
what a human reviewer writes on it. The old feedback intake (features 013
and 015) lived inside the fixed six-step driver and was deleted with it in
spec 026's Phase 10 clean break (`docs/feedback-intake.md`). Today a
reviewer's request for changes on a Kestrel PR is lost: the operator has to
re-enter it by hand.

The code-host layer still reads review comments on both hosts
(`CodeHost.list_review_comments`, `acknowledge`, `get_change_request`), but
nothing on the board calls it. The board already has the loop this needs:
the verifier's findings become remediation work, the work is re-verified up
to a cap, anything that needs a human decision escalates, and a clean
result is delivered to the same PR.

A workflow usually reads as **done** when review feedback arrives. That is
not a blocker. A workflow's outcome is derived from its cards: done means
nothing is open and the delivery card is done. The board only adds cards,
so any new card makes the request `in_progress` again, in the phase of the
new work. CI repair already relies on this.

## Decisions

- **Only marked comments count.** A comment is acted on only if it contains
  the configured marker (`feedback_marker`, default `@kestrel`). Comments
  from ignored authors (`feedback_ignore_authors`) and bots are skipped,
  and so are Kestrel's own comments. Everything else on the PR is ordinary
  conversation.
- **The verifier triages.** New marked comments are batched into one
  read-only review-triage card for the verifier. The verifier reads them
  against the delivered change and reports `<VERIFIER_FINDINGS>`:
  - a requested change becomes `nonconformance`;
  - a question, an unclear ask, or an ask outside the approved scope
    becomes an escalation category (`ambiguity`, `requirement_conflict`,
    `policy_risk`).
  From there the verifier's routing runs unchanged: remediation, then
  re-verification, the round cap, escalation, and delivery.
- **Answers go on the PR.** Kestrel acknowledges each accepted comment with
  a reaction. An escalation raised from review feedback is posted as a
  reply on the pull/merge request, next to the comment it came from,
  rather than on the task-source ticket.
- **Same behaviour on GitHub and GitLab.** Everything above goes through
  the code-host port. Nothing on the board knows which host it is talking
  to.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A requested change is made on the same PR (Priority: P1)

The operator reviews a PR Kestrel delivered and leaves a marked comment
asking for a change. Without touching the Kestrel UI, the change is made
and pushed to the same PR.

**Why this priority**: This is the feature. Without it, review feedback has
to be retyped into Kestrel by hand.

**Independent Test**: Deliver a workflow to a PR, add a marked comment
requesting a concrete change, and watch the board: triage, then
remediation, then re-verification, then delivery. A new commit lands on
the same PR.

**Acceptance Scenarios**:

1. **Given** a delivered workflow whose PR is open and whose outcome is
   done, **When** a reviewer adds a marked comment asking for a change,
   **Then** the comment gets a reaction and a review-triage card appears.
   The workflow reads `in_progress` in the Build phase.
2. **Given** that triage card, **When** the verifier reports the ask as
   `nonconformance`, **Then** a remediation card for the coder is created.
   Its prompt contains the comment's text, author and file/line location,
   not just a one-line title.
3. **Given** the remediation is done, **When** re-verification comes back
   clean, **Then** the work is delivered again to the same PR. No second PR
   is opened.
4. **Given** a comment with an inline file/line position (GitHub review
   comment, GitLab discussion note), **When** it is triaged, **Then** the
   location reaches the verifier and the coder.

---

### User Story 2 - A question is answered on the PR (Priority: P2)

A reviewer's marked comment is a question, or asks for something the
approved scope doesn't cover. Kestrel doesn't guess: it escalates, and the
escalation is visible on the PR where the reviewer is looking.

**Why this priority**: Without it, a question either becomes wrong work or
disappears into the Kestrel UI unseen by the reviewer.

**Independent Test**: Add a marked question on a delivered PR. Check that
no remediation card is created, a `coordinator_review` escalation appears
on the board, and a reply appears on the PR.

**Acceptance Scenarios**:

1. **Given** a marked comment that the verifier reports as `ambiguity`,
   **When** its result is routed, **Then** a `coordinator_review`
   escalation is created and a reply is posted on the pull/merge request.
   The reply goes in the comment's own thread when the host supports
   threading.
2. **Given** the reply has been posted, **When** routing for the same
   result runs again (replay), **Then** no second reply is posted.

---

### User Story 3 - Feedback stops when the PR is finished (Priority: P3)

Once a PR is merged or closed, Kestrel stops reading it.

**Why this priority**: This bounds polling cost and stops late comments on
a merged PR from starting work on code that is already shipped.

**Independent Test**: Merge (or close) a delivered PR, add a marked
comment, and confirm nothing is created.

**Acceptance Scenarios**:

1. **Given** a delivered workflow whose PR is merged or closed, **When** the
   review poll runs, **Then** no comments are read and no cards are
   created.
2. **Given** a workflow that was never delivered, or whose code host does
   not support change requests (local tasks), **When** the review poll
   runs, **Then** it is skipped.

---

### Edge Cases

- **Unmarked comments** are never acted on and never acknowledged.
- **Kestrel's own comments**, including its replies and delivery or
  screenshot comments, are never read back as feedback, even if they quote
  the marker.
- **Edited comments**: a comment is acted on once, the first time it is
  seen with the marker. A later edit of the same comment does not act
  again.
- **Several marked comments between polls** go into one triage card.
- **A comment arriving while earlier review work is still open** gets its
  own triage card on the next poll. The re-verification only waits for
  that comment's own remediation.
- **Untrusted content**: a comment the input-security screening quarantines
  never reaches the verifier. It waits for the operator to release or
  discard it, like any other quarantined input.
- **Round cap reached**: when review-feedback remediation reaches
  `max_verify_iterations`, the same "Verification cap reached" escalation
  as for task work is created, and it is replied on the PR.
- **Unparseable triage result**: escalates exactly as any unparseable
  verifier result does, including the operator's Retry.
- **Code host errors**: a failed read for one workflow is logged and
  retried on the next poll. It does not stop other workflows. The cursor
  only advances once the batch has been handed to the board.
- **Acknowledgement or reply fails**: this is best-effort. The feedback is
  still acted on, and a failed reply is retried like other external
  projections.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST periodically read review comments on every
  delivered workflow's pull/merge request while that request is open,
  through the code-host port only, for both GitHub and GitLab.
- **FR-002**: The system MUST stop reading a request once the code host
  reports it merged or closed. It MUST skip workflows without a change
  request and code hosts that don't support change requests.
- **FR-003**: The system MUST act only on comments that contain the
  configured feedback marker. It MUST ignore comments from configured
  ignored authors, from bots, and from Kestrel itself.
- **FR-004**: Each comment MUST be acted on at most once, identified by its
  host-native external id, across polls, restarts and replays. This holds
  even if the comment is edited later.
- **FR-005**: The system MUST keep a per-workflow read position, so that
  comments older than the last handled batch are not re-read in full on
  every poll.
- **FR-006**: Every accepted comment MUST pass the existing untrusted-input
  boundary (spec 026 FR-018 to FR-023) before it reaches any agent. A
  quarantined comment MUST NOT reach the verifier until the operator
  releases it.
- **FR-007**: Each batch of newly accepted comments MUST become exactly one
  read-only verification card for the verifier, the review-triage card. It
  carries each comment's body, author, location (file and line when
  inline) and external id.
- **FR-008**: The verifier MUST report review-triage results in the
  existing `<VERIFIER_FINDINGS>` format and categories. A requested change
  maps to `nonconformance`; a question, an unclear ask or an ask outside
  the approved scope maps to an escalation category.
- **FR-009**: Review-triage results MUST be routed by the same verifier
  routing as task verification: remediation cards, re-verification,
  escalation, the `max_verify_iterations` round cap, and delivery once
  clean. The round cap and re-verification MUST apply to review-feedback
  work, which today is not tied to a task node.
- **FR-010**: A remediation card created from review feedback MUST give the
  coder the originating comment's text, author and location as context,
  in addition to its title.
- **FR-011**: A clean re-verification of review-feedback work MUST deliver
  to the existing pull/merge request, never open a new one.
- **FR-012**: The system MUST acknowledge each accepted comment on the code
  host with a reaction.
- **FR-013**: An escalation raised from review feedback, including a round
  cap reached or an unparseable triage result, MUST be posted as a reply
  on the pull/merge request, in the comment's thread where the host
  supports it. Each escalation MUST be posted at most once.
- **FR-014**: The code-host port MUST offer a way to comment on a
  change request, optionally in reply to a given comment, with GitHub and
  GitLab implementations. Code hosts without change requests treat it as
  a no-op.
- **FR-015**: A workflow whose outcome is done MUST become `in_progress`
  again when review feedback creates work, and done again once that work
  is delivered, without any card moving backwards.
- **FR-016**: The operator documentation MUST describe the feature,
  replacing `docs/feedback-intake.md`. The feedback marker settings MUST no
  longer be listed as vestigial. `docs/architecture.md` MUST be corrected
  where it says Kestrel never opens a change request.

### Key Entities

- **Review comment**: one piece of reviewer feedback on a pull/merge
  request. It has an external id, author, body, creation time and optional
  file/line location. It is read from the code host; the board does not
  store it on its own.
- **Review read position**: per workflow, how far review comments have been
  handled for the current change request.
- **Review-triage card**: a verification card whose input is a batch of
  review comments rather than a task's implementation. Its findings drive
  remediation, re-verification and escalation like any verification.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A marked change request on a delivered PR produces a new
  commit on the same PR with no operator action in the Kestrel UI, beyond
  releasing quarantined input when screening holds it.
- **SC-002**: The same scenario gives the same outcome on GitHub and
  GitLab. The fixture/fake code host covers both paths in tests.
- **SC-003**: No review comment ever creates work more than once. This is
  checked by replaying polls and routing in tests.
- **SC-004**: A marked comment is picked up within one poll interval of
  being posted.
- **SC-005**: A reviewer's question is answered on the PR itself in 100% of
  escalations raised from review feedback, unless the host call fails, in
  which case it is retried.

## Assumptions

- Polling, not webhooks. Polling works the same on both hosts and needs no
  inbound exposure. The existing GitHub webhook stays limited to issue
  events.
- The review poll runs on the same interval setting pattern as the CI poll.
  The interval is configurable, with a sensible default.
- Review comments on the pull/merge request are in scope. Comments on the
  originating task-source ticket, and marker commands such as
  approve/reject, are out of scope.
- Gitea (via the GitLab adapter) returns no review comments today. It stays
  unsupported.
- One PR per workflow, as delivery already guarantees.
