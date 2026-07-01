"""Tests for the persistence layer and migrations."""
from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config


def _migrate(db_path: Path) -> str:
    """Apply all migrations to a fresh SQLite file."""
    url = f"sqlite:///{db_path}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return url


def test_migrations_create_tables(tmp_path: Path) -> None:
    """Ensure migrations create the session and event tables."""
    url = _migrate(tmp_path / "test.db")
    inspector = sa.inspect(sa.create_engine(url))
    names = set(inspector.get_table_names())
    assert {"session", "event"} <= names
