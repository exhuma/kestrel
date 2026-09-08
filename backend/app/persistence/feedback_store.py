"""Durable feedback dedup ledger, mid-run queue, and read cursors.

Backs the feedback-intake pipeline (feature 013): a webhook delivery and a
poll cycle racing to observe the same ticket comment or PR review must not
both act on it, and mid-run feedback held for the next round/step boundary
must survive a process restart the same way a parked gate already does.
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.db import get_sessionmaker
from app.persistence.tables import FeedbackCursorRow, FeedbackItemRow

#: States that close out a feedback item's lifecycle (stamps processed_at).
_TERMINAL_STATES = frozenset({"applied", "ignored"})


class FeedbackStore:
    """Claims/queries feedback items and tracks per-scope read cursors."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def claim(self, item: FeedbackItemRow) -> bool:
        """
        Atomically claim ``item`` by its ``external_id``.

        Insert-if-absent on the primary key: a webhook delivery and a poll
        cycle racing to observe the same comment (or a re-delivery) cannot
        both claim it — exactly one insert succeeds.

        :param item: The fully-populated row to persist (caller has already
            routed it to a ``workflow_id``/``task_ref`` and set ``state``).
        :returns: ``True`` if this call claimed it (newly inserted),
            ``False`` if ``external_id`` was already present (dedup hit).
        """
        try:
            with self._factory.begin() as db:
                db.add(item)
            return True
        except IntegrityError:
            return False

    def queued_for(self, workflow_id: str) -> list[FeedbackItemRow]:
        """
        Return a run's still-``queued`` feedback, oldest first.

        :param workflow_id: The run to look up.
        :returns: Queued items in the order they arrived.
        """
        with self._factory() as db:
            stmt = (
                select(FeedbackItemRow)
                .where(
                    FeedbackItemRow.workflow_id == workflow_id,
                    FeedbackItemRow.state == "queued",
                )
                .order_by(FeedbackItemRow.created_at)
            )
            return list(db.scalars(stmt))

    def mark(
        self,
        external_id: str,
        state: str,
        target_step: str | None = None,
    ) -> None:
        """
        Update a claimed item's processing state.

        :param external_id: The item to update.
        :param state: New state (``"queued"`` | ``"dispatched"`` |
            ``"applied"`` | ``"ignored"``).
        :param target_step: The triage-classified re-entry step, when known.
        """
        with self._factory.begin() as db:
            item = db.get(FeedbackItemRow, external_id)
            if item is None:
                return
            item.state = state
            if target_step is not None:
                item.target_step = target_step
            if state in _TERMINAL_STATES:
                item.processed_at = datetime.now(timezone.utc)

    def cursor(self, scope: str) -> str | None:
        """
        Return the last-read cursor for ``scope``, or ``None``.

        :param scope: ``"ticket:<task_ref>"`` or ``"pr:<repo>#<number>"``.
        """
        with self._factory() as db:
            row = db.get(FeedbackCursorRow, scope)
            return row.cursor if row is not None else None

    def set_cursor(self, scope: str, value: str) -> None:
        """
        Advance ``scope``'s cursor to ``value`` (create or update).

        :param scope: ``"ticket:<task_ref>"`` or ``"pr:<repo>#<number>"``.
        :param value: The adapter-opaque cursor to persist.
        """
        now = datetime.now(timezone.utc)
        with self._factory.begin() as db:
            row = db.get(FeedbackCursorRow, scope)
            if row is None:
                db.add(
                    FeedbackCursorRow(
                        scope=scope, cursor=value, updated_at=now
                    )
                )
            else:
                row.cursor = value
                row.updated_at = now


@lru_cache
def get_feedback_store() -> FeedbackStore:
    """Return the process-wide FeedbackStore singleton."""
    return FeedbackStore(get_sessionmaker())
