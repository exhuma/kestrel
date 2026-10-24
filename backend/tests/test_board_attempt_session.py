"""A card attempt records the backend session that ran it (#86, #62).

The session id is the key to the attempt's agent output in the server
log (``kestrel.agent``), so it is written as soon as the backend reports
it, even if the turn later fails.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.backends.base import TurnRequest, TurnResult
from app.models_board import ClaimRequest, WorkCard
from app.persistence.board_claims_store import BoardClaimsStore
from app.persistence.board_store import BoardStore
from app.persistence.board_tables import BoardCardAttemptRow
from app.services.board.dispatch_ready import dispatch_ready_work
from app.services.board.specialists import SpecialistRoster
from tests.board_test_support import board_session_factory
from tests.test_board_claims import _WORKFLOW
from tests.test_board_scheduling import _dispatch_services, _specialist


def _attempt_session(tmp_path: Path, card_id: str, sequence: int) -> str | None:
    """The session id stored on one attempt row."""
    with board_session_factory(tmp_path)() as db:
        row = db.get(BoardCardAttemptRow, (card_id, sequence))
        assert row is not None
        return row.session_id


def _ready_card(card_id: str = "card-1") -> WorkCard:
    return WorkCard(
        id=card_id,
        workflow_id="wf-1",
        kind="analysis",
        title="Investigate",
        state="ready",
        eligible_roles=("developer",),
    )


class _SessionBackend:
    """A backend that reports a session id, then finishes or fails."""

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail
        self.request: TurnRequest | None = None

    async def run_turn(self, req: TurnRequest) -> TurnResult:
        self.request = req
        assert req.on_session_id is not None
        req.on_session_id("sess-42")
        await asyncio.sleep(0)
        if self._fail:
            raise RuntimeError("backend exploded")
        return TurnResult(session_id="sess-42", final_text="<RESULT>x</RESULT>")


def test_a_new_attempt_has_no_session_until_one_is_recorded(
    tmp_path: Path,
) -> None:
    """Ensure the column starts empty and record_session fills it."""
    factory = board_session_factory(tmp_path)
    board, claims = BoardStore(factory), BoardClaimsStore(factory)
    board.create_workflow(_WORKFLOW)
    board.create_card(_ready_card())
    claims.claim_card(ClaimRequest("card-1", "developer", 60))
    assert _attempt_session(tmp_path, "card-1", 1) is None

    assert claims.record_session("card-1", 1, "sess-1") is True

    assert _attempt_session(tmp_path, "card-1", 1) == "sess-1"


def test_recording_a_session_for_an_unknown_attempt_is_a_no_op(
    tmp_path: Path,
) -> None:
    """Ensure an attempt that does not exist is reported, not invented."""
    claims = BoardClaimsStore(board_session_factory(tmp_path))
    assert claims.record_session("nope", 1, "sess-1") is False


@pytest.mark.asyncio
async def test_dispatch_stores_the_session_id_and_tags_the_card(
    tmp_path: Path,
) -> None:
    """Ensure a dispatched turn writes its session id on the attempt and
    hands the backend the card id for its log lines."""
    roster = SpecialistRoster({"developer": _specialist()})
    services, store = _dispatch_services(tmp_path, roster)
    store.create_card(_ready_card())
    backend = _SessionBackend()

    await dispatch_ready_work(
        "wf-1", services, lambda _specialist: backend, timeout_seconds=5
    )

    assert _attempt_session(tmp_path, "card-1", 1) == "sess-42"
    assert backend.request is not None
    assert backend.request.card_id == "card-1"


@pytest.mark.asyncio
async def test_dispatch_keeps_the_session_id_of_a_failed_turn(
    tmp_path: Path,
) -> None:
    """Ensure a turn that dies after reporting its session still leaves
    the id, since that is when an operator most needs the log lines."""
    roster = SpecialistRoster({"developer": _specialist()})
    services, store = _dispatch_services(tmp_path, roster)
    store.create_card(_ready_card())

    await dispatch_ready_work(
        "wf-1", services, lambda _specialist: _SessionBackend(fail=True),
        timeout_seconds=5,
    )

    assert _attempt_session(tmp_path, "card-1", 1) == "sess-42"
