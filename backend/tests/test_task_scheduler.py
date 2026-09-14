"""Tests for source-neutral child-task scheduling rules."""
from __future__ import annotations

from app.models_workflow import WorkflowRun
from app.services.task_scheduler import (
    ScheduledTask,
    integration_branch,
    is_startable,
    modifying_repositories,
)


def test_task_waits_for_prerequisites_and_repo_modifier() -> None:
    """A child starts only after prerequisites and repository exclusivity."""
    task = ScheduledTask("o/r#2", "o/r", ("o/r#1",))
    assert is_startable(task, {"o/r#1"}, set()) is True
    assert is_startable(task, set(), set()) is False
    assert is_startable(task, {"o/r#1"}, {"o/r"}) is False


def test_modifying_repositories_excludes_waiting_ci_runs() -> None:
    """CI waiting does not block a separate run from modifying the repo."""
    runs = [
        WorkflowRun(id="one", repo="o/r", status="coding"),
        WorkflowRun(id="two", repo="other/r", status="awaiting_ci"),
    ]
    assert modifying_repositories(runs) == {"o/r"}


def test_child_uses_its_parent_feature_integration_branch() -> None:
    """Every published child uses its parent's shared integration branch."""
    assert integration_branch(
        ScheduledTask("o/r#2", "o/r", integration_branch="kestrel/issue-1")
    ) == "kestrel/issue-1"
    assert integration_branch(ScheduledTask("o/r#1", "o/r")) is None
