"""Pure branch-selection rules for decomposed child tasks."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScheduledTask:
    """A task's repository/branch identity for successor scheduling."""

    task_ref: str
    repo: str
    integration_branch: str = ""


def integration_branch(task: ScheduledTask) -> str | None:
    """Return a published child's parent feature integration branch."""
    return task.integration_branch or None
