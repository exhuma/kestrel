# Contract delta: board API (feature 031)

This delta amends `specs/026-autonomous-work-board/contracts/board-api.md`. That file
is updated in the same commit as the code, with the backend
(`schemas.py`) and frontend (`types/workflows.ts`) halves together
(constitution Principle I).

## Workflow Collection (`GET /api/board/workflows`)

| Field | Change | Meaning |
| --- | --- | --- |
| `parent_workflow_id` | **Removed** (breaking) | Decomposition no longer creates child workflows (FR-019). Supersedes feature 029 A1 / FR-040. |
| `open_manual_task_count` | **Added**, integer ≥ 0 | How many of the request's `manual_task` cards are neither `done` nor `cancelled`. The stage board shows "N manual task(s) assigned to you" when this is > 0 (FR-009). |

## Card kinds (additive)

- `manual_task`: work for the operator, created from an approved manual
  task. No specialist ever claims it. It sits in `awaiting_human` while
  actionable and in `waiting_dependency` while a prerequisite is open. Its
  `latest_artifact` is the approved task text (`task_spec`,
  `trust = "operator_approved"`).

## Card actions (additive)

```text
CardAction = retry | cancel | reassign | resolve_gate |
             request_coordinator_review | complete_manual_task
```

- `complete_manual_task` appears in `allowed_actions` only for a
  `manual_task` card in `awaiting_human`. It is applied through the existing
  `POST /api/board/workflows/{workflow_id}/cards/{card_id}/interventions` with
  `{"action": "complete_manual_task", "expected_revision": n}`, and `decision`
  and `answer` are ignored. On success the card is `done` and its dependents
  are re-evaluated. The endpoint returns 422 when the action isn't allowed and
  409 when the revision is stale, the same as for every other action.
- `resolve_gate` is **no longer** offered for a `manual_task` card, even
  though it is in `awaiting_human`.

## Behaviour notes (no shape change)

- Approving a `decomposition_gate` now adds cards to the **same** workflow:
  `implementation` + `verification` per coding task, and `manual_task` per
  manual task. It creates no ticket in the task source. The snapshot returned
  after the intervention already contains them.
- A workflow's delivery (the `delivery` card) is created once all coding work
  has a clean verification, not after each clean verification (research R7).
- `WorkCardSummaryOut` gains **no** field. The card-to-task link
  (`task_node_id`) stays internal.

## Task-source write-back

| Before | After |
| --- | --- |
| One `create_subtask` per approved task, and one `child_work` comment per child | **One** `approved_artifact` comment on the request's ticket listing the approved tasks and their classification (FR-006, R9). No sub-task is created. |

The `child_work` projection kind is removed. `create_subtask` stays on the
`TaskSource` port unused, for #64.
