"""Tests for source-neutral child-task branch-selection rules."""
from __future__ import annotations

from app.services.task_scheduler import ScheduledTask, integration_branch


def test_child_uses_its_parent_feature_integration_branch() -> None:
    """Every published child uses its parent's shared integration branch."""
    assert integration_branch(
        ScheduledTask("o/r#2", "o/r", integration_branch="kestrel/issue-1")
    ) == "kestrel/issue-1"
    assert integration_branch(ScheduledTask("o/r#1", "o/r")) is None
