"""Durable ledger of workflow-owned artifacts pending cleanup."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.models_workflow import WorkflowArtifact
from app.persistence.db import get_sessionmaker
from app.persistence.tables import WorkflowArtifactRow

_TERMINAL_STATES = frozenset({"cleaned", "absent", "closed"})


def _now_utc() -> datetime:
    """Return the repository's required naive current UTC timestamp."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class WorkflowArtifactStore:
    """Records workflow-owned resources and their cleanup progress."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        """Create a store that opens one transaction per operation."""
        self._factory = factory

    def record(self, artifact: WorkflowArtifact) -> WorkflowArtifact:
        """Persist ``artifact`` and return it with its allocated identity."""
        created_at = artifact.created_at or _now_utc()
        with self._factory.begin() as db:
            row = WorkflowArtifactRow(
                workflow_id=artifact.workflow_id,
                kind=artifact.kind,
                external_id=artifact.external_id,
                display_name=artifact.display_name,
                cleanup_mode=artifact.cleanup_mode,
                state=artifact.state,
                error=artifact.error,
                created_at=created_at,
                cleaned_at=artifact.cleaned_at,
            )
            db.add(row)
            db.flush()
            artifact.id = row.id
            artifact.created_at = created_at
        return artifact

    def list_for(self, workflow_id: str) -> list[WorkflowArtifact]:
        """Return all tracked artifacts for a workflow in creation order."""
        with self._factory() as db:
            rows = db.scalars(
                select(WorkflowArtifactRow)
                .where(WorkflowArtifactRow.workflow_id == workflow_id)
                .order_by(WorkflowArtifactRow.id)
            )
            return [self._artifact_from_row(row) for row in rows]

    def set_state(
        self, artifact_id: int, state: str, error: str | None = None
    ) -> None:
        """Set an artifact's cleanup state and bounded failure detail.

        Terminal states receive a completion timestamp. Retried ``pending`` and
        ``failed`` states clear it so the record remains actionable.
        """
        with self._factory.begin() as db:
            row = db.get(WorkflowArtifactRow, artifact_id)
            if row is None:
                return
            row.state = state
            row.error = error
            row.cleaned_at = (
                _now_utc() if state in _TERMINAL_STATES else None
            )

    def discard_resolved(self, workflow_id: str) -> None:
        """Remove terminal artifact records after a cleanup attempt.

        Failed and pending artifacts remain durable so a later cleanup can retry
        required work without rediscovering unowned resources.
        """
        with self._factory.begin() as db:
            db.execute(
                delete(WorkflowArtifactRow).where(
                    WorkflowArtifactRow.workflow_id == workflow_id,
                    WorkflowArtifactRow.state.in_(_TERMINAL_STATES),
                )
            )

    @staticmethod
    def _artifact_from_row(row: WorkflowArtifactRow) -> WorkflowArtifact:
        """Translate an ORM row into the workflow artifact domain model."""
        return WorkflowArtifact(
            id=row.id,
            workflow_id=row.workflow_id,
            kind=row.kind,
            external_id=row.external_id,
            display_name=row.display_name,
            cleanup_mode=row.cleanup_mode,
            state=row.state,
            error=row.error,
            created_at=row.created_at,
            cleaned_at=row.cleaned_at,
        )


@lru_cache
def get_workflow_artifact_store() -> WorkflowArtifactStore:
    """Return the process-wide workflow artifact store singleton."""
    return WorkflowArtifactStore(get_sessionmaker())
