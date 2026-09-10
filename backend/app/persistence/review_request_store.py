"""Durable revision tokens for externally reviewed workflow gates."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.db import get_sessionmaker
from app.persistence.tables import ReviewRequestRow


class ReviewRequestStore:
    """Creates, resolves, and retires external review-request revisions."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def active_for(
        self, workflow_id: str, gate: str
    ) -> ReviewRequestRow | None:
        """Return the active revision for a workflow gate, if any."""
        with self._factory() as db:
            statement = select(ReviewRequestRow).where(
                ReviewRequestRow.workflow_id == workflow_id,
                ReviewRequestRow.gate == gate,
                ReviewRequestRow.active.is_(True),
            )
            return db.scalar(statement)

    def token(self) -> str:
        """Return an opaque token suitable for a newly posted review request."""
        return secrets.token_urlsafe(18)

    def next_revision(self, workflow_id: str) -> int:
        """Return the display revision for the next review request."""
        with self._factory() as db:
            revision = db.scalar(
                select(
                    func.coalesce(func.max(ReviewRequestRow.revision), 0)
                ).where(ReviewRequestRow.workflow_id == workflow_id)
            )
            return int(revision) + 1

    def create(
        self, workflow_id: str, gate: str, revision: int, token: str
    ) -> ReviewRequestRow:
        """Record a successfully delivered active revision for a gate."""
        with self._factory.begin() as db:
            db.execute(
                update(ReviewRequestRow)
                .where(
                    ReviewRequestRow.workflow_id == workflow_id,
                    ReviewRequestRow.gate == gate,
                    ReviewRequestRow.active.is_(True),
                )
                .values(active=False)
            )
            row = ReviewRequestRow(
                token=token,
                workflow_id=workflow_id,
                gate=gate,
                revision=revision,
                active=True,
                created_at=datetime.now(timezone.utc),
            )
            db.add(row)
            db.flush()
            db.expunge(row)
            return row

    def is_active(self, token: str, workflow_id: str, gate: str) -> bool:
        """Whether ``token`` is the active revision for this workflow gate."""
        with self._factory() as db:
            row = db.get(ReviewRequestRow, token)
            return bool(
                row is not None
                and row.workflow_id == workflow_id
                and row.gate == gate
                and row.active
            )

    def retire(self, workflow_id: str, gate: str) -> None:
        """Retire the active revision for a workflow gate after its decision."""
        with self._factory.begin() as db:
            db.execute(
                update(ReviewRequestRow)
                .where(
                    ReviewRequestRow.workflow_id == workflow_id,
                    ReviewRequestRow.gate == gate,
                    ReviewRequestRow.active.is_(True),
                )
                .values(active=False)
            )


@lru_cache
def get_review_request_store() -> ReviewRequestStore:
    """Return the process-wide ReviewRequestStore singleton."""
    return ReviewRequestStore(get_sessionmaker())
