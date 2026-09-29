# Data model: Sub-tasks as cards inside the parent workflow

The research decisions this implements are in [research.md](research.md).

## Schema change: migration `0033_subtask_cards`

| Change | Detail |
| --- | --- |
| `board_card.task_node_id` | **Added.** `Text`, nullable, no default. The approved-decomposition task this card works on (R2). |
| `board_workflow.skip_decomposition` | **Dropped** (added by 0029). |
| `child_task_link` | **Dropped** (added by 0018, extended by 0023). Its rows are discarded (FR-016). |

Downgrade re-creates the column and the table with their original shapes. It
cannot restore dropped rows, and the migration's docstring says so.

The migration also updates the `test_migrations.py` expectations for 0029's
default.

## `WorkCard` (`models_board.py`)

```text
WorkCard
  … existing fields …
  task_node_id: str | None = None   # NEW, R2
```

Which cards carry a `task_node_id`:

| Card | Created by | `task_node_id` |
| --- | --- | --- |
| implementation for coding task *t* | materialisation | *t* |
| verification of *t* (round 1) | materialisation | *t* |
| manual card for manual task *t* | materialisation | *t* |
| `Remediate: …` implementation | verification routing | inherited from the verification |
| re-verification (round *n* > 1) | verification routing | inherited |
| `Verification cap reached: …` coordinator_review | verification routing | inherited |
| every other card (gates, coordinator-created work, delivery, CI repair) | — | `None` |

## `CardKind.MANUAL_TASK = "manual_task"` (new)

| Property | Value |
| --- | --- |
| `eligible_roles` | `()`: no specialist can ever claim it |
| `workspace_permission` | `none` |
| Created by | materialisation only (in `_CODE_ONLY_CARD_KINDS`, R8) |
| Phase projection | "Build" |
| Reference artifact | `task_spec` (trust `operator_approved`) |

### State transitions

```text
                  prerequisites open            all prerequisites done
 (created) ─────► waiting_dependency ──────────────────────────────┐
     │                  │                                         ▼
     │ no open prereqs  └──── cancel (operator) ──► cancelled   awaiting_human
     └───────────────────────────────────────────────────────────►  │
                                                                     │ complete_manual_task (operator)
                                                                     ▼
                                                                    done
```

- **New policy edge:** `waiting_dependency → awaiting_human` (R4). The
  dependency cascade takes it only for `manual_task`; every other kind still
  goes to `ready`.
- **Existing edges it uses:** `awaiting_human → done` and
  `awaiting_human | waiting_dependency → cancelled`, the latter through the
  generic `cancel` intervention.
- `done` releases dependents (FR-008). Like every cancelled card, a cancelled
  manual card does **not** release them (spec edge case).

## `CardAction.COMPLETE_MANUAL_TASK = "complete_manual_task"` (new)

- Offered by `allowed_actions_for` if, and only if, `kind == manual_task` and
  `state == awaiting_human`.
- `RESOLVE_GATE` is no longer offered for a `manual_task` card.
- Effect: `awaiting_human → done`, with event type `manual_task.completed`,
  then `advance_ready_dependents`.

## `CreateCardAction` (`coordinator.py`)

```text
CreateCardAction
  … existing fields …
  task_node_id: str | None = None   # NEW; set only by code, never parsed from coordinator output
```

## Materialisation input: the approved candidate

This is the existing `cab2_proposal` artifact, the `decomposition_gate`'s
`target_artifact_id`, read with `load_candidate(strict=False)`. Strict parsing
gains prerequisite validation (R11):

- every prerequisite is a `task_node_id` of the same candidate;
- no task lists itself;
- the prerequisite graph is acyclic.

### Materialisation output for a candidate of tasks T

For each *t* ∈ T, in candidate order:

| *t*.classification | Cards | Relations |
| --- | --- | --- |
| `coding` | `impl(t)`: implementation, `("coder",)`, write, title = *t*.title. `ver(t)`: verification, `("verifier",)`, read_only, title = "Verify: *t*.title". | `ver(t)` depends on `impl(t)`. `impl(t)` depends on `head(p)` for each prerequisite *p*. |
| `manual` | `man(t)`: manual_task, title = *t*.title | `man(t)` depends on `head(p)` for each prerequisite *p* |

Here `head(p)` is `impl(p)` for a coding prerequisite and `man(p)` for a manual
one. Initial states: a card with no dependency is `ready` (implementation) or
`awaiting_human` (manual). A card with dependencies is `waiting_dependency`,
and the cascade that runs right after the gate approval promotes it when its
dependencies are already done. `impl(t)` and `man(t)` get a `task_spec`
artifact. Idempotency: a no-op when the workflow already has any card with a
non-null `task_node_id`.

## `task_spec` reference artifact

| Field | Value |
| --- | --- |
| `producer_card_id` | the `impl(t)` or `man(t)` card |
| `logical_name` | `task_spec` |
| `revision` | 1 |
| `trust` | `operator_approved` |
| `content` | Markdown: `# <title>`, classification, prerequisites (by title), the body, then the "Estimate (agent, unverified)" section when *t* has an estimate. This is the text `published_body` used to put into child tickets. |

## Verification rounds (R6)

`round(t)` = the number of verification cards with `task_node_id == t`.

Routing of a finished verification card *v* with `task_node_id = t`:

| Findings | `round(t)` < cap | `round(t)` ≥ cap |
| --- | --- | --- |
| none | nothing, clean | nothing, clean |
| escalations only | `coordinator_review` per escalation (as today), tagged *t* | same |
| any non-escalation | `Remediate:` implementation per finding + one re-verification depending on them, all tagged *t*. Escalations as usual. | one `coordinator_review` "Verification cap reached: …" tagged *t*. No remediation. |

The cap is `Settings.max_verify_iterations`, default 3, passed as
`DispatchServices.verify_round_cap`. A verification card without a
`task_node_id` is routed exactly as today.

## `WorkflowSummaryOut` (`schemas.py`) / `BoardWorkflowSummary` (`types/workflows.ts`)

| Field | Change |
| --- | --- |
| `parent_workflow_id` | **Removed** (FR-019) |
| `open_manual_task_count: int` | **Added**, default 0: `manual_task` cards not in `done` or `cancelled` |

## Removed entities

`ChildTaskLinks`, `ChildTaskStore`, `ChildTaskSchedule`, `ChildTaskLinkRow`,
`ScheduledTask`, `SubtaskSentinel`, `ManualTaskSentinel`,
`Workflow.skip_decomposition` and `AcceptedTaskIntake.skip_decomposition`. The
full list, and what is deliberately kept, is in research R12.
