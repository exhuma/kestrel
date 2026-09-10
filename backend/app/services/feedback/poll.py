"""Poll transport for feedback: walks every run through its feedback source.

Mirrors ``JiraPollService``/``LocalTaskPollService``/``ReconcileService``'s
``PollSource`` shape (feature 004) so it plugs into the same lifespan/CLI
loop (``services/poll_source.py``) as every other source's background
cycle. One instance covers every task source AND every code host
uniformly — including GitHub's own poll backstop for a missed webhook
delivery (research.md R2) — since it walks runs, not a specific source's
ticket list.

The composed ``FeedbackSource`` initially delegates to existing ``TaskSource``
and ``CodeHost`` list methods, preserving the source adapters during extraction.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from functools import lru_cache

from app.config import get_settings
from app.models_workflow import WorkflowRun
from app.persistence.child_task_store import (
    ChildTaskLinks,
    get_child_task_store,
)
from app.persistence.feedback_store import FeedbackStore, get_feedback_store
from app.ports import Feedback, WorkItem
from app.services.feedback.intake import (
    FeedbackIntakeService,
    get_feedback_intake_service,
)
from app.services.feedback.retention import ChildTaskRetentionService
from app.services.workflows import WorkflowService, get_workflow_service
from app.services.workflows.shared import _now_utc

_log = logging.getLogger("kestrel.feedback.poll")

#: Terminal statuses never worth re-polling at all: the human already
#: explicitly ended these (a rejected PRD) or nothing was ever published
#: to revive/continue from (a plain failure). Mirrors
#: ``app.services.workflows.shared._TERMINAL_STATUSES`` minus the two
#: (``done``, ``escalated``) US3/US4 can still act on — duplicated here
#: rather than imported since that name is private to the workflows
#: package.
_NEVER_REPOLL_STATUSES = frozenset({"failed", "rejected", "decomposed"})

#: Terminal statuses still worth re-polling, bounded by
#: ``settings.feedback_window_days`` (research.md R7/R9, US3/US4): a
#: `done` run may still have an open change request; an `escalated` run
#: may still be resumable with guidance.
_REPOLLABLE_TERMINAL_STATUSES = frozenset({"done", "escalated"})


class FeedbackPollService:
    """Polls every still-relevant run through its feedback source."""

    def __init__(
        self,
        workflows: WorkflowService,
        store: FeedbackStore,
        intake: FeedbackIntakeService,
        child_tasks: ChildTaskLinks | None = None,
    ) -> None:
        self._workflows = workflows
        self._store = store
        self._intake = intake
        self._child_tasks = child_tasks
        self._retention = (
            ChildTaskRetentionService(
                workflows.settings, workflows, child_tasks
            )
            if child_tasks is not None else None
        )

    @property
    def name(self) -> str:
        """Display label for the poll dry-run listing."""
        return "feedback"

    async def list_work_items(self) -> list[WorkItem]:
        """No dry-run listing: this source polls existing runs, not
        tickets awaiting ingestion (required by the ``PollSource``
        protocol)."""
        return []

    async def run_cycle(self) -> None:
        """Poll every still-relevant run once; failures are isolated."""
        if self._retention is not None:
            await self._retention.run_cycle()
        runs = self._workflows.list()
        eligible = [run for run in runs if self._worth_polling(run)]
        _log.info(
            "feedback poll discovery count=%s eligible_count=%s",
            len(runs),
            len(eligible),
        )
        for run in eligible:
            await self._poll_run(run)

    def _worth_polling(self, run: WorkflowRun) -> bool:
        """Whether ``run`` still has anything left to poll for.

        Non-terminal: always. ``failed``/``rejected``/``decomposed``:
        never (nothing left to act on). ``done``/``escalated``: only
        within ``feedback_window_days`` of last going terminal.
        """
        if self._never_repoll(run):
            return False
        if self._always_repoll(run):
            return True
        terminal_at = run.terminal_at
        if terminal_at is None:
            return True
        window = timedelta(days=get_settings().feedback_window_days)
        return _now_utc() - terminal_at < window

    def _never_repoll(self, run: WorkflowRun) -> bool:
        """Return whether a terminal state permanently excludes feedback."""
        return bool(
            run.task_ref
            and self._is_retired_child(run.task_ref)
            or run.status in _NEVER_REPOLL_STATUSES
        )

    def _always_repoll(self, run: WorkflowRun) -> bool:
        """Return whether this run bypasses the generic terminal window."""
        return bool(
            run.status not in _REPOLLABLE_TERMINAL_STATUSES
            or run.task_ref and self._is_linked_child(run.task_ref)
        )

    def _is_retired_child(self, task_ref: str) -> bool:
        """Return whether the child link permanently excludes this run."""
        return self._child_tasks is not None and self._child_tasks.is_retired(
            task_ref
        )

    def _is_linked_child(self, task_ref: str) -> bool:
        """Return whether a child remains monitored until retirement."""
        return self._child_tasks is not None and self._child_tasks.is_linked(
            task_ref
        )

    async def _poll_run(self, run: WorkflowRun) -> None:
        """Read and route one run through its composed feedback source."""
        self._intake.redispatch_queued(run.id)
        source = self._workflows.feedback_source_for(run)
        scope = f"feedback:{run.id}"
        cursor = self._store.cursor(scope)
        try:
            items: list[Feedback] = await source.list_feedback(run, cursor)
        except Exception:  # noqa: BLE001 — one run must not stop the rest
            _log.exception("feedback poll failed for %s", scope)
            return
        _log.info(
            "feedback poll discovery scope=%s count=%s", scope, len(items)
        )
        for feedback in items:
            ref = self._feedback_ref(run, feedback)
            await self._intake.intake(feedback, task_ref=ref, source=source)
        if items:
            newest = max(item.created_at for item in items)
            self._store.set_cursor(scope, newest.isoformat())

    def _feedback_ref(self, run: WorkflowRun, feedback: Feedback) -> str:
        """Return the ticket or change-request identity for ``feedback``."""
        if feedback.origin == "review" and run.pr_number is not None:
            return f"{run.repo}#{run.pr_number}"
        return run.task_ref or f"{run.repo}#{run.issue_number}"

    async def run_forever(self) -> None:
        """Run a cycle immediately, then every configured interval."""
        while True:
            await self.run_cycle()
            await asyncio.sleep(get_settings().poll_interval_seconds)


@lru_cache
def get_feedback_poll_service() -> FeedbackPollService:
    """Return the process-wide FeedbackPollService singleton."""
    return FeedbackPollService(
        get_workflow_service(), get_feedback_store(),
        get_feedback_intake_service(), get_child_task_store(),
    )
