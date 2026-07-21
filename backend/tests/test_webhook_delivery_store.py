"""Tests for the webhook-delivery dedup store."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.persistence.tables import WebhookDeliveryRow
from app.persistence.webhook_delivery_store import (
    RETENTION,
    WebhookDeliveryStore,
)


def _store(tmp_path: Path) -> WebhookDeliveryStore:
    """Build a store on a freshly migrated SQLite file."""
    url = f"sqlite:///{tmp_path / 'wh.db'}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return WebhookDeliveryStore(sessionmaker(bind=sa.create_engine(url)))


def test_first_seen_is_new_second_is_duplicate(tmp_path: Path) -> None:
    """Ensure the first record is new and a re-delivery is a duplicate."""
    store = _store(tmp_path)
    assert store.seen("d1", "issues", "accepted", "o/r", 5) is False
    assert store.seen("d1", "issues", "accepted", "o/r", 5) is True


def test_distinct_ids_are_independent(tmp_path: Path) -> None:
    """Ensure different delivery ids do not collide."""
    store = _store(tmp_path)
    assert store.seen("a", "issues", "accepted") is False
    assert store.seen("b", "issues", "ignored") is False


def test_prune_drops_rows_past_retention(tmp_path: Path) -> None:
    """Ensure a record older than the retention window is pruned on insert."""
    url = f"sqlite:///{tmp_path / 'wh.db'}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    factory = sessionmaker(bind=sa.create_engine(url))
    store = WebhookDeliveryStore(factory)

    old = datetime.now(timezone.utc) - RETENTION - timedelta(days=1)
    with factory.begin() as db:
        db.add(
            WebhookDeliveryRow(
                delivery_id="old",
                event="issues",
                outcome="accepted",
                created_at=old,
            )
        )

    # A fresh insert triggers the prune of the stale row.
    store.seen("new", "issues", "accepted")

    with factory() as db:
        assert db.get(WebhookDeliveryRow, "old") is None
        assert db.get(WebhookDeliveryRow, "new") is not None
