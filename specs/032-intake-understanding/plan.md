# Implementation Plan: Visible screening and a real understanding step

**Branch**: `work` | **Date**: 2026-09-29 | **Spec**: [spec.md](spec.md)

## Summary

Ingestion creates the request first, with a "Screening input…" card, and
classifies afterwards, quarantining in place when the input is unsafe
(research R1–R5). After screening passes, or after a release, a `pm`
`understanding` card writes a restatement. The understanding gate opens only
once that restatement exists and targets it, and the cockpit shows it inline.
A rejection requires a correction and triggers a redraft, capped by a new
`board_understanding_redraft_cap` setting (R6–R8).

## Technical Context

**Language/Version**: Python 3.13, TypeScript / Vue 3

**Primary Dependencies**: FastAPI, SQLAlchemy 2, Vuetify 4. No new dependencies.

**Storage**: no migration. The new card kind is a text value, the restatement is an artifact, and `BoardStore.record_intake` updates existing columns.

**Testing**: pytest, vitest, `task quality`

**Constraints**: AGENTS.md structural limits. `gates.py`, `routers/board.py` and `dispatch_ready.py` are near 500 lines, so new logic goes into `understanding.py` and `intake.py`.

## Constitution Check

| Principle | Assessment |
| --- | --- |
| I. Contract fidelity | No DTO shape change. A new card kind (`understanding`), noted in board-api.md. **Pass** |
| II. Backend-owned | Screening, redraft and cap logic are service-layer. The frontend only displays and requires the correction text. **Pass** |
| III. Test-first | Every acceptance scenario gets a test. **Pass** |
| IV. Simplicity | One card kind and one setting, both required by the spec. No new tables. **Pass** |
| V. Kit-aligned | Vuetify only. **Pass** |

Access model: unscreened content is never stored on the request or shown
(FR-002); the title stays the ticket ref until screening passes. **Pass**

## Source changes

```text
backend/app/
├── config.py                          # + board_understanding_redraft_cap
├── models_board.py                    # + CardKind.UNDERSTANDING
├── persistence/board_store.py         # + record_intake(workflow_id, title, body)
├── services/ingestion.py              # create first, screen, continue_intake, re-screen
├── services/board/
│   ├── intake.py                      # NEW: screening card + finish/settle helpers
│   ├── understanding.py               # NEW: route result → gate; redraft; context
│   ├── service.py                     # + create_screening_workflow, settle_screening
│   ├── gates.py                       # rejection hook → understanding redraft
│   ├── coordinator.py                 # UNDERSTANDING code-only
│   ├── phases.py                      # UNDERSTANDING → "Understanding"
│   ├── dispatch_ready.py              # route + extra context for understanding
│   ├── bootstrap.py                   # wire cap; schedule_intake_continuation
│   └── dev_reset.py                   # rerun → fresh understanding card
├── routers/board.py                   # release → schedule continuation
backend/specialists/pm/{prompt.md,manifest.toml}, README.md
frontend/src/components/cockpit/ActionBanner.vue   # inline restatement
frontend/src/lib/asks.ts                           # rejection feedback for understanding
frontend/src/lib/personas.ts                       # screening/understanding event wording
config.toml.example, docs/architecture.md, board-api.md
```

## Complexity Tracking

| Addition | Why needed | Simpler alternative rejected because |
| --- | --- | --- |
| A mutation-free workflow creation path | An unscreened request must not wake the coordinator (R1) | Creating through the normal path triggers an LLM turn over empty content. |
| `settle_screening` bypassing the transition policy | The screening card is a system card that never passes through `review` (R3) | Two policy transitions mean two wakes and a fake "review" state. |
