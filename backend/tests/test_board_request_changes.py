"""A delivered request can be sent back for more work (spec 044's first
step): the feedback becomes a task on the same branch."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.models_board import WorkCard, Workflow
from app.persistence.board_artifact_store import BoardArtifactStore
from app.persistence.board_store import BoardStore
from app.ports import ChangeRequest
from app.services.board.artifacts import ArtifactsService
from app.services.board.delivery_readiness import delivery_due, delivery_trigger
from app.services.board.interventions import (
    InvalidInterventionError,
    StaleInterventionError,
)
from app.services.board.materialise import MaterialiseTarget, task_context
from app.services.board.phases import outcome_of
from app.services.board.requested_changes import (
    REQUESTED_EVENT,
    RequestChangesService,
)
from app.services.board.service import BoardService
from app.services.exceptions import GitError
from tests.board_test_support import board_session_factory

#: Longer than any title the feedback's first line may produce.
_TITLE_CEILING = 120
_FEEDBACK = "Rename the export button to **Download**.\n\nKeep the icon."


class _CodeHost:
    def __init__(self, state: str = "open", error: Exception | None = None):
        self._state = state
        self._error = error

    async def get_change_request(
        self, _repo: str, number: int
    ) -> ChangeRequest:
        if self._error is not None:
            raise self._error
        return ChangeRequest(number=number, state=self._state)


class _Board:
    """A delivered request and the service under test."""

    def __init__(self, tmp_path: Path, code_host: object | None) -> None:
        factory = board_session_factory(tmp_path)
        self.store = BoardStore(factory)
        board_service = BoardService(self.store)
        self.artifacts = ArtifactsService(
            self.store, BoardArtifactStore(factory), board_service
        )
        self.service = RequestChangesService(
            MaterialiseTarget(self.store, self.artifacts),
            board_service,
            {"jira-issue": code_host} if code_host else {},
        )
        self.store.create_workflow(Workflow(
            id="wf-1", source="jira-issue", task_ref="X-1", repo="o/r",
            base_branch="main", source_visibility="public", title="Demo",
        ))
        self.store.create_card(WorkCard(
            id="done-fix", workflow_id="wf-1", kind="implementation",
            title="Build it", state="done",
        ))
        self.store.create_card(WorkCard(
            id="delivery", workflow_id="wf-1", kind="delivery",
            title="Deliver", state="done",
        ))
        self.store.record_delivery("wf-1", 7, "https://git.example/mr/7")
        self.store.record_ci_status("wf-1", "passed")

    @property
    def workflow(self) -> Workflow:
        return self.store.get_workflow("wf-1")

    async def request(self, feedback: str = _FEEDBACK) -> WorkCard:
        return await self.service.request(
            self.workflow, feedback,
            expected_revision=self.workflow.revision,
        )

    def card(self, kind: str) -> WorkCard:
        return next(
            c for c in self.store.list_cards("wf-1")
            if c.kind == kind and c.state != "done"
        )


@pytest.fixture(name="board")
def _board(tmp_path: Path) -> _Board:
    return _Board(tmp_path, _CodeHost())


@pytest.mark.asyncio
async def test_feedback_starts_a_fix_and_its_verification(
    board: _Board,
) -> None:
    """Ensure the fix can start and its check waits for it."""
    fix = await board.request()

    check = board.card("verification")
    assert (fix.state, fix.eligible_roles) == ("ready", ("coder",))
    assert (check.state, check.eligible_roles) == (
        "waiting_dependency", ("verifier",)
    )
    assert fix.task_node_id == check.task_node_id is not None
    (relation,) = board.store.list_relations("wf-1")
    assert (relation.card_id, relation.depends_on_card_id) == (check.id, fix.id)


@pytest.mark.asyncio
async def test_the_request_is_open_again_and_says_why(board: _Board) -> None:
    """Ensure the board reopens, with the feedback in its history."""
    revision = board.workflow.revision

    await board.request()

    cards = board.store.list_cards("wf-1")
    assert outcome_of(cards) == "in_progress"
    assert board.workflow.revision == revision + 1
    event = board.store.list_events("wf-1")[-1]
    assert event.event_type == REQUESTED_EVENT
    assert "Rename the export button" in event.payload


@pytest.mark.asyncio
async def test_the_coder_and_verifier_both_get_the_feedback(
    board: _Board,
) -> None:
    """Ensure every card of the round works from the feedback."""
    fix = await board.request()
    check = board.card("verification")
    cards = board.store.list_cards("wf-1")

    for card in (fix, check):
        text = task_context(card, cards, board.artifacts)
        assert "Rename the export button" in text
        assert "existing branch" in text


@pytest.mark.asyncio
async def test_a_long_first_line_makes_a_short_title(board: _Board) -> None:
    """Ensure the feedback cannot blow up the board's labels."""
    fix = await board.request("x" * 400)

    assert len(fix.title) < _TITLE_CEILING


