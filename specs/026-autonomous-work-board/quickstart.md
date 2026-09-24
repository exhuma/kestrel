# Validation Guide: Autonomous Work Board

## Prerequisites

- A configured local task source and local bare repository, or configured
  GitHub/Jira task source and code host.
- A configured backend that can provide text turns; a file-edit-capable backend
  for coder cards.
- A valid specialist root with the default named roles.
- Standard local dependencies installed for `task quality`.

## Validate Specialist Configuration

1. Start Kestrel with the default specialist tree.
2. Confirm startup reports the loaded named roles without printing full prompt
   content.
3. Make one required manifest invalid, such as removing a required ability.
4. Confirm startup refuses the configuration before task ingestion starts.
5. Restore the manifest and restart successfully.

Expected outcome: no missing, incompatible, or unsafe specialist can receive a
card.

## Validate Safe Intake and Quarantine

1. Create a normal source task with a bounded ordinary request.
2. Observe the workflow and its initial board cards become available.
3. Submit a second source task or marked feedback containing an unsafe
   instruction pattern.
4. Open the resulting security review from Board or List.
5. Verify no specialist session, source acknowledgement, translation, or source
   mutation occurred for the quarantined input.
6. Release the review and verify a recorded decision permits the expected board
   event; repeat with discard and verify the source remains unchanged.

Expected outcome: external and gate input is fail-closed, deduplicated, and
operator-resolvable.

## Validate Scheduling and Recovery

1. Use a workflow containing two independent analysis cards, one coder card,
   and a dependent verifier card.
2. Observe both analysis cards claim concurrently when capacity permits.
3. Confirm the coder cannot run concurrently with another write-capable card
   for the same repository.
4. Stop Kestrel during an active card attempt and wait past its lease expiry.
5. Restart Kestrel and inspect the card event history and retained artifacts.

Expected outcome: completed artifacts survive; the interrupted attempt is
recorded; the card follows bounded retry, reassignment, or escalation policy;
and a repository never has two active writers.

## Validate Gates, Verification, and Projection

1. Drive understanding, refinement, PRD, and decomposition work to their gate
   cards. Resolve each through the board.
2. Submit an implementation nonconformance from verifier work and confirm an
   internal remediation card is created without a human gate.
3. Submit a requirements ambiguity and confirm a coordinator review and, when
   needed, human gate are created without changing the approved PRD.
4. Inspect the source task after ordinary claims/retries and after a gate,
   escalation, approved artifact, child work, and delivery.

Expected outcome: only the selected human-meaningful milestones project to the
source; public source cleanup affects only durably recorded Kestrel resources.

## Validate Operator UI

1. Open a workflow with cards in each waiting and terminal state.
2. Use Board to distinguish dependency waiting, human waiting, and quarantine.
3. Use List with only a keyboard to select a card, inspect details, and invoke
   an allowed action.
4. Open Graph, select the same card, filter direct dependencies, and confirm
   the shared detail view updates.
5. Trigger a stale intervention from a second browser state and confirm the UI
   reports the conflict without losing the operator's unsent draft.

Expected outcome: Graph explains relationships while Board/List remain the
complete accessible control surface.

## Required Automated Checks

Run the repository's full gate after implementation:

```text
task quality
```

Add backend tests for policy transitions, cycle rejection, atomic claims,
recovery, artifact provenance, all input transports, quarantine side-effect
blocking, and projection idempotency. Add frontend tests using mocked HTTP/SSE
for state grouping, safe rendering, interventions, stale revisions, keyboard
operation, and graph-to-detail selection.

## Validation results (2026-09-24, docs pass after Phase 10)

Run against the code as of the Phase 10 clean break (commits `33628b4`,
`3fc281c`), in a sandbox with no live `claude` login and no real GitHub/Jira
credentials, so only what's listed as "confirmed live" below was actually
exercised end-to-end; everything else is a static code-path check.

