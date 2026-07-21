"""Write-through dedup ledger for processed GitHub webhook deliveries."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.db import get_sessionmaker
from app.persistence.tables import WebhookDeliveryRow

#: Retention window for processed-delivery records. Comfortably past
#: GitHub's redelivery window, then pruned to keep the table bounded
#: (feature 002, FR-008/SC-008).
RETENTION = timedelta(days=7)


class WebhookDeliveryStore:
    """Records processed delivery ids to guarantee at-most-once action."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def seen(
        self,
        delivery_id: str,
        event: str,
        outcome: str,
        repo: str | None = None,
        issue_number: int | None = None,
    ) -> bool:
        """
        Record a delivery id, returning whether it was already present.

        Atomic insert-if-absent: the primary key on ``delivery_id`` makes a
        concurrent re-delivery a no-op. Prunes rows past the retention
        window on each insert to keep the table bounded.

        :param delivery_id: GitHub ``X-GitHub-Delivery`` id.
        :param event: GitHub event type (e.g. ``issues``).
        :param outcome: Synchronous disposition recorded for diagnosis.
        :param repo: ``owner/name`` when known.
        :param issue_number: Issue the delivery concerned, when known.
        :returns: ``True`` if the id was already recorded (duplicate),
            ``False`` if this call inserted it.
        """
        now = datetime.now(timezone.utc)
        try:
            with self._factory.begin() as db:
                db.execute(
                    delete(WebhookDeliveryRow).where(
                        WebhookDeliveryRow.created_at < now - RETENTION
                    )
                )
                db.add(
                    WebhookDeliveryRow(
                        delivery_id=delivery_id,
                        event=event,
                        outcome=outcome,
                        repo=repo,
                        issue_number=issue_number,
                        created_at=now,
                    )
                )
            return False
        except IntegrityError:
            return True


@lru_cache
def get_webhook_delivery_store() -> WebhookDeliveryStore:
    """Return the process-wide WebhookDeliveryStore singleton."""
    return WebhookDeliveryStore(get_sessionmaker())
