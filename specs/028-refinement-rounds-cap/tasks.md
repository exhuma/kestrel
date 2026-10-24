# Tasks: Bounded interview rounds and coordinator-routed PRD redrafts

**Input**: Design documents from `specs/028-refinement-rounds-cap/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md

**Tests**: Included — this repo's existing convention
(`backend/tests/test_board_*.py`) is pytest coverage alongside every
service change; `task quality` also requires it in practice.

**Organization**: Phase 3 = User Story 1 (#48, multi-round interviews).
Phase 4 = User Story 2 (#49, coordinator-routed redraft) — depends on
Phase 3's round-creation helper being in place (per spec.md: "#49
depends on #48's round machinery").

## Phase 1: Setup

- [x] T001 Add `board_refinement_round_cap: int` (`Field(default=1,
      ge=1)`) and `board_prd_redraft_cap: int` (`Field(default=1,
      ge=1)`) to `Settings` in `backend/app/config.py`, doc-commented
      following the `board_cab1_interview_max_questions` precedent
      immediately above/near it.

## Phase 2: Foundational

- [x] T002 Add `refinement_round_cap: int = 1` and
      `prd_redraft_cap: int = 1` fields to `GateRequirements` in
      `backend/app/services/board/gates.py`, plus read-only properties
      `GatesService.refinement_round_cap` / `.prd_redraft_cap` mirroring
      the existing `cab1_interview_max_questions` property.
- [x] T003 Add a `coordinator: CoordinatorService` constructor parameter
      to `GatesService.__init__` in `backend/app/services/board/gates.py`
      (stored as `self._coordinator`); confirm no import cycle (
      `coordinator.py` does not import `gates.py`).
- [x] T004 Wire T001/T002/T003 into `bootstrap.py::get_gates_service()`
      in `backend/app/services/board/bootstrap.py`: pass
      `refinement_round_cap=settings.board_refinement_round_cap`,
      `prd_redraft_cap=settings.board_prd_redraft_cap` into
      `GateRequirements(...)`, and `get_coordinator_service()` as the
      new `coordinator=` argument to `GatesService(...)`.
- [x] T005 Update the shared `_service()` test fixture in
      `backend/tests/test_board_gates.py` (used by both
      `test_board_gates.py` and `test_board_gates_prd.py`) to accept
      `refinement_round_cap`/`prd_redraft_cap` kwargs (default `1`) and
      construct/pass a `CoordinatorService` to `GatesService`.

**Checkpoint**: Config and DI wiring compiles; existing test suite still
passes unmodified (defaults preserve today's behavior — FR-014).

---

## Phase 3: User Story 1 — Multi-round interviews with a round cap (Priority: P1)

**Goal**: A persona's interview can take more than one round, up to a
configurable cap, with an explicit exit signal and round-aware prompts.

**Independent Test**: Run a workflow through refinement with
`board_refinement_round_cap=2`; give an ambiguous first-round answer;
confirm a second `refinement` card is created for that persona with
round-number context in its envelope, and that PRD drafting waits for
it. Entirely testable without touching `_maybe_redraft_prd`/PRD-gate
code at all.

### Tests for User Story 1

- [x] T006 [P] [US1] In `backend/tests/test_board_refinement.py`, add
      `TestParseRefinementQuestions` cases: `"satisfied": true` with a
      non-empty `questions` list still parses (satisfied is only
      terminal when questions is empty); `"satisfied": true` with an
      empty `questions` list parses successfully (no
      `RefinementResultError`); no `"satisfied"` key at all behaves
      exactly as today (empty list still raises).
- [x] T007 [P] [US1] In `backend/tests/test_board_refinement.py`, add
      `TestRouteRefinementResult` cases: `satisfied=true` + empty
      questions transitions the `refinement` card straight to `DONE`
      and creates no `refinement_gate`; `satisfied=false` (or absent)
      creates a `refinement_gate` exactly as today.
- [x] T008 [P] [US1] In `backend/tests/test_board_gates.py` (or a new
      `TestRefinementRounds` class in `test_board_gates_prd.py` next to
      `TestRefinementEnforcement`), test: resolving round 1's
      `refinement_gate` as answered, with `refinement_round_cap=2`,
      creates a round-2 `refinement` card for that persona;
      `_maybe_start_prd`-equivalent does NOT fire while round 2 is
      outstanding for any persona.
- [x] T009 [P] [US1] Same file as T008: with `refinement_round_cap=1`
      (default), resolving round 1's gate creates no round-2 card and
      PRD drafting proceeds exactly as today (regression guard for
      FR-014).
- [x] T010 [P] [US1] Same file as T008: with `refinement_round_cap=2`,
      a persona whose round-1 card is answered AND whose round-2 output
      is `satisfied=true`/no-questions does not consume a third round
      even though the cap allows it (FR-005/FR-006).
- [x] T011 [P] [US1] Same file as T008: with `refinement_round_cap=2`,
      a persona pinned at round 2 (the cap) whose round-2 gate is
      answered gets no round-3 card even if not satisfied (FR-002 hard
      stop); once every persona is at this state, PRD drafting starts
      (edge case from spec.md: "every persona reaches the round cap
      simultaneously").
- [x] T012 [P] [US1] In `backend/tests/test_board_envelopes.py`, add
      `TestCardEnvelope`/`TestExtraContext` cases: a `REFINEMENT` card's
      built envelope (via whatever helper `_dispatch_one` now calls —
      see T016) includes "round 2 of 2" (or equivalent) text and the
      persona's own prior round's question/answer content; the final
      round's text additionally instructs the specialist to consolidate
      and state assumptions rather than ask further questions.

### Implementation for User Story 1

- [x] T013 [US1] In `backend/app/services/board/refinement.py`, extend
      `parse_refinement_questions` (or add a small
      `parse_refinement_round(text) -> RefinementRound` wrapper
      dataclass with `questions: list[str]` and `satisfied: bool`) so an
      empty `questions` list is only valid when `satisfied` is `true`;
      keep the existing fail-closed `RefinementResultError` behavior for
      every other malformed shape.
- [x] T014 [US1] In `backend/app/services/board/refinement.py`, update
      `route_refinement_result` to accept a `board_service: BoardService`
      dependency (new parameter — check its callers in
      `dispatch_ready.py` and update them) and branch: when the parsed
      result is `satisfied` with no questions, call
      `board_service.transition_card(card.id, CardState.DONE.value,
      event_type="refinement.satisfied")` and return without creating a
      gate; otherwise keep today's gate-creation path unchanged.
- [x] T015 [US1] In `backend/app/services/board/gates.py`, add a private
      helper `_persona_round_state(cards, persona) -> tuple[int, bool]`
      (returns `(current_round, pending)`) per data-model.md's "Derived
      view: persona round state", and rewrite `_maybe_start_prd` (per
      research.md's decision) to check every persona's `pending` state
      instead of the flat "all `REFINEMENT_GATE` cards terminal" check.
      Rename `_maybe_start_prd` to keep its own single responsibility
      clear if the branching grows past the repo's complexity limit —
      split into `_maybe_start_prd` (unchanged call site/behavior) plus
      a new `_refinement_still_pending(cards) -> bool` helper it calls.
- [x] T016 [US1] In `backend/app/services/board/gates.py`, add
      `_maybe_advance_refinement_round(resolved_gate: WorkCard) -> None`
      called from `resolve()`'s `if decision == "approved":` branch
      (alongside the existing `_maybe_require_refinement` etc. calls):
      for a resolved `REFINEMENT_GATE`, compute the persona's
      `current_round` via T015's helper; if `current_round <
      self._required.refinement_round_cap`, create the next round's
      `REFINEMENT` card (same shape as `_maybe_require_refinement`'s
      existing per-persona `WorkCard(...)` construction, single
      persona).
- [x] T017 [US1] In `backend/app/services/board/dispatch_ready.py`
      (`_dispatch_one`), add a `REFINEMENT`-kind branch building
      round-aware `extra_context`: round number, configured cap, rounds
      remaining, and (reusing `gather_refinement_context`'s per-card
      answer-gathering, filtered to this persona's own
      `REFINEMENT_GATE` cards) the persona's prior-round Q&A; on the
      final round, append the "consolidate, state assumptions" 
      instruction from research.md.
- [x] T018 [US1] Update every caller of `route_refinement_result` (grep
      `dispatch_ready.py`) to pass the new `board_service` argument from
      T014.

**Checkpoint**: User Story 1 fully functional and independently
testable — multi-round interviews work end to end without any #49
change.

---

## Phase 4: User Story 2 — Coordinator-routed, capped PRD redraft (Priority: P2)

**Goal**: A PRD rejection is triaged by the coordinator (fix vs.
reinterview) instead of an unconditional automatic redraft, bounded by
a redraft cap that fails visibly when exhausted.

**Independent Test**: Reject a PRD with `board_prd_redraft_cap=1`;
confirm a `coordinator_review` card is created (not a `prd` card
directly); simulate the coordinator's next turn proposing a redraft or
a reinterview via `CoordinatorService.apply_actions` directly (bypassing
an LLM) and confirm each path applies correctly; reject a second time
and confirm the cap escalation path fires instead of a third
`coordinator_review`-then-retry cycle.

### Tests for User Story 2

- [x] T019 [P] [US2] In `backend/tests/test_board_gates_prd.py`, rewrite
      `TestPrdRedraft::test_rejection_creates_a_fresh_prd_card` (and its
      sibling `test_rejection_is_unconditional_on_the_required_flag`) to
      assert a `coordinator_review` card is created instead of a `prd`
      card, carrying the rejection feedback (assert via the stored
      `"context"` artifact content, not just the title).
- [x] T020 [P] [US2] Same file: add a test that, with
      `prd_redraft_cap=1`, rejecting the *second* `prd_gate` (i.e. the
      redraft's own gate, simulated by manually creating a second
      `prd`/`prd_gate` pair) creates an escalation `coordinator_review`
      card (title matching an "exhausted"/"budget" pattern, mirroring
      `ci_poll.py`'s own escalation title convention) and does not
      create a further `prd` or `coordinator_review`-for-judgment card.
- [x] T021 [P] [US2] In `backend/tests/test_board_dispatch.py` (or
      wherever `build_coordinator_envelope` is currently tested — grep
      first), add a test that a pending `coordinator_review` card
      carrying a `"context"` artifact has that artifact's content
      included in the built coordinator envelope, not just the card's
      title.
- [x] T022 [US2] In `backend/tests/test_board_refinement_e2e.py` (or a
      new `test_board_prd_redraft_e2e.py` if that file is already near
      its line-count limit — check first), add one end-to-end test
      driving: PRD rejection → `coordinator_review` created → a fake
      coordinator backend proposes `CreateCardAction(kind=PRD, ...)` →
      confirm a normal redraft proceeds; and a second variant where the
      fake backend proposes `CreateCardAction(kind=REFINEMENT,
      eligible_roles=(persona,))` → confirm it becomes that persona's
      next round per Phase 3's round-counting (round number derived
      correctly even though `GatesService` didn't create the card).

### Implementation for User Story 2

- [x] T023 [US2] In `backend/app/services/board/gates.py`, replace
      `_maybe_redraft_prd` with a router (keep the method name and call
      site in `resolve()`'s rejection branch unchanged) that: counts
      existing `PRD_GATE` cards for the workflow (data-model.md's
      `redrafts_so_far`); if under `self._required.prd_redraft_cap`,
      stores a `"context"` reference artifact (rejection feedback text
      — read via the existing `_RESPONSE_LOGICAL_NAME` artifact already
      stored on the rejected gate in `resolve()` — plus the rejected
      PRD draft's own content) and calls
      `self._coordinator.apply_actions(workflow_id, trigger,
      [CreateCardAction(kind=CardKind.COORDINATOR_REVIEW.value,
      title=...)])` with `trigger = f"prd_redraft:{prd_gate.id}"`
      (idempotent per rejected gate); otherwise calls `apply_actions`
      with an escalation-titled `coordinator_review` card instead,
      `trigger = f"prd_redraft:{workflow_id}:exhausted"`.
- [x] T024 [US2] In `backend/app/services/board/dispatch.py`, add an
      `ArtifactsService` constructor parameter to `SchedulingService`
      (mirrors `DispatchServices`) and extend
      `build_coordinator_envelope` to accept it (or the pre-fetched
      content) and append each pending `coordinator_review` card's
      `"context"` artifact content, if present, to the envelope.
- [x] T025 [US2] In `backend/app/services/board/bootstrap.py`, pass
      `get_artifacts_service()` into `get_scheduling_service()`'s
      `SchedulingService(...)` construction (T024's new parameter).
- [x] T026 [US2] Update `SchedulingService.wake()`'s call to
      `build_coordinator_envelope` to pass the artifacts dependency
      through (T024/T025 plumbing).

**Checkpoint**: Both user stories complete; a PRD rejection is fully
triaged through the coordinator and bounded by a visible failure state
on cap exhaustion.

---

## Phase 5: Polish & Cross-Cutting

- [x] T027 [P] Update `docs/architecture.md`'s board-domain section (if
      it documents the refinement/PRD gate flow) to reflect multi-round
      interviews and coordinator-routed redraft, per this repo's
      existing "update docs with behaviour changes" convention.
- [x] T028 Run `task quality` and fix any complexity/size violations
      surfaced by the new branching in `gates.py`/`dispatch.py` by
      extracting further private helpers (never by suppressing a
      check or editing a threshold — AGENTS.md).
- [x] T029 Run the full backend suite
      (`cd backend && uv run pytest -q`) to confirm no regression
      outside the touched files.
- [x] T030 Mark GitHub issues #48 and #49 resolved with a summary
      comment referencing the commit(s), consistent with how prior
      board-redesign issues in this session were closed out (see git
      log `fix(board):`/`feat(board):` commits referencing issue
      numbers).

## Dependencies & Execution Order

- Phase 1 → Phase 2 → Phase 3 (US1) → Phase 4 (US2) → Phase 5.
- Phase 4 depends on Phase 3: T023's "reinterview" path creates a
  `REFINEMENT` card that only behaves correctly once T015/T016's
  round-counting exists.
- Within Phase 3, T006–T012 (tests) are parallelizable against each
  other; T013–T018 (implementation) are mostly sequential within
  `gates.py`/`refinement.py` (same files) but T017 (`dispatch_ready.py`)
  can proceed in parallel with T015/T016 (`gates.py`) once T013/T014
  land.
- Within Phase 4, T019–T021 (tests) are parallelizable; T023 must land
  before T022's e2e test can pass; T024/T025/T026 are a small sequential
  chain (same feature, three files).

## Implementation Strategy

**MVP = Phase 1 + 2 + 3 (User Story 1 only)**: multi-round interviews
are independently valuable and independently testable without touching
PRD-redraft behavior at all — `_maybe_redraft_prd` keeps its current
unconditional-redraft behavior throughout Phase 3. Phase 4 is additive
on top and does not change Phase 3's contract other than by exercising
its round-creation path from a new caller (the coordinator).

## Implementation Notes (deviations from the plan above)

All tasks landed; three design choices changed shape during
implementation, each because the planned approach turned out to break
existing call sites or existing (correct) test scenarios:

- **No `GateSpec`/`eligible_roles` on gate cards.** The plan (T003,
  T016) assumed a `refinement_gate` could carry its persona directly.
  Doing that required changing `GatesService.create_gate`'s signature,
  which broke 37 existing call sites across 7 test files. Instead, a
  gate's persona is recovered via its target artifact's origin
  `refinement` card (`ArtifactsService.producer_card_id`, new) — see
  `refinement_rounds.py`'s `_persona_for_gate`. `create_gate`'s
  signature is unchanged.
- **Coordinator is carried on `GateRequirements`, not a separate
  `GatesService` constructor argument.** A dedicated `coordinator=`
  parameter pushed the constructor over the repo's 5-argument limit;
  it's a `GateRequirements` field instead, defaulting to `None` (same
  optional-collaborator convention as `DispatchServices.coordinator`),
  which also meant the existing `_service()` test fixture needed no
  change at all (T005 turned out to be unnecessary).
- **`still_pending` (T015) required a real fix, not just a rename.**
  The plan's "all lineage cards terminal" check doesn't hold: once a
  round's gate is created, `route_refinement_result` deliberately
  leaves the originating `refinement` card in `review` forever (it's
  the gate that represents the round from then on, matching how every
  other specialist-authored card behaves once a gate holds its
  output). Treating that permanently-`review` card as "pending" would
  have permanently blocked PRD drafting. `still_pending` instead treats
  a `refinement` card as resolved once *any* gate is linked to it via
  its target artifact, regardless of that card's own state.

Round-N/M envelope context (T017) and the coordinator-envelope
rejection-feedback wiring (T024–T026) landed as planned. New test
coverage: `tests/test_refinement_rounds.py`,
`tests/test_prd_redraft.py`, plus additions to
`tests/test_board_refinement.py`, `tests/test_board_gates_prd.py`,
`tests/test_board_envelopes.py`, `tests/test_board_scheduling.py`.
Full backend suite (921 tests, excluding 2 pre-existing unrelated
`test_claude_backend.py` failures) and `task quality` both pass.
