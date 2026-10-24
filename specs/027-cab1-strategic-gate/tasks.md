# Tasks: CAB-1 Strategic Fit Gate

**Input**: Design documents from `/specs/027-cab1-strategic-gate/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, quickstart.md

**Tests**: This repo's constitution (Principle III, NON-NEGOTIABLE) requires
behavior changes to ship with tests, so — unlike the generic template — test
tasks below are mandatory, not optional. A bug/behavior-affecting task is
not done until its test exists and passes.

**Organization**: Grouped by the four user stories in `spec.md` (US1–US4).
User Story 5 from the GitHub issue's post-approval "expanded audiences" idea
is explicitly out of scope (see spec Assumptions) — no tasks for it.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on an
  incomplete task)
- Paths are relative to the repo root

---

## Phase 1: Foundational (Blocking Prerequisites)

**Purpose**: The enum values, config surface, and roster entry every user
story's code depends on. No user story task can start before this phase is
done.

- [x] T001 Add `CardKind.CAB1_GATE = "cab1_gate"`, `.STRATEGIC_INTERVIEW =
      "strategic_interview"`, `.STRATEGIC_INTERVIEW_GATE =
      "strategic_interview_gate"` to `backend/app/models_board.py`
      (alongside the existing gate/interview kinds, same enum, same
      docstring style as the existing `REFINEMENT`/`REFINEMENT_GATE` pair)
- [x] T002 [P] Add `board_cab1_gate_required: bool = False` and
      `board_cab1_interview_max_questions: int = Field(default=3, gt=0)` to
      `backend/app/config.py`, alongside `board_prd_gate_required`,
      matching its docstring style (env var names
      `KESTREL_BOARD_CAB1_GATE_REQUIRED` /
      `KESTREL_BOARD_CAB1_INTERVIEW_MAX_QUESTIONS`)
- [x] T003 [P] Document both new settings in `config.toml.example` next to
      `board_prd_gate_required` / `board_decomposition_required`
- [x] T004 Add `cab1: bool = False` to `GateRequirements` in
      `backend/app/services/board/gates.py`
- [x] T005 Wire `cab1=settings.board_cab1_gate_required` into
      `GatesService`'s `GateRequirements(...)` construction in
      `get_gates_service()`, `backend/app/services/board/bootstrap.py`
- [x] T006 [P] Add `"strategic_interview"` to `allowed_card_types` in
      `backend/specialists/requester/manifest.toml`
- [x] T007 [P] Add a `config.py` bounds test asserting
      `board_cab1_interview_max_questions` defaults to `3` and rejects a
      non-positive value, in `backend/tests/test_config.py` (or the
      existing settings-bounds test module, matching its current pattern)

**Checkpoint**: Enum, config, and roster changes exist; `uv run pytest
backend/tests/test_config.py` and a plain import of `gates.py`/`bootstrap.py`
succeed. No behavior change yet — nothing reads `cab1` outside
`GateRequirements` until Phase 2.

---

## Phase 2: User Story 1 - A reviewer decides whether new work is worth pursuing (Priority: P1) 🎯 MVP

**Goal**: A `cab1_gate` card, once it exists, gates entry into `refinement`
the same way `understanding_gate` does today — approve proceeds, reject
does not, and the trigger swap is fully backward compatible when CAB-1 is
disabled.

**Independent Test**: Directly construct a `cab1_gate` via
`GatesService.create_gate(...)` (the same way `test_board_gates.py`
constructs `understanding_gate`/`decomposition_gate` today, without going
through the strategic-interview pipeline) and resolve it — approving must
create the `refinement` persona cards; rejecting must not.

### Tests for User Story 1

- [x] T008 [P] [US1] Unit test:
      `_refinement_trigger_kind()` returns `CAB1_GATE` when
      `GateRequirements(cab1=True)`, else `UNDERSTANDING_GATE`, in
      `backend/tests/test_board_gates.py`
- [x] T009 [P] [US1] Unit test: approving a directly-constructed
      `cab1_gate` (with `cab1=True`, `prd=True`) creates the three
      `refinement` persona cards, mirroring the existing
      `test_required_and_not_skipped_creates_three_interview_cards`
      pattern, in `backend/tests/test_board_gates_prd.py`
- [x] T010 [P] [US1] Unit test: with `cab1=True`, approving
      `understanding_gate` directly does **not** create `refinement` cards
      (they now wait for `cab1_gate`), in
      `backend/tests/test_board_gates_prd.py`
- [x] T011 [P] [US1] Regression test: with `GateRequirements()` defaults
      (`cab1=False`), approving `understanding_gate` still creates
      `refinement` cards directly, unchanged from current behavior (SC-005),
      in `backend/tests/test_board_gates.py`

### Implementation for User Story 1

- [x] T012 [US1] Add `_refinement_trigger_kind()` to `GatesService`
      (`backend/app/services/board/gates.py`), mirroring the existing
      `_decomposition_trigger_kind()`: returns `CardKind.CAB1_GATE.value`
      when `self._required.cab1`, else `CardKind.UNDERSTANDING_GATE.value`
- [x] T013 [US1] Change `_maybe_require_refinement`'s guard from the
      literal `understanding_gate.kind != CardKind.UNDERSTANDING_GATE.value`
      check to `resolved_gate.kind != self._refinement_trigger_kind()`
      (rename the parameter from `understanding_gate` to `resolved_gate` to
      match), same file
- [x] T014 [US1] Depends on T012/T013. Confirm `_maybe_require_refinement`
      is still called from the same `if decision == "approved":` block in
      `resolve()` — no call-site change needed, only the guard inside it

**Checkpoint**: `uv run pytest backend/tests/test_board_gates.py
backend/tests/test_board_gates_prd.py` passes. CAB-1's gating mechanic
works end-to-end when a `cab1_gate` exists by direct construction; nothing
yet creates one from `understanding_gate` — that's US2.

---

## Phase 3: User Story 2 - The requester gives light strategic context (Priority: P2)

**Goal**: Approving `understanding_gate` (with CAB-1 enabled) produces a
bounded, plain-language `strategic_interview` for the `requester` persona;
once answered, a `cab1_gate` is created automatically — connecting into
US1's gating mechanic.

**Independent Test**: With `cab1=True`, approve `understanding_gate` and
confirm exactly one `strategic_interview` card exists
(`eligible_roles == ("requester",)`); dispatch it with a fake backend
returning a question set at/under the configured cap; confirm exactly one
`strategic_interview_gate` exists; resolve it with an answer and confirm
exactly one `cab1_gate` exists.

### Tests for User Story 2

- [x] T015 [P] [US2] Unit test: approving `understanding_gate` with
      `cab1=True` creates exactly one `strategic_interview` card,
      `eligible_roles == ("requester",)`, and creates **no**
      `strategic_interview`/`cab1_gate` card when `cab1=False`, in
      `backend/tests/test_board_gates_prd.py`
- [x] T016 [P] [US2] Unit test: `route_strategic_interview_result` parses a
      `<REFINEMENT_QUESTIONS>`-shaped result into a `strategic_interview_gate`
      card with `requested_decision="answer"`, and truncates/rejects a
      question set over `board_cab1_interview_max_questions` (decide and
      assert the exact truncate-vs-reject behavior — truncate to the cap is
      the simpler default per spec FR-003/SC-003, document the choice in
      the test docstring), in `backend/tests/test_board_refinement.py`
      (or a new `test_board_cab1.py` if that file is already near its
      500-line module-length ceiling — check first)
- [x] T017 [P] [US2] Unit test: approving a `strategic_interview_gate`
      creates exactly one `cab1_gate` card, `state == "awaiting_human"`,
      via the new `_maybe_require_cab1_decision`, in
      `backend/tests/test_board_gates_prd.py`

### Implementation for User Story 2

- [x] T018 [US2] Add `route_strategic_interview_result(text, card,
      coordinator, gates, artifacts, max_questions)` to
      `backend/app/services/board/refinement.py`, mirroring
      `route_refinement_result` but creating a `STRATEGIC_INTERVIEW_GATE`
      card with `requested_decision="answer"`, and enforcing
      `max_questions` (from `settings.board_cab1_interview_max_questions`,
      threaded through the same way other config values already reach this
      module — check current call site before choosing a threading
      approach)
- [x] T019 [US2] Add `_maybe_require_cab1_interview(resolved_gate)` to
      `GatesService`, mirroring `_maybe_require_refinement`: no-op unless
      `self._required.cab1`, `resolved_gate.kind ==
      CardKind.UNDERSTANDING_GATE.value`, and not
      `workflow.skip_decomposition`; creates one `strategic_interview` card,
      `eligible_roles=("requester",)`
- [x] T020 [US2] Add `_maybe_require_cab1_decision(resolved_gate)` to
      `GatesService`: no-op unless `resolved_gate.kind ==
      CardKind.STRATEGIC_INTERVIEW_GATE.value`; creates one `cab1_gate`
      card via `self._store.create_card` + a matching `HumanGateRecord`
      (reuse the same two-step shape `create_gate` already uses — consider
      calling `self.create_gate(...)` directly instead of duplicating it)
- [x] T021 [US2] Call both new methods from the same `if decision ==
      "approved":` block in `GatesService.resolve()`, alongside the
      existing three `_maybe_*` calls
- [x] T022 [US2] Wire dispatch routing: find where `route_refinement_result`
      is currently invoked (dispatch_ready.py or similar, by card kind) and
      add the equivalent call for a completed `strategic_interview` card to
      `route_strategic_interview_result`

**Checkpoint**: `uv run pytest backend/tests/test_board_gates_prd.py
backend/tests/test_board_refinement.py` passes. The full chain
`understanding_gate → strategic_interview → strategic_interview_gate →
cab1_gate → refinement` now works end-to-end when CAB-1 is enabled.

---

## Phase 4: User Story 3 - A rejected task doesn't waste unrelated work (Priority: P2)

**Goal**: Confirm (not build — this reuses existing generic machinery) that
rejecting `cab1_gate` only invalidates what depends on it, and leaves prior
history intact.

**Independent Test**: Reject a `cab1_gate` and confirm no `refinement`
cards are created, and the `understanding_gate`/`strategic_interview`/
`strategic_interview_gate` cards remain in the store, terminal and
unaltered.

### Tests for User Story 3

- [x] T023 [US3] Integration test: with the full US2 chain run to a
      `cab1_gate`, reject it and assert (a) no `refinement` cards exist
      afterward, (b) `store.list_cards(workflow_id)` still contains the
      `understanding_gate`, `strategic_interview`, and
      `strategic_interview_gate` cards, all in a terminal state, in the new
      `backend/tests/test_board_cab1_e2e.py` (see quickstart.md step 7)

### Implementation for User Story 3

- [x] T024 [US3] No new production code expected — `_invalidate_dependents`
      already applies generically to any gate kind. If T023 fails, that is
      a real gap (not an oversight in this task list) — file it as a
      correction to Phase 2/3 rather than adding new invalidation logic
      here.

**Checkpoint**: `uv run pytest backend/tests/test_board_cab1_e2e.py`
passes; FR-007/SC-004 verified end-to-end.

---

## Phase 5: User Story 4 - An operator can turn the gate on or off (Priority: P3)

**Goal**: Confirm the whole feature is inert by default (SC-005) and prove
the full opposite-enabled path end-to-end, matching
`test_board_refinement_e2e.py`'s style for the existing PRD-gate flow.

**Independent Test**: Run the full `understanding_gate →
strategic_interview → strategic_interview_gate → cab1_gate → refinement`
chain through `dispatch_ready_work` with a fake backend (not by directly
constructing cards, unlike US1/US2's unit tests), and a second run with
`cab1=False` proving no CAB-1 cards appear at all.

### Tests for User Story 4

- [x] T025 [US4] End-to-end test in
      `backend/tests/test_board_cab1_e2e.py` (same file as T023): build
      the real `BoardService`/`GatesService`/`ClaimsService`/
      `DispatchServices` stack per `quickstart.md`'s automated section,
      run the full CAB-1-enabled chain via `dispatch_ready_work` with a
      fake backend, and assert the final `refinement` cards appear
      (steps 1–6 of quickstart.md)
- [x] T026 [P] [US4] In the same file, a `cab1=False` (default) scenario:
      approve `understanding_gate` and assert `refinement` cards appear
      directly, with zero `strategic_interview`/`strategic_interview_gate`/
      `cab1_gate` cards ever created (step 8 of quickstart.md — this is the
      authoritative SC-005 regression test, distinct from T011's narrower
      unit-level check)

### Implementation for User Story 4

- [x] T027 [US4] None expected beyond Phases 1–3 — this story is
      verification-only. If T025/T026 surface a gap, fix it in the
      relevant earlier phase's file, not here.

**Checkpoint**: All CAB-1 tests pass; `uv run pytest` (full backend suite)
and `task quality` (repo root) are clean.

---

## Final Phase: Polish & Cross-Cutting Concerns

- [x] T028 [P] Re-run `resolve_kits(task="CAB-1 strategic fit gate
      implementation")` before starting Phase 1 if it has not been run yet
      this session (per `AGENTS.md`/constitution Principle V)
- [x] T029 Run `task quality` from the repo root; fix any structural
      guardrail violation the same way the rest of this repo does (extract,
      don't suppress — see `AGENTS.md` "Code-quality guardrails")
- [ ] T030 Run the manual quickstart (`quickstart.md`'s "Manual" section)
      at least once against a real `task dev` session before considering
      GitHub #47 closeable — the automated tests above substitute for it
      during implementation but the issue's own acceptance note asks for a
      live click-through

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Foundational)**: No dependencies — start immediately. Blocks
  every user story.
- **Phase 2 (US1, P1)**: Depends on Phase 1. Independently testable and
  shippable on its own (a `cab1_gate` can be driven by hand/API even before
  US2's interview exists — matches how `understanding_gate` itself works
  today, resolved by a human with no specialist step first).
- **Phase 3 (US2, P2)**: Depends on Phase 1 and on US1's
  `_refinement_trigger_kind`/gating existing (US2's `cab1_gate` creation
  needs US1's gate-kind guard already in place to have any effect) — not
  independent of US1, unlike the template's general guidance; that
  dependency is real here and is called out explicitly rather than forced
  into false independence.
- **Phase 4 (US3, P2)**: Depends on Phase 3 (needs the full chain to exist
  to test rejection at the end of it).
- **Phase 5 (US4, P3)**: Depends on Phase 3 (needs the full chain for the
  end-to-end test); independent of Phase 4.
- **Final Phase**: Depends on all prior phases.

### Parallel Opportunities

- T002, T003, T006, T007 (Phase 1) can run in parallel once T001 exists.
- T008–T011 (Phase 2 tests) can be written in parallel; T012–T014
  (Phase 2 implementation) are sequential (same file, same method chain).
- T015–T017 (Phase 3 tests) can be written in parallel.
- T026 (Phase 5) can run in parallel with T025 (different scenario, same
  file — parallel-authorable, not necessarily parallel-runnable in one
  pytest file edit; use judgment).

---

## Implementation Strategy

### MVP First

1. Phase 1 (Foundational).
2. Phase 2 (US1) — the CAB-1 gate's core gating mechanic, directly
   constructible and testable without the interview pipeline. This alone
   is enough to demo "CAB-1 blocks refinement until approved" via a
   hand-created gate (e.g. through the existing generic API), even before
   US2 automates the interview that normally creates one.
3. **STOP and VALIDATE**: `uv run pytest backend/tests/test_board_gates.py
   backend/tests/test_board_gates_prd.py`.

### Incremental Delivery

1. Phase 1 → Phase 2 (US1) → validate → the CAB-1 mechanic exists but
   nothing triggers it automatically yet.
2. Phase 3 (US2) → validate → the full automatic chain exists.
3. Phase 4 (US3) → validate → rejection safety proven.
4. Phase 5 (US4) → validate → default-off + full end-to-end proven; ready
   for the manual quickstart and closing GitHub #47.
