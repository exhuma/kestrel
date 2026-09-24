"""Coordinator-action ledger persistence (feature 026, FR-005).

Every proposed coordinator action is recorded here — accepted or
rejected — before (and regardless of) whether it is applied, so a replay
or audit never has to trust the coordinator's own account of what it
proposed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models_board import CoordinatorActionRecord
from app.persistence.board_tables import BoardCoordinatorActionRow
from app.persistence.db import get_sessionmaker


def _row_to_record(row: BoardCoordinatorActionRow) -> CoordinatorActionRecord:
    return CoordinatorActionRecord(
        id=row.id,
        workflow_id=row.workflow_id,
        trigger=row.trigger,
        sequence=row.sequence,
        action_payload=row.action_payload,
        validation_decision=row.validation_decision,
        rejection_reason=row.rejection_reason,
        applied=row.applied_at is not None,
    )


class BoardCoordinatorStore:
    """Records every proposed coordinator action and its outcome."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def next_sequence(self, workflow_id: str) -> int:
        """Return the next per-workflow action sequence number."""
        with self._factory() as db:
            highest = db.scalar(
                select(func.max(BoardCoordinatorActionRow.sequence)).where(
                    BoardCoordinatorActionRow.workflow_id == workflow_id
                )
            )
            return (highest or 0) + 1

    def record_action(
        self,
        record: CoordinatorActionRecord,
        *,
        now: datetime | None = None,
    ) -> CoordinatorActionRecord:
        """Persist one proposed action and its validation outcome."""
        now = now or datetime.now(timezone.utc)
        row = BoardCoordinatorActionRow(
            id=record.id,
            workflow_id=record.workflow_id,
            trigger=record.trigger,
            sequence=record.sequence,
            action_payload=record.action_payload,
            validation_decision=record.validation_decision,
            rejection_reason=record.rejection_reason,
            applied_at=now if record.applied else None,
            created_at=now,
        )
        with self._factory.begin() as db:
            db.add(row)
            db.flush()
            db.expunge(row)
        return _row_to_record(row)

    def list_actions(self, workflow_id: str) -> list[CoordinatorActionRecord]:
        """Return every recorded action for *workflow_id*, oldest first."""
        with self._factory() as db:
            rows = (
                db.query(BoardCoordinatorActionRow)
                .filter(BoardCoordinatorActionRow.workflow_id == workflow_id)
                .order_by(BoardCoordinatorActionRow.sequence)
                .all()
            )
            return [_row_to_record(row) for row in rows]


@lru_cache
def get_board_coordinator_store() -> BoardCoordinatorStore:
    """Return the process-wide BoardCoordinatorStore singleton."""
    return BoardCoordinatorStore(get_sessionmaker())
