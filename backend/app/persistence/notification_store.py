"""Write-through persistence for in-app notifications."""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.notifications import Notification
from app.persistence.db import get_sessionmaker
from app.persistence.tables import NotificationRow


class NotificationStore:
    """Persists notifications for the in-app notification center."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def add(
        self,
        workflow_id: str,
        repo: str,
        issue_number: int | None,
        status: str,
        message: str,
    ) -> None:
        """
        Record a new notification.

        :param workflow_id: Id of the run that triggered this.
        :param repo: The run's repo, denormalized for display.
        :param issue_number: The run's issue number, denormalized.
        :param status: The run status that triggered this.
        :param message: The rendered notification text.
        """
        with self._factory.begin() as db:
            db.add(
                NotificationRow(
                    workflow_id=workflow_id,
                    repo=repo,
                    issue_number=issue_number,
                    status=status,
                    message=message,
                    created_at=datetime.now(timezone.utc),
                    read=False,
                )
            )

    def list_all(self) -> list[Notification]:
        """
        Return all notifications, most recent first.

        :returns: Every notification, newest first.
        """
        with self._factory() as db:
            stmt = select(NotificationRow).order_by(
                NotificationRow.id.desc()
            )
            return [
                Notification(
                    id=row.id,
                    workflow_id=row.workflow_id,
                    repo=row.repo,
                    issue_number=row.issue_number,
                    status=row.status,
                    message=row.message,
                    created_at=row.created_at,
                    read=row.read,
                )
                for row in db.scalars(stmt)
            ]

    def mark_read(self, notification_id: int) -> None:
        """
        Mark one notification as read.

        :param notification_id: Id of the notification to mark.
        """
        with self._factory.begin() as db:
            row = db.get(NotificationRow, notification_id)
            if row is not None:
                row.read = True


@lru_cache
def get_notification_store() -> NotificationStore:
    """
    Return the process-wide NotificationStore singleton.

    :returns: The cached notification store instance.
    """
    return NotificationStore(get_sessionmaker())
