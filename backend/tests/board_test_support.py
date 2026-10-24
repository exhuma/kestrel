"""Shared test-only setup for the board domain (feature 026).

Not a ``conftest.py`` fixture on purpose: every board test module wants
this at *module* scope (building fixed ``Workflow``/``WorkCard`` objects
alongside it), not per-test-function fixture injection.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import sessionmaker

from app.models_board import Workflow
from app.persistence.board_store import BoardStore
from tests.database_support import isolated_engine


def board_session_factory(tmp_path: Path) -> sessionmaker:
    """Return a session factory for the test's isolated, migrated database.

    Every call with the same *tmp_path* shares one database.
    """
    return sessionmaker(bind=isolated_engine(tmp_path))


def seed_workflows(factory: sessionmaker, *workflow_ids: str) -> None:
    """Create a bare workflow for each id, for rows that must refer to one.

    The database enforces foreign keys: a projection, card or comment
    needs its workflow to exist.
    """
    store = BoardStore(factory)
    for workflow_id in workflow_ids:
        store.create_workflow(Workflow(
            id=workflow_id, source="github-issue",
            task_ref=f"o/r#{workflow_id}", repo="o/r", base_branch="main",
            source_visibility="public", title=workflow_id,
        ))
