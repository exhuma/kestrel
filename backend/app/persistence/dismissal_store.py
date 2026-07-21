"""Durable per-issue dismissal tombstones (feature 002, FR-008a).

Abandoning an ingested run records a dismissal so a still-labelled issue is
not re-ingested/reconciled; removing the trigger label clears it.
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
    """Records/queries/clears dismissals keyed by ``(repo, issue_number)``."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def add(self, repo: str, issue_number: int) -> None:
        """
        Record a dismissal for ``(repo, issue_number)`` (idempotent).

        :param repo: ``owner/name``.
        :param issue_number: The dismissed issue.
        """
        try:
            with self._factory.begin() as db:
                db.add(
                    IssueDismissalRow(
                        repo=repo,
                        issue_number=issue_number,
                        created_at=datetime.now(timezone.utc),
                    )
                )
        except IntegrityError:
            # Already dismissed — adding again is a no-op.
            pass

    def is_dismissed(self, repo: str, issue_number: int) -> bool:
        """
        Return whether ``(repo, issue_number)`` is currently dismissed.

        :param repo: ``owner/name``.
        :param issue_number: The issue to check.
        :returns: ``True`` if a dismissal exists.
        """
        with self._factory() as db:
            return (
                db.get(IssueDismissalRow, (repo, issue_number)) is not None
            )

    def list_dismissed(self, repo: str) -> list[int]:
        """
        Return the issue numbers currently dismissed for ``repo``.

        Used by reconciliation to clear dismissals whose label was removed
        (feature 002, FR-008a).

        :param repo: ``owner/name``.
        :returns: Dismissed issue numbers.
        """
        with self._factory() as db:
            return list(
                db.scalars(
                    select(IssueDismissalRow.issue_number).where(
                        IssueDismissalRow.repo == repo
                    )
                )
            )

    def clear(self, repo: str, issue_number: int) -> None:
        """
        Remove any dismissal for ``(repo, issue_number)`` (idempotent).

        :param repo: ``owner/name``.
        :param issue_number: The issue to un-dismiss.
        """
        with self._factory.begin() as db:
            db.execute(
                delete(IssueDismissalRow).where(
                    IssueDismissalRow.repo == repo,
                    IssueDismissalRow.issue_number == issue_number,
                )
            )


@lru_cache
def get_dismissal_store() -> DismissalStore:
    """Return the process-wide DismissalStore singleton."""
    return DismissalStore(get_sessionmaker())
