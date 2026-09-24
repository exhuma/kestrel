"""Board workflow/card persistence: reads, creation, and relations.

Atomic claim/completion/lease-recovery lives in ``board_claims_store.py``
(split out for module-length budget); this module owns workflow/card/
relation/event CRUD only.
"""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models_board import BoardEventRecord, CardRelation, WorkCard, Workflow
from app.persistence.board_tables import (
    BoardCardRelationRow,
    BoardCardRow,
    BoardEventRow,
    BoardWorkflowRow,
)
from app.persistence.board_time import now_utc
from app.persistence.db import get_sessionmaker


def _row_to_workflow(row: BoardWorkflowRow) -> Workflow:
    """Map one ``BoardWorkflowRow`` to its pure :class:`Workflow` value."""
    return Workflow(
        id=row.id,
        source=row.source,
        task_ref=row.task_ref,
        repo=row.repo,
        base_branch=row.base_branch,
        source_visibility=row.source_visibility,
        title=row.title,
        state=row.state,
        revision=row.revision,
    )


def _row_to_card(row: BoardCardRow) -> WorkCard:
    """Map one ``BoardCardRow`` to its pure :class:`WorkCard` value object."""
    roles = tuple(r for r in row.eligible_roles.split(",") if r)
    return WorkCard(
        id=row.id,
        workflow_id=row.workflow_id,
        kind=row.kind,
        title=row.title,
        state=row.state,
        eligible_roles=roles,
        workspace_permission=row.workspace_permission,
        attempt_limit=row.attempt_limit,
        attempt_count=row.attempt_count,
        wait_reason=row.wait_reason,
    )


class WorkflowAlreadyExistsError(Exception):
    """Raised when a workflow already exists for this (source, task_ref).

    The unique index on ``(source, task_ref)`` is the durable de-dup
    guard for repeated delivery of the same source item (FR-021,
    Edge Cases): a webhook and a poll cycle racing to ingest the same
    ticket produce at most one workflow.
    """


