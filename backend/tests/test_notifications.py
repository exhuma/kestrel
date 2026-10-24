"""Tests for the notification record's signal classification and store."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import sessionmaker

from app.notifications import signal_class
from app.persistence.board_tables import BoardWorkflowRow
from app.persistence.notification_store import NotificationStore
from tests.database_support import isolated_engine


def _store() -> NotificationStore:
    """Build a store on an isolated database holding workflow ``wf-1``."""
    factory = sessionmaker(bind=isolated_engine())
    with factory.begin() as db:
        db.add(
            BoardWorkflowRow(
                id="wf-1", source="github-issue", task_ref="o/r#1",
                repo="o/r", source_visibility="public", title="t",
                state="active", created_at=datetime(2026, 10, 1),
            )
        )
    return NotificationStore(factory)


def test_signal_class_splits_gates_from_summaries() -> None:
    """Ensure awaiting_* gates are action-required and rest are summaries."""
    assert signal_class("awaiting_plan_approval") == "action_required"
    assert signal_class("awaiting_refine_input") == "action_required"
    assert signal_class("done") == "summary"
    assert signal_class("failed") == "summary"


def test_store_list_all_orders_newest_first() -> None:
    """Ensure notifications list most recent first."""
    store = _store()
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


def test_store_mark_read() -> None:
    """Ensure mark_read flips the read flag for that row only."""
    store = _store()
    store.add(
        workflow_id="wf-1", repo="o/r", issue_number=1,
        status="done", message="x",
    )
    notification_id = store.list_all()[0].id
    store.mark_read(notification_id)
    assert store.list_all()[0].read is True