**Confirmed live:**
- *Specialist Configuration* (steps 1-5): `uv run python -c
  "from app.services.board.bootstrap import get_specialist_roster; ..."`
  loads all 13 default roles. Corrupting `specialists/coder/manifest.toml`
  (dropping `file_edits` from `required_abilities` while
  `workspace_permission = "write"`) makes `load_roster()` raise
  `SpecialistLoadError: coder: workspace_permission 'write' requires the
  'file_edits' ability`; `app/main.py`'s startup path calls
  `get_specialist_roster()` unguarded, so this blocks app boot, not just a
  later dispatch. Manifest restored after the check; `git diff` confirms no
  residual change.
- Fresh-DB migration to head (`alembic upgrade head`) produces exactly the
  `board_*` tables (plus `child_task_link`, `event`, `issue_dismissal`,
  `notification`, `session`, `webhook_delivery`) and **no**
  `workflow_run`/`workflow_step`/`workflow_round_chip`/`workflow_artifact`/
  `review_request`/`feedback_item`/`feedback_cursor` table.
  `GET /api/board/workflows` returns `200 []` against that empty DB and
  `GET /livez` returns `200`, via `TestClient(create_app())`.
  `uv run python -m app poll` runs and reports "No task sources configured."
  (as expected with none set).

**Static-only (no live backend/credentials available in this sandbox):**
- *Safe Intake and Quarantine*: `QuarantineService`'s deterministic
  fail-closed paths (oversized content, missing/incapable `input-security`
  specialist) are code-confirmed; the LLM-classification path itself needs
  a working backend to exercise. Note: step 3's "marked feedback containing
  an unsafe instruction pattern" describes the old, now-removed
  comment-marker feedback pipeline (see `docs/feedback-intake.md`) — there
  is currently no board-domain path that ingests ticket-comment feedback at
  all, so this step cannot be driven as written; only the *task-body*
  intake half of this scenario is currently reachable.
- *Scheduling and Recovery*, step 2 ("Observe both analysis cards claim
  concurrently") and *Gates, Verification, and Projection*, step 2
  ("Submit an implementation nonconformance from verifier work"): **cannot
  currently pass**. `app/services/board/dispatch.py`'s `claim_and_dispatch`/
  `run_card_turn` (the code that has a specialist actually claim and work a
  `ready` card) has no caller anywhere in the app — `app/main.py` only
  starts the coordinator-wake and claim-recovery background loops, and the
  board's only mutation hook (`bootstrap.py`'s `_trigger_scheduling`) wakes
  the coordinator, never a specialist. A card can sit `ready` indefinitely.
  This is a real gap, not a sandbox limitation — see
  `docs/architecture.md#current-gap-no-verification-loop-or-task-source-write-back-yet`.
- *Gates, Verification, and Projection*, step 4 ("Inspect the source task
  after... gate, escalation, approved artifact, child work, and delivery"):
  **cannot currently pass** either — `app/services/board/projections.py`'s
  own module docstring states posting to a task source is not yet
  implemented, and `app/notifications.py`'s docstring confirms nothing
  currently produces a `Notification` row. No task-source-visible change
  should be expected for any of these milestones today.
- *Validate Operator UI*: not exercised (no browser in this sandbox);
  `WorkBoard.vue`/`WorkCardDetail.vue`/`WorkflowGraph.vue` and their
  `useBoard.ts` composable exist and match the described List/Graph/detail
  structure, but keyboard operation and the stale-intervention-conflict UI
  behaviour were not driven interactively.

**Net assessment**: the board's *data model, intake/quarantine, gates,
interventions, and read/SSE API* are solid and match this quickstart.
The *scheduling loop that actually performs specialist work* and *all
task-source write-back* (Phase 9 of `tasks.md`) are not yet built, so the
back half of this quickstart (concurrent claiming, live verification
findings, and source-visible projections) describes intended, not current,
behavior. Recommend either implementing Phase 9 before relying on those
scenarios, or annotating them here as forward-looking until then.