class BoardStore:
    """Reads, creation, and relation/event persistence for board workflows."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def create_workflow(
        self, workflow: Workflow, *, now: datetime | None = None
    ) -> None:
        """Create a workflow row (data-model.md "Workflow").

        :raises WorkflowAlreadyExistsError: If ``(source, task_ref)``
            already has a workflow.
        """
        try:
            with self._factory.begin() as db:
                db.add(
                    BoardWorkflowRow(
                        id=workflow.id,
                        source=workflow.source,
                        task_ref=workflow.task_ref,
                        repo=workflow.repo,
                        base_branch=workflow.base_branch,
                        source_visibility=workflow.source_visibility,
                        title=workflow.title,
                        state=workflow.state,
                        revision=workflow.revision,
                        created_at=now_utc(now),
                    )
                )
        except IntegrityError as exc:
            raise WorkflowAlreadyExistsError(
                f"{workflow.source}:{workflow.task_ref}"
            ) from exc

    def create_card(
        self, card: WorkCard, *, now: datetime | None = None
    ) -> None:
        """Create a work-card row (data-model.md "Work Card")."""
        created_at = now_utc(now)
        with self._factory.begin() as db:
            db.add(
                BoardCardRow(
                    id=card.id,
                    workflow_id=card.workflow_id,
                    kind=card.kind,
                    title=card.title,
                    state=card.state,
                    eligible_roles=",".join(card.eligible_roles),
                    workspace_permission=card.workspace_permission,
                    attempt_limit=card.attempt_limit,
                    wait_reason=card.wait_reason,
                    created_at=created_at,
                    updated_at=created_at,
                )
            )

    def add_relation(
        self,
        relation: CardRelation,
        *,
        created_by_action: str = "coordinator",
        now: datetime | None = None,
    ) -> None:
        """Persist one validated :class:`CardRelation` edge."""
        with self._factory.begin() as db:
            db.add(
                BoardCardRelationRow(
                    card_id=relation.card_id,
                    depends_on_card_id=relation.depends_on_card_id,
                    kind=relation.kind,
                    created_by_action=created_by_action,
                    created_at=now_utc(now),
                )
            )

    def list_relations(self, workflow_id: str) -> list[CardRelation]:
        """Return every relation among *workflow_id*'s cards."""
        with self._factory() as db:
            rows = (
                db.query(BoardCardRelationRow)
                .join(
                    BoardCardRow,
                    BoardCardRelationRow.card_id == BoardCardRow.id,
                )
                .filter(BoardCardRow.workflow_id == workflow_id)
                .all()
            )
            return [
                CardRelation(
                    card_id=row.card_id,
                    depends_on_card_id=row.depends_on_card_id,
                    kind=row.kind,
                )
                for row in rows
            ]

    def get_workflow(self, workflow_id: str) -> Workflow | None:
        """Return one workflow by id, or ``None`` if it does not exist."""
        with self._factory() as db:
            row = db.get(BoardWorkflowRow, workflow_id)
            return _row_to_workflow(row) if row is not None else None

    def list_workflows(self) -> list[Workflow]:
        """Return every workflow (board collection listing)."""
        with self._factory() as db:
            rows = db.query(BoardWorkflowRow).all()
            return [_row_to_workflow(row) for row in rows]

    def bump_workflow_revision(self, workflow_id: str) -> int:
        """Increment and return a workflow's snapshot revision."""
        with self._factory.begin() as db:
            workflow = db.get(BoardWorkflowRow, workflow_id)
            workflow.revision += 1
            return workflow.revision

    def set_card_state(
        self,
        card_id: str,
        state: str,
        *,
        wait_reason: str | None = None,
        now: datetime | None = None,
    ) -> None:
        """Set a card's state directly (policy already validated it)."""
        with self._factory.begin() as db:
            db.execute(
                update(BoardCardRow)
                .where(BoardCardRow.id == card_id)
                .values(
                    state=state,
                    wait_reason=wait_reason,
                    updated_at=now_utc(now),
                )
            )

    def append_event(
        self, event: BoardEventRecord, *, now: datetime | None = None
    ) -> None:
        """Append one safe, immutable board-history entry."""
        with self._factory.begin() as db:
            db.add(
                BoardEventRow(
                    workflow_id=event.workflow_id,
                    card_id=event.card_id,
                    event_type=event.event_type,
                    payload=event.payload,
                    causation_id=event.causation_id,
                    correlation_id=event.correlation_id,
                    created_at=now_utc(now),
                )
            )

    def list_events(self, workflow_id: str) -> list[BoardEventRecord]:
        """Return every board event for *workflow_id*, oldest first."""
        with self._factory() as db:
            rows = (
                db.query(BoardEventRow)
                .filter(BoardEventRow.workflow_id == workflow_id)
                .order_by(BoardEventRow.id)
                .all()
            )
            return [
                BoardEventRecord(
                    workflow_id=row.workflow_id,
                    event_type=row.event_type,
                    card_id=row.card_id,
                    payload=row.payload,
                    causation_id=row.causation_id,
                    correlation_id=row.correlation_id,
                )
                for row in rows
            ]

    def get_card(self, card_id: str) -> WorkCard | None:
        """Return one card by id, or ``None`` if it does not exist."""
        with self._factory() as db:
            row = db.get(BoardCardRow, card_id)
            return _row_to_card(row) if row is not None else None

    def list_cards(self, workflow_id: str) -> list[WorkCard]:
        """Return every card belonging to *workflow_id*."""
        with self._factory() as db:
            rows = (
                db.query(BoardCardRow)
                .filter(BoardCardRow.workflow_id == workflow_id)
                .all()
            )
            return [_row_to_card(row) for row in rows]


@lru_cache
def get_board_store() -> BoardStore:
    """Return the process-wide BoardStore singleton."""
    return BoardStore(get_sessionmaker())
