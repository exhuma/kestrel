"""Decisions and positions hold under concurrent writers (GitHub #87).

Each test lets a second transaction settle the same row and commit while
the call under test waits on it: a gate decided twice, a review resolved
twice, a card moved from a state it already left, a read position
created twice.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.models_board import WorkCard
from app.models_board_records import HumanGateRecord
from app.persistence.board_gate_store import BoardGateStore
from app.persistence.board_quarantine_store import (
    BoardQuarantineStore,
    QuarantineRequest,
)
from app.persistence.board_store import BoardStore
from app.persistence.board_tables import (
    BoardCardRow,
    BoardCommentCursorRow,
    BoardHumanGateRow,
    BoardSecurityReviewRow,
)
from app.persistence.comment_store import CommentStore
from app.services.board.policy import PolicyViolation
from app.services.board.service import BoardService
from tests.board_test_support import board_session_factory, seed_workflows
from tests.concurrency_support import contend


def _factory(tmp_path: Path, state: str = "ready") -> sessionmaker:
    """A database with workflow wf-1 and its card card-1 in *state*."""
    factory = board_session_factory(tmp_path)
    seed_workflows(factory, "wf-1")
    BoardStore(factory).create_card(WorkCard(
        id="card-1", workflow_id="wf-1", kind="prd_gate", title="Approve",
        state=state,
    ))
    return factory


def _engine(factory: sessionmaker) -> sa.Engine:
    return factory.kw["bind"]


def test_a_gate_decided_meanwhile_is_not_decided_again(
    tmp_path: Path,
) -> None:
    """Ensure a second decision on a gate leaves the first one standing."""
    factory = _factory(tmp_path, state="awaiting_human")
    gates = BoardGateStore(factory)
    gates.create_gate(HumanGateRecord(
        id="gate-1", card_id="card-1", requested_decision="approve",
    ))

    decided = contend(
        _engine(factory),
        lambda db: db.execute(sa.update(BoardHumanGateRow).values(
            decision="approved"
        )),
        lambda: gates.record_decision("card-1", "rejected"),
    )

    assert decided is None
    assert gates.get_for_card("card-1").decision == "approved"


def test_a_review_resolved_meanwhile_is_not_resolved_again(
    tmp_path: Path,
) -> None:
    """Ensure a discard racing a release neither wins nor bumps twice."""
    factory = board_session_factory(tmp_path)
    reviews = BoardQuarantineStore(factory)
    review = reviews.quarantine(QuarantineRequest(
        workflow=None, source_identity="github-issue:o/r#1",
        content_hash="a" * 64, policy_version="1",
        safe_content_ref="quarantine://x", classification_category="x",
    ))

    resolution = contend(
        _engine(factory),
        lambda db: db.execute(sa.update(BoardSecurityReviewRow).values(
            review_state="released"
        )),
        lambda: reviews.resolve_review(review.id, "discarded"),
    )

    assert not resolution.changed
    assert resolution.review.review_state == "released"


def test_a_card_moved_meanwhile_is_not_moved_from_its_old_state(
    tmp_path: Path,
) -> None:
    """Ensure a transition checked against a state the card has left
    since is refused rather than written over the newer state."""
    factory = _factory(tmp_path)
    service = BoardService(BoardStore(factory))

    with pytest.raises(PolicyViolation):
        contend(
            _engine(factory),
            lambda db: db.execute(sa.update(BoardCardRow).values(
                state="cancelled"
            )),
            lambda: service.transition_card(
                "card-1", "waiting_dependency", event_type="test.moved"
            ),
        )

    assert BoardStore(factory).get_card("card-1").state == "cancelled"


def test_a_read_position_created_meanwhile_is_moved_on(
    tmp_path: Path,
) -> None:
    """Ensure the first two writes of a request's read position do not
    collide."""
    factory = _factory(tmp_path)
    comments = CommentStore(factory)

    contend(
        _engine(factory),
        lambda db: db.execute(sa.insert(BoardCommentCursorRow).values(
            workflow_id="wf-1", cursor="first",
            updated_at=datetime.now(timezone.utc),
        )),
        lambda: comments.set_cursor("wf-1", "second"),
    )

    assert comments.get_cursor("wf-1") == "second"
