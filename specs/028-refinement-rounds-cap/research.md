# Phase 0 Research: Bounded interview rounds and coordinator-routed PRD redrafts

All unknowns below were resolved by reading the existing codebase
(`backend/app/services/board/gates.py`, `refinement.py`, `dispatch.py`,
`coordinator.py`, `ci_poll.py`) rather than external research — this is
an extension of an existing, well-established internal pattern set, not
a new technology choice.

## Decision: round number is derived, not stored

**Decision**: A persona's current round number for a workflow is the
count of `REFINEMENT`-kind cards already created for that persona in
that workflow (1-indexed), computed at read time (envelope-build time
and gate-resolution time) rather than stored as a new `WorkCard` field.

**Rationale**: `_maybe_start_prd` already counts existing cards of a
kind to decide "is refinement done" (`interviews = [c for c in cards if
c.kind == REFINEMENT_GATE.value]`) — deriving state from existing rows
is the established pattern in this file, not attempt/retry counters
(see below). Deriving the round number also means a `REFINEMENT` card
created by *either* `GatesService` (the normal first-round and
subsequent-round path) *or* `CoordinatorService.apply_actions`'s
`CreateCardAction` (the #49 "send it back to the interview" path) is
counted identically with no special-casing — the coordinator does not
need to know or set a round number itself.

**Alternatives considered**:
- A new `WorkCard.round: int` column. Rejected: requires a migration
  (violates the "no schema migration" constraint from the Technical
  Context) for information fully recoverable from existing rows.
- Reusing `WorkCard.attempt_count`/`attempt_limit`. Rejected per prior
  session research: `attempt_count` increments on every *claim*
  (including retries after a lease timeout on the *same* round), so it
  does not equal "round number" — a round that is claimed twice due to
  a crash would over-count. `attempt_limit` is enforced only at
  claim-lease-expiry, an unrelated concern.

## Decision: "satisfied" is a field on the existing `<REFINEMENT_QUESTIONS>` tag

**Decision**: Extend the JSON payload of the existing
`<REFINEMENT_QUESTIONS>{"questions": [...]}</REFINEMENT_QUESTIONS>` tag
with an optional `"satisfied": bool` (default `false` when absent).
`parse_refinement_questions` keeps requiring a non-empty `questions`
list *unless* `satisfied` is `true`, in which case an empty list is
accepted (the persona is declaring "no further questions"). When
`satisfied` is `true` and `questions` is empty, `route_refinement_result`
transitions the `refinement` card itself directly to `DONE` (no gate is
created — there is nothing for the operator to answer) instead of
creating a `refinement_gate`.

**Rationale**: Reuses the existing tag, parser, and
fail-closed-on-malformed convention (`RefinementResultError` →
`_escalate_unparseable`) rather than inventing a second tag. Old
specialist output with no `"satisfied"` key parses identically to today
(defaults to `false`, non-empty `questions` still required) — this is
what makes FR-014 ("existing behavior at minimum cap settings") true for
free, without a special-case branch.

**Alternatives considered**:
- A separate `<INTERVIEW_COMPLETE/>` tag. Rejected: two tags to parse
  and reconcile (what if both appear, or neither) for one binary signal
  that naturally attaches to the same question-set output.
- Inferring satisfaction from an empty `questions` list alone (no
  explicit flag). Rejected: indistinguishable from a malformed/empty
  proposal, which must stay a fail-closed parse error, not a silent
  "done" signal.

## Decision: "is this persona still pending?" replaces the flat all-gates-terminal check

**Decision**: `_maybe_start_prd`'s check (today: "every
`REFINEMENT_GATE` card in the workflow is terminal") is replaced with a
per-persona check: for each of the three personas, find that persona's
most-recently-*created* refinement-lineage card (a `REFINEMENT` card or
a `REFINEMENT_GATE` card, whichever is newer) and check whether it is
terminal. PRD drafting starts once every persona's latest card is
terminal.

**Rationale**: Under multi-round interviews, a persona's latest card
during an in-progress round 2 is a non-terminal `REFINEMENT` card with
no `REFINEMENT_GATE` yet — the old "all `REFINEMENT_GATE` cards
terminal" check would incorrectly read as "done" (vacuously true: round
1's gate is terminal, round 2's gate doesn't exist yet) and start PRD
drafting prematurely. Keying off each persona's *latest* card fixes
this, and collapses naturally back to the old check's behavior when
there is exactly one round per persona (the only case at minimum cap
settings, satisfying FR-014).

## Decision: round-advance decision happens at `refinement_gate` resolution, inside `GatesService`

**Decision**: When a `refinement_gate` is resolved (operator answers),
`GatesService` decides whether that persona gets another round: if the
round that just resolved was not satisfied-terminal and its round count
is below `board_refinement_round_cap`, create the next round's
`REFINEMENT` card (same shape as `_maybe_require_refinement`'s existing
per-persona card creation, with the round count now folded into
`extra_context` at dispatch time — see next decision). Otherwise, do
nothing further for that persona (its latest card — the just-resolved
gate — is already terminal, so the per-persona check above sees it as
done).

**Rationale**: This is the same place `_maybe_start_prd` already runs
today (end of `resolve()`); extending it in the same method keeps one
call site as the sole place refinement progression happens, matching
the existing "deterministic trigger, not the coordinator's initiative"
design note already in `_maybe_require_refinement`'s docstring.

## Decision: round N/M context threads through the existing `extra_context` envelope hook

**Decision**: `dispatch_ready.py::_dispatch_one`'s existing per-card-kind
`extra_context` construction (today: `gather_refinement_context(...)` for
`PRD` cards, `""` for `REFINEMENT` cards) gains a `REFINEMENT`-card
branch: build a string stating the round number, the cap, rounds
remaining, and — reusing `gather_refinement_context`'s own
per-`REFINEMENT_GATE`-card answer-gathering, scoped to this persona's
prior rounds — the persona's own prior Q&A. On the persona's last
available round, the string also instructs the specialist to consolidate
and state assumptions rather than ask further blocking questions
(FR-004), matching the CAB-1 interview's existing pattern of folding
policy text straight into the built prompt rather than a separate
mechanism.

**Rationale**: `build_card_envelope`'s only extension point is
`extra_context`; the caller (`_dispatch_one`) already switches on
`card.kind` to build it, so a `REFINEMENT` branch there is a pure
addition, not a signature change to `build_card_envelope` itself.

## Decision: PRD-redraft routing reuses `ci_poll.py`'s bounded-retry-then-escalate pattern verbatim

**Decision**: `_maybe_redraft_prd` is replaced with a PRD-rejection
router that counts existing `PRD_GATE` cards for the workflow (redrafts
so far = count − 1, since the first `PRD_GATE` is the original, not a
redraft). While under `board_prd_redraft_cap`, it calls
`CoordinatorService.apply_actions(workflow_id, trigger, [CreateCardAction(
kind=CardKind.COORDINATOR_REVIEW.value, title=...)])` — exactly
`ci_poll.py::_repair`'s shape, substituting a `coordinator_review` card
for the deterministic `implementation` card CI-repair creates, since
*which* fix to make here needs the coordinator's judgment, not a fixed
action. Once the cap is reached, it instead calls `apply_actions` with a
`coordinator_review` card titled to read as a final escalation —
identical in shape to `ci_poll.py::_escalate` — which is never
auto-resolved, satisfying "surfaced to the operator" (FR-012) the same
way CI-repair's budget-exhausted escalation already does today.

**Rationale**: This is a directly reusable, already-shipped pattern in
the same service layer (`CoordinatorService.apply_actions`'s validation
and per-`trigger` idempotency), not new machinery. It also naturally
gives the coordinator, not `GatesService`, the "fix vs. reinterview"
decision (FR-009): the coordinator's own next wake-up turn (triggered
automatically — every `BoardService` mutation already fires
`_trigger_scheduling`, see `bootstrap.py`) sees the pending
`coordinator_review` card and proposes either a `CreateCardAction(kind=
PRD, eligible_roles=("pm",))` (redraft — "fix directly", pm's own next
draft folds in the rejection feedback via `gather_refinement_context`'s
existing "Prior rejection feedback" section) or one or more
`CreateCardAction(kind=REFINEMENT, eligible_roles=(persona,))` (send
back to the interview — reusing the exact same multi-round machinery
from #48, since round number is derived, not coordinator-supplied).

**Alternatives considered**:
- A new `ProposedAction` variant that lets the coordinator submit
  revised PRD text directly. Rejected as unnecessary: the coordinator
  never authors long-form content in this codebase today (`apply_actions`
  only ever creates/transitions structured cards); "fix directly" is
  better modeled as "redraft with the feedback already in context" than
  as the coordinator hand-editing prose, and doing so keeps `#49`
  entirely inside the existing `CreateCardAction`/`TransitionCardAction`
  vocabulary.
- A synchronous LLM call inside `GatesService.resolve()` to decide
  fix-vs-reinterview immediately. Rejected: `resolve()` is a synchronous
  method with no backend/async access (it's called directly from the
  HTTP request path); an LLM judgment call must go through the existing
  async coordinator wake-up turn, not a new dispatch path.

## Decision: the coordinator's wake-up envelope needs the rejection feedback, not just a card title

**Decision**: `build_coordinator_envelope` (dispatch.py) gains a section
listing, for each `coordinator_review` card not yet terminal, that
card's own stored "context" reference artifact content (if any) — mirror
of how `gather_refinement_context` already surfaces a `prd_gate`'s
rejection-feedback artifact into `pm`'s next envelope. The PRD-redraft
router (previous decision) stores the rejection feedback and a pointer
to the rejected PRD's own content as that artifact when it creates the
review card. `SchedulingService` gains an `ArtifactsService` constructor
dependency (mirrors `DispatchServices`, which already holds one) to read
it.

**Rationale**: `build_coordinator_envelope` today only lists
`id [kind] state: title` per card — enough for the coordinator to know
*that* something needs review, not *why*. Without the actual feedback
text in the envelope, the coordinator cannot make the FR-009 judgment
call at all.

**Alternatives considered**:
- Put the feedback directly in the card's `title`. Rejected: rejection
  feedback is free-text operator input with no length bound; `title` is
  used elsewhere as a short display string (board listing, event log)
  and stuffing arbitrary-length feedback into it would break that
  contract for every other reader of `WorkCard.title`.
