# M-B · Orchestrator State Machine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

> **STATUS: DRAFT (task-level).** Depends on M-A's landed code
> (`SessionStore`, `ModelPolicy`, `KESTREL_` settings). Before
> execution, expand each task to step-level TDD detail
> (superpowers:writing-plans) against the then-current codebase.

**Goal:** A durable per-work-item state machine plus a StepRunner
that executes model-selected Claude steps — the full lifecycle
drivable end-to-end with stubbed/manual inputs, no GitHub yet.

**Architecture:** `work_item` rows carry the lifecycle state
(spec SRD §2.3). Transitions are pure functions over
`(state, event)` — no I/O — so they are table-testable. A thin
orchestrator service applies transitions, persists them, and invokes
`StepRunner`, which wraps M-A's `SessionRunner` with
`ModelPolicy.model_for(step)` and records per-step sessions.

**Tech Stack:** as M-A (FastAPI, SQLAlchemy/Alembic, pytest).

## Global Constraints

Same as M-A (80 cols, uv-only, Sphinx docstrings, full typing,
Alembic-only schema changes, "Ensure …" test docstrings).

---

### Task 1: WorkItem model, table, migration

**Files:**
- Create: `backend/app/orchestrator/__init__.py`
- Modify: `backend/app/persistence/tables.py` (add `WorkItemRow`)
- Create: `backend/alembic/versions/0002_work_item.py`
- Test: `backend/tests/test_orchestrator_models.py`

**Interfaces:**
- Produces: `WorkItemRow(id, source, external_id, title, state,
  created_at, updated_at)` with unique `(source, external_id)`;
  a `WorkItem` domain dataclass mirroring it.

- [ ] Table + migration `0002` written and applied.
- [ ] Round-trip test: insert, reload, unique-constraint enforced.
- [ ] Commit.

### Task 2: Pure state machine

**Files:**
- Create: `backend/app/orchestrator/states.py`
- Test: `backend/tests/test_states.py`

**Interfaces:**
- Produces: `WorkItemState` (str enum) with the spec §2.3 states:
  `intake, analyzing, awaiting_clarification,
  proposing_description, awaiting_description_approval,
  updating_issue, planning, awaiting_plan_approval, implementing,
  paused_for_clarification, creating_pr, done, rejected, failed`;
  `WorkItemEvent` (str enum) for triggers (e.g. `gaps_found`,
  `no_gaps`, `answers_submitted`, `approved`, `rejected`,
  `refine_requested`, `blocker_raised`, `blocker_answered`,
  `step_succeeded`, `step_failed`);
  `transition(state, event) -> WorkItemState` raising
  `InvalidTransition` otherwise.

- [ ] Full transition table implemented as data, not if-chains.
- [ ] Table-driven tests cover every legal edge and a sample of
      illegal ones (parametrized).
- [ ] Commit.

### Task 3: StepRunner

**Files:**
- Create: `backend/app/orchestrator/step_runner.py`
- Modify: `backend/app/persistence/tables.py` (+ migration `0003`:
  add `work_item_id`, `step`, `model` columns to `session`)
- Test: `backend/tests/test_step_runner.py`

**Interfaces:**
- Consumes: `SessionRunner.start/resume` and `build_argv(model=…)`
  (M-A Task 4), `get_policy()` (M-A), `SessionStore` (M-A).
- Produces: `StepRunner.run_step(work_item_id: int, step: str,
  prompt: str, resume_id: str | None = None) -> StepResult` where
  `StepResult` carries `session_id`, `final_text` (the result
  event's text), and `status`. Applies
  `get_policy().model_for(step)`; persists the step/model on the
  session row.

- [ ] Implemented with a fake `SessionRunner` in tests (no real
      claude calls; feed canned stream-json lines).
- [ ] Model policy verifiably applied per step (argv assertion).
- [ ] Commit.

### Task 4: Orchestrator service + manual-drive endpoints

**Files:**
- Create: `backend/app/orchestrator/service.py`
- Create: `backend/app/routers/work_items.py`
- Modify: `backend/app/main.py` (include router)
- Test: `backend/tests/test_work_items_api.py`

**Interfaces:**
- Produces: `POST /api/work-items` (manual creation: title + body —
  the stubbed stand-in for GitHub intake), `GET /api/work-items`,
  `GET /api/work-items/{id}`, and a temporary
  `POST /api/work-items/{id}/advance` accepting a `WorkItemEvent`
  name to drive transitions manually. The service persists every
  transition. (The `advance` endpoint is scaffolding; M-D/M-E
  replace it with real questionnaire/approval endpoints.)

- [ ] Lifecycle drivable intake → done via the API with stubbed
      step execution.
- [ ] Illegal event returns 409 with the current state.
- [ ] Commit.

### Task 5: Restart durability

**Files:**
- Test: `backend/tests/test_orchestrator_durability.py`

- [ ] Test: drive an item to `awaiting_plan_approval`, rebuild all
      singletons (fresh registry/service on the same DB), assert
      state and step history restored.
- [ ] Commit.

## Verification

- `uv run pytest -v` green; state-machine table tests cover all
  legal transitions.
- Manual: create a work item via `curl`, advance it through the
  whole lifecycle, restart the backend at `awaiting_plan_approval`,
  confirm `GET /api/work-items/{id}` shows the same state.
- Tick M-B in `kestrel-roadmap.md`.
