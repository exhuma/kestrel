# Phase 0 Research: CAB-1 Strategic Fit Gate

## Decision: Mirror the existing optional-gate pattern exactly

**Decision**: Implement CAB-1 as two new deterministic steps inserted
between `understanding_gate` and the existing `refinement`/`refinement_gate`
pair, using the exact same mechanism already used for
`board_prd_gate_required` / `board_decomposition_required`
(`backend/app/services/board/gates.py`):

1. `strategic_interview` (analogous to `refinement`) — a single card, one
   specialist role (`requester`), created deterministically right after
   `understanding_gate` approval when CAB-1 is enabled.
2. `strategic_interview_gate` (analogous to `refinement_gate`) — created
   once the `requester` persona drafts its bounded question set; resolved
   by a human (the original requester) with a free-text answer, the same
   `answer`-decision path `refinement_gate` already uses.
3. `cab1_gate` — created deterministically once `strategic_interview_gate`
   is approved; a pure approve/reject human decision with no answer
   payload (mirrors `understanding_gate`/`decomposition_gate`, not
   `prd_gate`'s redraft-on-reject path — see spec Assumptions).
4. The existing `_maybe_require_refinement` trigger (currently fixed to
   `understanding_gate`) becomes conditional the same way
   `_decomposition_trigger_kind` already is: `cab1_gate` when CAB-1 is
   required, else `understanding_gate` unchanged (backward compatible,
   satisfies SC-005).

**Rationale**: `GatesService` already has this exact deterministic-trigger
pattern for two other optional gates (`_maybe_require_decomposition`,
`_maybe_require_refinement`, `_decomposition_trigger_kind`). Reusing it
keeps CAB-1 consistent with Principle IV (deliberate simplicity — no new
mechanism where an existing one fits) and satisfies the GitHub issue's own
instruction to follow the `board_prd_gate_required` pattern.

**Alternatives considered**:
- A single combined `cab1_gate` card that both asks the requester's
  questions and records the reviewer's decision — rejected: conflates two
  different actors (the requester answering vs. the CAB-1 reviewer
  deciding) into one gate, and the spec (User Story 2) requires the
  reviewer to see the requester's answer *before* deciding, which needs two
  separate records for the same reason `refinement_gate` and `prd_gate` are
  already separate steps in the existing flow.
- Routing the CAB-1 question-drafting through the coordinator's own
  judgment instead of a deterministic trigger — rejected: this codebase's
  established rule (see `_required` field's docstring in `gates.py`) is
  that a hard guarantee needs a hard trigger, not an LLM's initiative;
  CAB-1 is exactly this kind of hard guarantee (FR-006).

## Decision: Reuse the `requester` specialist persona, not a new one

**Decision**: The `strategic_interview` card's `eligible_roles` is
`("requester",)` — the same persona already used in post-approval
refinement (`backend/specialists/requester/prompt.md`), not a new
specialist definition.

**Rationale**: That persona's existing prompt is already scoped to
"interviewing PRODUCT (the business stakeholder)" in "the plainest, least
technical language possible" — precisely what FR-003 requires. Adding a
second, near-duplicate persona would violate Principle IV (YAGNI) for no
behavioral gain. The card-kind distinction (`strategic_interview` vs.
`refinement`) is what keeps the two interviews structurally separate
(FR-002), not persona duplication.

**Alternatives considered**: A dedicated `cab1-interviewer` persona —
rejected as unjustified duplication; the existing `requester` persona's
prompt already matches the tone/audience this step needs.

## Decision: Question cap is a new config value, not a hardcoded constant

**Decision**: Add `board_cab1_interview_max_questions: int = Field(default=3,
gt=0)` alongside `board_prd_gate_required` in `backend/app/config.py`, and
enforce it in the same place the existing `<REFINEMENT_QUESTIONS>` tag is
parsed (`backend/app/services/board/refinement.py`) for the new
`strategic_interview` route.

**Rationale**: SC-003 requires "never exceeds its configured cap" —
"configured" implies an operator-visible setting, consistent with every
other gate-related knob already living in `config.toml.example` alongside
`board_prd_gate_required`/`board_decomposition_required`.

**Alternatives considered**: A fixed constant (e.g. always 3) — rejected
only because the spec's own wording ("configured cap") calls for an
operator-tunable value; the other gate flags are all configurable for the
same reason.

## Decision: CAB-1 rejection is terminal (no redraft loop)

**Decision**: `cab1_gate` rejection uses the existing generic rejection
path (`_invalidate_dependents`) with no analogue to `_maybe_redraft_prd`.

**Rationale**: Recorded explicitly in the spec's Assumptions after
reviewing every existing gate's rejection behavior:
`understanding_gate`/`decomposition_gate` rejections are already terminal
today (no redraft card is created); only `prd_gate` redrafts, because a PRD
is an iterative document. A strategic go/no-go is not iterative in the same
sense — GitHub #47 describes it as "a pure human decision," not a draft to
be revised. No existing code needs to change to support this; it is what
happens by simply not adding a `_maybe_redraft_cab1` method.

## Investigated and found not to exist yet: the "derived phase table"

GitHub #47 asks to "slot into the derived phase table (phase 3, stage
Discovery) used by the visualisation epic." Searched the full backend and
frontend for `Discovery`, any phase-table/stage-mapping module, and any
frontend code that maps `CardKind` to a phase: none exists yet, anywhere.
`frontend/src/lib/boardGraph.ts` and `frontend/src/types/workflows.ts`
render the board graph generically by card title/state/relation kind, with
no kind-to-phase concept at all — confirmed no `CardKind`-aware frontend
code exists currently.

**Conclusion**: that bullet describes forward-looking integration with the
separate read-surface/visualization workstream (Vikunja 698, GitHub
`#43→#46→#55→#56→#44`), which has not landed. There is nothing to "slot
into" yet. FR-009 ("visible in the same status/progress view used for its
other review stages") is satisfiable today by the existing generic
graph/board view alone — the same way `prd_gate`/`decomposition_gate` are
already visible with no phase-specific code. No phase-table work is part of
this feature; a follow-up note is left in `tasks.md` rather than blocking
here.

## Existing dispatch mechanics reused as-is (no research needed)

- `GatesService.create_gate`/`resolve`, `BoardService.transition_card`,
  `InterventionsService.apply`, `_invalidate_dependents`: all already
  generic across gate kinds; no changes needed beyond passing the two new
  `CardKind` values through.
- `dispatch_ready_work` / claim mechanics (`services/board/claims.py`,
  `dispatch_ready.py`): already route any `eligible_roles`-restricted,
  `ready`-state card to the right specialist backend regardless of kind;
  the new `strategic_interview` card needs no new dispatch code, only a
  parser/router function analogous to `route_refinement_result`
  (`services/board/refinement.py`) and a roster entry allowing `requester`
  to claim `strategic_interview` cards
  (`backend/specialists/requester/` — add `strategic_interview` to its
  `allowed_card_types`, mirroring how it already lists `refinement`).
