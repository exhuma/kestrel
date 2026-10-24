"""Immutable handoff-artifact persistence (feature 026).

An artifact's ``(producer_card_id, logical_name, revision)`` identity is
enforced unique by the schema (migration 0027); recording a duplicate is
therefore rejected with :class:`DuplicateArtifactError` rather than
silently overwriting a prior revision.
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models_board_records import HandoffArtifact
from app.persistence.board_tables import BoardArtifactRow
from app.persistence.db import get_sessionmaker, is_unique_violation


class DuplicateArtifactError(Exception):
    """Raised when a ``(producer_card_id, logical_name, revision)`` repeats."""


def _row_to_artifact(row: BoardArtifactRow) -> HandoffArtifact:
    """Map one ``BoardArtifactRow`` to its pure value object."""
    inputs = tuple(i for i in row.input_artifacts.strip("[]").split(",") if i)
    return HandoffArtifact(
        id=row.id,
        producer_card_id=row.producer_card_id,
        logical_name=row.logical_name,
        revision=row.revision,
        content_ref=row.content_ref,
        content_hash=row.content_hash,
        trust=row.trust,
        mime_type=row.mime_type,
        input_artifacts=inputs,
    )


class BoardArtifactStore:
    """Records and reads immutable handoff artifacts."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def record(
        self, artifact: HandoffArtifact, *, now: datetime | None = None
    ) -> HandoffArtifact:
        """Record one immutable artifact revision.

        :param artifact: The artifact's full identity and provenance.
        :raises DuplicateArtifactError: if this producer/name/revision
            triple was already recorded.
        """
        row = BoardArtifactRow(
            id=artifact.id,
            producer_card_id=artifact.producer_card_id,
            logical_name=artifact.logical_name,
            revision=artifact.revision,
            content_ref=artifact.content_ref,
            content_hash=artifact.content_hash,
            trust=artifact.trust,
            mime_type=artifact.mime_type,
            input_artifacts=f"[{','.join(artifact.input_artifacts)}]",
            created_at=now or datetime.now(timezone.utc),
        )
        try:
            with self._factory.begin() as db:
                db.add(row)
                db.flush()
                db.expunge(row)
        except IntegrityError as exc:
            if not is_unique_violation(exc):
                raise
            raise DuplicateArtifactError(
                f"artifact already recorded: {artifact.producer_card_id}/"
                f"{artifact.logical_name}@{artifact.revision}"
            ) from exc
        return _row_to_artifact(row)

    def get(self, artifact_id: str) -> HandoffArtifact | None:
        """Return one artifact by id, or ``None`` if it does not exist."""
        with self._factory() as db:
            row = db.get(BoardArtifactRow, artifact_id)
            return _row_to_artifact(row) if row is not None else None

    def list_for_card(self, producer_card_id: str) -> list[HandoffArtifact]:
        """Return every artifact revision produced by *producer_card_id*,
        by name and revision."""
        with self._factory() as db:
            rows = (
                db.query(BoardArtifactRow)
                .filter(BoardArtifactRow.producer_card_id == producer_card_id)
                .order_by(
                    BoardArtifactRow.logical_name, BoardArtifactRow.revision
                )
                .all()
            )
            return [_row_to_artifact(row) for row in rows]


@lru_cache
def get_board_artifact_store() -> BoardArtifactStore:
    """Return the process-wide BoardArtifactStore singleton."""
    return BoardArtifactStore(get_sessionmaker())
