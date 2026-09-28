# Implementation Plan: CAB-2 estimates, coding/manual split, and executive summary

**Branch**: `work` | **Date**: 2026-09-28 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/030-cab2-estimates-summary/spec.md`

## Summary

The pm's `<DECOMPOSITION>` gains a per-task `classification` (coding/manual)
and executive-summary prose. Once it is validated, decomposition routing no
longer opens CAB-2 directly. It creates an `estimation` card for `developer`,
which returns `<ESTIMATES>`: size, confidence, man-hours, agent tokens, review
hours, risks and rationale per task. When the estimates are valid, code merges
candidate and estimates into a `cab2_proposal` artifact (the gate target and
the structured estimate record). It then opens the existing
`decomposition_gate` titled with the coding/manual split, and attaches a
code-rendered Markdown executive summary to the gate card. After approval,
publishing adds an estimate section to every sub-task and marks manual ones
with a new sentinel, which ingestion refuses to turn into workflows.
Separately, the board snapshot gains `task_body`, and the cockpit rail opens
it through a direct-content mode of `ArtifactDialog`.

## Technical Context

**Language/Version**: Python 3.13 (backend), TypeScript / Vue 3 (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy 2, Pydantic; Vue 3, Vuetify 4 (no new dependencies)

**Storage**: SQLite; **no migration**. Card kind is a text column, and the new data is artifact content (research R1).

**Testing**: pytest (backend), vitest (frontend), `task quality`

**Target Platform**: single-user local web app (loopback)

**Project Type**: web application (backend + frontend)

**Performance Goals**: n/a. One extra specialist turn per decomposed request, which is inherent to the chosen design.

**Constraints**: the structural limits in AGENTS.md (branches ≤ 12, module ≤ 500 lines, JS function ≤ 60 lines, jscpd ≤ 3%). `_route_result` is at its branch budget (R9).

**Scale/Scope**: decompositions of 1 to about 15 tasks.

## Constitution Check

| Principle | Assessment |
| --- | --- |
| I. Contract fidelity | `task_body` is added to `BoardSnapshotOut` and `BoardSnapshot` in one commit; the board-api contract doc is amended. No other DTO changes (R3 avoids exposing `target_artifact_id`). **Pass** |
| II. Layered, backend-owned | Validation, totals, the manual guard and gate creation are all backend. The frontend only displays. No DDL. **Pass** |
| III. Test-first | Every scenario in quickstart.md gets a test before or with its code. The fake backends and the fixture task source are used, never a real `claude`. **Pass** |
| IV. Simplicity | No new table, dependency, gate kind, specialist role or setting. One new card kind and one new marker, both required by the spec. Complexity tracking is below. **Pass** |
| V. Kit-aligned | Vuetify components only (`v-alert`, `v-btn`, existing dialog). Colours come from theme names. **Pass** |

Access-model constraint (cleanup): manual sub-tasks are still recorded in
`child_task_link`, so reset/cleanup continues to own everything Kestrel
publishes. **Pass**

Post-design re-check: the same results. The design adds no endpoint and no
write path to a task source beyond the existing `create_subtask`.

## Project Structure

### Documentation (this feature)

```text
specs/030-cab2-estimates-summary/
├── spec.md
├── plan.md              # this file
├── research.md          # R1–R12
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── decomposition-output.md
│   ├── estimation-output.md
│   └── board-api-delta.md
└── tasks.md             # /speckit-tasks
```

### Source Code (touched or added)

```text
backend/
├── app/
│   ├── markers.py                          # + ManualTaskSentinel
│   ├── models_board.py                     # + CardKind.ESTIMATION; Workflow.task_body doc unchanged
│   ├── schemas.py                          # + BoardSnapshotOut.task_body
│   ├── routers/board_views.py              # fill task_body
│   ├── services/ingestion.py               # skip manual-marked bodies
│   ├── services/task_source_utils.py       # + has_manual_sentinel
│   └── services/board/
│       ├── decomposition.py                # strict/lenient parse, route → estimation card, publish w/ estimate + marker
│       ├── candidate.py                    # NEW: ClassifiedTask/Candidate model + strict/lenient parsing (keeps decomposition.py < 500)
│       ├── estimation.py                   # NEW: <ESTIMATES> parse/validate, route → proposal + gate + summary
│       ├── exec_summary.py                 # NEW: pure totals + Markdown renderer
│       ├── dispatch_ready.py               # routing table (R9); estimation extra context
│       ├── coordinator.py                  # estimation not coordinator-creatable (R8)
│       └── phases.py                       # ESTIMATION → Technical analysis
├── specialists/
│   ├── pm/prompt.md                        # classification + summary instructions
│   ├── developer/prompt.md                 # "On an estimation card…"
│   ├── developer/manifest.toml             # allowed_card_types += estimation
│   └── README.md                           # card-kind vocabulary
└── tests/                                  # test_board_decomposition.py, new test_board_estimation.py,
                                            # test_board_exec_summary.py, ingestion/coordinator/API tests

frontend/src/
├── types/workflows.ts                      # + BoardSnapshot.task_body
├── lib/artifacts.ts                        # request slot = direct content; exec_summary ← decomposition_gate; analysis += estimation
├── components/cockpit/ArtifactDialog.vue   # direct-content mode (note, no trust chip, no fetch)
├── components/cockpit/ArtifactRail.vue     # pass taskBody through
├── components/cockpit/ActionBanner.vue     # "Read executive summary" on CAB-2 ask
└── views/RequestCockpitView.vue            # pass snapshot.task_body

specs/026-autonomous-work-board/contracts/board-api.md   # amended (Principle I)
```

**Structure Decision**: existing web-app layout. There are three new backend
modules (`candidate.py`, `estimation.py`, `exec_summary.py`), because
`decomposition.py` would otherwise pass the 500-line module limit, and because
the summary renderer is pure and deserves its own tests.

## Complexity Tracking

| Addition | Why needed | Simpler alternative rejected because |
| --- | --- | --- |
| New `estimation` card kind + one extra agent turn | Developer decision: the estimator must be separate from the scoping pm | Estimates in the pm's own output: explicitly declined by the developer |
| Strict and lenient parse modes | Gates opened before this feature must still publish (FR-019); new output must never default to agent-eligible (#51) | One lenient parser silently makes unclassified tasks agent-eligible |
| `_route_result` → routing table | Adding an `elif` exceeds the branch limit; suppressions are forbidden | none that is compliant |
