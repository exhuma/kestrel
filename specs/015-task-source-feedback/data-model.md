# Data Model: Task-Source Feedback

## Review request

- `workflow_id`: owning run.
- `gate`: understanding, PRD, or decomposition.
- `revision`: monotonically increasing revision.
- `token`: opaque active response identity.
- `source_post_id`: external post identifier when available.
- `active`: exactly one active request per gate.

## Feedback decision

- `feedback_external_id`: deduplication key.
- `review_request_token`: optional matched request.
- `outcome`: approve, reject, request_changes, unclear.
- `original_body`: durable source text.
- `translation`: optional English text.
- `applied_at`: records one successful effect.

## Child task link

- `parent_workflow_id`: decomposition owner.
- `task_ref`: published child source identity.
- `latest_workflow_id`: newest child workflow generation.
- `closed_at`: source closure time.
- `retired_at`: one-time monitoring retirement.

## Re-adoption

An eligible open transition for a non-retired child task creates one successor
with `parent_run_id` set to the completed run and reason `reopened`.
