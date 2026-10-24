# Implementation Plan: Request activity at a glance

**Branch**: `work` | **Date**: 2026-09-29 | **Spec**: [spec.md](spec.md)

## Design

- **Live activity** (`services/board/live_activity.py`): a process-wide
  registry (`get_live_activity()`) holding what is running per workflow:
  `track(workflow_id, actor, subject)`, a context manager, and
  `current(workflow_id)`. It is used around:
  - the coordinator's turn (`SchedulingService`, actor `coordinator`);
  - each card turn (`dispatch_ready._dispatch_one`, actor = the
    specialist's label, subject = the card title);
  - screening (`IngestionService._screen`, actor `screening`).

  Being in memory, it is empty after a restart (FR-003, SC-002).
- **Problem events** (FR-004): `BoardService.record_problem(workflow_id,
  card_id, event_type, detail)` appends `coordinator.turn_failed` or
  `card.turn_failed`, with `{"detail": …}` as the payload, and publishes to
  the live views. It does not bump the revision (no coordinator re-wake) and
  does not fire `on_mutation`. It skips the write when the latest event is the
  same problem.
- **Derivation** (`services/board/activity.py`, pure):
  `activity_of(cards, events, live, done)` returns `RequestActivity(state,
  actor, subject, detail, since)`, applying FR-002's precedence.
  - A problem is the latest event, when that is a problem event.
  - *Queued* means ready cards with eligible roles, or a ready `delivery`.
  - *Stalled* covers everything else short of done. An orphaned claimed card
    gets a detail saying what will happen next.
  - `since` is the live start time, or the latest event's time.
- **DTO**: `RequestActivityOut` on `WorkflowSummaryOut` and
  `BoardSnapshotOut`, mirrored as `RequestActivity` in the frontend types
  (Principle I).
- **Frontend**: `ActivityLine.vue`, pure phrasing in `lib/activity.ts`, and a
  shared ticking clock for "2 min". It sits on `RequestCard` and in the
  cockpit header. `personas.ts` gets wording for the problem events.

No migration. No new dependency.
