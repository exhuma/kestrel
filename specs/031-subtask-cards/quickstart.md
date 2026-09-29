# Quickstart: validating feature 031

## Automated

```
task quality                         # structural limits, lint, dead code
cd backend && uv run pytest -q
cd frontend && npm test && npm run build
```

The scenarios the tests must cover. Each maps to a spec story or requirement:

| Scenario | Where |
| --- | --- |
| CAB-2 approval creates impl + verification per coding task and a manual card per manual task, all carrying the task's `task_node_id` and `task_spec`; `create_subtask` is never called (US1, FR-001/002) | backend materialisation tests |
| prerequisites become dependency edges: a dependent is `waiting_dependency` until its prerequisites are done; a manual prerequisite blocks a coding task (US1-2, US3-3, FR-003) | backend materialisation tests |
| approving the same gate twice / materialising twice creates no duplicate card (US1-4, FR-004) | backend materialisation tests |
| a legacy gate target (no ids, no classification) materialises with `t<n>` ids as coding tasks; unknown prerequisites are dropped (R11) | backend materialisation tests |
| strict parse rejects unknown / self / cyclic prerequisites → coordinator_review (R11) | backend candidate tests |
| coordinator cannot transition a tagged card, cannot create a `manual_task`; can still create its own implementation card (US1-3, FR-005) | backend coordinator tests |
| one breakdown comment per approval, idempotent, never gates work; no `child_work` projection (US1-5, FR-006/021) | backend bootstrap/projection tests |
| envelope for an implementation, verification, or remediation card with a `task_node_id` includes "Approved task:" + its `task_spec` (R3) | backend dispatch tests |
| manual card: never claimed; `awaiting_human` when unblocked; `complete_manual_task` → done → dependents advance; `resolve_gate` not offered (US3, FR-007/008) | backend interventions tests |
| `waiting_dependency → awaiting_human` only for `manual_task` in the cascade | backend dependents/policy tests |
| verification with findings → remediation + re-verification tagged; at the cap → one "Verification cap reached" coordinator_review, no remediation (R6) | backend verification tests |
| `delivery_due`: false while any coding/verification work is open or failed, or while a done implementation lacks a done verification; true once all clean; ignores manual cards; zero coding tasks → never (US2, US3-4, FR-012/015) | backend delivery tests (pure function) |
| delivery requested exactly once per distinct set of done implementation cards; a CI repair re-delivers into the same change request (FR-013) | backend dispatch-delivery tests |
| phase is not `done` while a manual card is open (US3-5, SC-004) | backend phases tests |
| listing: `open_manual_task_count` correct; no `parent_workflow_id` (FR-009/019) | backend board API tests |
| ingestion: a body carrying the old subtask or manual marker is an ordinary request (US4-3, FR-017) | backend ingestion tests |
| migration 0033 upgrades a DB with child links and a `skip_decomposition=1` workflow; downgrade restores the schema (US4-1/2) | backend migration tests |
| stage board: one card per request, no nesting; "2 manual tasks assigned to you" chip at count 2, absent at 0 (FR-009/019) | frontend `stages`, `RequestCard`, `RequestSubItems`, `StageBoardView` tests |
| cockpit manual-task panel: lists manual cards, "Read task" opens the artifact, "Mark done" posts `complete_manual_task` with the revision, and is hidden when not allowed (FR-010) | frontend `ManualTaskList` tests |

## Manual walk-through (fixture task source)

1. Enable decomposition (`KESTREL_BOARD_DECOMPOSITION_REQUIRED=true`) and run
   the dev stack with the fixture task source.
2. Ingest a fixture task whose decomposition will include a manual step:
   for example "Add the vendor API client; the API key must be requested
   from the vendor first." Approve the gates through to CAB-2.
3. Approve CAB-2. Then check that:
   - the fixture task directory has **no** new `children/` folder;
   - the request ticket has one new comment listing the tasks;
   - the stage board still shows one card for the request, reading "1 manual
     task assigned to you";
   - the cockpit's manual-task panel lists the key-request task, and the
     vendor-client implementation card waits on it.
4. "Read task" on the manual card opens the approved text and its estimate,
   with the `operator_approved` chip. "Mark done" moves it to done, and the
   implementation card becomes ready.
5. Let the coding tasks run. Implementation and verification never overlap
   in the worktree. No draft PR (for the fixture source, "local branch
   published") appears until the last coding task's verification is clean.
   Then exactly one appears.
6. If a manual card is still open after delivery, the request is not in the
   Done column. Mark it done and the request moves to Done.

## Upgrade check

On a copy of a database that has used decomposition before this feature:
`uv run alembic upgrade head`. Then check that the board lists the former
child workflows as ordinary top-level requests.
