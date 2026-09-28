# Phase 1 Data Model: Bounded interview rounds and coordinator-routed PRD redrafts

No new tables and no schema migration (see research.md's "round number
is derived, not stored" decision). This feature adds two configuration
values and two small, purely-computed views over existing rows.

## Configuration (new)

Both follow the existing `board_cab1_interview_max_questions` pattern
(`app/config.py`'s `Settings`, `KESTREL_` env prefix; threaded through
`GateRequirements` → `GatesService` in `bootstrap.py`).

| Field | Type | Default | Meaning |
|---|---|---|---|
| `board_refinement_round_cap` | `int` (`ge=1`) | `1` | Max interview rounds per persona per workflow. `1` = today's exact behavior (FR-014). |
| `board_prd_redraft_cap` | `int` (`ge=1`) | `1` | Max PRD redrafts per workflow after the original draft. `1` = exactly one redraft on first rejection, matching today's per-rejection behavior; a *second* consecutive rejection now escalates instead of looping (this is the bug #49 exists to fix). |

## Derived view: persona round state

Not a stored entity — a read-time computation over existing `WorkCard`
rows, used by `GatesService` (round-advance decision) and
`dispatch_ready.py` (envelope round-N/M text).

For one `(workflow_id, persona)` pair:

- **round_cards**: every `WorkCard` in the workflow with
  `kind in (REFINEMENT, REFINEMENT_GATE)` and `persona in
  eligible_roles`, ordered by creation time.
- **current_round**: count of `REFINEMENT`-kind cards in `round_cards`
  (1-indexed — the first `REFINEMENT` card created for a persona *is*
  round 1).
- **satisfied**: `true` if any `REFINEMENT`-kind card in `round_cards`
  produced a `"satisfied": true` question payload with no gate (see
  research.md); tracked via that card's direct transition to `DONE`
  with no corresponding `REFINEMENT_GATE`.
- **pending**: `true` if `round_cards`'s most-recently-created card is
  not in a terminal state (`DONE`/`FAILED`/`CANCELLED`) — i.e. this
  persona's interview is still in progress and PRD drafting must wait.

## Derived view: PRD redraft state

For one `workflow_id`:

- **prd_gate_cards**: every `WorkCard` in the workflow with
  `kind == PRD_GATE`, ordered by creation time.
- **redrafts_so_far**: `len(prd_gate_cards) - 1` (the first is the
  original draft, never a redraft).
- **cap_reached**: `redrafts_so_far >= board_prd_redraft_cap` at the
  moment the *latest* `prd_gate_cards` entry is rejected.

## New card-creation shapes (no new `CardKind` values)

- A `REFINEMENT` card created by `CoordinatorService.apply_actions`
  (the "send back to the interview" redraft-triage outcome) is
  structurally identical to one created by `GatesService` — same
  `CardKind.REFINEMENT`, `eligible_roles=(persona,)` — so it is counted
  by the derived view above with no special case.
- A `coordinator_review` card created by the PRD-redraft router carries
  one new reference artifact, logical name `"context"`, holding the
  rejection feedback and the rejected PRD's own content — read by
  `build_coordinator_envelope` (see research.md's last decision).

## State transitions (delta from existing data-model.md, spec 026)

- `REFINEMENT` card: existing transitions unchanged
  (`READY → CLAIMED → REVIEW → DONE`, or `→ FAILED`/`CANCELLED`), except
  it may now also go `CLAIMED → DONE` directly (via the "satisfied, no
  questions" path — no `REVIEW` step, since there is nothing for the
  board's ordinary artifact-acceptance flow to hold; this mirrors how a
  gate card itself already skips straight to `DONE`/`CANCELLED` on
  operator decision without a `REVIEW` state).
- `REFINEMENT_GATE` card resolution (`resolve()`) may now, as a
  consequence rather than a new state, cause a *new* `REFINEMENT` card
  to be created for the same persona (existing "gate resolution creates
  a follow-up card" shape, same as `_maybe_start_prd` already does).
- `PRD_GATE` rejection no longer directly creates a `PRD` card; it
  creates a `COORDINATOR_REVIEW` card instead (existing `CardKind`,
  new caller).
