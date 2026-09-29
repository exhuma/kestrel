# Implementation Plan: Sub-tasks as cards inside the parent workflow

**Branch**: `work` | **Date**: 2026-09-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/031-subtask-cards/spec.md`

## Summary

Approving CAB-2 stops publishing child tickets. Inside `GatesService.resolve()`,
a new `materialise.py` reads the approved `cab2_proposal` and creates cards in
the same workflow:

- per coding task, an `implementation` card for `coder` plus a
  `verification` card for `verifier` that depends on it;
- per manual task, a new `manual_task` card that only the operator can
  complete.

Every card carries its task's id in a new `board_card.task_node_id` column and
its approved text in a `task_spec` artifact. The envelope reads that artifact.
Prerequisites become dependency edges.

A task's verification findings now trigger remediation plus a re-verification,
capped by the existing `max_verify_iterations` setting (developer decision,
R6). Delivery becomes a pure readiness check: once every coding card is
cleanly verified, exactly one delivery is created, so one request gives one
branch and one PR.

The ticket gets one breakdown comment instead of sub-tasks. The child-link
machinery is deleted; `create_subtask` is kept for #64. The listing drops
`parent_workflow_id` and gains `open_manual_task_count`. The cockpit gets a
manual-task panel.

## Technical Context

**Language/Version**: Python 3.13 (backend), TypeScript / Vue 3 (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy 2, Alembic, Pydantic; Vue 3, Vuetify 4. No new dependencies.

**Storage**: SQLite. **One migration** (`0033`): add `board_card.task_node_id`, drop `board_workflow.skip_decomposition`, drop `child_task_link`.

**Testing**: pytest (backend), vitest (frontend), `task quality`, `npm run build`

**Target Platform**: single-user local web app (loopback)

**Project Type**: web application (backend + frontend)

**Performance Goals**: n/a. `delivery_due` is O(cards + relations) per dispatch pass, on boards of tens of cards.

**Constraints**:
- The structural limits in AGENTS.md: module ≤ 500 lines, branches ≤ 12,
  args ≤ 5, JS function ≤ 60 lines, jscpd ≤ 3 %.
- Near-limit modules: `gates.py` (457), `coordinator.py` (458),
  `dispatch_ready.py` (423), `routers/board.py` (483). New logic goes into new
  modules, and only the hooks go into these.
- Constitution Principle I: the listing DTO change lands in one commit with
  its frontend type.

**Scale/Scope**: decompositions of 1 to about 15 tasks. There are three
verification rounds per task at most by default.

## Constitution Check

| Principle | Assessment |
| --- | --- |
| I. Contract fidelity | `WorkflowSummaryOut` / `BoardWorkflowSummary` change together (field removed, field added). `CardAction` gains `complete_manual_task` on both sides. `board-api.md` is amended in the same commit ([contracts/board-api-delta.md](contracts/board-api-delta.md)). **Pass** |
| II. Layered, backend-owned | Materialisation, the manual-card rule, the round cap and delivery readiness are all service-layer. The frontend only shows `allowed_actions` and the count. Schema changes go only through Alembic `0033`. **Pass** |
| III. Test-first | Every row in [quickstart.md](quickstart.md) gets a test with or before its code. The fixture source and the fake backends are used, never a real `claude`. **Pass** |
| IV. Simplicity | The net code shrinks (the child-link store, re-adoption and scheduler go). One new card kind, one action, one column, one policy edge, and no new setting (the dead `max_verify_iterations` is reused). See Complexity Tracking. **Pass** |
| V. Kit-aligned | The manual-task panel and chip use Vuetify components (`v-list`, `v-chip`, `v-btn`) and theme colours only. **Pass** |

**Access-model constraint** (clean-up of public sources):
- The breakdown comment is a recorded `approved_artifact` projection, so reset
  clean-up owns it like any other kestrel comment.
- No sub-tasks are created any more.
- Legacy child tickets remain clean-up-able through the kept `"subtask"`
  clean-up kind, when their workflow-artifact records exist.

**Pass**

**Post-design re-check**: unchanged. The design adds no endpoint. The only new
write path to a task source is one comment per approval, through the existing
projection mechanism.

## Project Structure

### Documentation (this feature)

```text
specs/031-subtask-cards/
├── spec.md
├── plan.md              # this file
├── research.md          # R1–R14
├── data-model.md
├── quickstart.md
├── contracts/
│   └── board-api-delta.md
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks
```

### Source Code (touched, added, deleted)

```text
backend/
├── alembic/versions/0033_subtask_cards.py        # NEW: add task_node_id, drop skip_decomposition, drop child_task_link
├── app/
│   ├── config.py                                 # − child_task_closure_retention_days
│   ├── markers.py                                # − SubtaskSentinel, ManualTaskSentinel, their constants
│   ├── models_board.py                           # + CardKind.MANUAL_TASK, CardAction.COMPLETE_MANUAL_TASK,
│   │                                             #   WorkCard.task_node_id; − Workflow.skip_decomposition
│   ├── models_board_records.py                   # − AcceptedTaskIntake.skip_decomposition
│   ├── ports.py                                  # docstring only (create_subtask kept, unused, for #64)
│   ├── schemas.py                                # WorkflowSummaryOut: − parent_workflow_id, + open_manual_task_count;
│   │                                             #   BoardInterventionIn.action += complete_manual_task
│   ├── persistence/
│   │   ├── board_tables.py                       # + BoardCardRow.task_node_id; − skip_decomposition
│   │   ├── board_store.py                        # map task_node_id; drop skip_decomposition
│   │   ├── tables.py                             # − ChildTaskLinkRow
│   │   └── child_task_store.py                   # DELETED
│   ├── routers/
│   │   ├── board.py                              # drop child_task_store dep; schedule_breakdown_projection
│   │   ├── board_views.py                        # open_manual_task_count; drop parent link
│   │   ├── github_webhook.py                     # drop child-state observation
│   ├── services/
│   │   ├── ingestion.py                          # − _scheduled_child, child re-adoption, sentinel checks
│   │   ├── jira_poll.py, local_task_poll.py, reconcile.py   # drop child-state observation calls
│   │   ├── task_scheduler.py                     # DELETED
│   │   ├── task_source_utils.py                  # − subtask/manual sentinel helpers
│   │   └── board/
│   │       ├── materialise.py                    # NEW: candidate → cards, edges, task_spec; breakdown text
│   │       ├── delivery_readiness.py             # NEW: pure delivery_due(cards, relations) + trigger digest
│   │       ├── verification_rounds.py            # NEW: round count, cap, remediation + re-verification actions
│   │       ├── candidate.py                      # strict prerequisite validation (R11)
│   │       ├── decomposition.py                  # − publish_decomposition & friends
│   │       ├── gates.py                          # approval hook → materialise; − skip_decomposition exemptions
│   │       ├── coordinator.py                    # tagged cards immutable; MANUAL_TASK code-only;
│   │       │                                     #   CreateCardAction.task_node_id; − skip_decomposition
│   │       ├── dependents.py                     # manual cards → awaiting_human
│   │       ├── policy.py                         # + waiting_dependency → awaiting_human
│   │       ├── interventions.py                  # complete_manual_task; no resolve_gate for manual cards
│   │       ├── verification.py                   # tagged routing via verification_rounds
│   │       ├── dispatch_ready.py                 # task_spec extra context; drop _request_delivery call;
│   │       │                                     #   DispatchServices.verify_round_cap
│   │       ├── dispatch_delivery.py              # request delivery via delivery_due
│   │       ├── bootstrap.py                      # schedule_breakdown_projection; wire verify_round_cap
│   │       ├── projections.py                    # − "child_work"
│   │       ├── phases.py                         # MANUAL_TASK → Build
│   │       └── dev_reset.py                      # docstring
│   └── .vulture_allowlist.py                     # only if a kept port method needs it (expected: no)
├── specialists/
│   ├── coordinator/prompt.md                     # approved tasks already have impl + verification cards
│   └── README.md                                 # card-kind vocabulary: manual_task
└── tests/                                        # new: test_board_materialise.py, test_board_delivery_readiness.py,
                                                  #   test_board_verification_rounds.py; updated/removed: see research R12

