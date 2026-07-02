# M-B · Durable Workflow Runs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

> Supersedes the task-level draft
> `2026-07-01-kestrel-m-b-orchestrator.md`, which was written
> against the pre-merge spike. This plan targets the real master:
> `WorkflowService` (refine → plan → implement → PR, gates as
> awaited futures), in-memory `WorkflowRegistry`, and the M-A
> persistence layer (SQLAlchemy/Alembic, `SessionStore`).

**Goal:** Workflow runs survive a backend restart — gate-parked
runs (awaiting input/approval) resume exactly where they were;
mid-step runs fail loudly — and every Claude step uses the model
the policy selects.

**Architecture:** Keep the proven coroutine-per-run driver, but
make every state transition a persisted checkpoint
(`WorkflowStore`, mirroring M-A's `SessionStore`). Split the
linear `_drive` into resumable phases that dispatch on the
persisted step status, so a `recover()` pass at startup can
re-enter a run at its gate. Resume of the actual Claude session
uses the persisted `session_id` + workspace (`--resume`, the
spike-verified mechanic). `ModelPolicy` (M-A, currently dead
code) is wired into `run_blocking` via a new `model` argument.

**Tech Stack:** Python 3.12, FastAPI lifespan, SQLAlchemy 2.x +
Alembic (existing `backend/alembic/`), pytest(-asyncio).

## Global Constraints

- 80-char lines; `uv` only; Sphinx docstrings + full typing;
  `from __future__ import annotations`; no `Any`, no `global`.
- Schema changes via Alembic only (no `create_all`, no raw DDL).
- Tests in `backend/tests/`, docstrings start with "Ensure …".
- All commands run from `backend/` unless noted.
- Follow the write-through pattern established by
  `app/persistence/store.py` + `app/storage/registry.py` (M-A).

---

### Task 1: Workflow tables, migration, WorkflowStore

**Files:**
- Modify: `backend/app/models_workflow.py` (add `model` field)
- Modify: `backend/app/persistence/tables.py` (two new rows)
- Create: `backend/alembic/versions/0002_workflow_tables.py`
- Create: `backend/app/persistence/workflow_store.py`
- Test: `backend/tests/test_workflow_persistence.py` (new)

**Interfaces:**
- Consumes: `Base`, `get_sessionmaker()` (M-A);
  `WorkflowRun`/`WorkflowStep` dataclasses (existing).
- Produces:
  - `WorkflowStep.model: str | None = None` (new field).
  - `WorkflowRunRow` / `WorkflowStepRow` ORM rows; step PK is
    `(workflow_id, position)` so `save` is a clean upsert.
  - `WorkflowStore(factory)` with `save(run: WorkflowRun) ->
    None` (upsert run + all steps) and
    `load_all() -> list[WorkflowRun]`; singleton
    `get_workflow_store()`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_workflow_persistence.py`:

```python
"""Tests for durable workflow run persistence."""
from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import sessionmaker

from app.models_workflow import WorkflowRun, WorkflowStep
from app.persistence.workflow_store import WorkflowStore


def _migrate(db_path: Path) -> str:
    """Apply all migrations to a fresh SQLite file."""
    url = f"sqlite:///{db_path}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return url


def _store(tmp_path: Path) -> WorkflowStore:
    """Build a store on a freshly migrated SQLite file."""
    url = _migrate(tmp_path / "wf.db")
    return WorkflowStore(
        sessionmaker(bind=sa.create_engine(url))
    )


def _run() -> WorkflowRun:
    return WorkflowRun(
        id="wf-1",
        repo="o/r",
        issue_number=7,
        issue_title="Add widget",
        base_branch="main",
        branch="kestrel/issue-7",
        workspace="/tmp/wf-1",
        status="awaiting_refine_input",
        steps=[
            WorkflowStep(
                name="refine",
                session_id="s1",
                status="awaiting_input",
                deliverable="Round 1 questions",
                model="sonnet",
            ),
            WorkflowStep(name="plan"),
            WorkflowStep(name="implement"),
        ],
    )


def test_migrations_create_workflow_tables(
    tmp_path: Path,
) -> None:
    """Ensure migrations create the workflow tables."""
    url = _migrate(tmp_path / "t.db")
    names = set(
        sa.inspect(sa.create_engine(url)).get_table_names()
    )
    assert {"workflow_run", "workflow_step"} <= names


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    """Ensure a run and its steps survive a save/load cycle."""
    store = _store(tmp_path)
    store.save(_run())
    loaded = store.load_all()
    assert len(loaded) == 1
    run = loaded[0]
    assert run.id == "wf-1"
    assert run.status == "awaiting_refine_input"
    assert run.workspace == "/tmp/wf-1"
    assert [s.name for s in run.steps] == [
        "refine", "plan", "implement",
    ]
    assert run.steps[0].session_id == "s1"
    assert run.steps[0].deliverable == "Round 1 questions"
    assert run.steps[0].model == "sonnet"


def test_save_is_an_upsert(tmp_path: Path) -> None:
    """Ensure repeated saves update rather than duplicate."""
    store = _store(tmp_path)
    run = _run()
    store.save(run)
    run.status = "done"
    run.steps[0].status = "done"
    store.save(run)
    loaded = store.load_all()
    assert len(loaded) == 1
    assert loaded[0].status == "done"
    assert loaded[0].steps[0].status == "done"
    assert len(loaded[0].steps) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_workflow_persistence.py -v`
Expected: FAIL with
`ModuleNotFoundError: app.persistence.workflow_store`.

- [ ] **Step 3: Add the `model` field and ORM rows**

`backend/app/models_workflow.py` — extend `WorkflowStep`:

```python
@dataclass
class WorkflowStep:
    """One step of a workflow run, with its deliverable."""

    name: str
    session_id: str | None = None
    status: str = "pending"
    deliverable: str | None = None
    model: str | None = None
```

`backend/app/persistence/tables.py` — append:

```python
class WorkflowRunRow(Base):
    """One workflow run (durable mirror of WorkflowRun)."""

    __tablename__ = "workflow_run"

    id: Mapped[str] = mapped_column(primary_key=True)
    repo: Mapped[str] = mapped_column()
    issue_number: Mapped[int] = mapped_column()
    issue_title: Mapped[str] = mapped_column(default="")
    base_branch: Mapped[str] = mapped_column(default="")
    branch: Mapped[str] = mapped_column(default="")
    workspace: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(default="pending")
    pr_url: Mapped[str | None] = mapped_column(nullable=True)
    error: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )


