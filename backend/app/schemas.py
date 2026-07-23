"""Response/DTO schemas shared across the service and router layers.

These mirror the frontend business types in ``frontend/src/types/``;
keep them in sync when the API changes (see the type contract in
``.specify/memory/constitution.md``).
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
    #: A 1-2 word hint of the agent's current activity ("thinking",
    #: "reading", …), derived live from its event stream; None if idle.
    activity: str | None = None
    #: When status is "error", a short failure reason for the chip.
    error: str | None = None


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
    #: How many code↔verify iterations the verify step has entered (1-based;
    #: 0 before it runs). Drives the verify chip's remaining-runs indicator.
    verify_round: int = 0
    #: The backend id serving this step (e.g. "claude", "oc", "llm"), so
    #: the UI can show which agent runs each step.
    backend: str = ""
    #: How the UI should render ``deliverable``: ``"diff"`` for the code
    #: step's unified git diff (shown in a diff viewer), ``"markdown"``
    #: otherwise (prose / questionnaire fall through the markdown path).
    deliverable_format: str = "markdown"


class WorkflowSummary(BaseModel):
    """Workflow list item."""

    id: str
    repo: str
    #: GitHub issue number; ``null`` for a Jira-sourced run (feature 003).
    issue_number: int | None
    status: str


class WorkflowDetail(BaseModel):
    """Full workflow run for the detail endpoint."""

    id: str
    repo: str
    #: GitHub issue number; ``null`` for a Jira-sourced run (feature 003),
    #: whose ticket has no numeric id. Origin/task_ref stay internal (FR-026).
    issue_number: int | None
    issue_title: str
    status: str
    branch: str
    steps: list[WorkflowStepOut]
    current_session_id: str | None
    #: Live session chips for the step currently working/awaiting.
    active_sessions: list[StepSessionOut]
    #: The refine interview's current dynamic round cap (grows by one per
    #: retry round); shown as "Round N / cap".
    refine_round_cap: int
    #: Absolute ceiling on refine rounds (retries included); shown as
    #: "(max M)".
    refine_max_rounds: int
    #: The configured cap on code↔verify iterations
    #: (``max_verify_iterations``); with a step's ``verify_round`` this
    #: drives the verify chip's "N runs left" progress circle.
    verify_max_iterations: int
    #: When true, the UI lets a questionnaire be submitted incomplete
    #: (a configured safety net); unanswered questions go through blank.
    allow_incomplete_answers: bool
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
    #: Derived from status: "action_required" gate vs terminal "summary".
    signal_class: str
    message: str
    created_at: datetime
    read: bool
