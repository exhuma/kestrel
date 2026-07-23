"""ORM table definitions for kestrel."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Text
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
    error: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    #: Run origin: "manual" | "github-issue" | "jira-issue". Server-default
    #: keeps pre-existing rows valid; internal-only (not in the API).
    source: Mapped[str] = mapped_column(
        default="manual", server_default="manual"
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
    issue_number: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column()
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