class WorkflowStepRow(Base):
    """One step of a persisted workflow run."""

    __tablename__ = "workflow_step"

    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_run.id"), primary_key=True
    )
    position: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column()
    session_id: Mapped[str | None] = mapped_column(
        nullable=True
    )
    status: Mapped[str] = mapped_column(default="pending")
    deliverable: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    model: Mapped[str | None] = mapped_column(nullable=True)
```

- [ ] **Step 4: Write migration 0002**

Create `backend/alembic/versions/0002_workflow_tables.py`:

```python
"""Workflow run and step tables.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-02
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the workflow_run and workflow_step tables."""
    op.create_table(
        "workflow_run",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("repo", sa.String(), nullable=False),
        sa.Column(
            "issue_number", sa.Integer(), nullable=False
        ),
        sa.Column("issue_title", sa.String(), nullable=False),
        sa.Column("base_branch", sa.String(), nullable=False),
        sa.Column("branch", sa.String(), nullable=False),
        sa.Column("workspace", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("pr_url", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_table(
        "workflow_step",
        sa.Column(
            "workflow_id",
            sa.String(),
            sa.ForeignKey("workflow_run.id"),
            primary_key=True,
        ),
        sa.Column(
            "position", sa.Integer(), primary_key=True
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("deliverable", sa.Text(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
    )


def downgrade() -> None:
    """Drop the workflow tables."""
    op.drop_table("workflow_step")
    op.drop_table("workflow_run")
```

- [ ] **Step 5: Implement the store**

Create `backend/app/persistence/workflow_store.py`:

```python
"""Write-through persistence for workflow runs."""
from __future__ import annotations

from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models_workflow import WorkflowRun, WorkflowStep
from app.persistence.db import get_sessionmaker
from app.persistence.tables import (
    WorkflowRunRow,
    WorkflowStepRow,
)


class WorkflowStore:
    """Persists workflow runs and their steps."""

    def __init__(
        self, factory: sessionmaker[Session]
    ) -> None:
        self._factory = factory

    def save(self, run: WorkflowRun) -> None:
        """
        Upsert a run and all of its steps.

        Called at every state transition, so the database
        always holds the latest checkpoint.

        :param run: The run to persist.
        """
        with self._factory.begin() as db:
            db.merge(
                WorkflowRunRow(
                    id=run.id,
                    repo=run.repo,
                    issue_number=run.issue_number,
                    issue_title=run.issue_title,
                    base_branch=run.base_branch,
                    branch=run.branch,
                    workspace=run.workspace,
                    status=run.status,
                    pr_url=run.pr_url,
                    error=run.error,
                )
            )
            for i, step in enumerate(run.steps):
                db.merge(
                    WorkflowStepRow(
                        workflow_id=run.id,
                        position=i,
                        name=step.name,
                        session_id=step.session_id,
                        status=step.status,
                        deliverable=step.deliverable,
                        model=step.model,
                    )
                )

    def load_all(self) -> list[WorkflowRun]:
        """
        Load all persisted runs with their steps.

        :returns: Fully hydrated runs, steps in order.
        """
        with self._factory() as db:
            runs: list[WorkflowRun] = []
            for row in db.scalars(select(WorkflowRunRow)):
                stmt = (
                    select(WorkflowStepRow)
                    .where(
                        WorkflowStepRow.workflow_id == row.id
                    )
                    .order_by(WorkflowStepRow.position)
                )
                steps = [
                    WorkflowStep(
                        name=s.name,
                        session_id=s.session_id,
                        status=s.status,
                        deliverable=s.deliverable,
                        model=s.model,
                    )
                    for s in db.scalars(stmt)
                ]
                runs.append(
                    WorkflowRun(
                        id=row.id,
                        repo=row.repo,
                        issue_number=row.issue_number,
                        issue_title=row.issue_title,
                        base_branch=row.base_branch,
                        branch=row.branch,
                        workspace=row.workspace,
                        status=row.status,
                        steps=steps,
                        pr_url=row.pr_url,
                        error=row.error,
                    )
                )
            return runs


@lru_cache
def get_workflow_store() -> WorkflowStore:
    """
    Return the process-wide WorkflowStore singleton.

    :returns: The cached workflow store instance.
    """
    return WorkflowStore(get_sessionmaker())
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_workflow_persistence.py -v`
Expected: 3 PASS.

- [ ] **Step 7: Run the full suite and commit**

Run: `uv run pytest -q` — all pass.

```bash
git add -A
git commit -m "feat: persist workflow runs and steps (store + tables)"
```

---

### Task 2: Write-through WorkflowRegistry + preload

**Files:**
- Modify: `backend/app/storage/workflow_registry.py`
- Test: `backend/tests/test_workflow_persistence.py` (extend)

**Interfaces:**
- Consumes: `WorkflowStore`, `get_workflow_store()` (Task 1).
- Produces: `WorkflowRegistry(store: WorkflowStore | None =
  None)`; `create()` writes through; new `save(run)` persists
  the run's current state (no-op without store); new
  `preload(runs)`; `get_workflow_registry()` wires the store
  and preloads persisted runs. Task 4's checkpoints call
  `registry.save(run)`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_workflow_persistence.py`:

```python
from app.storage.workflow_registry import WorkflowRegistry


def test_registry_survives_restart(tmp_path: Path) -> None:
    """Ensure runs persist across registry rebuilds."""
    store = _store(tmp_path)
    reg = WorkflowRegistry(store=store)
    run = _run()
    reg.create(run)
    run.status = "awaiting_refine_approval"
    reg.save(run)

    fresh = WorkflowRegistry(store=store)
    fresh.preload(store.load_all())
    loaded = fresh.get("wf-1")
    assert loaded is not None
    assert loaded.status == "awaiting_refine_approval"
    assert loaded.steps[0].session_id == "s1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_workflow_persistence.py -v`
Expected: the new test FAILS with `TypeError` (unexpected
keyword `store`).

- [ ] **Step 3: Implement the write-through registry**

Replace `backend/app/storage/workflow_registry.py` with:

```python
"""Registry of workflow runs with optional persistence."""
from __future__ import annotations

from functools import lru_cache

from app.models_workflow import WorkflowRun
from app.persistence.workflow_store import (
    WorkflowStore,
    get_workflow_store,
)


class WorkflowRegistry:
    """Stores workflow runs in insertion order."""

    def __init__(
        self, store: WorkflowStore | None = None
    ) -> None:
        self._runs: dict[str, WorkflowRun] = {}
        self._store = store

    def create(self, run: WorkflowRun) -> WorkflowRun:
        """
        Store a new run and return it.

        :param run: The run to register.
        :returns: The same run, for chaining.
        """
        self._runs[run.id] = run
        if self._store is not None:
            self._store.save(run)
        return run

    def get(self, workflow_id: str) -> WorkflowRun | None:
        """
        Return a run by id, or None.

        :param workflow_id: Unique id of the run.
        :returns: The run, or None if unknown.
        """
        return self._runs.get(workflow_id)

    def list(self) -> list[WorkflowRun]:
        """
        Return all runs in insertion order.

        :returns: All registered runs.
        """
        return list(self._runs.values())

    def save(self, run: WorkflowRun) -> None:
        """
        Persist a run's current state.

        Called at every workflow state transition; a no-op
        when the registry has no store (unit tests).

        :param run: The run to checkpoint.
        """
        if self._store is not None:
            self._store.save(run)

    def preload(self, runs: list[WorkflowRun]) -> None:
        """
        Seed the registry with persisted runs.

        Does not write back to the store.

        :param runs: Runs loaded from persistence.
        """
        for run in runs:
            self._runs[run.id] = run


@lru_cache
def get_workflow_registry() -> WorkflowRegistry:
    """
    Return the process-wide WorkflowRegistry singleton.

    Preloads persisted runs so history survives restarts.
    Requires migrations (``uv run alembic upgrade head``).

    :returns: The cached workflow registry instance.
    """
    store = get_workflow_store()
    registry = WorkflowRegistry(store=store)
    registry.preload(store.load_all())
    return registry
```

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass (existing service tests construct
`WorkflowRegistry()` with no store — behaviour unchanged).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: write-through workflow registry with preload"
```

---

### Task 3: Wire ModelPolicy into workflow steps

**Files:**
- Modify: `backend/app/policy.py` (add `refine` step)
- Modify: `backend/app/services/runner.py`
  (`run_blocking` gains `model`)
- Modify: `backend/app/services/workflows.py`
  (pass model per phase, record on step)
- Test: `backend/tests/test_policy.py`,
  `backend/tests/test_workflow_service.py` (extend fakes +
  new test)

**Interfaces:**
- Consumes: `ModelPolicy`, `get_policy()`,
  `build_argv(model=…)` (all M-A).
- Produces: `run_blocking(prompt, cwd, permission_mode,
  resume_id=None, on_session_id=None, model=None)`;
  `DEFAULT_MODELS["refine"] == "sonnet"`; each workflow phase
  records its model on `step.model`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_policy.py`:

```python
def test_refine_step_has_a_default_model() -> None:
    """Ensure the workflow's refine step is in the policy."""
    assert ModelPolicy(overrides={}).model_for("refine") == (
        "sonnet"
    )
```

In `backend/tests/test_workflow_service.py`, extend
`_FakeRunner` to accept and record the model (replace the
`run_blocking` method):

```python
    async def run_blocking(self, prompt, cwd, permission_mode,
                           resume_id=None, on_session_id=None,
                           model=None) -> str:
        sid = resume_id or f"s{self._n}"
        self._n += 1
        self.calls = getattr(self, "calls", [])
        self.calls.append(
            {"resume_id": resume_id, "model": model,
             "permission_mode": permission_mode}
        )
        text = self._outputs.pop(0)
        if self.sessions.get(sid) is None:
            self.sessions._records[sid] = SessionRecord(
                session_id=sid, cwd=cwd
            )
        rec = self.sessions.get(sid)
        rec.events.append(
            ParsedEvent("result", sid, {"result": text})
        )
        rec.status = "idle"
        if on_session_id:
            on_session_id(sid)
        return sid
```

And add this test at the end of the file:

```python
@pytest.mark.asyncio
async def test_steps_use_policy_models() -> None:
    """Ensure each phase passes its policy model to claude."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "<REFINED_ISSUE>\nBuild it\n</REFINED_ISSUE>",
        "<PLAN>\nDo it\n</PLAN>",
        "Implemented",
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(
        lambda: svc.get(wid).status
        == "awaiting_refine_approval"
    )
    svc.approve(wid)
    await _wait(
        lambda: svc.get(wid).status
        == "awaiting_plan_approval"
    )
    svc.approve(wid)
    await _wait(
        lambda: svc.get(wid).status
        == "awaiting_implement_approval"
    )
    assert [c["model"] for c in runner.calls] == [
        "sonnet", "sonnet", "sonnet",
    ]
    assert [s.model for s in svc.get(wid).steps] == [
        "sonnet", "sonnet", "sonnet",
    ]
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_policy.py \
tests/test_workflow_service.py -v`
Expected: the policy test FAILS with `KeyError: 'refine'`;
the workflow test FAILS (`model` is None / attribute error).

- [ ] **Step 3: Implement**

`backend/app/policy.py` — add to `DEFAULT_MODELS`:

```python
DEFAULT_MODELS: dict[str, str] = {
    "gap_analysis": "haiku",
    "clarify": "haiku",
    "describe": "sonnet",
    "refine": "sonnet",
    "plan": "sonnet",
    "implement": "sonnet",
}
```

`backend/app/services/runner.py` — `run_blocking` signature
and argv call become:

```python
    async def run_blocking(
        self,
        prompt: str,
        cwd: str,
        permission_mode: str,
        resume_id: str | None = None,
        on_session_id: Callable[[str], None] | None = None,
        model: str | None = None,
    ) -> str:
```

and inside it:

```python
        argv = self.build_argv(
            prompt, resume_id, permission_mode, model
        )
```

(the docstring gains
`:param model: Model alias for --model, or None.`)

`backend/app/services/workflows.py` — import the policy:

```python
from app.policy import get_policy
```

In `_refine`'s loop, `_plan`, and `_implement`, resolve and
record the model, then pass it (exact call sites are shown in
Task 4/5's full method bodies — apply there if executing
in order; if executing this task standalone, add
`model=get_policy().model_for("refine"|"plan"|"implement")`
to each `run_blocking` call and set `step.model` to the same
value just before the call).

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: workflow steps use the model policy"
```

---

### Task 4: Checkpoint every state transition

**Files:**
- Modify: `backend/app/services/workflows.py`
- Test: `backend/tests/test_workflow_service.py` (extend)

**Interfaces:**
- Consumes: `WorkflowRegistry.save(run)` (Task 2).
- Produces: `self.workflows.save(run)` called after every
  status/deliverable mutation, so the DB always mirrors the
  in-memory state. Task 5 relies on these checkpoints being
  complete.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_workflow_persistence.py`
(service + fakes are importable from the service test module):

```python
import asyncio

from tests.test_workflow_service import (
    _FakeGit,
    _FakeGitHub,
    _FakeRunner,
    _wait,
)
from app.config import Settings
from app.services.workflows import WorkflowService
from app.storage.registry import SessionRegistry


def _persistent_service(
    store, github, runner, git
) -> WorkflowService:
    reg = WorkflowRegistry(store=store)
    reg.preload(store.load_all())
    return WorkflowService(
        settings=Settings(
            git_base="https://github.com", github_token="t"
        ),
        sessions=runner.sessions,
        workflows=reg,
        runner=runner,
        git=git,
        github=github,
    )


@pytest.mark.asyncio
async def test_gate_state_is_checkpointed(
    tmp_path: Path,
) -> None:
    """Ensure awaiting states are visible in the database."""
    store = _store(tmp_path)
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "What colour?",
    ])
    svc = _persistent_service(
        store, _FakeGitHub(body="vague"), runner, _FakeGit()
    )
    wid = await svc.create("o/r", 5)
    await _wait(
        lambda: svc.get(wid).status
        == "awaiting_refine_input"
    )
    persisted = {r.id: r for r in store.load_all()}[wid]
    assert persisted.status == "awaiting_refine_input"
    assert persisted.steps[0].status == "awaiting_input"
    assert persisted.steps[0].session_id is not None
    assert persisted.steps[0].deliverable == "What colour?"
```

(add `import pytest` to the file's imports if not present)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest \
tests/test_workflow_persistence.py::test_gate_state_is_checkpointed -v`
Expected: FAIL — the persisted status is still `"pending"`
(only `create()` wrote through; no checkpoints yet).

- [ ] **Step 3: Add checkpoints**

In `backend/app/services/workflows.py`, add
`self.workflows.save(run)` immediately after every mutation
of `run.status`, `run.error`, `run.pr_url`,
`run.issue_title`/`base_branch`, `step.status`,
`step.deliverable`, or `step.session_id` settling. The full
post-refactor method bodies in Task 5 include every
checkpoint — when executing in order, apply Task 5's bodies
and this task's test together if that is simpler; the test
above is the acceptance gate either way.

Checkpoint locations (if applying to the current code
directly): in `_drive` after `run.status = "cloning"`, after
setting `issue_title`/`base_branch`, after the sentinel
branch, after `run.status = "opening_pr"`, after
`run.status = "done"`, and in both `except` branches; in
`_refine` after `step.status = "running"`, after the
`awaiting_approval` block, after `step.status = "done"`, and
after the `awaiting_input` block; in `_plan` and
`_implement` after each `running`/`awaiting_approval`/`done`
assignment.

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: checkpoint workflow state on every transition"
```

---

### Task 5: Resumable phases + recover() on startup

**Files:**
- Modify: `backend/app/services/workflows.py` (restructure)
- Modify: `backend/app/main.py` (lifespan hook)
- Test: `backend/tests/test_workflow_recovery.py` (new)

**Interfaces:**
- Consumes: everything above.
- Produces:
  - Phases dispatch on persisted step status:
    `_refine(run, body=None)` re-enters at the reply-wait or
    the approval gate; `_plan(run)` / `_implement(run)`
    re-enter at their gates; `_deliver(run)` extracted
    (commit/push/PR/done).
  - `_continue(run, issue_body=None)` runs all unfinished
    phases in order.
  - `async recover() -> None`: for each persisted run,
    `awaiting_*` → rebuild `_Control` and spawn `_resume`;
    transient (`pending`, `cloning`, `refining`, `planning`,
    `implementing`, `opening_pr`) → `failed` with
    `error="backend restarted mid-step"`; terminal states
    untouched.
  - `create_app()` registers a lifespan that awaits
    `get_workflow_service().recover()` (httpx ASGITransport
    does not run lifespans, so tests are unaffected).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_workflow_recovery.py`:

```python
"""Tests for workflow recovery after a backend restart."""
from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.persistence.workflow_store import WorkflowStore
from app.storage.registry import SessionRegistry
from tests.test_workflow_persistence import (
    _migrate,
    _persistent_service,
)
from tests.test_workflow_service import (
    _FakeGit,
    _FakeGitHub,
    _FakeRunner,
    _wait,
)


def _store(tmp_path: Path) -> WorkflowStore:
    url = _migrate(tmp_path / "rec.db")
    return WorkflowStore(
        sessionmaker(bind=sa.create_engine(url))
    )


@pytest.mark.asyncio
async def test_recover_resumes_awaiting_input(
    tmp_path: Path,
) -> None:
    """Ensure a run parked at the interview survives restart."""
    store = _store(tmp_path)
    runner1 = _FakeRunner(SessionRegistry(), outputs=[
        "What colour?",
    ])
    svc1 = _persistent_service(
        store, _FakeGitHub(body="vague"), runner1, _FakeGit()
    )
    wid = await svc1.create("o/r", 5)
    await _wait(
        lambda: svc1.get(wid).status
        == "awaiting_refine_input"
    )
    old_sid = svc1.get(wid).steps[0].session_id

    # --- simulated restart: fresh registry/service/fakes ---
    runner2 = _FakeRunner(SessionRegistry(), outputs=[
        "<REFINED_ISSUE>\nBuild a blue widget\n"
        "</REFINED_ISSUE>",
    ])
    svc2 = _persistent_service(
        store, _FakeGitHub(body="vague"), runner2, _FakeGit()
    )
    await svc2.recover()

    run = svc2.get(wid)
    assert run.status == "awaiting_refine_input"

    svc2.reply(wid, "Blue, please")
    await _wait(
        lambda: svc2.get(wid).status
        == "awaiting_refine_approval"
    )
    # The reply resumed the ORIGINAL claude session.
    assert runner2.calls[0]["resume_id"] == old_sid
    assert (
        svc2.get(wid).steps[0].deliverable
        == "Build a blue widget"
    )


@pytest.mark.asyncio
async def test_recover_resumes_awaiting_plan_approval(
    tmp_path: Path,
) -> None:
    """Ensure a run parked at the plan gate survives restart."""
    store = _store(tmp_path)
    runner1 = _FakeRunner(SessionRegistry(), outputs=[
        "The plan",
    ])
    svc1 = _persistent_service(
        store,
        _FakeGitHub(body="x\n\n<!-- kestrel:refined -->"),
        runner1,
        _FakeGit(),
    )
    wid = await svc1.create("o/r", 5)
    await _wait(
        lambda: svc1.get(wid).status
        == "awaiting_plan_approval"
    )

    runner2 = _FakeRunner(SessionRegistry(), outputs=[
        "Implemented",
    ])
    git2 = _FakeGit()
    svc2 = _persistent_service(
        store,
        _FakeGitHub(body="x\n\n<!-- kestrel:refined -->"),
        runner2,
        git2,
    )
    await svc2.recover()
    assert svc2.get(wid).status == "awaiting_plan_approval"

    svc2.approve(wid)
    await _wait(
        lambda: svc2.get(wid).status
        == "awaiting_implement_approval"
    )
    svc2.approve(wid)
    await _wait(lambda: svc2.get(wid).status == "done")
    assert git2.pushed == [svc2.get(wid).branch]


@pytest.mark.asyncio
async def test_recover_fails_mid_step_runs(
    tmp_path: Path,
) -> None:
    """Ensure runs that died mid-step fail loudly."""
    store = _store(tmp_path)
    runner1 = _FakeRunner(SessionRegistry(), outputs=[
        "What colour?",
    ])
    svc1 = _persistent_service(
        store, _FakeGitHub(body="vague"), runner1, _FakeGit()
    )
    wid = await svc1.create("o/r", 5)
    await _wait(
        lambda: svc1.get(wid).status
        == "awaiting_refine_input"
    )
    # Force a mid-step snapshot into the store.
    run = svc1.get(wid)
    run.status = "refining"
    store.save(run)

    svc2 = _persistent_service(
        store, _FakeGitHub(body="vague"),
        _FakeRunner(SessionRegistry(), outputs=[]),
        _FakeGit(),
    )
    await svc2.recover()
    recovered = svc2.get(wid)
    assert recovered.status == "failed"
    assert "restarted" in (recovered.error or "")
    persisted = {r.id: r for r in store.load_all()}[wid]
    assert persisted.status == "failed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_workflow_recovery.py -v`
Expected: FAIL with `AttributeError: 'WorkflowService'
object has no attribute 'recover'`.

- [ ] **Step 3: Restructure the orchestration**

In `backend/app/services/workflows.py`, replace `_drive`,
`_refine`, `_plan`, and `_implement` with the following (the
prompts, `_Control`, `_Decision`, `_await_gate`,
`_result_text`, queries, and commands are unchanged; add
`_TRANSIENT` at module level near `_WF_TASKS`):

```python
_TRANSIENT = (
    "pending", "cloning", "refining",
    "planning", "implementing", "opening_pr",
)
```

```python
    async def recover(self) -> None:
        """
        Resume persisted runs after a process restart.

        Gate-parked runs (awaiting input or approval) get a
        fresh control and a driver task that re-enters at the
        gate. Runs that died mid-step are failed loudly —
        their subprocess is gone.
        """
        for run in self.workflows.list():
            if run.status.startswith("awaiting_"):
                self._control[run.id] = self._new_control()
                task = asyncio.create_task(
                    self._resume(run.id)
                )
                _WF_TASKS.add(task)
                task.add_done_callback(_WF_TASKS.discard)
            elif run.status in _TRANSIENT:
                run.status = "failed"
                run.error = "backend restarted mid-step"
                self.workflows.save(run)

    async def _resume(self, workflow_id: str) -> None:
        """Re-enter a gate-parked run after recovery."""
        run = self.get(workflow_id)
        try:
            await self._continue(run)
        except _Rejected:
            run.status = "rejected"
            self.workflows.save(run)
        except Exception as exc:
            _logger.exception(
                "workflow %s (%s#%s) failed during %s",
                workflow_id, run.repo, run.issue_number,
                run.status,
            )
            run.status = "failed"
            run.error = str(exc)
            self.workflows.save(run)

    async def _drive(self, workflow_id: str) -> None:
        run = self.get(workflow_id)
        try:
            run.status = "cloning"
            self.workflows.save(run)
            issue = await self.github.get_issue(
                run.repo, run.issue_number
            )
            run.issue_title = issue.title
            run.base_branch = (
                await self.github.get_default_branch(run.repo)
            )
            self.workflows.save(run)
            remote = f"{self.settings.git_base}/{run.repo}.git"
            await self.git.clone(remote, run.workspace)
            await self.git.checkout_branch(
                run.workspace, run.branch
            )

            if has_sentinel(issue.body):
                run.steps[0].status = "done"
                run.steps[0].deliverable = issue.body
                self.workflows.save(run)
                await self._continue(run)
            else:
                await self._continue(
                    run, issue_body=issue.body
                )
        except _Rejected:
            run.status = "rejected"
            self.workflows.save(run)
        except Exception as exc:  # record, do not crash loop
            _logger.exception(
                "workflow %s (%s#%s) failed during %s",
                workflow_id, run.repo, run.issue_number,
                run.status,
            )
            run.status = "failed"
            run.error = str(exc)
            self.workflows.save(run)

    async def _continue(
        self, run: WorkflowRun, issue_body: str | None = None
    ) -> None:
        """Run every unfinished phase, then deliver."""
        if run.steps[0].status != "done":
            await self._refine(run, issue_body)
        if run.steps[1].status != "done":
            await self._plan(run)
        if run.steps[2].status != "done":
            await self._implement(run)
        await self._deliver(run)

    async def _refine(
        self, run: WorkflowRun, body: str | None = None
    ) -> None:
        step = run.steps[0]
        sid = step.session_id
        if step.status == "awaiting_approval":
            await self._refine_finalize(run)
            return
        if step.status == "awaiting_input":
            # Recovered mid-interview: wait for the answer,
            # then resume the persisted claude session.
            prompt = await self._control[run.id].replies.get()
        else:
            if body is None:
                raise InvalidWorkflowStateError(
                    "fresh refine needs the issue body"
                )
            prompt = REFINE_PROMPT.format(issue=body)
        model = get_policy().model_for("refine")
        step.model = model
        while True:
            run.status = "refining"
            step.status = "running"
            self.workflows.save(run)
            sid = await self.runner.run_blocking(
                prompt, run.workspace, "plan", resume_id=sid,
                on_session_id=lambda s: setattr(
                    step, "session_id", s
                ),
                model=model,
            )
            text = self._result_text(sid)
            refined = extract_refined_issue(text)
            if refined is not None:
                step.deliverable = refined
                step.status = "awaiting_approval"
                run.status = "awaiting_refine_approval"
                self.workflows.save(run)
                await self._refine_finalize(run)
                return
            # Not yet refined: surface the question as the
            # step's deliverable so the UI can show it.
            step.deliverable = text
            step.status = "awaiting_input"
            run.status = "awaiting_refine_input"
            self.workflows.save(run)
            prompt = await self._control[run.id].replies.get()

    async def _refine_finalize(self, run: WorkflowRun) -> None:
        """Await the refine gate and write back the issue."""
        step = run.steps[0]
        decision = await self._await_gate(run.id)
        if not decision.approved:
            raise _Rejected()
        final = decision.deliverable or (
            step.deliverable or ""
        )
        await self.github.update_issue(
            run.repo, run.issue_number, append_sentinel(final)
        )
        step.deliverable = final
        step.status = "done"
        self.workflows.save(run)

    async def _plan(self, run: WorkflowRun) -> None:
        step = run.steps[1]
        if step.status != "awaiting_approval":
            run.status = "planning"
            step.status = "running"
            model = get_policy().model_for("plan")
            step.model = model
            self.workflows.save(run)
            refined = run.steps[0].deliverable or ""
            sid = await self.runner.run_blocking(
                PLAN_PROMPT.format(issue=refined),
                run.workspace, "plan",
                on_session_id=lambda s: setattr(
                    step, "session_id", s
                ),
                model=model,
            )
            text = self._result_text(sid)
            # Prefer the tagged block; fall back to raw text.
            step.deliverable = extract_plan(text) or text
            step.status = "awaiting_approval"
            run.status = "awaiting_plan_approval"
            self.workflows.save(run)
        decision = await self._await_gate(run.id)
        if not decision.approved:
            raise _Rejected()
        step.status = "done"
        self.workflows.save(run)
        # implement resumes this plan session via
        # run.steps[1].session_id.

    async def _implement(self, run: WorkflowRun) -> None:
        step = run.steps[2]
        if step.status != "awaiting_approval":
            run.status = "implementing"
            step.status = "running"
            model = get_policy().model_for("implement")
            step.model = model
            self.workflows.save(run)
            await self.runner.run_blocking(
                IMPLEMENT_PROMPT, run.workspace,
                "acceptEdits",
                resume_id=run.steps[1].session_id,
                on_session_id=lambda s: setattr(
                    step, "session_id", s
                ),
                model=model,
            )
            step.deliverable = await self.git.diff(
                run.workspace
            )
            step.status = "awaiting_approval"
            run.status = "awaiting_implement_approval"
            self.workflows.save(run)
        decision = await self._await_gate(run.id)
        if not decision.approved:
            raise _Rejected()
        step.status = "done"
        self.workflows.save(run)

    async def _deliver(self, run: WorkflowRun) -> None:
        """Commit, push, open the PR, and finish the run."""
        run.status = "opening_pr"
        self.workflows.save(run)
        await self.git.commit_all(
            run.workspace, f"Implement #{run.issue_number}"
        )
        await self.git.push(run.workspace, run.branch)
        run.pr_url = await self.github.create_pull_request(
            run.repo,
            head=run.branch,
            base=run.base_branch,
            title=(
                f"{run.issue_title} (#{run.issue_number})"
            ),
            body=(
                f"Closes #{run.issue_number}\n\n"
                "Opened by kestrel."
            ),
        )
        run.status = "done"
        self.workflows.save(run)
```

Note: `_refine`'s fresh-start error uses
`InvalidWorkflowStateError` (already imported).

- [ ] **Step 4: Wire recovery into the app lifespan**

`backend/app/main.py` — add the lifespan:

```python
"""FastAPI application factory for kestrel."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Recover persisted workflow runs on startup."""
    from app.services.workflows import get_workflow_service

    await get_workflow_service().recover()
    yield


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    app = FastAPI(title="kestrel", lifespan=_lifespan)
    ...
```

(the rest of `create_app` is unchanged; only the `FastAPI`
constructor gains `lifespan=_lifespan`)

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: all pass, including the three recovery tests and
all pre-existing workflow service tests (fresh-run behaviour
is unchanged).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: workflow runs survive restarts (resume + recover)"
```

---

### Task 6: Docs reconciliation + manual E2E

**Files:**
- Modify: `docs/superpowers/plans/kestrel-roadmap.md`
- Delete: `docs/superpowers/plans/2026-07-01-kestrel-m-b-orchestrator.md`
- Modify: `docs/superpowers/plans/2026-07-01-kestrel-m-c-github.md`
  (banner note)
- Modify: `docs/next-steps.md` (persistence item note)

- [ ] **Step 1: Reconcile the docs**

In `kestrel-roadmap.md`: point M-B at
`2026-07-02-kestrel-m-b-durable-workflows.md`, tick it when
verified, add a status-log row. In the M-C plan, add under
its STATUS banner:

```markdown
> **Reconciliation note (2026-07-02):** master already ships
> `GitHubClient`, `GitService`, and draft-PR creation. M-C's
> remaining scope is webhook ingress (HMAC + dedup), poll
> reconciliation, and per-run git-worktree isolation.
```

In `docs/next-steps.md`, mark the "Durable persistence" /
"Persistence layer" items as addressed for sessions (M-A)
and workflows (M-B), pointing at the kestrel roadmap as the
tracking doc going forward. Delete the superseded M-B draft:

```bash
git rm docs/superpowers/plans/2026-07-01-kestrel-m-b-orchestrator.md
```

- [ ] **Step 2: Manual E2E (the decisive proof)**

1. `uv run alembic upgrade head` (applies 0002).
2. Start the backend; start a workflow on a sandbox issue
   with a vague body; wait for `awaiting_refine_input`.
3. **Restart the backend.**
4. Reload the UI: the run must still be listed in
   `awaiting_refine_input` with its questions; answer them;
   confirm the refine session resumes (same session id in
   the telemetry feed) and the run proceeds to
   `awaiting_refine_approval`.
5. Also verify `GET /api/workflows` after restart shows the
   pre-restart run.

- [ ] **Step 3: Run both suites, tick roadmap, commit**

```bash
cd backend && uv run pytest -q
cd ../frontend && npm test
git add -A
git commit -m "docs: reconcile plans with master; close milestone M-B"
```
