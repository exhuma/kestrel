# Workflow Cleanup Contract

## `POST /api/workflows/{workflow_id}/cleanup`

Resets one workflow and removes its recorded artifacts.

### Success response

```json
{
  "status": "ok",
  "best_effort_failures": []
}
```

The selected workflow no longer exists after a successful response. The source
task remains available for the next polling cycle.

### Partial response

```json
{
  "status": "attention_required",
  "best_effort_failures": ["Unable to remove comment ..."],
  "required_failures": ["Unable to remove protected branch ..."]
}
```

Required failures retain the workflow and its failed artifact records so cleanup
can be retried. Best-effort failures do not prevent local workflow reset or poll
eligibility.

## `GET /api/workflows/{workflow_id}`

Adds an `artifacts` array while the workflow exists.

```json
{
  "artifacts": [
    {
      "kind": "child_task",
      "display_name": "RFC-124",
      "state": "pending",
      "cleanup_mode": "delete_or_close",
      "error": null
    }
  ]
}
```

The array contains currently tracked resources. It excludes artifacts confirmed
removed, closed, restored, or absent.
