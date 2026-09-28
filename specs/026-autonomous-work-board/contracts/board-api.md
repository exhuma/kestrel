# Board API Contract

This contract replaces the fixed-step workflow DTO. Backend schemas and
`frontend/src/types/workflows.ts` must mirror this shape exactly.

**Amendment (feature 029, board-api-additions.md)**: four fields are added,
each additive and read-only — no endpoint added, nothing renamed, nothing
writable:

- **Workflow Collection** (`WorkflowSummaryOut`): `title` (falls back to
  `task_label` when unrecorded), `parent_workflow_id` (nullable — the
  workflow this request was decomposed from), `cap_exhausted` (whether an
  interview round cap was hit without a usable answer).
- **Board Snapshot** (`BoardSnapshotOut`): `title`, same semantics.
- **Card Summary** (`WorkCardSummaryOut.gate`): `round`/`cap` (nullable —
  populated only for a round-capped `refinement_gate`).

See `specs/029-workflow-visualisation/contracts/board-api-additions.md` for
full rationale and semantics.

**Amendment (feature 030, board-api-delta.md)**: one more additive,
read-only field, and one card kind:

- **Board Snapshot** (`BoardSnapshotOut`): `task_body` — the request body as
  screened once at intake and frozen since; a later edit to the source
  ticket is **not** reflected. Snapshot only — **not** on the Workflow
  Collection.
- **Card kind** `estimation` — `developer`'s per-task estimates of a
  decomposition, whose valid result opens the `decomposition_gate` (CAB-2).
  That gate's `latest_artifact` is the executive summary.

See `specs/030-cab2-estimates-summary/contracts/board-api-delta.md`.

## Shared Enumerations

```text
CardState = ready | claimed | waiting_dependency | awaiting_human | review |
            quarantined | done | failed | cancelled

CardAction = retry | cancel | reassign | resolve_gate |
             release_quarantine | discard_quarantine |
             request_coordinator_review

RelationKind = dependency | reconciliation | supersedes
```

## Workflow Collection

`GET /api/workflows` returns workflow summaries. Each summary includes source
display identity, aggregate state, counts by `CardState`, and an
`action_required_count`. It contains no raw task or suspect input content.

`GET /api/workflows/events` streams full collection snapshots after any board
mutation and sends the current snapshot immediately on connection.

## Board Snapshot

`GET /api/workflows/{workflow_id}/board` returns:

```json
{
  "id": "workflow-id",
  "revision": 42,
  "task_label": "owner/repo#123",
  "task_link": "https://example.test/issues/123",
  "status": "active",
  "cards": ["WorkCardSummary"],
  "relationships": ["CardRelation"],
  "state_counts": {"ready": 2, "claimed": 1}
}
```

`GET /api/workflows/{workflow_id}/board/events` sends the same complete
snapshot immediately and after every committed board change. Each snapshot has
a monotonic `revision`. The client treats the snapshot as authoritative and does
not apply incremental patches.

## Card Summary and Detail

```json
{
  "id": "card-id",
  "title": "Validate approved requirements",
  "card_type": "verification",
  "state": "claimed",
  "eligible_roles": [{"id": "verifier", "label": "Verifier"}],
  "owner": {"specialist_id": "verifier", "label": "Verifier"},
  "lease": {"expires_at": "2026-09-24T12:00:00Z", "attempt": 1},
  "waiting_reason": null,
  "security_state": "trusted",
  "dependency_count": 2,
  "latest_artifact": {"id": "artifact-id", "label": "report", "revision": 1},
  "allowed_actions": ["cancel", "request_coordinator_review"]
}
```

`GET /api/workflows/{workflow_id}/cards/{card_id}` returns the summary plus
accepted inputs and outputs, relationships, attempt history, safe event history,
and gate/security-review summary. Artifact and event collections use cursor
pagination when a workflow exceeds the response limit.

Quarantined content is represented only by safe metadata: source identity,
integrity ID, category, policy version, timestamps, resolution, and an optional
escaped excerpt permitted by policy. It never appears as a raw body.

## Intervention

`POST /api/workflows/{workflow_id}/cards/{card_id}/interventions`

```json
{
  "action": "reassign",
  "expected_revision": 42,
  "assignee_id": "coder",
  "decision": null,
  "content": null
}
```

`expected_revision` is mandatory. The service validates card state, action,
role, scope, and source constraints. A stale request receives HTTP 409 and the
current safe board/card state. Unauthorized or impossible actions receive a
specific client error and create no state mutation.

`content` is always sent to the untrusted-input boundary before it can resolve
or amend a gate. Suspect content leaves the original gate unresolved and creates
or reuses a security review.

## HTTP Status Rules

| Status | Meaning |
| --- | --- |
| 200 | Read or intervention accepted; response contains safe current state. |
| 400 | Malformed request or unsupported action payload. |
| 404 | Workflow or card does not exist in that workflow. |
| 409 | Expected revision or allowed action is stale. |
| 422 | Policy rejects the requested transition or supplied decision. |

## Compatibility Boundary

The existing step fields (`steps`, `active_sessions`, round counters, and
step-oriented gate endpoints) are removed with the fixed workflow driver. This
is a green-field clean break, not a compatibility layer.
