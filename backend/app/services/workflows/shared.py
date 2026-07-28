"""Tiny cross-cutting leaf utilities shared by the driver and service."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

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
    "pending", "cloning", "refining",
    "designing", "coding", "verifying", "opening_pr",
)

#: Terminal statuses (feature 006): reaching one of these stops a run's
#: active/wait clock for good, centralized in ``_save()`` so no terminal
#: call site can forget to close it out.
_TERMINAL_STATUSES = ("done", "failed", "rejected", "escalated")


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
