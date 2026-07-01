"""Response/DTO schemas shared across the service and router layers.

These mirror the frontend business types in ``frontend/src/types/``;
keep them in sync when the API changes (see ``contract.md``).
"""
from __future__ import annotations

from pydantic import BaseModel


class SessionSummary(BaseModel):
    """Summary of one session for the list endpoint.

    :param session_id: Unique id of the session.
    :param status: Current lifecycle status (e.g. running, idle).
    :param event_count: Number of events recorded so far.
    """

    session_id: str
    status: str
    event_count: int


class WorkflowStepOut(BaseModel):
    """One workflow step for the API."""

    name: str
    session_id: str | None
    status: str
    deliverable: str | None


class WorkflowSummary(BaseModel):
    """Workflow list item."""

    id: str
    repo: str
    issue_number: int
    status: str


class WorkflowDetail(BaseModel):
    """Full workflow run for the detail endpoint."""

    id: str
    repo: str
    issue_number: int
    issue_title: str
    status: str
    branch: str
    steps: list[WorkflowStepOut]
    current_session_id: str | None
    pr_url: str | None
    error: str | None


class CreateWorkflowIn(BaseModel):
    """Request body to start a workflow."""

    repo: str
    issue_number: int


class ReplyIn(BaseModel):
    """Request body to answer the refine interview."""

    text: str


class ApproveIn(BaseModel):
    """Request body to approve a gate, optionally with an edited deliverable."""

    deliverable: str | None = None
