# Feature Specification: A failed request never reads as Done

**Feature Branch**: `work`

**Created**: 2026-09-30

**Status**: Implemented (2026-09-30)

**Input**: Handover "Failed Workflows Must Not Display as Done" (2026-09-30).
In the operator's local run `wf-36ca7a1a` (DTN-2302, "Kestrel UI Test 2"), the
pm's first-round interview card was stopped by the tool-loop guard, failed
after recovery, and was then cancelled by the coordinator. No gate, PRD,
decomposition or delivery card was ever created. Even so, the board showed the
request in **Done**, with every later phase marked **Skipped**.

## Context

`phases.py` derived "done" whenever every card was terminal. `failed` and
`cancelled` cards count as terminal, so a request that stopped failing, or was
abandoned, looked like one that finished. Three problems made this worse:

- **The coordinator could cancel a failed card.** That erased the failure,
  although the board already treats a failed card as the operator's decision
  ("Operator: retry or cancel", feature 035).
- **A failed interview card counted as finished for its batch.** The batch
  could move on without that specialist before the operator had decided.
- **Nothing re-checked an interview batch after a card left it outside the
  interview's own code** (recovery, the coordinator, the operator's cancel).
  The other specialists' questions were then never reviewed or asked, and the
  request looked finished.

## Decisions

- **The outcome is derived, not stored.** It comes from the card graph in the
  same pure projection, alongside the phase, so no migration is needed.
- **Four outcomes:**
  - `in_progress`: something is still open (an empty board included).
  - `failed`: any card is `failed`, whatever else is open.
  - `done`: nothing is open, nothing failed, and the request reached its end.
    It ends at a done delivery, or, when CAB-2 approved no coding work, at
    CAB-2 approval with every approved task done.
  - `cancelled`: nothing is open, nothing failed, and the request stopped
    before its end (a gate rejected, work cancelled).
- **A failed request stays where it failed.** Its phase is the phase of its
  failed card, so it stays visible in its column, flagged. It is never hidden
  as finished.
- **A cancelled request is finished but not done.** It moves to its own
  trailing **Cancelled** column and, like a done request, is hidden from the
  default listing.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A failure is shown as a failure (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a request with a failed card and every other card terminal,
   **When** the board is shown, **Then** its outcome is `failed`. It stays in
   the column of the failed card's phase with a "Failed" treatment and is
   listed by default.
2. **Given** that request's cockpit, **When** the spine is shown, **Then** the
   failed step reads "Failed", later steps read "Not reached", and none reads
   "Done" or "Skipped".
3. **Given** a request that completed its delivery, **When** the board is
   shown, **Then** it is Done, exactly as before.
4. **Given** a request stopped before its end with nothing failed (for
   example, CAB-1 rejected), **When** the board is shown, **Then** its outcome
   is `cancelled`. It sits in the Cancelled column, its spine reads
   "Cancelled" at the step where it stopped, and its activity says so.
5. **Given** open work, a human gate, or an open manual task, **When** the
   board is shown, **Then** nothing changes from today.

### User Story 2 - A failure waits for the operator (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a failed card, **When** the coordinator proposes to cancel or
   move it, **Then** the action is rejected: only the operator retries or
   cancels it.
2. **Given** a failed interview card, **When** the rest of its batch has
   drafted, **Then** the batch waits for the operator's decision.
3. **Given** the operator cancels that card, **When** the board is next
   dispatched, **Then** the batch continues without it: the other questions
   are reviewed and asked.

## Requirements *(mandatory)*

- **FR-001**: The backend MUST derive each request's `outcome`
  (`in_progress | done | failed | cancelled`) and expose it on the listing
  and the snapshot. `done` MUST require a reached end, never only terminal
  cards.
- **FR-002**: `phase` MUST be `done` only for a `done` outcome, and
  `cancelled` for a `cancelled` one. A failed request's phase is its failed
  card's phase.
- **FR-003**: The default listing MUST hide only `done` and `cancelled`
  requests.
- **FR-004**: The spine MUST mark phases `skipped` only on the way to a
  `done` outcome. A failed step MUST read "Failed", a cancelled stop
  "Cancelled", and unreached steps "Not reached", each with an icon as well
  as a word.
- **FR-005**: Activity MUST report a cancelled request as `cancelled`, and
  `done` only for a `done` outcome.
- **FR-006**: The board card MUST show "Failed" and "Cancelled" treatments,
  each with an icon and a word. Their order of precedence: quarantined,
  failed, cap reached, your move, done, cancelled.
- **FR-007**: The coordinator MUST NOT transition a `failed` card.
- **FR-008**: A `failed` interview card MUST hold its batch. Every dispatch
  MUST re-check the interview batches, so a batch moves on however one of
  its cards left it.

## Success Criteria *(mandatory)*

- **SC-001**: No request with a failed card is ever shown as Done or hidden
  by default.
- **SC-002**: A completed request still shows as Done.

## Out of scope

- The local tool-call limits (feature 036).
