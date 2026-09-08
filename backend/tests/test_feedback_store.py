"""Tests for migration 0015 and the FeedbackStore (feature 013)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.persistence.feedback_store import FeedbackStore
from app.persistence.tables import FeedbackItemRow


def _cfg(tmp_path: Path) -> tuple[Config, sa.Engine]:
    url = f"sqlite:///{tmp_path / 'm.db'}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg, sa.create_engine(url)


def _factory(tmp_path: Path) -> sessionmaker[sa.orm.Session]:
    cfg, engine = _cfg(tmp_path)
    command.upgrade(cfg, "head")
    return sessionmaker(bind=engine)


def _item(external_id: str, **overrides: object) -> FeedbackItemRow:
    defaults: dict[str, object] = {
        "external_id": external_id,
        "workflow_id": "wf-1",
        "task_ref": "o/r#7",
        "origin": "ticket",
        "author": "octocat",
        "body": "@kestrel please rename this",
        "state": "queued",
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return FeedbackItemRow(**defaults)


def test_upgrade_creates_feedback_tables_and_pr_number(
    tmp_path: Path,
) -> None:
    """0015 adds feedback_item/feedback_cursor and workflow_run.pr_number."""
    cfg, engine = _cfg(tmp_path)
    command.upgrade(cfg, "0014")
    command.upgrade(cfg, "0015")

    inspector = sa.inspect(engine)
    item_cols = {c["name"] for c in inspector.get_columns("feedback_item")}
    assert item_cols == {
        "external_id", "workflow_id", "task_ref", "origin", "author",
        "body", "state", "target_step", "created_at", "processed_at",
    }
    cursor_cols = {
        c["name"] for c in inspector.get_columns("feedback_cursor")
    }
    assert cursor_cols == {"scope", "cursor", "updated_at"}
    run_cols = {
        c["name"]: c for c in inspector.get_columns("workflow_run")
    }
    assert run_cols["pr_number"]["nullable"] is True
    index_names = {
        ix["name"] for ix in inspector.get_indexes("feedback_item")
    }
    assert "ix_feedback_item_workflow_state" in index_names


def test_downgrade_removes_feedback_tables_and_pr_number(
    tmp_path: Path,
) -> None:
    """Downgrading 0015 drops both tables and workflow_run.pr_number."""
    cfg, engine = _cfg(tmp_path)
    command.upgrade(cfg, "0015")

    command.downgrade(cfg, "0014")

    inspector = sa.inspect(engine)
    assert not inspector.has_table("feedback_item")
    assert not inspector.has_table("feedback_cursor")
    run_cols = {c["name"] for c in inspector.get_columns("workflow_run")}
    assert "pr_number" not in run_cols


def test_claim_is_atomic_insert_if_absent(tmp_path: Path) -> None:
    """A second claim of the same external_id is a no-op, not an error."""
    store = FeedbackStore(_factory(tmp_path))
    assert store.claim(_item("gh-issue-comment:1")) is True
    assert store.claim(_item("gh-issue-comment:1")) is False


def test_queued_for_returns_only_that_runs_queued_items(
    tmp_path: Path,
) -> None:
    """queued_for filters by workflow_id and state, oldest first."""
    store = FeedbackStore(_factory(tmp_path))
    store.claim(_item("a", workflow_id="wf-1"))
    store.claim(_item("b", workflow_id="wf-1"))
    store.claim(_item("c", workflow_id="wf-2"))
    store.mark("b", "applied")

    queued = store.queued_for("wf-1")

    assert [item.external_id for item in queued] == ["a"]


def test_mark_sets_state_target_step_and_processed_at(
    tmp_path: Path,
) -> None:
    """mark() updates state/target_step and stamps processed_at on close."""
    factory = _factory(tmp_path)
    store = FeedbackStore(factory)
    store.claim(_item("a"))

    store.mark("a", "applied", target_step="code")

    with factory() as db:
        row = db.get(FeedbackItemRow, "a")
        assert row.state == "applied"
        assert row.target_step == "code"
        assert row.processed_at is not None


def test_mark_unknown_external_id_is_a_no_op(tmp_path: Path) -> None:
    """Marking an id that was never claimed does not raise."""
    store = FeedbackStore(_factory(tmp_path))
    store.mark("does-not-exist", "applied")


def test_cursor_round_trip(tmp_path: Path) -> None:
    """set_cursor then cursor reads back the same value; unset is None."""
    store = FeedbackStore(_factory(tmp_path))
    assert store.cursor("ticket:o/r#7") is None

    store.set_cursor("ticket:o/r#7", "2026-09-01T00:00:00Z")
    assert store.cursor("ticket:o/r#7") == "2026-09-01T00:00:00Z"

    store.set_cursor("ticket:o/r#7", "2026-09-02T00:00:00Z")
    assert store.cursor("ticket:o/r#7") == "2026-09-02T00:00:00Z"
