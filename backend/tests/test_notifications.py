"""Tests for the Notifier protocol, templates, and persistence."""
from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.models_workflow import WorkflowRun
from app.notifications import InAppNotifier, render_message
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


def _run(status: str) -> WorkflowRun:
    return WorkflowRun(id="wf-1", repo="o/r", issue_number=5, status=status)


def test_migrations_create_notification_table(tmp_path: Path) -> None:
    """Ensure migrations create the notification table."""
    url = _migrate(tmp_path / "t.db")
    names = set(sa.inspect(sa.create_engine(url)).get_table_names())
    assert "notification" in names


def test_render_message_for_known_statuses() -> None:
    """Ensure known statuses render a specific, repo-scoped message."""
    msg = render_message(_run("awaiting_refine_approval"))
    assert "o/r#5" in msg
    assert "review" in msg.lower()


def test_render_message_falls_back_for_unknown_status() -> None:
    """Ensure an unrecognised status still renders something useful."""
    msg = render_message(_run("some_future_status"))
    assert "o/r#5" in msg


def test_in_app_notifier_records_awaiting_status(tmp_path: Path) -> None:
    """Ensure an awaiting_* status is recorded."""
    store = _store(tmp_path)
    notifier = InAppNotifier(store)
    notifier.notify(_run("awaiting_plan_approval"))
    items = store.list_all()
    assert len(items) == 1
    assert items[0].workflow_id == "wf-1"
    assert items[0].repo == "o/r"
    assert items[0].issue_number == 5
    assert items[0].status == "awaiting_plan_approval"
    assert items[0].read is False


def test_in_app_notifier_records_done_and_failed(tmp_path: Path) -> None:
    """Ensure done and failed statuses are recorded."""
    store = _store(tmp_path)
    notifier = InAppNotifier(store)
    notifier.notify(_run("done"))
    notifier.notify(_run("failed"))
    assert len(store.list_all()) == 2


def test_in_app_notifier_ignores_transient_and_rejected(
    tmp_path: Path,
) -> None:
    """Ensure transient and rejected statuses are not recorded."""
    store = _store(tmp_path)
    notifier = InAppNotifier(store)
    for status in ("pending", "cloning", "refining", "rejected"):
        notifier.notify(_run(status))
    assert store.list_all() == []


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
