"""Response/DTO schemas shared across the service and router layers.

These mirror the frontend business types in ``frontend/src/types/``;
keep them in sync when the API changes (see ``contract.md``).
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SessionSummary(BaseModel):
    """Summary of one session for the list endpoint.

    :param session_id: Unique id of the session.
    :param status: Current lifecycle status (e.g. running, idle).
    :param event_count: Number of events recorded so far.
    :param created_at: When the session started, if known.
    :param workflow: The run that used this session ("repo#issue"),
        or None for a free-form session.
    """

    session_id: str
    status: str
    event_count: int
    created_at: datetime | None = None
    workflow: str | None = None


class StepSessionOut(BaseModel):
    """One live session chip for the active workflow step."""

    profile_id: str
    label: str
    badge: str
    session_id: str | None
    status: str


class WorkflowStepOut(BaseModel):
    """One workflow step for the API."""

    name: str
    session_id: str | None
    status: str
    deliverable: str | None
    #: Monotonic counter, bumped only on a genuine refine-questionnaire
    #: change; lets the frontend ignore no-op SSE updates instead of
    #: resetting in-progress form answers.
    refine_round: int


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
    #: Live session chips for the step currently working/awaiting.
    active_sessions: list[StepSessionOut]
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


class RejectIn(BaseModel):
    """Request body to reject a gate.

    With a refinement prompt the deliverable is regenerated;
    without one the run ends as rejected.
    """

    refinement_prompt: str | None = None


class AnswersIn(BaseModel):
    """Request body to answer a structured questionnaire."""

    answers: dict[str, object]


class NotificationOut(BaseModel):
    """One notification for the API."""

    id: int
    workflow_id: str
    repo: str
    issue_number: int
    status: str
    message: str
    created_at: datetime
    read: bool
