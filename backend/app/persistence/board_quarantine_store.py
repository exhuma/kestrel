"""Untrusted-input and security-review persistence (feature 026, FR-020,
FR-021).

Split out of ``board_store.py`` for module-length budget and because
quarantine is a distinct concern: every write here either records a
bounded, hashed input or resolves an existing review — it never mutates
an ordinary work card's state.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models_board import (
    CardKind,
    CardState,
    Workflow,
)
from app.models_board_records import (
    SecurityReviewRecord,
    UntrustedInputRecord,
)
from app.persistence.board_tables import (
    BoardCardRow,
    BoardEventRow,
    BoardSecurityReviewRow,
    BoardUntrustedInputRow,
    BoardWorkflowRow,
)
from app.persistence.db import get_sessionmaker


@dataclass(frozen=True)
class QuarantineRequest:
    """Everything needed to record one quarantine decision.

    :param workflow: The existing workflow to attach the review card to,
        or ``None`` to create a new one to host it (a brand-new suspect
        task has no workflow yet).
    :param source_identity: Bounded source metadata for the input.
    :param content_hash: Integrity hash of the screened content.
    :param policy_version: The screening policy version applied.
    :param safe_content_ref: Reference to the safely stored content.
    :param classification_category: The deterministic/classifier finding.
    :param reason: The deterministic/classifier's own short, safe
        explanation of *why* — an operator needs this to decide release
        vs. discard, not just the category.
    :param card_title: Safe operator-facing label for the review card.
    """

    workflow: Workflow | None
    source_identity: str
    content_hash: str
    policy_version: str
    safe_content_ref: str
    classification_category: str
    reason: str | None = None
    card_title: str = "Security review"


def _quarantine_id(prefix: str, request: QuarantineRequest) -> str:
    """A deterministic id for one (prefix, source, content) triple."""
    return f"{prefix}-{request.source_identity}-{request.content_hash[:12]}"


def _row_to_input(row: BoardUntrustedInputRow) -> UntrustedInputRecord:
    return UntrustedInputRecord(
        id=row.id,
        source_identity=row.source_identity,
        content_hash=row.content_hash,
        policy_version=row.policy_version,
        safe_content_ref=row.safe_content_ref,
    )


def _row_to_review(
    row: BoardSecurityReviewRow, workflow_id: str
) -> SecurityReviewRecord:
    return SecurityReviewRecord(
        id=row.id,
        untrusted_input_id=row.untrusted_input_id,
        card_id=row.card_id,
        workflow_id=workflow_id,
        classification_category=row.classification_category,
        review_state=row.review_state,
        reason=row.reason,
        resolution=row.resolution,
    )


class BoardQuarantineStore:
    """Records quarantine decisions and resolves them."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def find_untrusted_input(
        self, source_identity: str, content_hash: str
    ) -> UntrustedInputRecord | None:
        """Return the prior record for this exact (source, content), if any."""
        with self._factory() as db:
            row = db.scalar(
                select(BoardUntrustedInputRow).where(
                    BoardUntrustedInputRow.source_identity == source_identity,
                    BoardUntrustedInputRow.content_hash == content_hash,
                )
            )
            return _row_to_input(row) if row is not None else None

    def find_review_for_input(
        self, untrusted_input_id: str
    ) -> SecurityReviewRecord | None:
        """Return the review covering *untrusted_input_id*, if any."""
        with self._factory() as db:
            row = db.scalar(
                select(BoardSecurityReviewRow).where(
                    BoardSecurityReviewRow.untrusted_input_id
                    == untrusted_input_id
                )
            )
            if row is None:
                return None
            card = db.get(BoardCardRow, row.card_id)
            return _row_to_review(row, card.workflow_id)

    def find_review_for_card(
        self, card_id: str
    ) -> SecurityReviewRecord | None:
        """Return the review gating *card_id*, if any (board-view lookup)."""
        with self._factory() as db:
            row = db.scalar(
                select(BoardSecurityReviewRow).where(
                    BoardSecurityReviewRow.card_id == card_id
                )
            )
            if row is None:
                return None
            card = db.get(BoardCardRow, row.card_id)
            return _row_to_review(row, card.workflow_id)

    def quarantine(
        self, request: QuarantineRequest, *, now: datetime | None = None
    ) -> SecurityReviewRecord:
        """Record one quarantine: untrusted input, review, and its card.

        Creates a new workflow only when ``request.workflow`` is ``None``.
        """
        now = now or datetime.now(timezone.utc)
        with self._factory.begin() as db:
            if request.workflow is not None:
                workflow_id = request.workflow.id
            else:
                workflow_id = self._create_hosting_workflow(db, request, now)
            input_id = self._record_input(db, request, now)
            card_id = self._create_review_card(db, workflow_id, request, now)
            review = BoardSecurityReviewRow(
                id=f"review-{input_id}",
                untrusted_input_id=input_id,
                card_id=card_id,
                classification_category=request.classification_category,
                reason=request.reason,
                review_state="pending",
                created_at=now,
            )
            db.add(review)
            db.flush()
            db.expunge(review)
            return _row_to_review(review, workflow_id)

    def _create_hosting_workflow(
        self, db: Session, request: QuarantineRequest, now: datetime
    ) -> str:
        """Create a minimal quarantined workflow to host a new review."""
        workflow_id = f"wf-quarantine-{request.source_identity}"
        db.add(
            BoardWorkflowRow(
                id=workflow_id,
                source=request.source_identity.split(":", 1)[0],
                task_ref=request.source_identity,
                repo="",
                base_branch="",
                source_visibility="private",
                title=request.card_title,
                state="quarantined",
                created_at=now,
            )
        )
        return workflow_id

    def _record_input(
        self, db: Session, request: QuarantineRequest, now: datetime
    ) -> str:
        input_id = _quarantine_id("input", request)
        db.add(
            BoardUntrustedInputRow(
                id=input_id,
                source_identity=request.source_identity,
                content_hash=request.content_hash,
                policy_version=request.policy_version,
                safe_content_ref=request.safe_content_ref,
                created_at=now,
            )
        )
        return input_id

    def _create_review_card(
        self,
        db: Session,
        workflow_id: str,
        request: QuarantineRequest,
        now: datetime,
    ) -> str:
        card_id = _quarantine_id("card", request)
        db.add(
            BoardCardRow(
                id=card_id,
                workflow_id=workflow_id,
                kind=CardKind.SECURITY_REVIEW.value,
                title=request.card_title,
                state=CardState.QUARANTINED.value,
                #: Surfaced by the existing WorkCardSummaryOut.waiting_reason
                #: field the frontend already renders generically — a
                #: quarantined card needs no new API/UI plumbing for this.
                wait_reason=request.reason,
                created_at=now,
                updated_at=now,
            )
        )
        return card_id

    def resolve_review(
        self,
        review_id: str,
        resolution: str,
        *,
        now: datetime | None = None,
    ) -> ReviewResolution | None:
        """Resolve a pending review as ``"released"`` or ``"discarded"``.

        The operator's decision completes the review (feature 041): its
        card becomes ``done`` on release — nothing else ever moves it on,
        and an open card would hold the request in Intake — or
        ``cancelled`` on discard. One commit bumps the request's
        revision and, for a discard, records the event. A review that is
        no longer pending is left as it is.

        :returns: The review and whether this call resolved it, or
            ``None`` if it does not exist.
        """
        now = now or datetime.now(timezone.utc)
        with self._factory.begin() as db:
            review = db.get(BoardSecurityReviewRow, review_id)
            if review is None:
                return None
            card = db.get(BoardCardRow, review.card_id)
            changed = review.review_state == "pending"
            if changed:
                _resolve(db, review, card, resolution, now)
            db.flush()
            db.expunge(review)
            return ReviewResolution(
                _row_to_review(review, card.workflow_id), changed
            )


@dataclass(frozen=True)
class ReviewResolution:
    """A review after a resolve call, and whether that call resolved it."""

    review: SecurityReviewRecord
    changed: bool


def _resolve(
    db: Session,
    review: BoardSecurityReviewRow,
    card: BoardCardRow,
    resolution: str,
    now: datetime,
) -> None:
    review.review_state = resolution
    review.resolution = resolution
    review.resolved_at = now
    released = resolution == "released"
    card.state = (
        CardState.DONE.value if released else CardState.CANCELLED.value
    )
    card.updated_at = now
    if not released:
        # A release's own event comes with the continued intake
        # (``screening.released``); a discard has nothing that follows.
        db.add(
            BoardEventRow(
                workflow_id=card.workflow_id,
                card_id=card.id,
                event_type="screening.discarded",
                created_at=now,
            )
        )
    workflow = db.get(BoardWorkflowRow, card.workflow_id)
    if workflow is not None:
        workflow.revision += 1


@lru_cache
def get_board_quarantine_store() -> BoardQuarantineStore:
    """Return the process-wide BoardQuarantineStore singleton."""
    return BoardQuarantineStore(get_sessionmaker())
