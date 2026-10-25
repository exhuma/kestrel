"""Atomic card claims and repository write leases (feature 026).

Split out of ``board_store.py`` for module-length budget. Every write
here is one conditional statement whose outcome says who won, never a
read followed by a write (mirroring the transactional-claim decision in
``specs/026-autonomous-work-board/research.md``):

- a claim is ``UPDATE ... WHERE state = 'ready'``: PostgreSQL locks the
  row an ``UPDATE`` matches and re-checks the condition once a competing
  transaction commits, so no row back means another claimant won;
- a writer's repository is taken by inserting its claim lease with
  ``ON CONFLICT (workspace_repo) DO NOTHING``, which waits for a
  competing insert and then backs off;
- completion, recovery and release each start by deleting the claim
  lease, so of two racing for one claim only the one whose ``DELETE``
  returns the row goes on.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache

from sqlalchemy import case, delete, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.models_board import (
    ClaimLease,
    ClaimRequest,
)
from app.models_board_records import (
    ClaimOutcome,
    CompleteOutcome,
)
from app.persistence.board_tables import (
    BoardCardAttemptRow,
    BoardCardRow,
    BoardClaimLeaseRow,
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
            repository.
        :param now: Injectable clock for tests.
        """
        now = now_utc(now)
        with self._factory() as db:
            sequence = db.execute(
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
                .returning(BoardCardRow.attempt_count)
            ).scalar_one_or_none()
            if sequence is None:
                return ClaimOutcome(success=False, reason="not_ready")
            if not _take_lease(db, request, sequence, now):
                db.rollback()
                return ClaimOutcome(
                    success=False, reason="workspace_lease_unavailable"
                )
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
            db.commit()
            return ClaimOutcome(success=True, attempt_sequence=sequence)

    def record_session(
        self, card_id: str, attempt_sequence: int, session_id: str
    ) -> bool:
        """Note which backend session an attempt runs, so an operator can
        go from the attempt to that session's server-log lines.

        :returns: Whether the attempt exists.
        """
        with self._factory.begin() as db:
            attempt = db.get(BoardCardAttemptRow, (card_id, attempt_sequence))
            if attempt is None:
                return False
            attempt.session_id = session_id
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
        with self._factory.begin() as db:
            attempt = db.get(BoardCardAttemptRow, (card_id, attempt_sequence))
            if attempt is None:
                return CompleteOutcome(success=False, reason="not_found")
            # Freeing the claim (and with it the repository) is what
            # decides whether this completion or a concurrent recovery
            # or release wins.
            held = _end_claim(db, card_id, attempt_sequence) is not None
            attempt.result = result
            attempt.ended_at = now
            attempt.status = "completed" if held else "stale"
            if not held:
                return CompleteOutcome(success=False, reason="stale")
            db.execute(
                update(BoardCardRow)
                .where(BoardCardRow.id == card_id)
                .values(state=new_state, updated_at=now)
            )
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
        with self._factory.begin() as db:
            expired = db.execute(
                delete(BoardClaimLeaseRow)
                .where(BoardClaimLeaseRow.expires_at <= now)
                .returning(
                    BoardClaimLeaseRow.card_id,
                    BoardClaimLeaseRow.attempt_sequence,
                )
            ).all()
            for card_id, attempt_sequence in expired:
                _interrupt(db, card_id, attempt_sequence, now)
                db.execute(
                    update(BoardCardRow)
                    .where(BoardCardRow.id == card_id)
                    .values(state=_RETRY_OR_FAIL, updated_at=now)
                )
            return [card_id for card_id, _ in expired]

    def release_claim(
        self, card_id: str, *, now: datetime | None = None
    ) -> bool:
        """Release an active claim on operator authority (cancel/reassign).

        Unlike :meth:`expire_leases`, this never decides the card's next
        state — the caller (an intervention) does that separately — it
        only marks the active attempt ``interrupted`` and frees the claim
        and its repository.

        :returns: Whether an active lease was found and released.
        """
        now = now_utc(now)
        with self._factory.begin() as db:
            attempt_sequence = _end_claim(db, card_id)
            if attempt_sequence is None:
                return False
            _interrupt(db, card_id, attempt_sequence, now)
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


#: An expired claim's card goes back to ``ready`` while it has attempts
#: left, else to ``failed`` (decided on the row, not read beforehand).
_RETRY_OR_FAIL = case(
    (BoardCardRow.attempt_count >= BoardCardRow.attempt_limit, "failed"),
    else_="ready",
)


def _take_lease(
    db: Session, request: ClaimRequest, sequence: int, now: datetime
) -> bool:
    """Insert the claim's lease, holding its repository if it has one.

    :returns: Whether it was inserted; ``False`` when another active
        claim holds the repository (once that claim's transaction is
        settled, if it is still in progress).
    """
    taken = db.execute(
        insert(BoardClaimLeaseRow)
        .values(
            card_id=request.card_id,
            attempt_sequence=sequence,
            holder_specialist_id=request.specialist_id,
            workspace_repo=request.workspace_repo,
            expires_at=now + timedelta(seconds=request.lease_seconds),
        )
        .on_conflict_do_nothing(index_elements=["workspace_repo"])
        .returning(BoardClaimLeaseRow.card_id)
    )
    return taken.first() is not None


def _end_claim(
    db: Session, card_id: str, attempt_sequence: int | None = None
) -> int | None:
    """Delete *card_id*'s claim lease (only *attempt_sequence*'s, if
    given).

    :returns: The attempt the deleted lease belonged to, or ``None`` when
        there was none to delete (or a concurrent caller deleted it
        first).
    """
    statement = delete(BoardClaimLeaseRow).where(
        BoardClaimLeaseRow.card_id == card_id
    )
    if attempt_sequence is not None:
        statement = statement.where(
            BoardClaimLeaseRow.attempt_sequence == attempt_sequence
        )
    return db.execute(
        statement.returning(BoardClaimLeaseRow.attempt_sequence)
    ).scalar_one_or_none()


def _interrupt(
    db: Session, card_id: str, attempt_sequence: int, now: datetime
) -> None:
    """Mark an abandoned or released attempt ``interrupted``."""
    db.execute(
        update(BoardCardAttemptRow)
        .where(
            BoardCardAttemptRow.card_id == card_id,
            BoardCardAttemptRow.sequence == attempt_sequence,
        )
        .values(status="interrupted", ended_at=now)
    )
