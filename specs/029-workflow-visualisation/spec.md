# Feature Specification: Workflow visualisation rework

**Feature Branch**: `work`

**Created**: 2026-09-28

**Status**: Draft

**Input**: GitHub epic #40 — "workflow visualisation rework (stage board, request
cockpit, interview view)". Sub-issues #57 (stage board), #58 (request cockpit),
#59 (interview workspace), #60 (retire the graph view).

## Context

The operator's mental model of kestrel is a **department**: one request is
ingested, a coordinator sequences it, named specialists work it, and the
operator gates it at a few decision points. The current UI contradicts that
model in three ways:

1. **One request reads as several.** The home surface is a flat, unordered list
   keyed on an opaque workflow identifier. Decomposition children appear as
   siblings of their parent, so sub-work looks like peer work.
2. **The structural view is a straight line.** The dependency graph derives
   position purely from dependency edges, and real boards are chains — so it
   renders a horizontal line, carrying a graph-rendering dependency to say
   nothing a labelled sequence could not say better.
3. **The parts that need the operator cannot be operated.** Interview answers
   and PRD-rejection feedback cannot be submitted from the UI at all, even
   though the backend accepts both.

This feature replaces the visualisation with three purpose-built surfaces and
retires the graph. It introduces **no new workflow behaviour**: no new pipeline
stage, and no change to how work is claimed, sequenced, or gated.

It is **not** purely presentational, though the first draft of this spec assumed
it was. A consistency audit on 2026-09-28 established that four of the facts these
surfaces must show are not exposed by the board API at all — a request's human
title, the parent link that makes a decomposition child a child, the interview
round and its cap, and whether a round cap was exhausted. Defect (2) is
*precisely* problem 1 above, so cutting it would leave the epic's main complaint
unfixed. The feature therefore also adds four **additive, read-only** fields to
existing board DTOs (FR-040–FR-043). No field changes meaning, no endpoint is
added, and nothing becomes writable.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See every request, and where each one stands (Priority: P1)

The operator opens kestrel and sees one card per ingested request, arranged in
columns by the coarse stage the request has reached. Each card names the request
by its source reference and title — not by an internal identifier — states the
exact phase in words, shows true position within the ten-phase sequence, and
flags whether the request is waiting on the operator. Sub-work belonging to a
request (interview personas, implementation tasks) appears **inside** that
request's card, never as a separate card elsewhere on the board.

**Why this priority**: This is the entry point and the surface the operator
looks at most. It alone fixes the "one request reads as several" defect and
makes the portfolio legible at a glance, which is the epic's core complaint. It
is viable on its own: even with no other surface built, the operator gets an
honest overview where today there is an unordered list.

**Independent Test**: Load the board with a fixture set containing a
quarantined request, a decomposed parent with children, a request awaiting an
operator decision, and a completed request. Verify the column placement, the
per-card phase line, the count of cards (one per ingested request), that
children render nested inside their parent, and that the waiting-on-operator
card is visibly distinguished.

**Acceptance Scenarios**:

1. **Given** four ingested requests at phases Understanding, Pre-assessment,
   PRD sign-off and Build, **When** the operator opens the board, **Then** each
   appears as exactly one card, in the column for its stage (Intake &
   alignment, Discovery, Definition, Build & deliver respectively).
2. **Given** a request whose work was decomposed into three child items,
   **When** the operator views the board, **Then** exactly one card is shown
   for that request, with the three children listed inside it.
3. **Given** a request that is blocked awaiting an operator decision, **When**
   the operator views the board, **Then** that card carries a distinct
   "your move" treatment and names the decision being asked for.
4. **Given** a request that was quarantined at intake, **When** the operator
   views the board, **Then** it appears once, with a quarantine treatment
   distinct from both the normal and the "your move" treatment.
5. **Given** a request that has reached its round cap without a usable answer,
   **When** the operator views the board, **Then** the card shows a
   cap-reached treatment distinct from an ordinary waiting state.
6. **Given** a board with every request terminal, **When** the operator opens
   it, **Then** those requests appear in the Done column rather than being
   silently dropped or cluttering the active columns.
7. **Given** a board with no ingested requests at all, **When** the operator
   opens it, **Then** an explanatory empty state is shown rather than six blank
   columns.
