"""Tests for durable external review-request revisions."""

from __future__ import annotations

from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.persistence.review_request_store import ReviewRequestStore


def _factory(tmp_path):
    """Create a session factory against an isolated migrated SQLite database."""
    engine = create_engine(f"sqlite:///{tmp_path}/reviews.db")
    return sessionmaker(bind=engine)


def test_review_request_revisions_are_durable_and_supersedable(
    tmp_path,
) -> None:
    """A later gate review receives a new token and retires the earlier one."""
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path}/reviews.db")
    command.upgrade(cfg, "head")
    store = ReviewRequestStore(_factory(tmp_path))
    first = store.create("wf-1", "awaiting_refine_approval", 1, "first")

    assert store.is_active(first.token, "wf-1", "awaiting_refine_approval")
    store.retire("wf-1", "awaiting_refine_approval")
    second = store.create("wf-1", "awaiting_refine_approval", 2, "second")

    assert second.revision == first.revision + 1
    assert not store.is_active(first.token, "wf-1", "awaiting_refine_approval")
    assert store.is_active(second.token, "wf-1", "awaiting_refine_approval")


def test_recording_a_review_retires_prior_active_gate_token(tmp_path) -> None:
    """Only the successfully latest post remains active for a workflow gate."""
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path}/reviews.db")
    command.upgrade(cfg, "head")
    store = ReviewRequestStore(_factory(tmp_path))
    first = store.create("wf-1", "awaiting_refine_approval", 1, "first")
    second = store.create("wf-1", "awaiting_refine_approval", 2, "second")

    assert not store.is_active(first.token, "wf-1", "awaiting_refine_approval")
    assert store.is_active(second.token, "wf-1", "awaiting_refine_approval")
