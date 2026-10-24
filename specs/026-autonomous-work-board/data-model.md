# Data Model: Autonomous Work Board

## Aggregate Boundaries

`Workflow` is the durable aggregate for one accepted task. It owns cards,
relations, artifacts, gates, events, and external projections. A workflow
snapshots task-source visibility at creation. Configuration changes cannot turn
a public workflow into a private one.

## Workflow

| Field | Rules |
| --- | --- |
| `id` | Stable opaque identifier. |
| `source`, `task_ref` | Source-native identity; unique together. |
| `repo`, `base_branch` | Repository context fixed before write work. |
| `source_visibility` | `public` or `private`, copied from source capability. |
| `title` | Safe display title after input acceptance. |
| `state` | Summary state derived from active cards and terminal outcome. |
| `revision` | Monotonic version for snapshots and optimistic interventions. |

## Work Card

| Field | Rules |
| --- | --- |
| `id`, `workflow_id` | Stable identity and owning workflow. |
| `kind` | Closed card-kind vocabulary; policy defines its contract. |
| `title` | Safe operator label. |
| `state` | One of the universal states below. |
| `eligible_roles` | Validated specialist IDs; agents cannot add themselves. |
| `workspace_permission` | `none`, `read_only`, or `write`; writer needs a lease. |
| `acceptance_contract` | Closed structured requirement for result validation. |
| `attempt_limit`, `attempt_count` | Bounded retry authority. |
| `wait_reason` | Safe explanation for human or dependency waiting. |
| `scope_authority_artifact` | Exact approved PRD or successor revision. |

### Card States

| State | Meaning | Allowed origins |
| --- | --- | --- |
| `ready` | Dependencies, role, capacity, and policy permit claim. | Policy |
| `claimed` | One durable specialist attempt owns the card. | Atomic claim |
| `waiting_dependency` | Upstream work is incomplete. | Policy |
| `awaiting_human` | A gate requires an operator decision. | Gate creation |
| `review` | Output awaits validation or reconciliation. | Specialist result |
| `quarantined` | Input security requires explicit review. | Input intake only |
| `done` | Accepted output is durable. | Validated completion |
| `failed` | Non-retryable or retry budget exhausted. | Policy/recovery |
| `cancelled` | Superseded or operator-approved cancellation. | Policy only |

`waiting_dependency`, `awaiting_human`, and `quarantined` are disjoint.
Quarantine is not a generic blocker. A card has an explicit relation or review
record explaining every non-ready state.

## Card Relation

| Field | Rules |
| --- | --- |
| `card_id`, `depends_on_card_id` | Directed edge; self-edge and cycle forbidden. |
| `kind` | Success, decision, supersession, or reconciliation relationship. |
| `required_artifact_revision` | Optional exact immutable artifact input. |
| `created_by_action` | Coordinator or operator decision. |

Successful dependency completion moves dependent cards toward `ready`. A scope
or artifact invalidation cancels or returns only affected downstream cards to a
policy-selected waiting state; historical outputs remain immutable.

## Claim, Attempt, and Workspace Lease

| Entity | Key fields | Invariants |
| --- | --- | --- |
| `CardAttempt` | Card, sequence, specialist, backend, session, result | Sequence is unique and terminal attempts never change. |
| `ClaimLease` | Card, attempt, holder, expiry, heartbeat | One active claim per card. |
| `WorkspaceLease` | Repository, claim, expiry | One active write lease per repository. |

A write claim is atomic: it changes a ready card to claimed, records the
attempt, and obtains the repository lease in one transaction. Claim expiry
closes the attempt as interrupted before retry, reassignment, or escalation is
decided. A late result after expiry is preserved as stale evidence and cannot
overwrite a newer attempt.

## Handoff Artifact

| Field | Rules |
| --- | --- |
| `producer_card`, `logical_name`, `revision` | Unique immutable identity. |
| `content_ref`, `content_hash`, `mime_type` | Durable content outside snapshots. |
| `input_artifacts` | Exact consumed revisions, not mutable latest pointers. |
| `trust` | At least untrusted, released, agent output, or operator approved. |
| `retention` | Operational retention policy. |
| `project_material` | Explicit true permits inclusion in the project change. |

## Human Gate and Security Review

`HumanGate` is associated with one gate card and one target artifact revision.
It records the requested decision, accepted decision input, affected work, and
an immutable decision history. A changed PRD/review creates a new revision and
successor gate; it never edits a prior approval.

`UntrustedInput` records bounded source metadata, content hash, policy version,
and safe content reference. It is unique by source identity plus integrity hash.
`SecurityReview` records deterministic findings, constrained classifier result,
review state, and operator release/discard resolution. Full suspect content is
not copied into board events, log fields, or operator summary payloads.

## Coordinator Action and Board Event

`CoordinatorAction` stores one proposed structured action with its trigger,
sequence, validation decision, rejection reason, and application time. The
policy is the only path to apply an accepted action.

`BoardEvent` is append-only workflow history. It links a safe event payload to
one card when relevant, a causation ID, and a correlation ID. It drives
coordinator wakes and board SSE ticks but does not replace current-state reads.

## External Projection

| Field | Rules |
| --- | --- |
| `kind` | Gate, escalation, approved artifact, child work, or delivery. |
| `idempotency_key` | Unique per source and projection. |
| `state`, `error` | Pending, completed, or retryable failure. |
| `external_id` | Recorded source resource identity for safe cleanup. |
| `payload_hash` | Detects unintended duplicate or mismatched writes. |

Routine claims, retries, and card completions cannot create projections. For a
public source, cleanup operates only on projection records that establish
Kestrel ownership.