8. **Given** any card on the board, **When** the operator navigates with the
   keyboard only, **Then** every card is reachable and openable, and every
   intervention available by pointer is also available by keyboard.

---

### User Story 2 - Understand one request: where it is, why, and what it produced (Priority: P2)

From a board card the operator opens a cockpit for that one request. The cockpit
answers three different questions in three dedicated regions — **where** the
request is (a labelled ten-phase sequence marking gates distinctly and
highlighting the current phase), **why** it got there (a chronological,
persona-attributed narrative of the coordinator's sequencing, each specialist's
framing, and the operator's own past decisions), and **what** it has produced (a
durable list of artifacts with their states, each openable to read its content).
Above all three sits a single prominent statement of what the request needs from
the operator right now, with the action attached to it.

**Why this priority**: Depends on nothing but the board card being openable, and
it is where the operator does the actual work of judging a request. Second
because it is only reachable once a board exists to reach it from.

**Independent Test**: Open the cockpit for a fixture request mid-pipeline.
Verify the phase sequence marks the current phase and distinguishes gate phases
from work phases; the feed lists events oldest-to-newest with a persona against
each; the artifact list shows each artifact with a state; and the pending
decision is stated once, prominently, with its action.

**Acceptance Scenarios**:

1. **Given** a request at phase "PRD sign-off", **When** the operator opens its
   cockpit, **Then** the ten-phase sequence highlights "PRD sign-off" as
   current, shows the five earlier phases as passed and the four later as not
   yet reached, and marks the gate phases distinctly from the work phases.
2. **Given** a request with recorded board events, **When** the operator views
   the cockpit, **Then** events are listed oldest-first, each attributed to the
   persona responsible, and new events arriving while the cockpit is open
   appear without a manual refresh.
3. **Given** a board event with no attributable persona (a workflow-level event,
   or a gate the operator resolved), **When** it is shown in the feed, **Then**
   it is attributed neutrally rather than to an arbitrary or invented
   specialist.
4. **Given** a request with a PRD artifact, **When** the operator opens it from
   the artifact list, **Then** its content is shown as text, and its provenance
   is stated so unreviewed agent output cannot be mistaken for something the
   operator approved.
5. **Given** a request awaiting a PRD sign-off decision, **When** the operator
   opens the cockpit, **Then** exactly one prominent element states that ask and
   carries its actions, and that element is not duplicated elsewhere on the
   page.
6. **Given** a request awaiting nothing, **When** the operator opens the
   cockpit, **Then** no action prompt is shown at all rather than an empty or
   disabled one.
7. **Given** any answer-shaped interaction (interview answers, rejection
   feedback), **When** the operator engages it from the cockpit, **Then** they
   are taken to the dedicated input surface rather than typing into the feed.
8. **Given** a request whose underlying data fails to load, **When** the
   operator opens its cockpit, **Then** the failure is stated plainly and the
   operator can return to the board without reloading the application.

---

### User Story 3 - Answer an interview without corrupting the PRD (Priority: P3)

The operator reaches a dedicated, input-shaped surface to answer a specialist's
interview questions. Questions are grouped by the persona that asked them.
Answers are drafted with in-progress work preserved, so a half-finished round is
not lost. Every question offers an honest escape hatch — "I don't know, let the
PRD record an assumption" and "not relevant" — so the operator is never forced
to invent an answer. The surface states which round this is and how many rounds
remain, so the operator knows when a round is the last chance to answer before
assumptions are baked in. On submit, the operator is returned to the cockpit.

**Why this priority**: It closes the "cannot be operated" defect and is the only
story that unblocks work rather than merely displaying it. Third because it is
reached from the cockpit and is the most interaction-heavy surface to build.

**Independent Test**: Open the interview surface for a fixture request with two
personas asking questions across a capped multi-round interview. Verify
per-persona grouping, that the round indicator states both current round and
cap, that drafts survive leaving and returning, that both escape hatches are
selectable per question, and that submitting returns to the cockpit.

**Acceptance Scenarios**:

1. **Given** an interview with questions from two personas, **When** the
   operator opens it, **Then** questions are grouped under the persona that
   asked them.
2. **Given** a partially answered interview, **When** the operator navigates
   away and returns, **Then** the answers already typed are still present.
