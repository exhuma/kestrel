# Research: Sub-tasks as cards inside the parent workflow

Decisions for [spec.md](spec.md). Four design questions were settled with the
developer before the spec was written; see its *Context*. A fifth question, the
verification-loop cap (R6), was settled with the developer on 2026-09-29 while
planning. Everything else here is an engineering call, recorded so it can be
reviewed.

## R1 — Where the approved decomposition becomes cards

**Decision**: synchronously, inside `GatesService.resolve()` on a
`decomposition_gate` approval, next to the existing `_maybe_*` follow-ups. The
logic lives in a new module, `services/board/materialise.py`.
`gates.py` is at 457 lines and gets only a one-call hook.

**Rationale**: every other deterministic follow-up to a gate (refinement
cards, the PRD card, the decomposition card) is created there. Doing it in the
same call puts the new cards into the same board revision the operator's
approval produced, and `advance_ready_dependents` then runs over them as it
does today. It needs only collaborators `GatesService` already holds: the
store, the gate store and `ArtifactsService`, which can read the gate's target
artifact by id.

**Alternatives considered**:
- A background task, the way `schedule_decomposition_publish` works today.
  That was only needed because publishing makes a network round trip per
  child. Creating cards is local, and making it asynchronous would open a
  window in which CAB-2 is approved but the board still shows no work.
- A coordinator action. Rejected by the developer (FR-004).

## R2 — Linking a card to the task it came from

**Decision**: a new nullable column `board_card.task_node_id` (Text), mirrored
as `WorkCard.task_node_id: str | None = None`. It is set on every card created
from an approved task (implementation, verification, manual), and on the
remediation, re-verification and cap-escalation cards that follow from it
(R6). Coordinator-created cards leave it `NULL`.

**Rationale**: four things need to know "which approved task is this card
about": the envelope (R3), the per-task verification round count (R6), the
coordinator's no-touch rule (R8), and idempotency (R1). One indexed field
serves all four. The candidate's `task_node_id` is already the stable
per-task identity: strict parsing assigns `t<n>` when the pm omits one, and
duplicates are rejected.

**Alternatives considered**:
- Deriving the link from relation edges (card → gate → candidate). Remediation
  and re-verification cards have no edge to the gate, so it breaks after one
  round.
- Encoding the id in the card title. Titles are for display.

## R3 — How a card carries its task's body and estimate

**Decision**: at materialisation, every implementation and manual card gets a
reference artifact, `task_spec`. It is the approved task rendered as Markdown:
title, body, classification, prerequisites and estimate. Its trust level is
`operator_approved`, because CAB-2 approved exactly this text. It is written
with `ArtifactsService.store_reference_artifact` (no acceptance side effect).

- **Envelope**: `_extra_context_for` gains one branch. For any card with a
  `task_node_id`, it reads the `task_spec` of that node's materialised
  implementation card, or its manual card, and prefixes "Approved task:".
  This covers implementation, verification, remediation and re-verification
  cards alike. `build_card_envelope` is unchanged.
- **Cockpit**: `task_spec` is the manual card's `latest_artifact`, so
  "Read task" reuses `ArtifactDialog`'s existing open-by-id path. No new DTO
  field is needed for the body or the estimate.

**Rationale**: artifacts are how content already travels between cards and to
the UI (the PRD, the executive summary, the candidate). A card has no body
column, and adding one would widen the card DTO for every card kind.

**Alternatives considered**:
- A `body` column on `board_card` plus a DTO field. This widens the
  contract for one kind of card, which constitution Principle I makes costly.
- Reading the candidate from the gate on every envelope build. Remediation
  cards cannot find the gate (R2), and it re-parses JSON on every turn.

## R4 — Manual card lifecycle

**Decision**:
- New `CardKind.MANUAL_TASK = "manual_task"`, with `eligible_roles=()` and
  `workspace_permission=none`. It is never claimable, because `_is_eligible`
  already requires the claimant's id to be in `eligible_roles`.
- It is created in `awaiting_human` when it has no open prerequisites, and in
  `waiting_dependency` otherwise.
- New policy edge `waiting_dependency → awaiting_human`.
  `advance_ready_dependents` sends a manual card there instead of to `ready`.
- New `CardAction.COMPLETE_MANUAL_TASK = "complete_manual_task"`, offered by
  `allowed_actions_for` only for a `manual_task` in `awaiting_human`. It moves
  the card to `done`, through the existing `awaiting_human → done` edge, then
  runs `advance_ready_dependents`.
- `RESOLVE_GATE` is no longer offered for a `manual_task`, although it sits in
  `awaiting_human`. `allowed_actions_for` gains a kind check.

**Rationale**:
- `awaiting_human` is the board's existing meaning of "the operator's move".
  It already counts towards `action_required_count` and the "Your move"
  chip, with no new state.
- `ready → done` is not a legal edge. The only legal way to `done` without a
  claim is from `awaiting_human`, which is how gates work.
