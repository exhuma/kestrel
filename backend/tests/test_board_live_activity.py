"""Live activity: "working" only while something runs (feature 033)."""
from __future__ import annotations

import pytest

from app.services.board.live_activity import LiveActivity


def test_a_turn_is_live_only_while_it_runs() -> None:
    live = LiveActivity()

    with live.track("wf-1", "pm", "Restate the request"):
        turn = live.current("wf-1")
        assert (turn.actor, turn.subject) == ("pm", "Restate the request")

    assert live.current("wf-1") is None


def test_a_failed_turn_is_no_longer_live() -> None:
    """Ensure a crash or timeout never leaves a request "working"."""
    live = LiveActivity()

    with pytest.raises(TimeoutError), live.track("wf-1", "coordinator"):
        raise TimeoutError

    assert live.current("wf-1") is None


def test_the_longest_running_turn_is_reported() -> None:
    live = LiveActivity()

    with live.track("wf-1", "coordinator"), live.track("wf-1", "pm", "x"):
        assert live.current("wf-1").actor == "coordinator"
        assert live.current("wf-2") is None
