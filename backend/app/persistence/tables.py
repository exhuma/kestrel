"""ORM table definitions for kestrel."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Text
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
)


class Base(DeclarativeBase):
    """Declarative base for all kestrel tables."""


class SessionRow(Base):
    """One dispatched claude session."""

    __tablename__ = "session"

    session_id: Mapped[str] = mapped_column(primary_key=True)
    cwd: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column()
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )


class EventRow(Base):
    """One parsed stream-json event belonging to a session."""

    __tablename__ = "event"

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("session.session_id")
    )
    type: Mapped[str] = mapped_column()
    raw: Mapped[str] = mapped_column(Text)


class WorkflowRunRow(Base):
    """One workflow run (durable mirror of WorkflowRun)."""

    __tablename__ = "workflow_run"

    id: Mapped[str] = mapped_column(primary_key=True)
    repo: Mapped[str] = mapped_column()
    #: GitHub issue number; NULL for a Jira-sourced run (feature 003).
    issue_number: Mapped[int | None] = mapped_column(nullable=True)
    issue_title: Mapped[str] = mapped_column(default="")
    base_branch: Mapped[str] = mapped_column(default="")
    branch: Mapped[str] = mapped_column(default="")
    workspace: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(default="pending")
    pr_url: Mapped[str | None] = mapped_column(nullable=True)
    #: The same pull/merge request as ``pr_url``, as a number (feature 013).
    #: NULL for pre-migration rows and runs with no open request yet; those
    #: still resolve by matching on ``pr_url`` (no backfill).
    pr_number: Mapped[int | None] = mapped_column(nullable=True)
    error: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    #: Run origin: "github-issue" | "jira-issue" | "fixture-issue".
    #: Internal-only (not in the API). Migration 0014 relabelled the retired
    #: "manual" origin onto "github-issue" and moved the server-default.
    source: Mapped[str] = mapped_column(
        default="github-issue", server_default="github-issue"
    )
    #: Source-native ticket identity (feature 003): GitHub "owner/name#123",
    #: Jira "RFC-123". Server-default "" keeps pre-existing rows valid; the
    #: migration backfills it.
    task_ref: Mapped[str] = mapped_column(default="", server_default="")
    #: Worktree-relative artifact directory (.kestrel/<date>-<serial>/) for
    #: this run's step-handover files. Server-default "" keeps pre-existing
    #: rows valid; empty until the worktree is provisioned. Internal-only.
    artifact_dir: Mapped[str] = mapped_column(
        Text, default="", server_default=""
    )
    #: The project's user-facing boundary ("http" | "ui" | "both" | "none"),
    #: set once by the design step (feature 005); NULL before design has run
    #: (or for a run created before this column existed). Internal-only.
    boundary: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Cumulative active-work / gate-wait seconds (feature 006).
    #: Server-default 0 keeps pre-existing rows valid.
    active_seconds: Mapped[float] = mapped_column(
        default=0.0, server_default="0"
    )
    wait_seconds: Mapped[float] = mapped_column(
        default=0.0, server_default="0"
    )
    #: Which clock is running now ("active" | "waiting"); NULL before
    #: start / after a terminal. Feature 006.
    clock_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Naive UTC timestamp clock_state last changed; NULL iff
    #: clock_state is NULL. Feature 006.
    clock_since: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    #: FK to the run this one continues from (feature 013, US4); NULL for
    #: every run that isn't a linked successor.
    parent_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_run.id"), nullable=True
    )


class WorkflowStepRow(Base):
    """One step of a persisted workflow run."""

    __tablename__ = "workflow_step"

    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_run.id"), primary_key=True
    )
    position: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column()
    session_id: Mapped[str | None] = mapped_column(
        nullable=True
    )
    status: Mapped[str] = mapped_column(default="pending")
    deliverable: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    model: Mapped[str | None] = mapped_column(nullable=True)
    #: Monotonic counter bumped only when the refine step's interview
    #: genuinely advances to a new round (see WorkflowStep.refine_round).
    refine_round: Mapped[int] = mapped_column(default=0)
    #: 1-based count of code↔verify iterations the verify step has entered
    #: (see WorkflowStep.verify_round). Server-default 0 keeps pre-existing
    #: rows valid.
    verify_round: Mapped[int] = mapped_column(
        default=0, server_default="0"
    )


class WorkflowRoundChipRow(Base):
    """One frozen session chip from a completed workflow round.

    The durable history trail behind :class:`~app.models_workflow.RoundChip`
    — written once a step's live chip set is retired, so completed rounds'
    chips survive a restart/reload (unlike the ephemeral ``active_sessions``
    on :class:`WorkflowStepRow`, which is never persisted at all).
    """

    __tablename__ = "workflow_round_chip"
    __table_args__ = (
        Index(
            "ix_workflow_round_chip_workflow_step",
            "workflow_id", "step_name",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_run.id")
    )
    step_name: Mapped[str] = mapped_column()
    round_index: Mapped[int] = mapped_column()
    profile_id: Mapped[str] = mapped_column()
    label: Mapped[str] = mapped_column()
    badge: Mapped[str] = mapped_column(default="sys")
    session_id: Mapped[str | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column()
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retired_at: Mapped[datetime] = mapped_column(DateTime)


class WebhookDeliveryRow(Base):
    """One processed GitHub webhook delivery (dedup / at-most-once).

    Keyed by GitHub's ``X-GitHub-Delivery`` id; retention-bounded by
    pruning old rows on insert (feature 002, FR-004/FR-008).
    """

    __tablename__ = "webhook_delivery"

    delivery_id: Mapped[str] = mapped_column(primary_key=True)
    event: Mapped[str] = mapped_column()
    outcome: Mapped[str] = mapped_column()
    repo: Mapped[str | None] = mapped_column(nullable=True)
    issue_number: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class IssueDismissalRow(Base):
    """A durable tombstone that a ticket's run was rejected/abandoned.

    Suppresses re-ingestion/reconciliation for a ``task_ref`` until the
    ticket stops qualifying (GitHub: trigger label removed; Jira: the RFC
    leaves the qualifying JQL). Source-neutral key (feature 003, FR-033;
    generalized from the feature-002 ``(repo, issue_number)`` composite).
    """

    __tablename__ = "issue_dismissal"

    task_ref: Mapped[str] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class NotificationRow(Base):
    """One recorded notification for the in-app notification center."""

    __tablename__ = "notification"

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True
    )
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_run.id")
    )
    repo: Mapped[str] = mapped_column()
    #: GitHub issue number; ``NULL`` for a Jira-sourced run (feature 003),
    #: whose ticket has no numeric id — identify the run via ``workflow_id``.
    issue_number: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column()
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    read: Mapped[bool] = mapped_column(Boolean, default=False)


class FeedbackItemRow(Base):
    """One piece of marker-gated feedback (feature 013).

    Keyed by each adapter's own opaque ``external_id`` — the same
    insert-if-absent dedup pattern as :class:`WebhookDeliveryRow`/
    :class:`IssueDismissalRow`, applied here to a race between the GitHub
    webhook and the poll backstop (or a re-delivery) observing the same
    comment. ``workflow_id`` is nullable because post-terminal feedback may
    arrive for a ticket with no live run to attach to yet.
    """

    __tablename__ = "feedback_item"
    __table_args__ = (
        Index(
            "ix_feedback_item_workflow_state",
            "workflow_id", "state",
        ),
    )

    external_id: Mapped[str] = mapped_column(Text, primary_key=True)
    workflow_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_run.id"), nullable=True
    )
    task_ref: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    #: "queued" | "dispatched" | "applied" | "ignored".
    state: Mapped[str] = mapped_column(Text)
    #: Set once the triage turn has classified this item; NULL until then.
    target_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    #: Set when ``state`` moves to "applied" or "ignored".
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )


class FeedbackCursorRow(Base):
    """How far a ticket/PR's feedback has been read (feature 013).

    Deliberately not a column on ``workflow_run``: a ticket's cursor must
    outlive any single run (post-terminal feedback) and a linked successor
    run must inherit its parent's cursor rather than re-reading from the
    beginning.
    """

    __tablename__ = "feedback_cursor"

    #: "ticket:<task_ref>" or "pr:<repo>#<number>".
    scope: Mapped[str] = mapped_column(Text, primary_key=True)
    #: Opaque, adapter-defined — passed back into list_comments/
    #: list_review_comments' ``since`` parameter verbatim.
    cursor: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