- A dedicated action keeps manual tasks out of the gate machinery. A gate
  has a reject path that invalidates dependents, and it projects to the
  task source. Neither fits "I did this".

**Alternatives considered**:
- Reusing the gate records with a new `requested_decision`. That brings the
  reject path and gate projections along with it.
- Parking the card in `ready` and adding a `ready → done` edge. `ready`
  means "a specialist may claim this", and it doesn't show up as "Your move".

## R5 — Verification is created with the work

**Decision**: for every coding task, materialisation creates an
`implementation` card and a `verification` card.
- The implementation card: `eligible_roles=("coder",)`, `write`.
- The verification card: `("verifier",)`, `read_only`, and it depends on the
  implementation card.

Each implementation card also depends on the implementation cards of the
task's prerequisites, or on their manual cards. It does not depend on their
verification cards (see R10 for ordering).

**Rationale**: FR-011 requires each task to be verified on its own. Today a
verification card exists only if the coordinator decides to create one, which
would leave FR-012's delivery rule depending on an LLM's initiative.

## R6 — Remediation, re-verification and the round cap (developer decision)

**Decision** (developer, 2026-09-29): fold the core of #61 into this feature,
for materialised tasks only.

- A verification card that carries a `task_node_id` and has non-escalation
  findings produces, as today, one `Remediate:` implementation card per
  finding. These now carry the same `task_node_id`, through a new
  `CreateCardAction.task_node_id` field. The field is code-only: it is never
  parsed from coordinator output.
- It also produces one **re-verification** card with the same `task_node_id`,
  depending on every remediation card. It is created by a second
  `apply_actions` call with the trigger `reverification:<card>:<attempt>`,
  because the first call's ids only exist after it returns.
- The **round** is the number of verification cards for that `task_node_id`.
  When a card with findings is already at round `max_verify_iterations`
  (the existing, currently unused setting, default 3), it creates neither
  remediation nor re-verification. It creates one `coordinator_review` card,
  "Verification cap reached: <task title>", which carries the `task_node_id`.
- Escalation findings keep today's behaviour: a `coordinator_review` card.
- The cap is passed in as `DispatchServices.verify_round_cap`.

**Rationale**: once verification is deterministic, "wait for the clean
verification" needs a re-verification after every fix. Without a cap the
loop can run for ever. `max_verify_iterations` is the natural knob: it is
already configured and documented, and read by nothing since the fixed
driver was removed.

**Left in #61**: wiring `SpecialistDefinition.retry_limit` and capping
coordinator-created (untagged) work.

## R7 — When delivery happens

**Decision**: delivery is still only ever requested by a clean
verification (`_route_verification` → `_request_delivery`). That request is
now gated by a pure check, `delivery_due(cards, relations)`, and delivery
goes ahead only when both of these hold:

1. no `implementation`, `verification`, `reconciliation` or
   `coordinator_review` card is still open (non-terminal) or `failed`;
