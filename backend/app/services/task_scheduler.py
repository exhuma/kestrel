"""Pure eligibility and branch-selection rules for decomposed child tasks."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol


@dataclass(frozen=True)
class ScheduledTask:
    """A task's repository and prerequisite identities for scheduling."""

    task_ref: str
    repo: str
    prerequisites: tuple[str, ...] = ()
    integration_branch: str = ""


_MODIFYING_STATUSES = frozenset({
    "cloning", "describing", "refining", "analyzing", "designing",
    "coding", "verifying", "repairing_ci", "opening_pr",
})


class _RunState(Protocol):
    """The minimal workflow-run state the scheduler reads."""

    repo: str
    status: str


def is_startable(
    task: ScheduledTask,
    ready_task_refs: set[str],
    active_repos: Iterable[str],
) -> bool:
    """Return whether prerequisites are ready and its repo has no modifier."""
    return (
        set(task.prerequisites) <= ready_task_refs
        and task.repo not in set(active_repos)
    )


def modifying_repositories(runs: Iterable[_RunState]) -> set[str]:
    """Return repositories with a run currently allowed to change code."""
    return {
        run.repo for run in runs if run.status in _MODIFYING_STATUSES
    }


def integration_branch(task: ScheduledTask) -> str | None:
    """Return a published child's parent feature integration branch."""
    return task.integration_branch or None
