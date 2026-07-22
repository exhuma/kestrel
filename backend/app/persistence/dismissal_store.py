"""Durable per-ticket dismissal tombstones (feature 002 FR-008a; feature 003
FR-033).

Rejecting a PRD or abandoning a run records a dismissal so a still-qualifying
ticket is not re-ingested/reconciled; the ticket leaving its qualifying filter
(GitHub label removed, or a Jira RFC leaving the JQL) clears it. Keyed by the
source-neutral ``task_ref`` so GitHub and Jira share one guard.
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.db import get_sessionmaker
from app.persistence.tables import IssueDismissalRow


class DismissalStore:
    """Records / queries / clears dismissals keyed by ``task_ref``."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def add(self, task_ref: str) -> None:
        """
        Record a dismissal for ``task_ref`` (idempotent).

        :param task_ref: Source-native ticket id (e.g. ``owner/name#7`` or
            ``RFC-123``).
        """
        try:
            with self._factory.begin() as db:
                db.add(
                    IssueDismissalRow(
                        task_ref=task_ref,
                        created_at=datetime.now(timezone.utc),
                    )
                )
        except IntegrityError:
            # Already dismissed — adding again is a no-op.
            pass

    def is_dismissed(self, task_ref: str) -> bool:
        """
        Return whether ``task_ref`` is currently dismissed.

        :param task_ref: The ticket id to check.
        :returns: ``True`` if a dismissal exists.
        """
        with self._factory() as db:
            return db.get(IssueDismissalRow, task_ref) is not None

    def all(self) -> list[str]:
        """
        Return every currently-dismissed ``task_ref``.

        Used by reconciliation / the Jira poll to clear dismissals whose
        ticket no longer qualifies (feature 003, FR-033).

        :returns: All dismissed task refs.
        """
        with self._factory() as db:
            return list(db.scalars(select(IssueDismissalRow.task_ref)))

    def clear(self, task_ref: str) -> None:
        """
        Remove any dismissal for ``task_ref`` (idempotent).

        :param task_ref: The ticket to un-dismiss.
        """
        with self._factory.begin() as db:
            db.execute(
                delete(IssueDismissalRow).where(
                    IssueDismissalRow.task_ref == task_ref
                )
            )


@lru_cache
def get_dismissal_store() -> DismissalStore:
    """Return the process-wide DismissalStore singleton."""
    return DismissalStore(get_sessionmaker())
