"""Atomic card claims and repository write leases (feature 026).

Split out of ``board_store.py`` for module-length budget. Conditional
``UPDATE ... WHERE state = 'ready'`` statements are the concurrency
primitive here (mirroring the transactional-claim decision in
``specs/026-autonomous-work-board/research.md``): SQLite serializes
writes, so a rowcount of zero means another transaction already won the
claim, without any explicit locking.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache

from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from app.models_board import (
    ClaimLease,
    ClaimOutcome,
    ClaimRequest,
    CompleteOutcome,
)
from app.persistence.board_tables import (
    BoardCardAttemptRow,
    BoardCardRow,
    BoardClaimLeaseRow,
    BoardWorkspaceLeaseRow,
)
from app.persistence.board_time import now_utc
from app.persistence.db import get_sessionmaker


class BoardClaimsStore:
    """Atomic claim/completion/recovery for board cards and write leases."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def claim_card(
        self, request: ClaimRequest, *, now: datetime | None = None
    ) -> ClaimOutcome:
        """Atomically claim a ``ready`` card, and its repository lease.

        :param request: The claim's card, specialist, lease, and optional
            workspace-lease parameters.
        :param now: Injectable clock for tests.
        """
        now = now_utc(now)
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

    def heartbeat_claim(
        self,
        card_id: str,
        *,
        extend_seconds: float,
        now: datetime | None = None,
    ) -> bool:
        """Extend an active claim's lease so a long-running attempt survives.

        :returns: Whether an active lease was found and extended.
        """
        now = now_utc(now)
        with self._factory.begin() as db:
            lease = db.get(BoardClaimLeaseRow, card_id)
            if lease is None:
                return False
            lease.expires_at = now + timedelta(seconds=extend_seconds)
            lease.heartbeat_at = now
            return True

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
        now = now_utc(now)
        with self._factory() as db:
            attempt = db.get(BoardCardAttemptRow, (card_id, attempt_sequence))
            if attempt is None:
                return CompleteOutcome(success=False, reason="not_found")
            lease = db.get(BoardClaimLeaseRow, card_id)
            is_active = (
                lease is not None
                and lease.attempt_sequence == attempt_sequence
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
        now = now_utc(now)
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

    def release_claim(
        self, card_id: str, *, now: datetime | None = None
    ) -> bool:
        """Release an active claim on operator authority (cancel/reassign).

        Unlike :meth:`expire_leases`, this never decides the card's next
        state — the caller (an intervention) does that separately — it
        only marks the active attempt ``interrupted`` and frees the claim
        and workspace leases.

        :returns: Whether an active lease was found and released.
        """
        now = now_utc(now)
        with self._factory() as db:
            lease = db.get(BoardClaimLeaseRow, card_id)
            if lease is None:
                return False
            attempt = db.get(
                BoardCardAttemptRow, (card_id, lease.attempt_sequence)
            )
            if attempt is not None:
                attempt.status = "interrupted"
                attempt.ended_at = now
            db.delete(lease)
            db.query(BoardWorkspaceLeaseRow).filter(
                BoardWorkspaceLeaseRow.claim_card_id == card_id
            ).delete()
            db.commit()
            return True

    def get_active_lease(self, card_id: str) -> ClaimLease | None:
        """Return *card_id*'s current claim lease, or ``None`` if unclaimed."""
        with self._factory() as db:
            row = db.get(BoardClaimLeaseRow, card_id)
            if row is None:
                return None
            return ClaimLease(
                card_id=row.card_id,
                attempt_sequence=row.attempt_sequence,
                specialist_id=row.holder_specialist_id,
                expires_at=row.expires_at,
            )

    def count_active_read_claims(self, *, now: datetime | None = None) -> int:
        """Count active claims on non-write cards (across all workflows).

        The process-wide read-only concurrency cap
        (``board_max_parallel_read_cards``) is enforced against this
        count, not per-workflow — SC-002's "independent read-only cards
        run concurrently" is a whole-process capacity guarantee.
        """
        now = now_utc(now)
        with self._factory() as db:
            return (
                db.query(BoardClaimLeaseRow)
                .join(
                    BoardCardRow, BoardClaimLeaseRow.card_id == BoardCardRow.id
                )
                .filter(
                    BoardCardRow.workspace_permission != "write",
                    BoardClaimLeaseRow.expires_at > now,
                )
                .count()
            )


@lru_cache
def get_board_claims_store() -> BoardClaimsStore:
    """Return the process-wide BoardClaimsStore singleton."""
    return BoardClaimsStore(get_sessionmaker())
