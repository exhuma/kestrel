# Implementation Plan: CAB-1 Strategic Fit Gate

**Branch**: `work` (this repo does not use per-feature branches; see
`docs/development.md`) | **Date**: 2026-09-28 | **Spec**:
[spec.md](./spec.md)

**Input**: Feature specification from `/specs/027-cab1-strategic-gate/spec.md`

## Summary

Insert one new pure-human gate (`cab1_gate`) between the existing
`understanding_gate` and `refinement` steps, preceded by a new, bounded,
requester-facing `strategic_interview`/`strategic_interview_gate` pair.
Both are implemented as one more deterministic, config-gated trigger in
`GatesService`, following the exact pattern `board_prd_gate_required` and
`board_decomposition_required` already establish — no new mechanism, no new
router endpoint (the existing generic `/interventions` route resolves the
new gate kinds the same way it resolves every other kind), no new database
table.

## Technical Context

**Language/Version**: Python 3.12 (backend), matches the rest of `backend/`

**Primary Dependencies**: FastAPI, SQLAlchemy 2.x, Pydantic — no new
dependency introduced

**Storage**: SQLite via SQLAlchemy/Alembic, existing `board_work_card` /
`board_human_gate` tables — no schema migration needed (new `CardKind`
values are just new strings in an existing closed-vocabulary column, the
same way `prd_gate`/`decomposition_gate` needed none)

**Testing**: pytest (backend) — an end-to-end test mirroring
`tests/test_board_refinement_e2e.py`, plus unit tests for the new
`GatesService` trigger methods, plus a `config.py` bounds test

**Target Platform**: Linux server (existing backend), unchanged

**Project Type**: Web application (FastAPI backend + Vue/Vuetify frontend,
existing structure) — this feature is backend-only; no frontend change is
required (the existing generic board/graph views already render any card
kind by title/state, see `research.md`)

**Performance Goals**: N/A — no new hot path; same order-of-magnitude gate
count per workflow as the existing PRD/decomposition gates

**Constraints**: Must not change behavior when `board_cab1_gate_required`
is left at its default `False` (SC-005) — verified by a dedicated
regression test, not just by construction

**Scale/Scope**: Single-user, personal-scale (Principle IV) — same as the
rest of the board domain

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Contract Fidelity**: No frontend/backend type-contract change — this
  feature adds no new API shape; the existing `BoardInterventionIn`/gate
  response types already cover an arbitrary gate kind generically. PASS.
- **II. Layered, Backend-Owned Architecture**: All new logic lives in
  `app/services/board/gates.py` (services layer) and a new parser/router
  function in `app/services/board/refinement.py`-adjacent code; no raw SQL,
  no schema owned outside Alembic (none needed). PASS.
- **III. Test-First Discipline**: Plan requires the e2e + unit tests
  described in `quickstart.md` before/alongside implementation; the
  SC-005 backward-compatibility claim is itself covered by a test, not
  left to inspection. PASS (to be enforced at task-authoring/implementation
  time).
- **IV. Deliberate Simplicity & Single-User Scope**: No new specialist
  persona (reuses `requester`), no new database table, no new dependency,
  no new router endpoint — the smallest change that satisfies the spec's
  functional requirements, and reuses three already-established patterns
  (`_maybe_require_refinement`, `_maybe_require_decomposition`,
  `_decomposition_trigger_kind`) rather than inventing a fourth. PASS.
- **V. Kit-Aligned Consistency & Observability**: No UI styling change (no
  frontend change at all). `resolve_kits` will be re-run at
  `/speckit-tasks`/implementation time per this session's task, per
  `AGENTS.md`. PASS (pending, not a design-time gate).

No violations to record in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/027-cab1-strategic-gate/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
└── tasks.md              # Phase 2 output (/speckit-tasks, not yet run)
```

No `contracts/` directory: this feature exposes no new external interface.
The one relevant surface — resolving a gate — is the existing generic
`POST /api/board/workflows/{workflow_id}/cards/{card_id}/interventions`
route (`backend/app/routers/board.py`), already documented in
`specs/026-autonomous-work-board`'s own `contracts/` and unchanged by this
feature (it dispatches by the card's *state*, not a hardcoded kind list).

### Source Code (repository root)

```text
backend/
├── app/
│   ├── config.py                          # + board_cab1_gate_required,
│   │                                       #   board_cab1_interview_max_questions
│   ├── models_board.py                    # + CardKind.STRATEGIC_INTERVIEW,
│   │                                       #   .STRATEGIC_INTERVIEW_GATE, .CAB1_GATE
│   └── services/board/
│       ├── gates.py                       # + GateRequirements.cab1,
│       │                                   #   _refinement_trigger_kind(),
│       │                                   #   _maybe_require_cab1_interview(),
│       │                                   #   _maybe_require_cab1_decision()
│       ├── bootstrap.py                   # get_gates_service(): + cab1=...
│       └── refinement.py                  # + route_strategic_interview_result()
│                                           #   (question-cap enforced here)
├── specialists/requester/manifest.toml    # allowed_card_types += "strategic_interview"
└── tests/
    ├── test_board_cab1_e2e.py             # new (mirrors test_board_refinement_e2e.py)
    ├── test_board_gates.py / _prd.py      # + unit tests for the new triggers
    └── test_config.py (or equivalent)     # + bounds test for the new int field

config.toml.example                        # + documented example for both new flags
```

No `frontend/` changes (see Technical Context / research.md).

**Structure Decision**: Existing `backend/app/services/board/` layout, no
new modules — extends `gates.py` and `refinement.py` in place, matching
where `prd_gate`/`decomposition_gate` logic already lives, per Principle IV
(no new abstraction where extending an existing, actively-used one is
sufficient).

## Complexity Tracking

*No violations — table intentionally omitted.*
