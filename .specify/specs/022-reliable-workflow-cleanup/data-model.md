# Data Model: Reliable Workflow Cleanup

## Workflow Artifact

A durable, workflow-owned record for one externally observable or local
resource that cleanup may need to remove.

| Field | Description |
|---|---|
| id | Stable database identity. |
| workflow_id | Originating workflow run. |
| kind | Resource category: workspace, local branch, remote branch, source body, attachment, child task, comment, or change request. |
| external_id | Provider-native identity or local path required by cleanup. |
| display_name | Safe operator-facing identity shown on the dashboard. |
| cleanup_mode | Required removal, close fallback, restore, or best effort. |
| state | Pending, cleaned, absent, closed, or failed. |
| error | Last bounded failure message, if cleanup remains unresolved. |
| created_at | Naive UTC creation timestamp. |
| cleaned_at | Naive UTC completion timestamp, when applicable. |

## Source Task Snapshot

A source-body artifact records the source task's exact body before the workflow
publishes a PRD. Its `external_id` is the source task reference and its private
payload is the pre-publication body. It is removed after restoration succeeds
or the task no longer exists.

## Relationships

- One workflow run has zero or more workflow artifacts.
- A workflow artifact belongs to exactly one workflow run.
- Child-task DAG records remain scheduling metadata; cleanup removes a child
  link only after the linked source item is removed, closed, or absent.

## State Transitions

```text
pending -> cleaned
pending -> absent
pending -> closed
pending -> failed
failed  -> cleaned | absent | closed | failed
```

Terminal cleanup states are removed from durable tracking once the cleanup run
finishes. `failed` remains visible and retryable.