3. **Given** a draft being edited, **When** it is saved, **Then** the operator
   receives unambiguous confirmation that the draft is stored, distinguishable
   from a final submission.
4. **Given** a question the operator cannot answer, **When** they choose "I
   don't know", **Then** the answer is recorded as a request for the PRD to
   state an assumption rather than as an empty answer.
5. **Given** a question that does not apply, **When** they mark it "not
   relevant", **Then** it no longer blocks submission.
6. **Given** an interview at round 3 of a cap of 3, **When** the operator opens
   it, **Then** the surface states that this is the final round before
   assumptions are recorded in the PRD.
7. **Given** a new round advancing while answers from the previous round exist,
   **When** the operator opens the interview, **Then** previous answers are
   reconciled against the new round's questions rather than silently discarded
   or misattributed.
8. **Given** a completed interview, **When** the operator submits, **Then** they
   are returned to the cockpit for that request and the submission's effect is
   visible there.
9. **Given** required questions still unanswered and unwaived, **When** the
   operator attempts to submit, **Then** submission is refused and the
   outstanding questions are identified.

---

### User Story 4 - Return to, and share, a specific surface (Priority: P4)

Every surface the operator can reach is individually addressable: the board, a
named request's cockpit, and that request's interview each have their own
address. The operator can bookmark a cockpit, reopen it after restarting the
browser, use the browser's back control to retrace their steps, and land
directly on the right surface from a notification link.

**Why this priority**: Cross-cutting rather than a slice of visible value on its
own, but it is a prerequisite for User Story 3's "return to the cockpit on
submit" and for notification deep-links to reach anything but the board. Fourth
because each other story is demonstrable without it, while its own value is only
visible once there are several surfaces to move between.

**Independent Test**: Visit each surface's address directly in a fresh browser
session and confirm the correct surface renders with the correct request loaded;
then walk board → cockpit → interview and confirm the back control retraces that
path in reverse.

**Acceptance Scenarios**:

1. **Given** the address of a specific request's cockpit, **When** it is opened
   in a fresh session, **Then** the cockpit for that request renders directly
   without first showing the board.
2. **Given** the operator has walked board → cockpit → interview, **When** they
   use the browser back control twice, **Then** they arrive at the cockpit and
   then the board.
3. **Given** an address naming a request that does not exist, **When** it is
   opened, **Then** the operator is shown an explanatory message and a route
   back to the board, not a blank page or an error trace.
4. **Given** a notification carrying a deep link to a request, **When** the
   operator follows it, **Then** the cockpit for that request opens directly.
5. **Given** an address in the form used before this feature (`?run=<id>`),
   **When** it is opened, **Then** it still resolves to that request rather
   than silently landing on the board.
6. **Given** any surface address, **When** it is shared or bookmarked, **Then**
   it carries no secret — consistent with the existing constraint on
   notification deep-links.

---

### User Story 5 - Retire the straight-line graph (Priority: P5)

The dependency-graph view and the third-party graph-rendering dependency behind
it are removed, along with the list/graph toggle and the old nav-list surface
they lived in. Nothing the operator relied on is lost, because the phase
sequence states the same ordering more honestly and with labels.

**Why this priority**: Pure cleanup, and it must come last — the graph is the
only structural view that exists today, so removing it before the phase
sequence and the board are in place would leave a gap.

**Independent Test**: Confirm the graph view and toggle are gone, the
graph-rendering dependency is absent from the dependency manifest, dead-code and
dependency-hygiene checks report nothing new, and the full quality gate passes.

**Acceptance Scenarios**:

1. **Given** the stage board and the cockpit's phase sequence are in place,
   **When** the graph view and its dependency are removed, **Then** no surface
   references them and no operator-visible capability is lost.
2. **Given** the removal is complete, **When** dead-code and dependency-cycle
   checks run, **Then** they report no new findings.
3. **Given** the removal is complete, **When** the full quality gate runs,
   **Then** it passes.

---

### Edge Cases

- **A request in a stage with no phase** — a request whose every card is
  terminal maps to the synthetic `Done` phase; it must land in the Done column,
  not be dropped and not be forced into `Build & deliver`.
