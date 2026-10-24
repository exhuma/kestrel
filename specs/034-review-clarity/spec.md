# Feature Specification: Answerable interviews, a telling spine, visible work

**Feature Branch**: `work`

**Created**: 2026-09-29

**Status**: Implemented (2026-09-29)

**Input**: The Vikunja 710 review, after a full test run:

1. "The interview is very hard to respond to because it contains only
   plain-text fields. It should try to prioritise multiple-choice whenever
   there's a clear choice. Keep plain-text on open questions/comments."
2. "The spine on top of the workflow is all white on the finished workflow.
   Proper status icons on each step would be more informative."
3. "The 'cancelled' items on the card are not visible anywhere so I don't
   know *what* was cancelled."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Answer an interview by picking (Priority: P1)

A persona asks "Who uses the export?" with the options *Finance*, *Sales*
and *Everyone*. The operator picks one, optionally adds a comment, and
moves on. Open questions ("Anything else we should know?") stay free text.

**Acceptance Scenarios**:

1. **Given** a question with options, **When** it is shown, **Then** the
   options can be picked: one of them, or several when the question allows
   it. A comment field is always available.
2. **Given** a question without options, **When** it is shown, **Then** it
   is a text field, as today.
3. **Given** any question, **Then** "I don't know" and "Not relevant" still
   work.
4. **Given** submitted answers, **Then** the recorded answer names the
   chosen options and the comment, readable by the PRD's author.
5. **Given** the personas' prompts, **Then** they ask for options wherever
   there is a clear set of answers. The strategic-fit interview does the
   same.
6. **Given** a malformed question (for example a single option, or none),
   **Then** the round is rejected the same way malformed output is today.

### User Story 2 - See each step's status on the spine (Priority: P2)

Each of the ten steps shows its own status: *done*, *in progress*,
*waiting for you*, *problem*, *skipped* or *not reached*. It is correct on
a finished request too.

**Acceptance Scenarios**:

1. **Given** a finished request, **Then** every step it went through shows
   *done*, and every step it never needed shows *skipped*. None is left
   blank.
2. **Given** a request in progress, **Then** earlier steps are *done*, the
   current one is *in progress* or *waiting for you*, and later ones are
   *not reached*.
3. **Given** a step whose work failed, **Then** it shows *problem*.

### User Story 3 - See every piece of work, and why it ended (Priority: P2)

The cockpit lists every card of the request, grouped by state: in
progress, waiting, ready, done, cancelled, failed. Each card shows who it
was for, and for a cancelled or failed one, what ended it (the operator,
the coordinator, a rejected gate, recovery…).

**Acceptance Scenarios**:

1. **Given** a request with cancelled cards, **When** the operator opens
   it, **Then** each cancelled card is listed with its title and why it
   was cancelled.
2. **Given** the stage-board card's state counts, **Then** they lead to
   that list.

## Requirements *(mandatory)*

- **FR-001**: A question MAY be a plain string (open) or an object
  `{"prompt": str, "options": [str, …], "multiple": bool}` with 2 to 8
  distinct options. Anything else is malformed. This applies to refinement
  interviews and to the strategic-fit interview.
- **FR-002**: The requester, pm and uiux prompts MUST prefer options
  whenever a question has a clear set of answers, and keep open questions
  as plain strings.
- **FR-003**: The interview MUST render options as single or multiple
  choice, plus an optional comment field, and keep both escape hatches.
  An answer needs at least one choice or a comment.
- **FR-004**: The serialised answer MUST name the chosen options and the
  comment.
- **FR-005**: The snapshot MUST carry each phase's status, derived on the
  backend (`done | active | waiting | problem | skipped | upcoming`), and
  the spine MUST show it with a distinct icon and colour per status (never
  colour alone).
- **FR-006**: The cockpit MUST list every card grouped by state, with the
  explanation of its latest event for cancelled and failed cards. The
  board card is itself a link to the cockpit, so its state counts lead
  there; they get no link of their own (a link inside a link is invalid
  and unreachable by keyboard).

## Success Criteria *(mandatory)*

- **SC-001**: A question with a clear set of answers is answered with one
  click.
- **SC-002**: No spine step is ever shown without a status.
- **SC-003**: Every card counted on the board card can be found, with its
  outcome, in the cockpit.
