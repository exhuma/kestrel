"""Tests for the persistence layer and migrations."""
from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import sessionmaker

from app.models import ParsedEvent
from app.persistence.store import SessionStore
from app.storage.registry import SessionRegistry


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


def _store(tmp_path: Path) -> SessionStore:
    """Build a store on a freshly migrated SQLite file."""
    url = _migrate(tmp_path / "store.db")
    factory = sessionmaker(bind=sa.create_engine(url))
    return SessionStore(factory)


def test_registry_survives_restart(tmp_path: Path) -> None:
    """Ensure sessions and events persist across registries."""
    store = _store(tmp_path)
    reg = SessionRegistry(store=store)
    reg.create("s1", "/tmp/s1")
    reg.append_event(
        "s1",
        ParsedEvent(
            type="assistant", session_id="s1", raw={"n": 1}
        ),
    )
    reg.set_status("s1", "idle")

    fresh = SessionRegistry(store=store)
    fresh.preload(store.load_all())
    rec = fresh.get("s1")
    assert rec is not None
    assert rec.cwd == "/tmp/s1"
    assert rec.status == "idle"
    assert [e.raw for e in rec.events] == [{"n": 1}]