- **An unrecognised phase name** — the phase projection deliberately skips card
  kinds it does not know rather than raising. A phase name the frontend does not
  recognise must degrade to showing the name verbatim with no position marker,
  never crash the board or blank the column.
- **An unrecognised stage name** — a stage the board has no column for must still
  place its request somewhere visible (a trailing column), because FR-002
  guarantees every request appears exactly once. Filtering it out to keep the
  column count at six would break that guarantee the first time a stage is added
  backend-side.
- **More requests than fit** — the board's columns must remain usable as the
  number of requests in one stage grows, without pushing other columns off
  screen or collapsing a column to unreadable width.
- **Ten phases at a narrow viewport** — the labelled phase sequence must stay
  legible at a laptop width. A ten-column board layout was already tried and
  rejected for exactly this reason (see `docs/mockups/mockup-a-portfolio-board.png`,
  cut off at "Implementation"); if the horizontal sequence cannot render ten
  labelled items legibly, it must fall back to a vertical labelled sequence
  rather than to bespoke horizontal-stepper styling.
- **A long-running feed** — a request with a large event history must not degrade
  the cockpit, and arrival of a new event must not yank the operator away from
  content they are reading if they have scrolled back.
- **A stale decision** — if the request advanced between the cockpit rendering
  and the operator acting, the action must be refused rather than applied to
  outdated state, and the operator must be told why.
- **A single-round interview** — where no round cap is in force, the round
  indicator must degrade to stating a single round rather than showing an empty
  or misleading progress indicator.
- **Concurrent surfaces** — the same request open in two browser tabs must not
  produce conflicting submissions being silently accepted.
- **Connectivity loss** — a live surface that loses its event stream must say so
  rather than appearing merely quiet, and must recover when connectivity
  returns.

## Requirements *(mandatory)*

### Functional Requirements

#### Stage board (home surface)

- **FR-001**: The default surface MUST present ingested requests grouped into
  the six stages of the existing phase projection — Intake & alignment,
  Discovery, Definition, Planning, Build & deliver, Done — in that order.
- **FR-002**: The board MUST show exactly one card per ingested request. Work
  belonging to a request MUST be rendered inside that request's card and MUST NOT
  appear as a separate top-level card. This covers two distinct cases, which are
  not the same problem:
  - **Cards within a workflow** (interview personas, implementation items) —
    already available on the snapshot.
  - **Decomposition children**, which are re-ingested as *their own workflows*
    with their own source refs. Nesting these requires the parent link of FR-040.
- **FR-003**: Each card MUST identify its request by source reference **and**
  human title, not by an internal workflow identifier. Requires FR-041.
- **FR-004**: Each card MUST state its exact current phase in words, in addition
  to its stage placement, and MUST indicate the request's position within the
  ten-phase sequence.
- **FR-005**: The board MUST visually distinguish, with three treatments that
  are not interchangeable: a request awaiting an operator decision
  ("your move"), a request that has reached a round cap (requires FR-042), and a
  request that was quarantined at intake.
- **FR-006**: The board MUST NOT offer card dragging as a means of changing
  state (spec 026 **FR-032**). Stage placement is derived, not operator-set.
- **FR-007**: Every intervention and navigation available on the board by
  pointer MUST also be available by keyboard (spec 026 FR-031).
- **FR-008**: The board MUST show an explanatory empty state when no requests
  have been ingested.
- **FR-009**: The board MUST replace the previous nav-list surface as the
  default, rather than being added alongside it.
- **FR-044**: Terminal requests MUST be retrieved for the Done column. The
  listing filters them out by default (`include_completed=false`), so the board
  MUST request them explicitly — otherwise the Done column is permanently empty
  and FR-001's sixth column is decorative. Frontend-only; no API change needed.

#### Request cockpit (detail surface)

- **FR-010**: The cockpit MUST be scoped to exactly one request; nothing
  belonging to another request may appear on it.
- **FR-011**: The cockpit MUST present the ten phases as a labelled sequence,
  marking gate phases distinctly from work phases and highlighting the current
  phase.
- **FR-012**: The cockpit MUST present a chronological narrative feed of the
  request's recorded events, oldest first, each attributed to the persona
  responsible.
- **FR-013**: Where no persona can be attributed to an event, the feed MUST
  attribute it neutrally and MUST NOT invent or guess an actor. (The backing
  projection derives the persona from a card's eligible role at read time and
  supplies none for workflow-level or operator-resolved events.)
