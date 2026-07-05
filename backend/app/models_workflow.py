"""Domain models for workflow runs."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StepSession:
    """One live claude session backing a step, shown as a UI chip.

    A named session (a refinement specialist, the coordinator, the
    writer, or a plan/implement worker) that is or was active during a
    step. Purely ephemeral telemetry: it exists only while a step is
    running — a transient phase that never survives a restart — so it is
    deliberately *not* persisted to ``WorkflowStepRow``.

    :param profile_id: Stable id (a profile id, or "coordinator"/
        "writer"/"planner"/"builder").
    :param label: Human-readable mnemonic for the chip.
    :param badge: Theme tone token (see ``styles/theme.css``).
    :param session_id: The claude session id once known, else None.
    :param status: "running" while live, "idle" once finished.
    :param activity: A 1-2 word hint of what the agent is doing right
        now (e.g. "thinking", "reading", "editing"), derived live from
        its event stream; None when unknown or idle.
    :param error: When ``status == "error"``, a short reason (timeout,
        crash, or "no response") shown on the chip; None otherwise.
    """

    profile_id: str
    label: str
    badge: str = "sys"
    session_id: str | None = None
    status: str = "running"
    activity: str | None = None
    error: str | None = None


@dataclass
class WorkflowStep:
    """One step of a workflow run, with its deliverable."""

    name: str
    session_id: str | None = None
    status: str = "pending"
    deliverable: str | None = None
    model: str | None = None
    #: Monotonic counter bumped only when the refine step's interview
    #: genuinely advances to a new round; the single source of truth
    #: for round-change detection (distinguishes a genuine
    #: questionnaire change from a no-op SSE update).
    refine_round: int = 0
    #: Live sessions backing this step right now (ephemeral chip state;
    #: never persisted — see :class:`StepSession`).
    active_sessions: list[StepSession] = field(default_factory=list)


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
