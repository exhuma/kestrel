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

from app.models_board import CardRelation, WorkCard, Workflow
from app.models_board_records import BoardEventRecord
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
        change_request_number=row.change_request_number,
        ci_repair_round=row.ci_repair_round,
        ci_status=row.ci_status,
        task_body=row.task_body,
        approved_prd=row.approved_prd,
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
        task_node_id=row.task_node_id,
        source_card_id=row.source_card_id,
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
                        change_request_number=workflow.change_request_number,
                        ci_repair_round=workflow.ci_repair_round,
                        ci_status=workflow.ci_status,
                        task_body=workflow.task_body,
                        approved_prd=workflow.approved_prd,
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
                    task_node_id=card.task_node_id,
                    source_card_id=card.source_card_id,
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

    def list_workflows(self, *, newest_first: bool = False) -> list[Workflow]:
        """Return every workflow.

        :param newest_first: Order by creation time, most recent first —
            what the board collection listing needs (GitHub #45).
            Internal callers that only need membership or don't care
            about order (dedup checks, CI polling) leave this off rather
            than pay for an ``ORDER BY`` they don't use.
        """
        with self._factory() as db:
            query = db.query(BoardWorkflowRow)
            if newest_first:
                query = query.order_by(BoardWorkflowRow.created_at.desc())
            return [_row_to_workflow(row) for row in query.all()]

    def bump_workflow_revision(self, workflow_id: str) -> int:
        """Increment and return a workflow's snapshot revision."""
        with self._factory.begin() as db:
            workflow = db.get(BoardWorkflowRow, workflow_id)
            workflow.revision += 1
            return workflow.revision

    def record_delivery(
        self, workflow_id: str, change_request_number: int | None
    ) -> None:
        """Record a fresh delivery's change request (T052).

        Resets ``ci_repair_round``/``ci_status`` — a new delivery, whether
        from the original coder work, an automated CI repair, or an
        operator's own manual fix, earns a fresh CI verdict and repair
        budget rather than carrying over a prior one.
        """
        with self._factory.begin() as db:
            workflow = db.get(BoardWorkflowRow, workflow_id)
            workflow.change_request_number = change_request_number
            workflow.ci_repair_round = 0
            workflow.ci_status = None

    def record_ci_status(self, workflow_id: str, status: str) -> int:
        """Record the latest CI poll verdict (T052).

        Increments ``ci_repair_round`` when *status* is ``"failed"`` —
        one round per observed failure, since each triggers (at most) one
        repair card.

        :returns: The workflow's ``ci_repair_round`` after this call.
        """
        with self._factory.begin() as db:
            workflow = db.get(BoardWorkflowRow, workflow_id)
            workflow.ci_status = status
            if status == "failed":
                workflow.ci_repair_round += 1
            return workflow.ci_repair_round

    def record_approved_prd(self, workflow_id: str, content: str) -> None:
        """Record a ``prd_gate``'s approved content (T078).

        The durable "approved scope" every later card's envelope reads
        alongside ``task_body`` — set once here rather than by flipping
        an artifact's trust value after the fact.
        """
        with self._factory.begin() as db:
            workflow = db.get(BoardWorkflowRow, workflow_id)
            workflow.approved_prd = content

    def record_intake(
        self, workflow_id: str, *, title: str, task_body: str
    ) -> None:
        """Record a screened request's title and body (feature 032):
        a request exists before screening, showing only its ticket ref,
        and gets its content only once the content is safe."""
        with self._factory.begin() as db:
            workflow = db.get(BoardWorkflowRow, workflow_id)
            workflow.title = title
            workflow.task_body = task_body

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
                    created_at=row.created_at,
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