- **FR-014**: The cockpit MUST present the request's durable artifacts — original
  request, understanding check, CAB-1 decision, interview rounds, PRD, technical
  analysis, executive summary, pull request — each with its state and each
  openable to read its content.
- **FR-015**: Artifact content MUST never become live markup, and MUST
  surface the artifact's provenance so unreviewed agent output is
  distinguishable from operator-approved content. (Amended by feature 043
  FR-005: Markdown content is rendered as formatted Markdown with raw HTML
  escaped and unsafe link protocols dropped; other content is shown as
  text.)
- **FR-016**: When a request is waiting on the operator, the cockpit MUST state
  that single ask prominently and attach its actions to that statement. When it
  is waiting on nothing, no such element may be shown.
- **FR-017**: The feed MUST be read-only. Every answer-shaped interaction MUST
  navigate to the dedicated input surface.
- **FR-018**: The cockpit MUST reflect newly arriving events without requiring a
  manual refresh, and MUST NOT scroll away from content the operator has
  deliberately scrolled back to.
- **FR-019**: The cockpit MUST replace the dependency-graph view as the
  structural view of a request.

#### Interview workspace (input surface)

- **FR-020**: The interview MUST be a surface of its own, distinct from the
  cockpit, reached from it and returning to it on submission.
- **FR-021**: Questions MUST be grouped by the persona that asked them.
- **FR-022**: In-progress answers MUST be preserved without an explicit save
  action, and the operator MUST receive unambiguous feedback distinguishing a
  stored draft from a final submission.
- **FR-023**: Every question MUST offer both escape hatches: "I don't know — let
  the PRD state an assumption", and "not relevant". Neither may be recorded as
  an empty answer.
- **FR-024**: The surface MUST state the current round and the round cap, and
  MUST make explicit when the current round is the last opportunity to answer
  before assumptions are recorded in the PRD.
- **FR-025**: When a round advances, answers from the previous round MUST be
  reconciled against the new round's questions rather than discarded or
  misattributed.
- **FR-026**: Submission MUST be refused while required questions remain neither
  answered nor waived, and the outstanding questions MUST be identified.
- **FR-027**: Where no multi-round cap applies, the round indicator MUST degrade
  to stating a single round. Requires FR-042.
- **FR-045**: The interview MUST load its question set from the request's
  interview artifact, and MUST state plainly when that artifact cannot be read
  rather than presenting an empty interview as though there were nothing to
  answer.
- **FR-046**: Submitting the interview MUST record every answer against its
  question through the existing gate-resolution path, carrying the snapshot
  revision the operator saw so a superseded submission is refused rather than
  applied to moved-on state. The four answer states of FR-023 MUST remain
  distinguishable in what is recorded — an "I don't know" and a "not relevant"
  MUST NOT both arrive as empty text.

#### Navigation and addressability

- **FR-028**: Each surface — board, a request's cockpit, a request's interview —
  MUST have its own address, resolvable directly in a fresh session.
- **FR-029**: The browser's back **and forward** controls MUST retrace the
  operator's path between surfaces in both directions.
- **FR-030**: An address naming a request that does not exist MUST produce an
  explanatory message and a route back to the board.
- **FR-031**: The pre-existing `?run=<id>` deep-link form MUST continue to
  resolve to that request, so existing notification links do not break.
- **FR-032**: No surface address may carry a secret, consistent with the
  constitution's existing constraint on notification deep-links.
- **FR-047**: The existing agent-session debug surface MUST remain reachable. It
  is reached by a view toggle today, and that toggle is removed with the nav list
  — so it needs an address of its own or it becomes unreachable. Its *contents*
  are out of scope; only its reachability is in.

#### Retirement

- **FR-033**: The dependency-graph view, its layout projection, its tests, and
  the third-party graph-rendering dependency MUST be removed once the board and
  the cockpit's phase sequence are in place. **This supersedes spec 026 FR-030**,
  which mandated a dependency-graph view; the phase sequence discharges that
  requirement's intent (show a request's structure) more honestly, and the
  supersession MUST be recorded rather than left as a silent contradiction
  between two specs.
- **FR-034**: The list/graph toggle and the superseded nav-list surface MUST be
  removed with it.