2. every `done` implementation card that carries a `task_node_id` (an
   approved task's work, including its remediation) has a `done`
   verification card depending on it.

Manual cards are ignored, which is the FR-008 part of "does not block
delivery". The request is idempotent through the coordinator's trigger
ledger. It is keyed by a digest of the ids of the `done` implementation
cards (`delivery:<digest>`), so it fires once per distinct set of finished
work. A later CI-repair implementation card changes the set, and the next
clean verification then triggers exactly one more delivery, which updates
the existing change request (FR-013). A breakdown with only manual tasks has
no verification to trigger delivery at all, which covers FR-015.

**Rationale**: the first clean verification must no longer deliver while other
coding work is open (FR-012). Keeping "a clean verification" as the only
trigger preserves today's guarantee that nothing is pushed unverified.

**Rejected during implementation**: a check evaluated on every dispatch pass,
which requires every done implementation card to be covered by a
verification edge. Pre-031 flows break it: coordinator-created verifications
and CI-repair cards carry no such edge, so either those workflows stall or,
if the edge condition is relaxed, a finished remediation would be delivered
unverified.

**Accepted consequence**: when a task hits its verification cap (R6) and the
resulting `coordinator_review` is resolved, delivery waits for the next clean
verification, which the coordinator or the operator must bring about. The
cap exists precisely to stop and ask. Also, a clean verification in a
workflow where coordinator-created work is still open no longer delivers
early. That is intended (FR-012).

**Behaviour change for non-decomposed workflows**: only the "still open"
condition applies, since that work carries no `task_node_id`. Single-task
workflows behave as before.

## R8 — The coordinator cannot touch approved cards

**Decision**:
- `_validate_transition` rejects any coordinator transition of a card with a
  `task_node_id` ("card comes from an approved decomposition").
- `MANUAL_TASK` joins `_CODE_ONLY_CARD_KINDS`, like `ESTIMATION`, so the
  coordinator cannot create one.
- The coordinator prompt gets one sentence: approved tasks already come with
  their implementation and verification cards, so it must not duplicate them.

Operator interventions (`cancel`, `retry`, `reassign`) are unaffected (FR-005).

## R9 — The breakdown comment

**Decision**: `schedule_decomposition_publish` becomes
`schedule_breakdown_projection`, still a background task scheduled by the
router after a `decomposition_gate` approval. It posts one projection of kind
`approved_artifact` with the idempotency key `approved_artifact:<gate card id>`.
The body is rendered by a pure function in `materialise.py`: the approved task
titles, each with its classification, in candidate order. The `child_work`
projection kind is removed from `VALID_PROJECTION_KINDS` (FR-021).

**Rationale**: the approved breakdown is an approved artifact, the same class
of write-back as the approved PRD. It needs no new projection kind, and it is
cleaned up by reset the same way (constitution access-model constraint: a
Kestrel-owned, recorded artifact).

## R10 — Ordering and workspace granularity (#54's open question)

**Finding**: `ClaimsService._request_for` already takes the per-repository
workspace lease for every `read_only` or `write` claim, not only for writes. So
implementation and verification cards of one workflow can never run at the
same time in its single worktree. The same holds across workflows on the same
repository.

**Decision**: keep the per-repository lease. No new locking, and no serial
chain of dependency edges between independent tasks. Order among ready cards
follows claim order, and prerequisites enforce order where the pm declared it.

**Accepted consequence**: a verification of task A may run on a tree that
already contains task B's commits. This is harmless: delivery waits for every
task's verification (R7), and the PR contains all of them anyway.

## R11 — Prerequisite validation

**Finding**: `load_candidate` does not check that a task's `prerequisites`
name tasks in the same candidate, or that they are acyclic.

**Decision**:
- Strict parsing (fresh pm output) rejects unknown ids, self-references and
  cycles, with `DecompositionResultError`. It fails closed to
  `coordinator_review`, as for any other malformed candidate.
- Materialisation reads gates approved before this feature through lenient
  parsing. It assigns `t<n>` ids where they are missing, drops unknown
  prerequisites with a logged warning, and relies on `BoardStore.add_relation`'s
  existing `CycleError` as the last line of defence.

## R12 — What is deleted, what is kept

**Deleted**:
- `persistence/child_task_store.py`, `ChildTaskLinkRow`, and the
  `child_task_link` table (migration).
- `Workflow.skip_decomposition` and its column (migration), and every
  `skip_decomposition` exemption in `gates.py` and `coordinator.py`.
- `SubtaskSentinel`, `ManualTaskSentinel`, `SUBTASK_SENTINEL`,
  `MANUAL_SENTINEL`, and `has_subtask_sentinel` / `has_manual_sentinel` /
  `append_subtask_sentinel` (`task_source_utils.py`).
- `services/task_scheduler.py`.
- `publish_decomposition`, `published_body`, `_markers_for` and
  `_estimate_section`. Estimate rendering moves to `task_spec` (R3).
- Child re-adoption in `IngestionService`: `_scheduled_child`,
  `observe_child_source_state`, `observe_missing_child_source_tasks`,
  `observe_child_retrigger`, `maybe_start_reopened_successor` and
  `start_successor_run`. Also their callers in `jira_poll.py`,
  `local_task_poll.py`, `reconcile.py` and `routers/github_webhook.py`.
- `Settings.child_task_closure_retention_days`. Unknown TOML keys are
  ignored (`_CONFIG_FILE_FIELDS` is an allow-list, and `extra="ignore"`), so
  an operator's existing config still loads.
- `WorkflowSummaryOut.parent_workflow_id` and the frontend child nesting.

**Kept** (FR-018, for #64): `TaskSource.create_subtask` / `complete_subtask`,
`SubtaskContextError`, all three adapters, and the `"subtask"` clean-up kind,
which is still needed to remove legacy children on reset. The dead-code check
does not flag them: vulture runs at `--min-confidence 80`, and unused methods
are reported at 60 %.

## R13 — Stage board and cockpit

**Decision**:
- `WorkflowSummaryOut.open_manual_task_count: int = 0` counts `manual_task`
  cards in a non-terminal state. `RequestCard.vue` shows "N manual task(s)
  assigned to you" as a chip when the count is above zero.
  `RequestSubItems.vue` loses its children list.
- The cockpit gets a `ManualTaskList.vue` panel: every manual card with its
  state, "Read task" (opens `task_spec`), and "Mark done" when
  `allowed_actions` contains `complete_manual_task`.
- `asks.ts` is unchanged. The action banner keeps showing at most one gate
  ask. Manual tasks are long-running to-dos, not the single pending decision
  FR-016 of feature 029 reserves the banner for.
- `phases.py`: `MANUAL_TASK` belongs to "Build".
- `personas.ts`: `manual_task.completed` becomes an operator event.

## R14 — The pm's "self-contained task" rule (spec 012 FR-010)

**Decision**: unchanged. The pm prompt still asks for self-contained task
bodies. The spec does not relax it, and relaxing it would change what
CAB-2 shows. It can be revisited after using the new flow (see the
developer's intent on #63).
