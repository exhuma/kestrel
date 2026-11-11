"""Tests for the webhook-delivery dedup store."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import sessionmaker

from app.persistence.tables import WebhookDeliveryRow
from app.persistence.webhook_delivery_store import (
    RETENTION,
    WebhookDeliveryStore,
)
from tests.database_support import isolated_engine


def _store() -> WebhookDeliveryStore:
    """Build a store on an isolated, migrated database."""
    return WebhookDeliveryStore(sessionmaker(bind=isolated_engine()))


def test_first_seen_is_new_second_is_duplicate() -> None:
    """Ensure the first record is new and a re-delivery is a duplicate."""
    store = _store()
    assert store.seen("d1", "issues", "accepted", "o/r", 5) is False
    assert store.seen("d1", "issues", "accepted", "o/r", 5) is True


def test_distinct_ids_are_independent() -> None:
    """Ensure different delivery ids do not collide."""
    store = _store()
    assert store.seen("a", "issues", "accepted") is False
    assert store.seen("b", "issues", "ignored") is False


def test_prune_drops_rows_past_retention() -> None:
    """Ensure a record older than the retention window is pruned on insert."""
    factory = sessionmaker(bind=isolated_engine())
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
