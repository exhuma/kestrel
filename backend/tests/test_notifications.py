"""Tests for the notification record's signal classification and store."""
from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.notifications import signal_class
from app.persistence.notification_store import NotificationStore


def _migrate(db_path: Path) -> str:
    """Apply all migrations to a fresh SQLite file."""
    url = f"sqlite:///{db_path}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return url


def _store(tmp_path: Path) -> NotificationStore:
    """Build a store on a freshly migrated SQLite file."""
    url = _migrate(tmp_path / "notif.db")
    return NotificationStore(sessionmaker(bind=sa.create_engine(url)))


def test_migrations_create_notification_table(tmp_path: Path) -> None:
    """Ensure migrations create the notification table."""
    url = _migrate(tmp_path / "t.db")
    names = set(sa.inspect(sa.create_engine(url)).get_table_names())
    assert "notification" in names


def test_signal_class_splits_gates_from_summaries() -> None:
    """Ensure awaiting_* gates are action-required and rest are summaries."""
    assert signal_class("awaiting_plan_approval") == "action_required"
    assert signal_class("awaiting_refine_input") == "action_required"
    assert signal_class("done") == "summary"
    assert signal_class("failed") == "summary"


def test_store_list_all_orders_newest_first(tmp_path: Path) -> None:
    """Ensure notifications list most recent first."""
    store = _store(tmp_path)
    store.add(
        workflow_id="wf-1", repo="o/r", issue_number=1,
        status="done", message="first",
    )
    store.add(
        workflow_id="wf-1", repo="o/r", issue_number=1,
        status="failed", message="second",
    )
    items = store.list_all()
    assert [n.message for n in items] == ["second", "first"]


def test_store_mark_read(tmp_path: Path) -> None:
    """Ensure mark_read flips the read flag for that row only."""
    store = _store(tmp_path)
    store.add(
        workflow_id="wf-1", repo="o/r", issue_number=1,
        status="done", message="x",
    )
    notification_id = store.list_all()[0].id
    store.mark_read(notification_id)
    assert store.list_all()[0].read is True
