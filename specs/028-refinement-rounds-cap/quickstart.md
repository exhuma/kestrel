# Quickstart: validating bounded interview rounds and coordinator-routed PRD redrafts

## Prerequisites

- `cd backend && uv sync` (existing dev setup)
- No migration to run — this feature adds no tables/columns.

## Config

Both new settings have safe defaults (`1`, matching today's behavior).
To exercise multi-round/multi-redraft behavior locally:

```
KESTREL_BOARD_REFINEMENT_ROUND_CAP=3
KESTREL_BOARD_PRD_REDRAFT_CAP=2
KESTREL_BOARD_PRD_GATE_REQUIRED=true   # refinement/PRD flow must be on
```

## Automated validation (primary)

```
cd backend
uv run pytest tests/test_board_gates_prd.py tests/test_board_gates.py \
  tests/test_board_refinement.py tests/test_board_envelopes.py \
  tests/test_board_refinement_e2e.py -q
```

Key scenarios exercised (see spec.md's Acceptance Scenarios for the
full list):

1. A persona whose first-round answer is satisfactory proceeds straight
   to PRD drafting after round 1 (unchanged today-behavior case).
2. A persona that signals `"satisfied": false` gets a second
   `refinement` card; its envelope contains round-number/cap text and
   its own prior round's Q&A.
3. A persona pinned at the round cap is told, in its envelope, to
   consolidate rather than ask further questions.
4. A `prd_gate` rejection under the redraft cap creates a
   `coordinator_review` card (not a `prd` card directly); a subsequent
   coordinator turn's `CreateCardAction` determines whether a `prd`
   redraft or a fresh `refinement` round follows.
5. A `prd_gate` rejection at the redraft cap creates a final
   `coordinator_review` escalation card and no further `prd` card.

## Manual smoke test (optional, since a full click-through isn't
required for this task)

1. Start the backend (`task backend`) with the env vars above.
2. Ingest a deliberately vague fixture task (`board_prd_gate_required`
   and `board_cab1_gate_required` off, so refinement starts right after
   `understanding_gate`).
3. Answer round 1's questions ambiguously; confirm round 2 is created
   for at least one persona, and its card's envelope (visible via
   `GET /api/board/cards/{id}` or the event log) mentions "round 2 of
   3".
4. Reject the resulting PRD with clear correction feedback; confirm a
   `coordinator_review` card appears rather than an immediate new `prd`
   card, and that it resolves (on the next scheduling pass) into either
   a PRD redraft or a fresh interview round.
