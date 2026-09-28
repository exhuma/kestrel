# Quickstart: Validating CAB-1

## Automated (primary validation path)

This feature reuses existing, already-tested machinery
(`GatesService.create_gate`/`resolve`, `InterventionsService.apply`,
`dispatch_ready_work`) end-to-end, the same way
`tests/test_board_refinement_e2e.py` validates the PRD-gate flow. Add an
analogous `tests/test_board_cab1_e2e.py`:

1. Build the real `BoardService`/`GatesService`
   (`GateRequirements(cab1=True)`)/`ClaimsService`/`DispatchServices` stack
   (see `test_board_refinement_e2e.py` for the exact wiring).
2. Create a workflow, approve its `understanding_gate` via
   `gates.resolve(...)`.
3. Assert exactly one `strategic_interview` card exists, `eligible_roles ==
   ("requester",)`.
4. Run `dispatch_ready_work` with a fake backend returning a
   `<REFINEMENT_QUESTIONS>`-shaped result capped at the configured max;
   assert exactly one `strategic_interview_gate` card exists afterward.
5. `gates.resolve(strategic_interview_gate.id, "approved", answer="...")`;
   assert exactly one `cab1_gate` card exists, `state == "awaiting_human"`.
6. `gates.resolve(cab1_gate.id, "approved")`; assert the three
   `refinement` persona cards now exist (unchanged downstream behavior).
7. A second scenario: `gates.resolve(cab1_gate.id, "rejected")`; assert no
   `refinement` cards are created and the workflow's earlier cards
   (`understanding_gate`, `strategic_interview`, `strategic_interview_gate`)
   remain in the store, terminal and unaltered (FR-007/SC-004).
8. A third scenario: `GateRequirements(cab1=False)` (default) — approve
   `understanding_gate` and assert `refinement` cards are created directly,
   with no `strategic_interview`/`cab1_gate` cards at all (SC-005).

Also extend `backend/tests/test_board_gates.py` /
`test_board_gates_prd.py`-style unit tests for the two new private trigger
methods in isolation, and a `config.py` test asserting
`board_cab1_interview_max_questions` defaults to `3` and rejects `<= 0`.

Run: `cd backend && uv run pytest tests/test_board_cab1_e2e.py -v`, then the
full suite (`uv run pytest`) and `task quality` from the repo root, exactly
as for every other change in this repo (`AGENTS.md`).

## Manual (optional, mirrors GitHub #47's own acceptance note)

1. In `config.toml` (or via `KESTREL_BOARD_CAB1_GATE_REQUIRED=true`), enable
   the flag.
2. `task local-tasks:reset && task local-tasks:init && task dev`.
3. Ingest the `hello` local task; approve `understanding_gate` in the UI.
4. Confirm a `strategic_interview` card appears and, once dispatched,
   produces a `strategic_interview_gate` asking a small number of
   plain-language questions.
5. Answer it; confirm a `cab1_gate` card appears awaiting a plain
   approve/reject decision, with no scope/cost/feasibility fields.
6. Approve it; confirm the three existing persona `refinement` cards
   appear, exactly as they do today post-`understanding_gate` when
   `board_prd_gate_required` is on.
