# Implementation Plan: Bounded interview rounds and coordinator-routed PRD redrafts

**Branch**: `028-refinement-rounds-cap` (working on `work`, no dedicated
feature branch — consistent with this session's other board-redesign
commits, which all land directly on `work`)

**Date**: 2026-09-28

**Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/028-refinement-rounds-cap/spec.md`

## Summary

Two changes to `backend/app/services/board/`:

1. **Multi-round interviews (#48)**: a persona's refinement interview may
   run more than one round, up to a configured cap, with an explicit
   "satisfied" exit signal so a persona doesn't consume rounds it doesn't
   need. Round number/remaining-rounds are injected into the specialist
   prompt. Round number is *derived* (counted from existing cards), not a
   new stored field, so it works identically whether a round is created
   by `GatesService` (normal flow) or by the coordinator (the
   reinterview path from #49).

2. **Coordinator-routed PRD redraft with a cap (#49)**: a `prd_gate`
   rejection no longer deterministically creates a new `prd` card.
   Instead it routes through `CoordinatorService`, reusing the exact
   bounded-retry-then-escalate pattern `ci_poll.py`'s CI-repair loop
   already uses: while under the redraft cap, create a
   `coordinator_review` card carrying the rejection feedback for the
   coordinator's next (automatically triggered) wake-up turn to judge;
   once the cap is reached, escalate with a final `coordinator_review`
   card instead, surfacing the failure to the operator.

## Technical Context

**Language/Version**: Python 3.13 (existing backend)

**Primary Dependencies**: FastAPI, SQLAlchemy (existing; no new deps)

**Storage**: Existing SQLite/Postgres board tables via `BoardStore`. No
schema migration — round/redraft counts are derived by counting existing
`WorkCard` rows, matching how `_maybe_start_prd` already counts
`refinement_gate` cards today.

**Testing**: pytest (existing `backend/tests/test_board_*.py` suite)

**Target Platform**: Linux server (existing backend deployment)

**Project Type**: Existing web service (FastAPI backend + Vue frontend);
this feature is backend-only, no frontend change (per spec Assumptions,
UI surfacing is explicitly out of scope, tracked separately)

**Performance Goals**: N/A — synchronous, low-volume board-state
transitions; no new performance-sensitive path

**Constraints**: Must preserve exact current behavior when both new caps
are at their minimum configured value (FR-014); must not add a DB
migration (derives counts from existing rows, mirroring
`_maybe_start_prd`'s existing "count cards of a kind" pattern)

**Scale/Scope**: Backend service-layer change across 4 existing modules
(`gates.py`, `refinement.py`, `dispatch.py`, `bootstrap.py`/`config.py`),
no new modules

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Principle I (type-mirror / recorded deviations)**: No new frontend
  type is introduced (backend-only feature); no constitution deviation
  needed.
- **Layering (import-linter)**: `GatesService` gains a `CoordinatorService`
  dependency. Direction is safe: `coordinator.py` does not import
  `gates.py` (verified — its own imports are `policy.py`/`service.py`
  only), so `gates.py -> coordinator.py` introduces no cycle.
  `refinement.py` already imports both today.
- **Code-quality guardrails** (AGENTS.md): new logic must stay within
  the existing per-function limits (complexity ≤10, ≤40 statements,
  ≤5 args, etc.) — the design below deliberately splits "should this
  persona get another round" and "route a PRD rejection" into small
  private helpers on `GatesService`, mirroring the existing
  `_maybe_*` method-per-concern style, rather than growing `resolve()`
  itself.
- **No new exemptions**: no grandfather-list or threshold edits
  anticipated.

Gate: **PASS**, no violations to justify in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/028-refinement-rounds-cap/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
└── tasks.md              # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── config.py                       # + board_refinement_round_cap,
│   │                                    #   board_prd_redraft_cap
│   ├── services/board/
│   │   ├── gates.py                     # round-aware refinement flow,
│   │   │                                #   coordinator-routed redraft
│   │   ├── refinement.py                # "satisfied" exit-signal parsing
│   │   ├── dispatch.py                  # round N/M envelope context,
│   │   │                                #   coordinator sees review
│   │   │                                #   card context
│   │   └── bootstrap.py                 # wire new settings + a
│   │                                    #   CoordinatorService dep into
│   │                                    #   GatesService, artifacts into
│   │                                    #   SchedulingService
│   └── ...
└── tests/
    ├── test_board_gates_prd.py          # extend TestPrdRedraft
    ├── test_board_gates.py              # round-cap unit tests
    ├── test_board_refinement.py         # satisfied-signal parsing tests
    ├── test_board_envelopes.py          # round N/M envelope assertions
    └── test_board_refinement_e2e.py     # multi-round + redraft e2e
```

**Structure Decision**: No new modules. All changes land in the four
existing `backend/app/services/board/` files already responsible for
this domain, following this repo's existing pattern of extending a
service with a new private `_maybe_*` method rather than introducing a
new layer.

## Complexity Tracking

*No Constitution Check violations — table intentionally omitted.*