- **FR-035**: Removal MUST introduce no new dead-code, dependency-cycle, or
  duplication findings, and the full quality gate MUST pass.

#### Presentation constraints

- **FR-036**: Every surface MUST be built from the project's existing component
  library. Bespoke styling is permitted only for a gap named and justified in
  the implementation plan.
- **FR-037**: All colour MUST come from the theme. Literal colour values are
  prohibited (constitution Principle V).
- **FR-038**: Operator confirmations MUST use the application's own dialog
  affordance, not the browser's native confirmation prompt.
- **FR-039**: This feature MUST add no workflow behaviour, no pipeline stage, and
  no change to how cards are created, claimed, or transitioned. The phase
  projection remains display-only and MUST NOT become a driver (spec 026
  FR-037).

#### Board API additions (additive, read-only)

Four facts the surfaces above must show are not currently exposed. Each is an
**additive** field on an existing response — nothing is renamed, nothing changes
meaning, no endpoint is added, and nothing becomes writable. The frontend/backend
type contract MUST be updated on both sides in the same change (constitution
Principle I).

- **FR-040**: A request's listing entry MUST expose the identity of the request it
  was decomposed from, where it was. The parent relationship is already persisted
  but is exposed by no response today, which is why decomposition children still
  read as siblings — problem 1 of this spec. Without it FR-002 cannot hold.
- **FR-041**: A request's listing entry and its snapshot MUST expose the request's
  human title, distinct from its source reference. Both are needed: the reference
  identifies, the title explains. Without it FR-003 cannot hold.
- **FR-042**: A gate awaiting interview answers MUST expose the current round and
  the round cap in force. The round is derived server-side and reaches the agent
  today but no client; the cap is server configuration. Without them FR-024 and
  FR-027 cannot hold, and "round 3 of 3" cannot be stated.
- **FR-043**: A request MUST expose whether a round cap has been exhausted without
  a usable answer, as a fact rather than something the client infers by comparing
  counts. Without it the `cap-reached` treatment of FR-005 cannot be distinguished
  from an ordinary wait.

**Boundary**: these four exist to make facts the backend already knows visible.
If satisfying one appears to need new *behaviour* — a new state, a new
transition, a write path — that is a finding to raise with the developer, not to
build (see FR-039).

### Key Entities

This feature introduces no new persisted data. It reads projections that already
exist:

- **Request** — one ingested ticket and the workflow tracking it. Carries a
  source reference, a title, a status, a derived phase, a derived stage, and a
  count of items awaiting the operator. One board card per request.
- **Phase / Stage** — a display-only projection over card kinds: ten ordered
  phases grouped into six stages, plus a synthetic `Done` once every card is
  terminal. Read-only, with no bearing on card transitions.
- **Board event** — one recorded occurrence in a request's history, with a type,
  an optional originating card, a payload, a timestamp, and an optionally
  derived specialist persona. The narrative feed's unit.
- **Artifact** — a durable output of a request, with a kind, a state, retrievable
  content, and a trust marker distinguishing agent output from operator-approved
  content. The artifact list's unit.
- **Gate** — a point where a request awaits an operator decision, carrying the
  decision being requested and, once resolved, the decision made. Drives the
  board's "your move" treatment and the cockpit's action statement.
- **Interview round** — a numbered round of persona-attributed questions within a
  capped sequence, with per-question answers that may be substantive, waived as
  unknown, or marked not relevant.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A request that is ingested once appears exactly once on the home
  surface, in every case — including quarantine and decomposition, which today
  each produce extra entries.
- **SC-002**: The operator can name the current phase of every request on the
  board without opening any of them.
- **SC-003**: The operator can identify every request awaiting their input from
  the home surface alone, with no request that needs them left unflagged and no
  request flagged that does not.
- **SC-004**: Opening one request answers where it is, why it got there, and
  what it has produced without leaving that surface.
- **SC-005**: An interview round can be completed and submitted entirely from
  the UI — a task that is impossible today.
- **SC-006**: No interview question can be submitted with an invented answer: a
  question the operator cannot answer is recordable as an assumption request or
  as not relevant.
- **SC-007**: An interrupted interview loses no typed answer when the operator
  leaves the surface and returns.
