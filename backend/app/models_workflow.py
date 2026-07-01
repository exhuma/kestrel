"""Domain models for workflow runs."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WorkflowStep:
    """One step of a workflow run, with its deliverable."""

    name: str
    session_id: str | None = None
    status: str = "pending"
    deliverable: str | None = None


@dataclass
class WorkflowRun:
    """A GitHub issue -> code workflow run."""

    id: str
    repo: str
    issue_number: int
    issue_title: str = ""
    base_branch: str = ""
    branch: str = ""
    workspace: str = ""
    status: str = "pending"
    steps: list[WorkflowStep] = field(default_factory=list)
    pr_url: str | None = None
    error: str | None = None
