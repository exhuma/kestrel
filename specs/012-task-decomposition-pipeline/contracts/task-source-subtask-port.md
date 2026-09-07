# Contract: `TaskSource.create_subtask`

## Signature

```python
async def create_subtask(
    self, parent_ref: str, title: str, body: str
) -> str:
    """Create a follow-up task linked to parent_ref; return its new ref."""
```

Added to the `TaskSource` Protocol (`backend/app/ports.py`), required on
every implementation (`GitHubTaskSource`, `JiraTaskSource`,
`FixtureTaskSource`) — no default no-op, since decomposition applies
uniformly to every ingested task (spec.md FR-016) and there is no "source
can't do this" branch (spec.md Edge Cases).

## Preconditions

- `parent_ref` identifies an existing ticket this `TaskSource` can resolve
  (the run's own originating ticket).
- `title`/`body` are already final — the caller (`gap_analysis()`) has
  already run the self-containment check (`contracts/gap-analysis-output.
  md`) before calling this.
- `body` carries the `SUBTASK_SENTINEL` marker
  (`backend/app/services/workflow_text.py`) so a later fast-pathed run
  recognizes it (see `contracts/workflow-states.md`).

## Postconditions (binding on every implementation)

1. **Returns** the new ticket's source-native ref (same shape `TaskSource.
   get_task`/`display_label` expect elsewhere — GitHub `"owner/name#123"`,
   Jira an issue key, fixture a file-backed ref).
2. **MUST NOT** cause the created ticket to satisfy this source's
   ingestion-trigger condition at creation time (spec.md FR-013):
   - GitHub: the new issue is created **without** the configured
     `trigger_label`.
   - Jira: the new sub-task issue is created in a state the operator's
     documented `jql` guidance (`docs/setup-jira-workflow.md`) is written
     to exclude by default.
   - Fixture: the new task file is written the same way any other
     not-yet-triggered fixture task is (fixture ingestion is manually
     invoked per existing convention — no automatic trigger to avoid).
3. **MUST** record the parent/child relationship natively where the
   source supports it (Jira: native `Sub-task` issue type + parent field)
   or via an explicit reference in the body (GitHub, fixture: `Sub-task of
   <parent_ref>` line) — this is the only durable record of the
   relationship; kestrel's own database stores none (`data-model.md`).
4. Best-effort semantics match the rest of `TaskSource` (`post_comment`,
   `attach`): a transient failure on one follow-up task's creation must
   not corrupt or duplicate another's — each `create_subtask` call is
   independent.

## Test contract

- Given a set of follow-up tasks from `gap_analysis`, each created ticket,
  fetched back via `get_task`, has a body containing both the
  self-contained content and `SUBTASK_SENTINEL`.
- Given a GitHub-sourced run, none of the created follow-up issues carry
  the configured `trigger_label`.
- Given a Jira-sourced run, the created sub-task's issue type and parent
  link match Jira's native subdivision shape (not a plain unlinked issue).
- A `create_subtask` failure for one follow-up task in a batch does not
  prevent the others from being created (independent, best-effort per
  call).
