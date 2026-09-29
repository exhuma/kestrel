# Tasks: Visible screening and a real understanding step

**Input**: `specs/032-intake-understanding/` (spec.md, plan.md, research.md)

**Tests**: required (constitution Principle III), written with the code.

US2 (understanding) is built first: US1's "screening passed" continues into
it.

## Phase 1: Foundational

- [ ] T001 Add `CardKind.UNDERSTANDING` (models_board.py); map it to the "Understanding" phase (phases.py); make it code-only (coordinator.py); allow it for pm (specialists/pm/manifest.toml)
- [ ] T002 Add `board_understanding_redraft_cap` (config.py, default 2, ≥ 0) and `GateRequirements.understanding_redraft_cap`, wired in bootstrap.py; document it in config.toml.example

## Phase 2: User Story 2 — Confirm an understanding that is actually there (P1)

- [ ] T003 [US2] Create backend/app/services/board/understanding.py:
  - `create_understanding_card(store, workflow_id)`;
  - `route_understanding_result(text, card, services)`, which stores the `restatement` artifact and opens the understanding gate targeting it, or escalates on an unreadable result;
  - `understanding_context(card, …)`, the previous restatement plus the operator's correction for a redraft;
  - `maybe_redraft_understanding(gate, store, coordinator, cap)`.
- [ ] T004 [US2] Wire it in: `_ROUTES` and `_extra_context_for` (dispatch_ready.py), and the rejection branch of `GatesService.resolve` (gates.py)
- [ ] T005 [US2] pm prompt: an "On an understanding card…" section (specialists/pm/prompt.md); README card kinds
- [ ] T006 [US2] dev_reset rerun creates a fresh understanding card instead of a record-less gate (dev_reset.py)
- [ ] T007 [US2] Backend tests (test_board_understanding.py):
  - result → artifact + targeted gate;
  - unreadable result → review, no gate;
  - rejection → a redraft whose context contains the restatement and the correction;
  - past the cap → review;
  - the coordinator can't create the card;
  - dev reset.
- [ ] T008 [US2] Frontend: the banner shows the restatement inline for `confirm_understanding`, and rejecting it requires a correction (ActionBanner.vue, asks.ts), with tests

## Phase 3: User Story 1 — See a new request the moment it is picked up (P1)

- [ ] T009 [US1] `BoardStore.record_intake`, `BoardService.create_screening_workflow` (bus only, no `on_mutation`) and `settle_screening` (one commit)
- [ ] T010 [US1] Create backend/app/services/board/intake.py with the screening-card helpers (create, find, finish on pass, cancel on quarantine)
- [ ] T011 [US1] Rework `IngestionService._start_via_board`:
  - create first, then screen with `intake_for_existing_workflow`;
  - pass → record the ticket, create the understanding card, settle;
  - suspect → cancel the screening card and announce;
  - re-screen an interrupted request on the next poll;
  - add `continue_intake(workflow_id)`.
- [ ] T012 [US1] Router: after a release, schedule `continue_intake` in the background (routers/board.py + bootstrap helper)
- [ ] T013 [US1] Backend tests:
  - listed before classification finishes;
  - no coordinator wake while screening;
  - pass → title, body and understanding card;
  - suspect → quarantine on the same request;
  - release continues it, discard ends it;
  - an interrupted screening is redone;
  - no content before screening.
- [ ] T014 [US1] Update the existing ingestion tests to the new flow

## Phase 4: Polish

- [ ] T015 [P] Feed wording for `screening.passed` / `screening.quarantined` (personas.ts); board-api.md card kind; architecture.md intake section; the spec 012 US1 note
- [ ] T016 Full gate: `task quality`, backend and frontend tests, prettier, build; a reproduction run against the fake slow LLM; commit, push, and close #67/#68
