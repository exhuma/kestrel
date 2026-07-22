# Phase 1 Data Model: GitHub Ingestion & Repo Ops

Entities, persisted schema, and the Alembic migration. Schema is owned exclusively
by Alembic (Constitution II); no `create_all`/raw DDL. New migration is `0006`
(`down_revision = "0005"`), mirroring `alembic/versions/0003_notification_table.py`.
It creates `webhook_delivery` and `issue_dismissal` and adds `workflow_run.source`.

## New table: `webhook_delivery`

Durable record that a GitHub delivery was processed — the at-most-once guarantee
(FR-004), restart-safe (FR-022), bounded by retention (FR-008/SC-008).

| Column | Type | Notes |
|--------|------|-------|
| `delivery_id` | `String` PK | GitHub `X-GitHub-Delivery` UUID |
| `event` | `String` | GitHub event type (e.g. `issues`) |
| `outcome` | `String` | `run-started` \| `duplicate` \| `ignored` \| `rejected-signature` \| `run-failed` (FR-021) |
| `repo` | `String`, nullable | `owner/name` when known (null for pre-verification rejects) |
| `issue_number` | `Integer`, nullable | issue the delivery concerned, when known |
| `created_at` | `DateTime` | naive UTC (project convention) |

**Rules**
- PK on `delivery_id` gives insert-if-absent semantics; a re-delivered id is a
  `duplicate` and starts no run (FR-004).
- `WebhookDeliveryStore.seen(delivery_id, ...)` inserts and reports prior presence;
  on insert it prunes rows with `created_at < now - 7d` (retention bound, SC-008).
- Never stores signatures, the secret, or the token (FR-006).

## New table: `issue_dismissal`

Durable tombstone that a maintainer abandoned an issue's run — suppresses
re-ingestion while the trigger label remains (FR-008a).

| Column | Type | Notes |
|--------|------|-------|
| `repo` | `String` | `owner/name`; part of composite PK |
| `issue_number` | `Integer` | part of composite PK |
| `created_at` | `DateTime` | naive UTC |

**Rules**
- Composite PK `(repo, issue_number)` — one dismissal per issue.
- `DismissalStore.add(repo, issue)` on abandon; `is_dismissed(repo, issue)` gates
  `maybe_start_run`; `clear(repo, issue)` on `unlabeled` webhook or when
  reconciliation sees the issue is no longer trigger-labelled.
- Bounded: at most one row per abandoned issue; removed on label removal.

## Modified table: `workflow_run` (+ `source`)

Adds the FR-019 task-source discriminator to the existing row
(`persistence/tables.py:46-62`).

| Column | Type | Notes |
|--------|------|-------|
| `source` | `String`, not null, server_default `"manual"` | `"manual"` \| `"github-issue"` |

**Rules**
- Existing rows backfill to `"manual"` via `server_default` (safe migration; no
  data loss on downgrade beyond dropping the column).
- Mirrors onto the domain model `WorkflowRun.source` (`models_workflow.py:59-73`)
  and is persisted/rehydrated in `WorkflowStore.save`/`load_all`
  (`persistence/workflow_store.py`).
- **Internal-only** — NOT added to `WorkflowSummary`/`WorkflowDetail` in
  `schemas.py` or to `frontend/src/types/` (clarification Q3), so ingested and
  manual runs are indistinguishable in the UI (FR-009).

## Domain model changes

### `WorkflowRun` (`models_workflow.py`)
- **+ `source: str = "manual"`** — set to `"github-issue"` by the ingestion path;
  left `"manual"` by the existing `POST /api/workflows` route. Internal-only (not
  surfaced to the API/UI — clarification Q3).

No other run/step fields change. Gate statuses are unchanged — the notifier keys on
the existing run-level `awaiting_*` statuses set in `workflows.py`
(`awaiting_refine_input`, `awaiting_refine_approval`, `awaiting_plan_approval`,
`awaiting_implement_input`, `awaiting_implement_approval`).

## Configuration entities (`config.py`, env `KESTREL_*`)

| Setting | Type | Default | Purpose |
|---------|------|---------|---------|
| `webhook_secret` | `str` (secret) | `""` | HMAC shared secret for delivery verification (FR-002/FR-020) |
| `watched_repos` | `list[str]` | `[]` | Allow-list of `owner/name`; ingestion/reconcile ignore anything outside it |
| `trigger_label` | `str` | `"kestrel"` | Label that flags an issue |
| `reconcile_interval_seconds` | `int` | `300` | Reconciliation cadence (FR-015) |
| `public_base_url` | `str` | `""` | Base for gate deep-links; unset ⇒ link-less comments (FR-024/FR-020a) |

Reused (unchanged): `github_token` (issue reads, reconciliation, comment posting),
`github_api_base`, `git_base`, `workspace_root`.

## Ephemeral / in-memory structures (not persisted)

- **Per-repo worktree lock map**: `dict[str, asyncio.Lock]` in `GitService`,
  guarding fetch + `worktree add`/`remove` per repo (R-09). Rebuilt per process; no
  schema.
- **Reconciliation task handle**: module-level `asyncio.Task` (mirrors `_WF_TASKS`,
  `workflows.py:63`), cancelled on shutdown.
- **No "last gate notified" marker** — deliberately omitted; restart idempotency is
  inherited from the recovery invariant (R-07).

## Relationships & lifecycle

```
GitHub delivery ──(X-GitHub-Delivery)──> webhook_delivery  (dedup, at-most-once)
        │                                        │
        │ authentic + labeled + watched          │ records outcome
        ▼                                        ▼
ingestion.maybe_start_run ──not dismissed? + guard (repo,issue)──> WorkflowService.create(source="github-issue")
        ▲                                                         │
reconciliation loop ──(list_issues_by_label)──────────────────────┘
   │    │                                                         │
   │    └─ clear issue_dismissal for issues no longer labelled    │
   │                                                   WorkflowRun (source column, internal)
   │  abandon (delete) ──> issue_dismissal.add(repo,issue)        │  status → awaiting_*
   │  unlabeled webhook ──> issue_dismissal.clear(repo,issue)     ▼
   │                                          CompositeNotifier: InAppNotifier (row) +
   │                                          GitHubIssueNotifier (issue comment + deep-link)
```

**Run working copy lifecycle (isolated)**: `bare mirror (per repo, persistent)` →
`git worktree add (per run)` → run executes/pushes/opens PR in the worktree →
`git worktree remove` on done/failed/rejected/abandon (bare mirror retained).

## Validation rules (from requirements)

- A delivery with missing/invalid signature is never recorded as `run-started` and
  starts no run (FR-002/FR-004); its outcome is `rejected-signature`.
- At most one `workflow_run` per `(repo, issue_number)` is created by ingestion
  (FR-008), enforced in `ingestion.maybe_start_run` before `create()`.
- A dismissed `(repo, issue_number)` starts no run via webhook or reconciliation
  until the dismissal is cleared by label removal (FR-008a).
- A failed run-start leaves no `workflow_run` row and no `issue_dismissal` row, so
  reconciliation re-attempts the still-labelled issue (FR-013a).
- `source` is always one of `{"manual","github-issue"}`.
- Gate comments contain only template text + optional deep-link — never deliverable
  content (FR-031).
