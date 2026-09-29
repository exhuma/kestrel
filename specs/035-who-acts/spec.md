# Feature Specification: Say who is expected to act

**Feature Branch**: `work`

**Created**: 2026-09-29

**Status**: Implemented (2026-09-29)

**Input**: Review of Vikunja 710 (2026-09-29). After answering the CAB-1
strategic interview, the board still showed "Your move" and "1 awaiting
human". The request had moved on at once to the CAB-1 decision, but nothing
said that the new move was a different one, for a different role. The
developer asked for the UI to say *who* is expected to act.

## Context

kestrel has one user, but that user wears several hats. They answer as the
requester, decide as the change advisory board (CAB), do the manual tasks, and
look after the system as its operator. "Your move" names none of these.
When one decision follows another, the board looks unchanged.

### Decision settled before this spec (2026-09-29, with the developer)

| Waiting card | Who acts | What |
| --- | --- | --- |
| Understanding check | Requester | confirm the understanding |
| Strategic interview | Requester | answer the interview |
| CAB-1 | CAB | decide strategic fit |
| Refinement interview | Requester | answer the interview |
| PRD sign-off | Requester | sign off the PRD |
| CAB-2 | CAB | go / no-go |
| Manual task | You | do the task |
| Quarantine | Operator | review the input |
| Failed card | Operator | retry or cancel |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Know whose move it is (Priority: P1)

The board card, the cockpit's decision banner, and the cockpit's work list
each say who is expected to act and what they are asked to do, for example
"Your move · CAB: decide strategic fit". When the interview is answered and
the CAB-1 decision opens, the board card changes from "Requester: answer the
interview" to "CAB: decide strategic fit".

**Independent Test**: take a request to the strategic interview. The board
card reads "Requester: answer the interview". Answer it. Once the CAB-1 gate
opens, the card reads "CAB: decide strategic fit".

**Acceptance Scenarios**:

1. **Given** a card waits on a human, **When** the board is listed, **Then**
   the request says who acts and what, per the table above.
2. **Given** several cards wait, **When** the board card is shown, **Then**
   it names the first and says how many more are waiting.
3. **Given** the cockpit's decision banner, **When** it shows a decision,
   **Then** it names who is expected to make it.
4. **Given** the work list, **When** it shows a waiting card, **Then** it
   names who the card waits on.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The backend MUST decide who acts on each card that waits on a
  human, and what they are asked to do, as stable codes (per the table
  above). The frontend MUST only phrase those codes.
- **FR-002**: Each card in the snapshot MUST carry its `awaiting` value, or
  none. Each request in the listing MUST carry the list of its cards'
  `awaiting` values, in card order.
- **FR-003**: The board card, the decision banner, and the work list MUST
  show who acts.

## Success Criteria *(mandatory)*

- **SC-001**: Every "your move" on the board names a role and an action.
- **SC-002**: Two decisions that follow each other never read the same on
  the board card.

## Assumptions

- The roles are hats the single user wears, not accounts. Nothing is
  enforced per role.
- A card that is waiting on another card (`waiting_dependency`) waits on
  nobody. It is not listed.

## Out of scope

- Assigning roles to different people.
