# Contract delta: board API (feature 030)

It amends `specs/026-autonomous-work-board/contracts/board-api.md`. That file
is updated in the same commit as the code.

## Board Snapshot (`GET /api/board/workflows/{id}`), additive

| Field | Type | Meaning |
| --- | --- | --- |
| `task_body` | string | The request body, screened once at intake and frozen after that. Later edits to the source ticket are **not** reflected. Empty when intake stored none. |

**Not** added to the Workflow Collection (`GET /api/board/workflows`).

## Card kinds, additive

- `estimation`: the Engineering specialist's per-task estimates of a
  decomposition. Read-only workspace.

## Gate artifacts, behaviour note

A `decomposition_gate` created by this feature has its own `latest_artifact`,
the executive summary (`label = "executive_summary"`), readable through the
existing `GET /api/board/artifacts/{id}/content` endpoint (`trust =
"agent_output"`). Gates created before this feature have none.

No endpoint is added or removed. No field changes meaning.
