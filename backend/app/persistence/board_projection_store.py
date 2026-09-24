"""External-projection ledger persistence (feature 026, FR-033..FR-035).

``idempotency_key`` is unique by schema (migration 0027): a webhook and a
poll cycle racing to report the same real-world milestone produce at
most one projection row, mirroring the same durable de-dup pattern as
``WorkflowAlreadyExistsError`` for workflow creation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models_board import ExternalProjectionRecord
from app.persistence.board_tables import BoardExternalProjectionRow
from app.persistence.db import get_sessionmaker


def _row_to_record(
    row: BoardExternalProjectionRow,
) -> ExternalProjectionRecord:
    return ExternalProjectionRecord(
        id=row.id,
        workflow_id=row.workflow_id,
        kind=row.kind,
        idempotency_key=row.idempotency_key,
        payload_hash=row.payload_hash,
        state=row.state,
        error=row.error,
        external_id=row.external_id,
    )


class BoardProjectionStore:
    """Records, reads, and resolves external-projection ledger entries."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def plan(
        self, record: ExternalProjectionRecord, *, now: datetime | None = None
    ) -> ExternalProjectionRecord:
        """Record a planned projection, or return the existing one.

        Idempotent by ``idempotency_key``: a second ``plan`` call for an
        already-recorded key is a no-op that returns the original record
        unchanged, rather than racing a duplicate insert.
        """
        existing = self.get_by_idempotency_key(record.idempotency_key)
        if existing is not None:
            return existing
        moment = now or datetime.now(timezone.utc)
        row = BoardExternalProjectionRow(
            id=record.id,
            workflow_id=record.workflow_id,
            kind=record.kind,
            idempotency_key=record.idempotency_key,
            payload_hash=record.payload_hash,
            state=record.state,
            error=record.error,
            external_id=record.external_id,
            created_at=moment,
            updated_at=moment,
        )
        try:
            with self._factory.begin() as db:
                db.add(row)
                db.flush()
                db.expunge(row)
        except IntegrityError:
            # Lost a race with a concurrent planner for the same key.
            existing = self.get_by_idempotency_key(record.idempotency_key)
            if existing is not None:
                return existing
            raise
        return _row_to_record(row)

    def get(self, projection_id: str) -> ExternalProjectionRecord | None:
        """Return one projection by id, or ``None`` if it does not exist."""
        with self._factory() as db:
            row = db.get(BoardExternalProjectionRow, projection_id)
            return _row_to_record(row) if row is not None else None

    def get_by_idempotency_key(
        self, idempotency_key: str
    ) -> ExternalProjectionRecord | None:
        """Return the projection for *idempotency_key*, if one exists."""
        with self._factory() as db:
            row = (
                db.query(BoardExternalProjectionRow)
                .filter(
                    BoardExternalProjectionRow.idempotency_key
                    == idempotency_key
                )
                .one_or_none()
            )
            return _row_to_record(row) if row is not None else None

    def mark_completed(
        self,
        projection_id: str,
        *,
        external_id: str | None = None,
        now: datetime | None = None,
    ) -> ExternalProjectionRecord:
        """Resolve a projection as durably delivered."""
        with self._factory.begin() as db:
            row = db.get(BoardExternalProjectionRow, projection_id)
            row.state = "completed"
            row.external_id = external_id
            row.error = None
            row.updated_at = now or datetime.now(timezone.utc)
            db.flush()
            db.expunge(row)
            return _row_to_record(row)

    def mark_failed(
        self, projection_id: str, error: str, *, now: datetime | None = None
    ) -> ExternalProjectionRecord:
        """Resolve a projection attempt as retryable."""
        with self._factory.begin() as db:
            row = db.get(BoardExternalProjectionRow, projection_id)
            row.state = "retryable_failure"
            row.error = error
            row.updated_at = now or datetime.now(timezone.utc)
            db.flush()
            db.expunge(row)
            return _row_to_record(row)

    def list_retryable(self) -> list[ExternalProjectionRecord]:
        """Return every projection currently in ``retryable_failure``."""
        with self._factory() as db:
            rows = (
                db.query(BoardExternalProjectionRow)
                .filter(BoardExternalProjectionRow.state == "retryable_failure")
                .all()
            )
            return [_row_to_record(row) for row in rows]

    def owned_external_ids(self, workflow_id: str) -> list[tuple[str, str]]:
        """Return ``(kind, external_id)`` for every completed, Kestrel-owned
        external resource for *workflow_id* — the durable cleanup ledger
        (FR-035): cleanup may change only these, never anything else."""
        with self._factory() as db:
            rows = (
                db.query(BoardExternalProjectionRow)
                .filter(
                    BoardExternalProjectionRow.workflow_id == workflow_id,
                    BoardExternalProjectionRow.state == "completed",
                    BoardExternalProjectionRow.external_id.is_not(None),
                )
                .all()
            )
            return [(row.kind, row.external_id) for row in rows]


@lru_cache
def get_board_projection_store() -> BoardProjectionStore:
    """Return the process-wide BoardProjectionStore singleton."""
    return BoardProjectionStore(get_sessionmaker())
