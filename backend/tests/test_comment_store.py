"""The comment store: a read position per request and one row per
considered comment (feature 046, T036)."""
from __future__ import annotations

from pathlib import Path

from app.persistence.comment_store import (
    CLAIMED,
    HELD,
    CommentStore,
    InboundComment,
    Outcome,
)
from tests.announcement_support import WORKFLOW_ID, build_stack
from tests.board_test_support import board_session_factory

_COMMENT = InboundComment("jira-comment:KEY-1:1", WORKFLOW_ID, "acc-1")


def _store(tmp_path: Path) -> CommentStore:
    build_stack(tmp_path)  # migrates and creates the workflow
    return CommentStore(board_session_factory(tmp_path))


def test_the_cursor_starts_empty_and_keeps_what_it_is_given(
    tmp_path: Path,
) -> None:
    """Ensure the read position round-trips, and moves on."""
    store = _store(tmp_path)
    assert store.get_cursor(WORKFLOW_ID) is None

    store.set_cursor(WORKFLOW_ID, "2026-10-05T10:00:00.000+0000")
    store.set_cursor(WORKFLOW_ID, "2026-10-05T11:00:00.000+0000")

    assert store.get_cursor(WORKFLOW_ID) == "2026-10-05T11:00:00.000+0000"


def test_a_comment_is_claimed_once(tmp_path: Path) -> None:
    """Ensure a second claim, from any cycle, is refused."""
    store = _store(tmp_path)

    assert store.claim(_COMMENT) is True
    assert store.claim(_COMMENT) is False
    assert store.get(_COMMENT.external_id).state == CLAIMED


def test_a_claim_survives_a_new_store(tmp_path: Path) -> None:
    """Ensure "at most once" holds across a restart."""
    _store(tmp_path).claim(_COMMENT)

    restarted = CommentStore(board_session_factory(tmp_path))

    assert restarted.claim(_COMMENT) is False


def test_an_outcome_is_recorded(tmp_path: Path) -> None:
    """Ensure what became of a comment is kept."""
    store = _store(tmp_path)
    store.claim(_COMMENT)

    store.record_outcome(
        _COMMENT.external_id,
        Outcome("decided", gate_card_id="card-1", intent="approve"),
    )

    found = store.get(_COMMENT.external_id)
    assert (found.state, found.gate_card_id, found.intent) == (
        "decided", "card-1", "approve"
    )


def test_a_held_comment_is_found_by_its_review_and_reclaimed_once(
    tmp_path: Path,
) -> None:
    """Ensure a release continues the held comment exactly once."""
    store = _store(tmp_path)
    store.claim(_COMMENT)
    store.record_outcome(
        _COMMENT.external_id, Outcome(HELD, security_review_id="review-1")
    )

    held = store.held_for_review("review-1")

    assert held is not None and held.external_id == _COMMENT.external_id
    assert store.held_for_review("review-other") is None
    assert store.reclaim_held(_COMMENT.external_id) is True
    assert store.reclaim_held(_COMMENT.external_id) is False


def test_a_comment_that_is_not_held_cannot_be_reclaimed(
    tmp_path: Path,
) -> None:
    """Ensure only a held comment is taken on again."""
    store = _store(tmp_path)
    store.claim(_COMMENT)
    store.record_outcome(_COMMENT.external_id, Outcome("decided"))

    assert store.reclaim_held(_COMMENT.external_id) is False
