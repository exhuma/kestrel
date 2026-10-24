"""Shared test-only setup for the board domain (feature 026).

Not a ``conftest.py`` fixture on purpose: every board test module wants
this at *module* scope (building fixed ``Workflow``/``WorkCard`` objects
alongside it), not per-test-function fixture injection.
"""
from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.orm import sessionmaker

from alembic import command


def board_session_factory(tmp_path: Path) -> sessionmaker:
    """Return a session factory for an isolated, migrated SQLite database."""
    database = tmp_path / "board.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "head")
    return sessionmaker(bind=sa.create_engine(f"sqlite:///{database}"))
