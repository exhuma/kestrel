"""Human-gate decision persistence (feature 026, FR-016).

One row per gate card (``card_id`` is unique): a changed PRD or review
never edits a prior approval, it creates a new revision and a new
successor gate card instead (data-model.md "Human Gate"), so this store
never needs to update ``requested_decision``/``target_artifact_id`` after
creation — only ``decision`` moves from unset to recorded.
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy.orm import Session, sessionmaker

from app.models_board_records import HumanGateRecord
from app.persistence.board_tables import BoardHumanGateRow
from app.persistence.db import get_sessionmaker


def _row_to_record(row: BoardHumanGateRow) -> HumanGateRecord:
    return HumanGateRecord(
        id=row.id,
        card_id=row.card_id,
        requested_decision=row.requested_decision,
        target_artifact_id=row.target_artifact_id,
        decision=row.decision,
    )


class BoardGateStore:
    """Reads and records one gate card's decision."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def create_gate(
        self, gate: HumanGateRecord, *, now: datetime | None = None
    ) -> None:
        """Create a gate's decision record (data-model.md "Human Gate")."""
        with self._factory.begin() as db:
            db.add(
                BoardHumanGateRow(
                    id=gate.id,
                    card_id=gate.card_id,
                    target_artifact_id=gate.target_artifact_id,
                    requested_decision=gate.requested_decision,
                    decision=gate.decision,
                    created_at=now or datetime.now(timezone.utc),
                )
            )

    def get_for_card(self, card_id: str) -> HumanGateRecord | None:
        """Return the gate record for *card_id*, or ``None`` if absent."""
        with self._factory() as db:
            row = (
                db.query(BoardHumanGateRow)
                .filter(BoardHumanGateRow.card_id == card_id)
                .one_or_none()
            )
            return _row_to_record(row) if row is not None else None

    def record_decision(
        self, card_id: str, decision: str, *, now: datetime | None = None
    ) -> HumanGateRecord:
        """Record the operator's decision for *card_id*'s gate."""
        with self._factory.begin() as db:
            row = (
                db.query(BoardHumanGateRow)
                .filter(BoardHumanGateRow.card_id == card_id)
                .one()
            )
            row.decision = decision
            row.decision_at = now or datetime.now(timezone.utc)
            db.flush()
            db.expunge(row)
            return _row_to_record(row)


@lru_cache
def get_board_gate_store() -> BoardGateStore:
    """Return the process-wide BoardGateStore singleton."""
    return BoardGateStore(get_sessionmaker())
