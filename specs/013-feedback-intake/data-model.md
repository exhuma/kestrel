# Phase 1 Data Model: Feedback Intake

One new migration (`0015_feedback.py`): two new tables, one new nullable
column. No existing column changes shape or meaning.

## `Feedback` (dataclass, `backend/app/ports.py`)

The port-level read result — not itself a database row (the persisted form
is `FeedbackItemRow`, below).

```python
@dataclass
class Feedback:
    external_id: str        # source-native, adapter-minted, opaque
    origin: Literal["ticket", "review"]
    author: str
    body: str
    created_at: datetime
```

`external_id` is what makes cross-transport dedup possible (R3/R6): the
GitHub adapter mints e.g. `"gh-issue-comment:8812"` or
`"gh-pr-review:445102"`; Jira mints `"jira-comment:{issue}:{id}"`; fixture
mints `"fixture:{slug}:{line}"`. Whatever the adapter mints, it's stable and
globally unique for that piece of feedback.

## `ChangeRequest` (dataclass, `backend/app/ports.py`)

```python
@dataclass
class ChangeRequest:
    number: int
    url: str
    state: Literal["open", "merged", "closed"]
    head_branch: str
    base_branch: str
```

`state` is what R7's revive-vs-successor decision reads.

## `feedback_item` (table, `backend/app/persistence/tables.py`)

| Column | Type | Notes |
|---|---|---|
| `external_id` | TEXT | **Primary key.** Atomic insert-if-absent — the same dedup mechanism `WebhookDeliveryStore`/`DismissalStore` already use for external-event dedup (R3). |
| `workflow_id` | TEXT, nullable | FK to `workflow_run.id`. Nullable because post-terminal feedback (User Story 4) may arrive for a ticket with no live run to attach to yet. |
| `task_ref` | TEXT | The originating ticket's ref — how feedback is routed when `workflow_id` is not yet known. |
| `origin` | TEXT | `"ticket"` \| `"review"`. |
| `author` | TEXT | Used by R6's author-denylist guard, and for display. |
| `body` | TEXT | Raw feedback text (marker already verified present before a row is ever written). |
| `state` | TEXT | `"queued"` \| `"dispatched"` \| `"applied"` \| `"ignored"`. Makes the mid-run queue durable across a restart (FR-007). |
| `target_step` | TEXT, nullable | Set once the triage turn (R5) has classified it; null until then. |
| `created_at` | DATETIME | Naive UTC, matching this project's existing timestamp convention (constitution's recorded persistence deviation). |
| `processed_at` | DATETIME, nullable | Set when `state` moves to `applied` or `ignored`. |

Index: `(workflow_id, state)` — the lookup `FeedbackDispatcher` needs for
"what's queued for this run."

## `feedback_cursor` (table)

| Column | Type | Notes |
|---|---|---|
| `scope` | TEXT | **Primary key.** `"ticket:<task_ref>"` or `"pr:<repo>#<number>"`. |
| `cursor` | TEXT | Opaque, adapter-defined — passed back into `list_comments`/`list_review_comments`'s `since` parameter verbatim. |
| `updated_at` | DATETIME | Naive UTC. |

Deliberately not a column on `workflow_run`: a ticket's cursor must outlive
any single run (post-terminal feedback, User Story 4) and a linked successor
run (R7) must inherit its parent's cursor rather than re-reading everything
from the beginning.

## `workflow_run.pr_number` (new column, nullable INTEGER)

The missing PR→run index (today only `pr_url`, a string, is stored — see
`research.md` R4). Set in `deliver()` at the same point `pr_url` already is,
via the new pure `change_request_number(pr_url)` helper — existing rows with
no `pr_number` still resolve by matching on `pr_url`, so **no backfill is
required**.

## `WorkflowStep` / `WorkflowRun` — unchanged shape

Feedback-driven re-entry (`reentry.py::rewind_to`) only ever *rewrites*
existing `WorkflowStep`/`WorkflowRun` fields already defined by feature
012's data model (`status`, per-step `status`/`deliverable`/`session_id`,
`verify_round`) — no new field is added to either dataclass. See
`contracts/change-request-resume.md` for the exact transition rules.

## Validation rules (from `spec.md` Functional Requirements)

- FR-003: a `feedback_item` row is only ever created for feedback the
  marker-matcher (`services/feedback/marker.py`) already confirmed carries
  the trigger token — unmarked feedback is discarded before it reaches
  persistence at all, never merely marked `ignored`.
- FR-004/FR-006 (self-loop guard, R6): `feedback_item.author` MUST be
  checked against `settings.feedback_ignore_authors` (and, for GitHub,
  `user.type == "Bot"`) before a row is claimed — enforced in
  `FeedbackIntakeService`, the single convergence point, so no transport
  (webhook or poll) can bypass it.
- FR-008/FR-011: `FeedbackDispatcher` MUST resolve `run.pr_number` (falling
  back to `pr_url` containment for pre-migration rows) before deciding
  revive-vs-successor for review-origin feedback.
- FR-013: a `decomposed` run's feedback MUST route to a single-shot
  correction path (`publish_correction()`), never back through
  `run_gap_analysis` — enforced by `FeedbackDispatcher`'s branch on
  `run.status`, not left to the triage turn's judgment.
