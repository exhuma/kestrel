"""Tests for durable workflow run persistence."""
from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import sessionmaker

from app.models_workflow import WorkflowRun, WorkflowStep
from app.persistence.workflow_store import WorkflowStore
from app.storage.workflow_registry import WorkflowRegistry


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
