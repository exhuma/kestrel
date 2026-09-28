# Contract: board API additions

**Feature**: `specs/029-workflow-visualisation` | **Date**: 2026-09-28

Amends `specs/026-autonomous-work-board/contracts/board-api.md`. Four **additive,
read-only** fields on existing responses. No endpoint is added, no existing field
is renamed or changes meaning, and nothing becomes writable.

Each exists because a requirement the developer chose to keep cannot otherwise
hold. They were found by a consistency audit on 2026-09-28, after a first draft of
this feature wrongly assumed the board API was already complete.

Per constitution Principle I the backend schema and
`frontend/src/types/workflows.ts` change in the **same commit** — the type contract
may not drift.

---

## A1. Decomposition parent link — `WorkflowSummaryOut`

**Requirement**: FR-040. **Unblocks**: FR-002, SC-001.

A nullable identifier naming the workflow this request was decomposed from.

**Why it is needed at all.** `publish_decomposition` creates each child through
`task_source.create_subtask` (`backend/app/services/board/decomposition.py:134-160`),
so every child is re-ingested as *its own workflow* with its own source ref. The
parent relationship is already queryable —
`ChildTaskStore.parent_workflow_id(task_ref) -> str | None`
(`backend/app/persistence/child_task_store.py:36`) — but is exposed by **no schema
and no router**, so the projection layer need only call a lookup that exists. This
is exactly why decomposition children still read as sibling top-level entries,
which is problem 1 of this feature's spec.

**Why the client cannot work around it.** The relationship is absent from every
response. There is nothing to infer it from: a child's source ref does not encode
its parent, and matching on titles would be a guess.

**Semantics**:

- `null` — this request was not decomposed from anything (the common case).
- otherwise — the id of the parent workflow, which the board uses to nest this
  request inside the parent's card instead of listing it top-level.
- A parent that is itself filtered out of the listing (e.g. terminal, with
  `include_completed=false`) MUST NOT cause its child to disappear. The child falls
  back to top-level rather than being nested under something absent — FR-002's
  guarantee is that every request appears exactly **once**, not at most once.

---

## A2. Human title — `WorkflowSummaryOut`, `BoardSnapshotOut`

**Requirement**: FR-041. **Unblocks**: FR-003, SC-002.

The request's human-readable title, **in addition to** `task_label`.

**Why it is needed.** `task_label` is set from `workflow.task_ref`
(`backend/app/routers/board_views.py:117,137`) — the source-native reference such
as `owner/name#123` (`backend/app/models_board.py:145`). `Workflow.title` exists on
the domain model — `backend/app/models_board.py:147`, "safe display title after
input acceptance", already used to build the delivery title at
`backend/app/services/board/delivery.py:43` — but appears on neither DTO. So today a
board card can show what a request *is called by its tracker* but not what it *is
about*.

**Both are kept, deliberately**: the reference identifies (and is what the operator
searches their tracker for), the title explains. FR-003 asks for both; collapsing
them would lose one.

**Semantics**: a request with no recorded title falls back to its `task_label`
rather than rendering blank.

---

## A3. Interview round and cap — gate detail on `WorkCardSummaryOut`

**Requirement**: FR-042. **Unblocks**: FR-024, FR-027, SC-006.

A nullable `{ round, cap }` on the gate detail of a gate awaiting interview
answers.

**Why it is needed.** Feature 028 (`a353f9b`) put a real round cap in force, but
touched services, config and tests only — `grep round backend/app/schemas.py`
returns nothing. The round is derived rather than stored
(`backend/app/services/board/refinement_rounds.py:4-10`) and reaches only the agent
envelope (`:137`); the cap is server configuration
(`board_refinement_round_cap`, `backend/app/config.py:340`). Neither has ever
reached a client.

**Why the client cannot work around it.** The round is a server-side derivation and
the cap is server config. Counting prior artifacts client-side would approximate
the round and could not discover the cap at all — and "round 3 of 3" is precisely
the statement FR-024 requires, because it is the operator's last chance to answer
before assumptions are baked into the PRD.

**Semantics**:

- `null` — not a round-capped gate. Renders as a single round (FR-027), not as
  zero-of-zero.
- **The cap defaults to 1** (`board_refinement_round_cap: int = Field(default=1, ge=1)`,
  `backend/app/config.py:340`), so on a default deployment the single-round case of
  FR-027 is the *common* path, not a rare edge. Build and test it as the default.
- `round` is 1-based; `round === cap` is what the UI turns into the final-round
  warning. The warning is derived from the values so the two cannot disagree.

---

## A4. Cap-exhausted marker — `WorkflowSummaryOut`

**Requirement**: FR-043. **Unblocks**: FR-005's `cap-reached` treatment.

Whether this request has exhausted its round cap without a usable answer.

**Why it is needed.** FR-005 requires three *non-interchangeable* treatments, one
of which is cap-reached. Nothing on the listing marks cap exhaustion today.

**Why it is a field rather than a client derivation.** Even with A3, a client could
only compare `round` to `cap` on a gate it happens to be looking at — the board
lists requests without their gates, and "reached the cap without a usable answer"
is a judgement the pipeline makes, not an arithmetic identity. Recording it as a
fact keeps the board honest and the rule single-sourced (Principle II: the backend
owns the judgement).

---

## Boundary

These four make **facts the backend already knows** visible. If satisfying one
appears to require new behaviour — a new state, a new transition, a write path, a
new endpoint — that is a finding to raise with the developer, not to build
(FR-039). The phase projection in particular stays display-only and must never
become a driver (spec 026 FR-037).

## Verification

| Addition | Backend test | Frontend test |
| --- | --- | --- |
| A1 parent link | `null` for a normal request; the parent id for a decomposed child; child not nested under an absent parent | Board nests a child inside its parent; falls back to top-level when the parent is missing |
| A2 title | Present on both DTOs; falls back to `task_label` when unrecorded | Card shows ref **and** title |
| A3 round/cap | `null` for a non-capped gate; `{round, cap}` on a capped one | Round indicator states "3 of 3"; single round when `null` |
| A4 cap-exhausted | `false` normally; `true` once exhausted | `cap-reached` treatment distinguishable from `your-move` |

Backend tests are pytest against the routers; frontend tests mock all HTTP
(Principle III). Both sides of each addition land in the same commit, and
`specs/026-autonomous-work-board/contracts/board-api.md` is amended in that commit
too.
