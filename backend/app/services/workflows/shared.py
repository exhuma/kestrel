"""Tiny cross-cutting leaf utilities shared by the driver and service."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from app.models_workflow import Step, WorkflowRun, WorkflowStep

_logger = logging.getLogger(__name__)


def _log_driver_exception(task: asyncio.Task, workflow_id: str) -> None:
    """Log a driver task's terminal exception, if any.

    Without this, a driver coroutine that raises past its own try/except
    (e.g. a secondary failure while already handling one) dies with its
    exception unretrieved — asyncio logs only a generic, easy-to-miss "Task
    exception was never retrieved" warning, and neither ``run.status`` nor
    the app's own logs ever record what happened. This is the one place
    every driver task funnels through on completion, so it is the right
    place to guarantee a crash is always visible.
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        _logger.error(
            "workflow %s: driver task failed unexpectedly", workflow_id,
            exc_info=exc,
        )

#: Statuses that cannot survive a restart: their claude
#: subprocess (or transient side-effect) died with the process.
_TRANSIENT = (
    "pending", "cloning", "describing", "refining", "analyzing",
    "designing", "coding", "verifying", "opening_pr",
)

#: Terminal statuses (feature 006): reaching one of these stops a run's
#: active/wait clock for good, centralized in ``_save()`` so no terminal
#: call site can forget to close it out.
_TERMINAL_STATUSES = ("done", "failed", "rejected", "escalated", "decomposed")


class _Rejected(Exception):
    """Internal signal that a gate was rejected.

    Lives here (not in ``driver/__init__.py``) so ``driver/describe.py``
    (and any other split-out step module) can raise the exact same class
    the top-level ``drive()``/``resume()`` handlers catch, without a
    circular import back into the package's ``__init__``.
    """


def _now_utc() -> datetime:
    """Naive UTC now (this repo's timestamp convention — see the
    constitution's Persistence deviation): a ``clock_since`` value that
    round-trips through SQLite comes back naive, so every value fed to
    ``set_clock`` must be naive too, or the elapsed-time subtraction
    raises.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _slug_ref(task_ref: str) -> str:
    """A branch-safe slug of a task_ref (e.g. Jira ``RFC-123``)."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", task_ref).strip("-") or "run"


def _derive_branch(
    issue_number: int | None,
    task_ref: str,
    parent_run_id: str | None = None,
) -> str:
    """Branch name for a new run, from its ticket identity.

    A linked successor (feature 013, US4) deliberately shares its
    parent's ``task_ref`` (so ticket-feedback routing keeps finding it —
    ``FeedbackIntakeService._route_ticket``'s "newest run for this ref"
    rule), so it gets a distinguishing suffix here instead of colliding
    with the parent's own, still-live branch.
    """
    branch = (
        f"kestrel/issue-{issue_number}" if issue_number is not None
        else f"kestrel/{_slug_ref(task_ref)}"
    )
    if parent_run_id is not None:
        branch = f"{branch}-{uuid.uuid4().hex[:6]}"
    return branch


@dataclass(frozen=True)
class TicketRef:
    """A ticket's identity, source-neutral (feature 003).

    ``repo`` is the *code repository*; ``task_ref`` is the source-native
    ticket id (defaults to ``owner/name#n`` for GitHub). A Jira ticket
    sets ``task_ref`` (the RFC key), leaves ``issue_number`` ``None``,
    and provides a resolved ``base_branch``.
    """

    repo: str
    issue_number: int | None = None
    task_ref: str | None = None
    base_branch: str | None = None


def build_run(
    ticket: TicketRef,
    *,
    source: str,
    workspace_root: str,
    parent_run_id: str | None = None,
) -> WorkflowRun:
    """Build a fresh, unpersisted run and its step skeleton.

    Pure construction only (feature 012's test-pyramid fix): no
    persistence, no driver task. Kept separate from
    ``WorkflowService.create()`` so a test asserting on a run's shape
    doesn't have to spin up the full async orchestration to get one.

    :param parent_run_id: Set only for a linked successor run (feature
        013, US4) — see :func:`_derive_branch` for why that earns the
        branch a distinguishing suffix.
    """
    tref = ticket.task_ref or f"{ticket.repo}#{ticket.issue_number}"
    branch = _derive_branch(ticket.issue_number, tref, parent_run_id)
    return WorkflowRun(
        id="wf-" + uuid.uuid4().hex[:8],
        repo=ticket.repo,
        issue_number=ticket.issue_number,
        task_ref=tref,
        base_branch=ticket.base_branch or "",
        branch=branch,
        workspace=os.path.join(workspace_root, f"wf-{uuid.uuid4().hex[:8]}"),
        steps=[WorkflowStep(name=step) for step in Step.sequence()],
        source=source,
        parent_run_id=parent_run_id,
    )
