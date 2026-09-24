"""Board workflow/card persistence: reads, creation, and atomic claims.

Conditional ``UPDATE ... WHERE state = 'ready'`` statements are the
concurrency primitive here (mirroring the transactional-claim decision in
``specs/026-autonomous-work-board/research.md``): SQLite serializes
writes, so a rowcount of zero means another transaction already won the
claim, without any explicit locking.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models_board import (
    BoardEventRecord,
    CardRelation,
    ClaimOutcome,
    ClaimRequest,
    CompleteOutcome,
    WorkCard,
    Workflow,
)
from app.persistence.board_tables import (
    BoardCardAttemptRow,
    BoardCardRelationRow,
    BoardCardRow,
    BoardClaimLeaseRow,
    BoardEventRow,
    BoardWorkflowRow,
    BoardWorkspaceLeaseRow,
)
from app.persistence.db import get_sessionmaker


def _now(value: datetime | None) -> datetime:
    """Return *value* (or the current time) as naive UTC.

    SQLite's ``DateTime`` column round-trips naive datetimes; normalizing
    every clock read here keeps stored and injected-for-tests values
    comparable without a tz-aware/naive mismatch.
    """
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


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
    """Reads, creation, and atomic claim/completion for board workflows."""

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
                        created_at=_now(now),
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
        created_at = _now(now)
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
                    created_at=_now(now),
                )
            )

    def get_workflow(self, workflow_id: str) -> Workflow | None:
        """Return one workflow by id, or ``None`` if it does not exist."""
        with self._factory() as db:
            row = db.get(BoardWorkflowRow, workflow_id)
            return _row_to_workflow(row) if row is not None else None

    def bump_workflow_revision(
        self, workflow_id: str, *, now: datetime | None = None
    ) -> int:
        """Increment and return a workflow's snapshot revision."""
        now = _now(now)
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
                    state=state, wait_reason=wait_reason, updated_at=_now(now)
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
                    created_at=_now(now),
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

    def claim_card(
        self, request: ClaimRequest, *, now: datetime | None = None
    ) -> ClaimOutcome:
        """Atomically claim a ``ready`` card, and its repository lease.

        :param request: The claim's card, specialist, lease, and optional
            workspace-lease parameters.
        :param now: Injectable clock for tests.
        """
        now = _now(now)
        with self._factory() as db:
            card = db.get(BoardCardRow, request.card_id)
            if card is None or card.state != "ready":
                return ClaimOutcome(success=False, reason="not_ready")
            existing_lease = (
                db.get(BoardWorkspaceLeaseRow, request.workspace_repo)
                if request.workspace_repo is not None
                else None
            )
            if existing_lease is not None and existing_lease.expires_at > now:
                return ClaimOutcome(
                    success=False, reason="workspace_lease_unavailable"
                )
            # Captured before the bulk UPDATE: Session.execute()'s default
            # synchronize_session="evaluate" updates already-loaded ORM
            # objects in place, so reading attempt_count afterward would
            # double-count the increment.
            sequence = card.attempt_count + 1
            result = db.execute(
                update(BoardCardRow)
                .where(
                    BoardCardRow.id == request.card_id,
                    BoardCardRow.state == "ready",
                )
                .values(
                    state="claimed",
                    attempt_count=BoardCardRow.attempt_count + 1,
                    updated_at=now,
                )
            )
            if result.rowcount == 0:
                db.rollback()
                return ClaimOutcome(success=False, reason="not_ready")
            db.add(
                BoardCardAttemptRow(
                    card_id=request.card_id,
                    sequence=sequence,
                    specialist_id=request.specialist_id,
                    backend_id=request.backend_id,
                    status="active",
                    started_at=now,
                )
            )
            db.add(
                BoardClaimLeaseRow(
                    card_id=request.card_id,
                    attempt_sequence=sequence,
                    holder_specialist_id=request.specialist_id,
                    expires_at=now + timedelta(seconds=request.lease_seconds),
                )
            )
            if request.workspace_repo is not None:
                ws_seconds = (
                    request.workspace_lease_seconds or request.lease_seconds
                )
                self._acquire_workspace_lease(
                    db,
                    existing_lease,
                    request.workspace_repo,
                    request.card_id,
                    now + timedelta(seconds=ws_seconds),
                )
            db.commit()
            return ClaimOutcome(success=True, attempt_sequence=sequence)

    def _acquire_workspace_lease(
        self,
        db: Session,
        existing: BoardWorkspaceLeaseRow | None,
        repo: str,
        card_id: str,
        expires_at: datetime,
    ) -> None:
        """Create or reuse (an expired) workspace-lease row for *repo*."""
        if existing is not None:
            existing.claim_card_id = card_id
            existing.expires_at = expires_at
        else:
            db.add(
                BoardWorkspaceLeaseRow(
                    repo=repo, claim_card_id=card_id, expires_at=expires_at
                )
            )

    def complete_attempt(
        self,
        card_id: str,
        attempt_sequence: int,
        *,
        result: str,
        new_state: str,
        now: datetime | None = None,
    ) -> CompleteOutcome:
        """Complete an attempt if it still holds the active claim.

        A completion for an attempt that no longer holds the card's claim
        lease (superseded by expiry/reclaim) is preserved as stale
        evidence and does not advance the card (data-model.md).
        """
        now = _now(now)
        with self._factory() as db:
            attempt = db.get(BoardCardAttemptRow, (card_id, attempt_sequence))
            if attempt is None:
                return CompleteOutcome(success=False, reason="not_found")
            lease = db.get(BoardClaimLeaseRow, card_id)
            is_active = (
                lease is not None and lease.attempt_sequence == attempt_sequence
            )
            attempt.result = result
            attempt.ended_at = now
            attempt.status = "completed" if is_active else "stale"
            if not is_active:
                db.commit()
                return CompleteOutcome(success=False, reason="stale")
            db.execute(
                update(BoardCardRow)
                .where(BoardCardRow.id == card_id)
                .values(state=new_state, updated_at=now)
            )
            db.query(BoardClaimLeaseRow).filter(
                BoardClaimLeaseRow.card_id == card_id
            ).delete()
            db.commit()
            return CompleteOutcome(success=True)

    def expire_leases(self, *, now: datetime | None = None) -> list[str]:
        """Close every claim lease that expired by *now*.

        Each expired attempt is marked ``interrupted``; the card returns to
        ``ready`` for a fresh attempt, or ``failed`` once its attempt limit
        is exhausted (full retry/reassign/escalate policy is a later
        phase's concern — this is the durable primitive it will build on).

        :returns: The ids of cards whose lease expired.
        """
        now = _now(now)
        with self._factory() as db:
            expired = (
                db.query(BoardClaimLeaseRow)
                .filter(BoardClaimLeaseRow.expires_at <= now)
                .all()
            )
            card_ids = [lease.card_id for lease in expired]
            for lease in expired:
                self._close_expired_lease(db, lease, now)
            db.commit()
            return card_ids

    def _close_expired_lease(
        self, db: Session, lease: BoardClaimLeaseRow, now: datetime
    ) -> None:
        """Mark one abandoned attempt interrupted and free its card."""
        attempt = db.get(
            BoardCardAttemptRow, (lease.card_id, lease.attempt_sequence)
        )
        if attempt is not None:
            attempt.status = "interrupted"
            attempt.ended_at = now
        card = db.get(BoardCardRow, lease.card_id)
        next_state = "ready"
        if card is not None and card.attempt_count >= card.attempt_limit:
            next_state = "failed"
        db.execute(
            update(BoardCardRow)
            .where(BoardCardRow.id == lease.card_id)
            .values(state=next_state, updated_at=now)
        )
        db.delete(lease)
        db.query(BoardWorkspaceLeaseRow).filter(
            BoardWorkspaceLeaseRow.claim_card_id == lease.card_id
        ).delete()


@lru_cache
def get_board_store() -> BoardStore:
    """Return the process-wide BoardStore singleton."""
    return BoardStore(get_sessionmaker())
