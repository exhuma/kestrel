# Phase 1 Data Model: CAB-1 Strategic Fit Gate

No new database tables or SQLAlchemy models are introduced. This feature
adds three closed-vocabulary enum values and two config fields to existing
entities; every row still lives in the existing `board_work_card` /
`board_human_gate` tables (`backend/app/persistence/board_tables.py`).

## New `CardKind` values (`backend/app/models_board.py`)

| Value | Claimed by | Created by | Purpose |
|---|---|---|---|
| `strategic_interview` | `requester` specialist | `GatesService._maybe_require_cab1_interview`, deterministically on `understanding_gate` approval, only when CAB-1 is required | Drafts a bounded set of plain-language, strategy-focused questions for the original requester. Mirrors `refinement`. |
| `strategic_interview_gate` | Human (the requester) | `route_strategic_interview_result` (new, mirrors `route_refinement_result` in `services/board/refinement.py`), once the `strategic_interview` card's questions are parsed | Holds the requester's free-text answer. `requested_decision="answer"`, resolved via the existing `answer`-bearing gate-resolution path (`GatesService.resolve(..., answer=...)`). Mirrors `refinement_gate`. |
| `cab1_gate` | Human (the CAB-1 reviewer) | `GatesService._maybe_require_cab1_decision` (new), deterministically once `strategic_interview_gate` is approved | Pure approve/reject strategic-fit decision. `requested_decision="approve_strategic_fit"`. No target artifact, no answer payload — mirrors `understanding_gate`/`decomposition_gate`, not `prd_gate`. |

No new `CardState` values — all three use the existing universal state
machine (`ready` → `claimed`/`awaiting_human` → terminal).

## New config fields (`backend/app/config.py`, alongside `board_prd_gate_required`)

| Field | Type | Default | Purpose |
|---|---|---|---|
| `board_cab1_gate_required` | `bool` | `False` | Enables the whole CAB-1 sequence (strategic interview + gate). Off by default (FR-005, SC-005) — identical posture to `board_decomposition_required`/`board_prd_gate_required`. |
| `board_cab1_interview_max_questions` | `int` (`gt=0`) | `3` | The strategic interview's hard question cap (FR-003, SC-003), enforced where its `<REFINEMENT_QUESTIONS>`-style tag is parsed. |

Both are documented in `config.toml.example` next to the existing gate
flags, following the same comment style.

## `GateRequirements` (`backend/app/services/board/gates.py`)

Gains one field: `cab1: bool = False`, constructed from
`board_cab1_gate_required` in `services/board/bootstrap.py::get_gates_service`
exactly like `decomposition`/`prd` already are.

## Sequencing change: refinement's trigger kind becomes conditional on CAB-1

`GatesService` already has `_decomposition_trigger_kind()`, which returns
`prd_gate` when PRD is required, else `understanding_gate`. This feature
adds the analogous `_refinement_trigger_kind()`:

```text
_refinement_trigger_kind() -> str:
    return CardKind.CAB1_GATE if self._required.cab1 else CardKind.UNDERSTANDING_GATE
```

`_maybe_require_refinement`'s guard changes from a literal
`understanding_gate.kind != CardKind.UNDERSTANDING_GATE.value` check to
`resolved_gate.kind != self._refinement_trigger_kind()`, matching the
existing decomposition-trigger pattern exactly. When CAB-1 is disabled
(default), `_refinement_trigger_kind()` returns `understanding_gate` and
behavior is byte-for-byte unchanged (SC-005).

## New deterministic triggers on `GatesService.resolve`'s approval path

Two new private methods, called from the same `if decision == "approved":`
block in `resolve()` that already calls
`_maybe_require_refinement`/`_maybe_require_decomposition`/`_maybe_approve_prd`:

- `_maybe_require_cab1_interview(understanding_gate)`: no-op unless
  `required.cab1` and `understanding_gate.kind == UNDERSTANDING_GATE`
  (and not `workflow.skip_decomposition`, matching the existing subtask
  exemption `_maybe_require_refinement` already applies). Creates one
  `strategic_interview` card, `eligible_roles=("requester",)`.
- `_maybe_require_cab1_decision(strategic_interview_gate)`: no-op unless
  `strategic_interview_gate.kind == STRATEGIC_INTERVIEW_GATE`. Creates one
  `cab1_gate` card, `state=AWAITING_HUMAN` (created directly awaiting a
  human decision — it has no specialist work to do first, unlike
  `understanding_gate`/`decomposition_gate`/`prd_gate` which are all also
  created directly `awaiting_human`; consistent with that group). The
  `HumanGateRecord` is created alongside it via `create_gate`, the same
  call every other gate already uses — this is the same call shape the
  intake-gate fix (GitHub #42) generalized in `IngestionService`.

## Sequencing summary (CAB-1 enabled)

```text
ingest -> understanding_gate (approve)
       -> strategic_interview (requester persona drafts ≤N questions)
       -> strategic_interview_gate (human/requester answers)
       -> cab1_gate (human/CAB-1 reviewer approves or rejects)
       -> [approved] refinement (existing requester/pm/uiux persona cards, unchanged)
       -> [rejected] nothing further; only cards depending on cab1_gate
          (none, by construction — refinement is not created until this
          gate approves) are invalidated; the workflow's prior history
          stays intact (FR-007, SC-004)
```

With CAB-1 disabled (default): unchanged existing sequence,
`understanding_gate (approve) -> refinement` directly.

## Specialist roster change

`backend/specialists/requester/manifest.toml`'s `allowed_card_types` gains
`"strategic_interview"` alongside its existing `["analysis", "refinement"]`.
No other specialist manifest changes; no new specialist directory (see
`research.md` — reuses the existing `requester` persona).