@pytest.mark.asyncio
async def test_the_new_push_has_its_ci_watched_again(board: _Board) -> None:
    """Ensure a passed verdict for the old code does not stop the poll."""
    await board.request()

    assert board.workflow.ci_status == "pending"


@pytest.mark.asyncio
async def test_finished_changes_are_delivered_again(board: _Board) -> None:
    """Ensure the round counts as new work to deliver, once verified."""
    before = delivery_trigger(board.store.list_cards("wf-1"))
    fix = await board.request()
    check = board.card("verification")
    relations = board.store.list_relations("wf-1")
    assert delivery_due(board.store.list_cards("wf-1"), relations) is False

    board.store.set_card_state(fix.id, "done")
    board.store.set_card_state(check.id, "done")

    cards = board.store.list_cards("wf-1")
    assert delivery_due(cards, relations) is True
    assert delivery_trigger(cards) != before


@pytest.mark.asyncio
@pytest.mark.parametrize("feedback", ["", "   \n "])
async def test_feedback_is_required(board: _Board, feedback: str) -> None:
    """Ensure nobody starts a round with nothing to do."""
    with pytest.raises(InvalidInterventionError, match="what should change"):
        await board.request(feedback)


@pytest.mark.asyncio
async def test_a_stale_view_is_refused(board: _Board) -> None:
    """Ensure feedback is not applied to a board the reviewer did not see."""
    with pytest.raises(StaleInterventionError):
        await board.service.request(
            board.workflow, _FEEDBACK,
            expected_revision=board.workflow.revision + 1,
        )


@pytest.mark.asyncio
async def test_work_in_progress_is_refused(board: _Board) -> None:
    """Ensure a second round cannot start on top of the first."""
    await board.request()

    with pytest.raises(InvalidInterventionError, match="delivered"):
        await board.request()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["merged", "closed"])
async def test_a_finished_change_request_is_refused(
    tmp_path: Path, state: str
) -> None:
    """Ensure no work starts that could never reach a reviewer."""
    board = _Board(tmp_path, _CodeHost(state))

    with pytest.raises(InvalidInterventionError, match=state):
        await board.request()

    assert outcome_of(board.store.list_cards("wf-1")) == "done"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [GitError("boom"), httpx.ConnectError("down")]
)
async def test_an_unreachable_code_host_is_refused(
    tmp_path: Path, error: Exception
) -> None:
    """Ensure not knowing the change request's state stops the round."""
    board = _Board(tmp_path, _CodeHost(error=error))

    with pytest.raises(InvalidInterventionError, match="could not confirm"):
        await board.request()


@pytest.mark.asyncio
async def test_a_source_without_change_requests_can_still_ask(
    tmp_path: Path,
) -> None:
    """Ensure a local task source has nothing to check."""
    board = _Board(tmp_path, None)

    fix = await board.request()

    assert fix.state == "ready"
