"""Tests for the per-issue dismissal store."""
from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.persistence.dismissal_store import DismissalStore


def _factory(tmp_path: Path):
    """Build a sessionmaker on a freshly migrated SQLite file."""
    url = f"sqlite:///{tmp_path / 'd.db'}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return sessionmaker(bind=sa.create_engine(url))


def test_add_then_is_dismissed(tmp_path: Path) -> None:
    """Ensure a dismissed issue reads back as dismissed; others do not."""
    store = DismissalStore(_factory(tmp_path))
    assert store.is_dismissed("o/r", 7) is False
    store.add("o/r", 7)
    assert store.is_dismissed("o/r", 7) is True
    # A different issue in the same repo is unaffected.
    assert store.is_dismissed("o/r", 8) is False


def test_clear_removes_dismissal(tmp_path: Path) -> None:
    """Ensure clear() un-dismisses an issue."""
    store = DismissalStore(_factory(tmp_path))
    store.add("o/r", 7)
    store.clear("o/r", 7)
    assert store.is_dismissed("o/r", 7) is False


def test_add_is_idempotent(tmp_path: Path) -> None:
    """Ensure adding the same dismissal twice does not error."""
    store = DismissalStore(_factory(tmp_path))
    store.add("o/r", 7)
    store.add("o/r", 7)
    assert store.is_dismissed("o/r", 7) is True


def test_dismissal_is_durable(tmp_path: Path) -> None:
    """Ensure a dismissal survives a fresh store instance (persisted)."""
    factory = _factory(tmp_path)
    DismissalStore(factory).add("o/r", 7)
    # A brand-new store over the same DB still sees it.
    assert DismissalStore(factory).is_dismissed("o/r", 7) is True
