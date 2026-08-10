# Contract: `POST /api/workflows/{workflow_id}/rerun`

New endpoint, `backend/app/routers/workflows.py`, alongside the existing
`POST /{workflow_id}/cleanup` (`workflows.py:228-239`). Calls the new
`WorkflowService.rerun()` (`services/workflows/service.py`).

## Request

No body. `workflow_id` is the existing run id path parameter, same as every
other `/{workflow_id}/*` route in this router.

## Response — `200 OK`

```json
{ "workflow_id": "wf-a1b2c3d4" }
```

The **new** run's id (not the one being rerun) — matching the existing
`POST /api/workflows` create response shape (`{"workflow_id": str}`,
`workflows.py:105-112`), since rerun's net effect is "abandon this run, then
create a new one for the same task."

## Response — `403 Forbidden`

```json
{ "detail": "rerun is not available for this workflow's task source" }
```

Raised when `RerunNotAllowedError` propagates from `WorkflowService.rerun()`
— i.e. the run's task source reports `visibility() != "private"` (any
GitHub- or Jira-originated run). See `research.md` §4 for why this is 403
rather than the existing 409 used for `InvalidWorkflowStateError`.

## Response — `404 Not Found`

```json
{ "detail": "unknown workflow" }
```

Existing `WorkflowNotFoundError` handler (`main.py:121-129`) — unchanged,
reused as-is when `workflow_id` doesn't exist.

## Side effects (mirrors `cleanup()`, then diverges)

1. Cancels the run's driver task, terminates and removes every session
   whose `cwd == run.workspace`, force-tears-down the workspace — identical
   to `_abandon_common` (shared with `delete()`/`cleanup()`).
2. Force-deletes the run's branch from both the local mirror and the actual
   remote — identical to `cleanup()`.
3. Clears the run's dismissal — identical to `cleanup()`.
4. **Diverges from `cleanup()` here**: instead of stopping and waiting for
   the next scheduled poll to notice the ticket is undismissed, `rerun()`
   immediately calls `ingestion.maybe_start_run(...)` with the just-abandoned
   run's `task_ref`/`code_repo`/`issue_number`/`base_branch`/`source`,
   synchronously starting the replacement run before the HTTP response is
   returned. This is what satisfies spec SC-002 (fresh run starts within
   seconds, not after the poll interval).

## Client contract (frontend)

`frontend/src/composables/useWorkflows.ts` gains `rerun(id): Promise<void>`,
same shape as the existing `cleanup(id)` (`useWorkflows.ts:241-253`): POSTs
the endpoint, clears `current` if it was the rerun target, then `refresh()`s
the list so the sidebar picks up the new run.

`WorkflowSummary`/`WorkflowDetail`'s new `rerunnable: boolean` field (see
`data-model.md`) gates whether `WorkflowPanel.vue` renders the Rerun button
at all — this is a UX convenience only; the 403 above is the actual
enforcement (Constitution Principle II).