- **SC-008**: Every surface is reachable by its own address in a fresh session,
  and the browser's back control retraces the operator's path.
- **SC-009**: Existing `?run=<id>` links continue to resolve to their request.
- **SC-010**: Every surface is fully operable by keyboard alone.
- **SC-011**: At a 1280 px viewport width, all six stage columns are reachable
  and each card's source ref, phase line and attention treatment are readable
  without horizontal truncation — the failure the rejected ten-column layout
  demonstrated. The width is named so this is testable rather than a matter of
  opinion.
- **SC-012**: The frontend production dependency count does not increase: the
  graph-rendering dependency is removed in the same feature as the one added for
  navigation, which is justified in the plan against the alternative of
  hand-rolling it.
- **SC-013**: The full quality gate passes, with no new suppression, threshold
  edit, or grandfather-list entry introduced to make it pass.

## Assumptions

- **The backend is *mostly* complete — four fields short.** The heavy
  prerequisites landed in commit `31cbe6a`: the phase/stage projection, the
  per-request events endpoint, the artifact content endpoint, and gate detail with
  free-text answers. An audit on 2026-09-28 then found four facts these surfaces
  must show that no response exposes — human title, decomposition parent link,
  interview round/cap, and cap exhaustion. Rather than quietly weakening the
  requirements that depend on them, the developer chose to add the four as
  additive read-only fields (FR-040–FR-043).
  **The rule still stands for anything else**: a further gap found during
  implementation is a finding to raise, not a licence to extend the API
  opportunistically. No endpoint is added and no existing field changes meaning.
- **Duplicate-entry collapsing is already done.** The listing already collapses
  duplicate quarantine entries and imposes an order (commit `66c9af1`, #45).
  FR-002 is about presentation of children within a card, not about re-fixing
  the listing.
- **Multi-round interviews already exist, but are invisible to a client.** The
  round cap landed in commit `a353f9b` (#48/#49,
  `specs/028-refinement-rounds-cap/`), so a real cap is in force — but that commit
  touched services, config and tests only. The round is derived server-side and
  reaches the agent envelope; neither it nor the cap appears in `schemas.py`.
  FR-042 exposes them. Single-round remains a valid degraded case (FR-027).
- **Navigation is a new dependency, deliberately.** The decision to adopt a
  routing library rather than extend the existing single-parameter deep-link
  reader was taken with the developer on 2026-09-28. The alternative would mean
  hand-writing history management, address parsing, and back-button behaviour —
  reimplementing a routing library less well. Principle IV requires the added
  dependency to be justified in the plan's Complexity Tracking table; it does not
  forbid it. Recording it here so the plan does not relitigate it.
- **Prior art is to be reused, not rewritten.** The interview surface has
  substantial reusable predecessors removed in the Phase 10 clean break
  (`3fc281c^`): a questionnaire form with debounced autosave and round-advance
  answer reconciliation, its grouping and answer model, and round chips, plus
  their tests. FR-022 and FR-025 are to be satisfied by recovering that logic,
  not by rewriting it.
- **Event attribution is a read-time derivation, not a recorded fact.** No actor
  is recorded against a board event; the persona is derived from a card's
  eligible role. FR-013 exists because of this, and this feature must not
  present derived attribution as though it were recorded.
- **The mockups are layout references, not an implementation model.** They are
  hand-written throwaway markup that settles layout and information
  architecture only. Per a decision with the developer on 2026-09-28 they are to
  be committed; the `.gitignore` negation exempting them from the blanket image
  ignore is already in place, so they need only be added, and then references
  from this spec and from #57/#58/#59 resolve for a later reader.
- **Viewport target is a laptop**, single operator, modern browser, local
  network. No mobile layout, no multi-user concerns, no offline mode.
- **Scope excludes** any change to workflow behaviour; the *contents* of the
  dispatch/session debug surface (its reachability is in scope per FR-047, because
  removing the view toggle would otherwise orphan it); notification *generation*
  (following an existing notification to the right surface is in scope, emitting
  different ones is not); new endpoints or any change to an existing field's
  meaning (FR-040–FR-043 are purely additive); and the stale entries in the
  frontend lint grandfather list — that file is CI-guarded and its cleanup needs
  the developer's explicit sign-off, tracked on #60.
