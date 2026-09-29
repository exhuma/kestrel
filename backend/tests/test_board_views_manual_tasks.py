"""The listing's open-manual-task count (feature 031, FR-009)."""
from __future__ import annotations

from app.routers.board_views import workflow_summary
from tests.test_board_views import (
    _WORKFLOW,
    _card,
    _StubChildTasks,
    _StubGates,
)


def test_open_manual_tasks_are_counted() -> None:
    """Ensure the board can say "N manual tasks assigned to you"."""
    cards = [
        _card("m1", kind="manual_task", state="awaiting_human"),
        _card("m2", kind="manual_task", state="waiting_dependency"),
        _card("m3", kind="manual_task", state="done"),
        _card("m4", kind="manual_task", state="cancelled"),
        _card("i1", kind="implementation", state="ready"),
    ]
    summary = workflow_summary(
        _WORKFLOW, cards, _StubGates(), _StubChildTasks()
    )
    open_manual_tasks = 2
    assert summary.open_manual_task_count == open_manual_tasks