frontend/
├── src/
│   ├── types/workflows.ts                        # − parent_workflow_id, + open_manual_task_count, + complete_manual_task
│   ├── lib/stages.ts                             # − partitionByParentage / children
│   ├── lib/personas.ts                           # manual_task.completed = operator event
│   ├── components/board/RequestCard.vue          # "N manual tasks assigned to you" chip
│   ├── components/board/RequestSubItems.vue      # − children list
│   ├── components/cockpit/ManualTaskList.vue     # NEW: manual cards, Read task, Mark done
│   ├── components/WorkCardDetail.vue             # ACTION_LABELS += complete_manual_task
│   └── views/RequestCockpitView.vue              # mount ManualTaskList
└── tests/                                        # stages, RequestCard, RequestSubItems, StageBoardView, ManualTaskList, support/board.ts

specs/026-autonomous-work-board/contracts/board-api.md   # amended (Principle I)
specs/012-task-decomposition-pipeline/spec.md            # "Superseded on child tickets by 031" note (FR-022)
docs/architecture.md                                      # one workflow → one branch → one PR; lost per-task tickets (#63)
config.toml.example                                       # drop child_task_closure_retention_days if present
```

**Structure Decision**: the existing web-app layout. There are three new
backend modules: `materialise.py`, `delivery_readiness.py` and
`verification_rounds.py`. They keep the four near-limit modules under 500
lines, and they isolate the three pieces of pure logic that most need their
own unit tests.

### Suggested commit slices

Each slice leaves `task quality` and both test suites green.

1. **Cards from CAB-2**: migration (`task_node_id` only), `MANUAL_TASK`, the
   policy edge, `materialise.py`, the gates hook, the `task_spec` envelope,
   coordinator immutability, candidate prerequisite validation, and the
   breakdown comment in place of publishing. After this slice the child
   machinery is unreachable but not yet deleted.
2. **Verification rounds and single delivery**: `verification_rounds.py`,
   `delivery_readiness.py`, and the dispatch wiring.
3. **Manual tasks for the operator**: `complete_manual_task`, the listing
   count, and in one commit (Principle I) the frontend chip, panel and types.
4. **Clean break**: delete the child-link store, re-adoption, the scheduler,
   the sentinels, `skip_decomposition` and the rest of the migration.
   `parent_workflow_id` goes in the same commit as the frontend nesting
   removal.
5. **Docs**: architecture, the 012 superseded note, `board-api.md`, the
   specialists README.

## Complexity Tracking

| Addition | Why needed | Simpler alternative rejected because |
| --- | --- | --- |
| `board_card.task_node_id` column | Four consumers need the card → task link: envelope, round count, coordinator guard, idempotency (R2) | Relation-derived lookup breaks after the first remediation round. Title parsing is fragile. |
| New policy edge `waiting_dependency → awaiting_human` | A manual card must land in "your move" when unblocked, and `ready → done` is illegal (R4) | Two transitions via `ready` emit a misleading "ready" event and briefly look claimable. |
| Verification round cap in this feature | Deterministic re-verification without a cap can loop for ever (R6, developer decision) | Uncapped: unsafe. No re-verification: delivery can stall. |
| Delivery readiness as a per-pass check | Several different events can be the last one before delivery (R7) | Triggering only on a clean verification misses an escalation resolved by the operator, and the workflow stalls. |
