"""Where reading a ticket's comments got to, and what became of each
reply (feature 046, research R8).

Two tables (migration 0036): a per-request read position, and one row per
comment kestrel considered. A comment is *claimed* by inserting its row
before anything is done with it: the primary key on its external id makes
"acted on at most once" hold across poll cycles, restarts and edits (an
edited comment keeps its id). A crash after the claim loses that reply
rather than acting on it twice.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.board_tables import (
    BoardCommentCursorRow,
    BoardInboundCommentRow,
)
from app.persistence.board_time import now_utc
from app.persistence.db import get_sessionmaker

#: The state of a comment taken on and not yet settled.
CLAIMED = "claimed"
#: The state of a comment screening held back.
HELD = "held"


@dataclass(frozen=True)
class InboundComment:
    """A comment kestrel considered, and what became of it.

    :param state: See :data:`CLAIMED`, :data:`HELD` and the other states
        in data-model.md.
    """

    external_id: str
    workflow_id: str
    author_account_id: str
    state: str = CLAIMED
    gate_card_id: str | None = None
    security_review_id: str | None = None
    intent: str | None = None


@dataclass(frozen=True)
class Outcome:
    """How a claimed comment was settled."""

    state: str
    gate_card_id: str | None = None
    security_review_id: str | None = None
    intent: str | None = None


def _record(row: BoardInboundCommentRow) -> InboundComment:
    return InboundComment(
        external_id=row.external_id,
        workflow_id=row.workflow_id,
        author_account_id=row.author_account_id,
        state=row.state,
        gate_card_id=row.gate_card_id,
        security_review_id=row.security_review_id,
        intent=row.intent,
    )


class CommentStore:
    """The read position per request, and the considered comments."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def get_cursor(self, workflow_id: str) -> str | None:
        """Where reading *workflow_id*'s comments continues, or ``None``
        to read from the start."""
        with self._factory() as db:
            row = db.get(BoardCommentCursorRow, workflow_id)
            return row.cursor if row is not None else None

    def set_cursor(
        self, workflow_id: str, cursor: str | None,
        *, now: datetime | None = None,
    ) -> None:
        """Record where reading *workflow_id*'s comments got to."""
        with self._factory.begin() as db:
            row = db.get(BoardCommentCursorRow, workflow_id)
            if row is None:
                row = BoardCommentCursorRow(workflow_id=workflow_id)
                db.add(row)
            row.cursor = cursor
            row.updated_at = now_utc(now)

    def claim(
        self, comment: InboundComment, *, now: datetime | None = None
    ) -> bool:
        """Take *comment* on, unless it already was.

        :returns: ``True`` when this call took it on; ``False`` when it
            was considered before (by any cycle, before any restart).
        """
        row = BoardInboundCommentRow(
            external_id=comment.external_id,
            workflow_id=comment.workflow_id,
            author_account_id=comment.author_account_id,
            state=CLAIMED,
            created_at=now_utc(now),
        )
        try:
            with self._factory.begin() as db:
                db.add(row)
        except IntegrityError:
            return False
        return True

    def reclaim_held(self, external_id: str) -> bool:
        """Take a held comment on again, after its review was released.

        :returns: ``True`` when this call took it on; ``False`` when it is
            not held (never was, or another call took it on first).
        """
        with self._factory.begin() as db:
            result = db.execute(
                update(BoardInboundCommentRow)
                .where(
                    BoardInboundCommentRow.external_id == external_id,
                    BoardInboundCommentRow.state == HELD,
                )
                .values(state=CLAIMED)
            )
            return result.rowcount == 1

    def record_outcome(
        self, external_id: str, outcome: Outcome,
        *, now: datetime | None = None,
    ) -> None:
        """Record how a claimed comment was settled."""
        with self._factory.begin() as db:
            row = db.get(BoardInboundCommentRow, external_id)
            if row is None:
                return
            row.state = outcome.state
            row.gate_card_id = outcome.gate_card_id
            row.security_review_id = outcome.security_review_id
            row.intent = outcome.intent
            row.processed_at = now_utc(now)

    def get(self, external_id: str) -> InboundComment | None:
        """The considered comment *external_id*, if there is one."""
        with self._factory() as db:
            row = db.get(BoardInboundCommentRow, external_id)
            return _record(row) if row is not None else None

    def held_for_review(self, review_id: str) -> InboundComment | None:
        """The comment security review *review_id* holds, if it is one."""
        with self._factory() as db:
            row = (
                db.query(BoardInboundCommentRow)
                .filter(BoardInboundCommentRow.security_review_id == review_id)
                .one_or_none()
            )
            return _record(row) if row is not None else None


@lru_cache
def get_comment_store() -> CommentStore:
    """Return the process-wide CommentStore singleton."""
    return CommentStore(get_sessionmaker())
