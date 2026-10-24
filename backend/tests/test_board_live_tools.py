"""A card turn's tool use, live on the request (feature 036)."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from app.backends.base import TurnStopped
from app.models_board import WorkCard
from app.services.board import live_activity
from app.services.board.activity import ActivityInputs, activity_of
from app.services.board.dispatch import CardTurnError
from app.services.board.dispatch_ready import dispatch_ready_work
from app.services.board.live_activity import (
    LiveActivity,
    tracking,
    turn_failure,
)
from app.services.board.service import BoardService
from app.services.board.specialists import SpecialistRoster
from tests.test_board_scheduling import (
    _dispatch_services,
    _FakeBackend,
    _specialist,
)


def test_each_tool_call_shows_on_the_live_turn() -> None:
    live = LiveActivity()
    with live.track("wf-1", "Project Manager", "Draft PRD") as note_tool:
        note_tool("read")
        note_tool("gitlab_list_project_issues")
        turn = live.current("wf-1")

    assert (turn.tool, turn.tool_calls) == ("gitlab_list_project_issues", 2)
    assert live.current("wf-1") is None


def test_live_views_are_told_at_most_every_two_seconds(monkeypatch) -> None:
    """Ensure a tool called every second does not flood live views."""
    clock = iter([0.0, 0.5, 1.9, 2.1, 2.2])
    monkeypatch.setattr(live_activity.time, "monotonic", lambda: next(clock))
    told: list[str] = []

    with LiveActivity().track(
        "wf-1", "pm", on_change=lambda: told.append("tick")
    ) as note_tool:
        for _ in range(5):
            note_tool("read")

    assert told == ["tick", "tick"]  # at 0.0 and 2.1


def test_untracked_work_takes_tool_notes_harmlessly() -> None:
    with tracking(None, "wf-1", "pm") as note_tool:
        note_tool("read")


def test_a_stopped_turn_says_why() -> None:
    """Ensure kestrel's own reason reaches the request, however wrapped."""
    try:
        try:
            raise TurnStopped("it called read 5 times with the same input")
        except TurnStopped as exc:
            raise CardTurnError(f"card turn backend error: {exc}") from exc
    except CardTurnError as wrapped:
        reason = turn_failure("Project Manager", wrapped)

    assert reason == (
        "Project Manager's turn was stopped: "
        "it called read 5 times with the same input"
    )


def test_working_activity_carries_the_last_tool() -> None:
    live = LiveActivity()
    with live.track("wf-1", "Project Manager", "Draft PRD") as note_tool:
        note_tool("grep")
        activity = activity_of(
            ActivityInputs([], [], live.current("wf-1"), "in_progress", {})
        )

    assert (activity.state, activity.tool, activity.tool_calls) == (
        "working", "grep", 1,
    )


@pytest.mark.asyncio
async def test_a_card_turn_reports_its_tools_live(tmp_path: Path) -> None:
    """Ensure a card turn's tool calls reach the live turn and live views
    while it runs."""
    roster = SpecialistRoster({"developer": _specialist()})
    services, store = _dispatch_services(tmp_path, roster)
    live = LiveActivity()
    announced: list[str] = []
    seen: list[tuple[str | None, int]] = []

    class _Board(BoardService):
        def announce(self, workflow_id: str) -> None:
            announced.append(workflow_id)

    class _Calling(_FakeBackend):
        async def run_turn(self, req):
            req.on_tool("read")
            turn = live.current("wf-1")
            seen.append((turn.tool, turn.tool_calls))
            return await super().run_turn(req)

    services = replace(services, board=_Board(store), live=live)
    store.create_card(
        WorkCard(
            id="card-1", workflow_id="wf-1", kind="analysis",
            title="Investigate", state="ready", eligible_roles=("developer",),
        )
    )

    await dispatch_ready_work(
        "wf-1", services, lambda _s: _Calling("<RESULT>ok</RESULT>"),
        timeout_seconds=5,
    )

    assert seen == [("read", 1)]
    assert "wf-1" in announced
