"""Poll transport for feedback: walks every non-terminal run's ticket.

Mirrors ``JiraPollService``/``FixturePollService``/``ReconcileService``'s
``PollSource`` shape (feature 004) so it plugs into the same lifespan/CLI
loop (``services/poll_source.py``) as every other source's background
cycle. One instance covers every task source uniformly — including
GitHub's own poll backstop for a missed webhook delivery (research.md
R2) — since it walks runs, not a specific source's ticket list.
"""
from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from app.config import get_settings
from app.models_workflow import WorkflowRun
from app.persistence.feedback_store import FeedbackStore, get_feedback_store
from app.ports import WorkItem
from app.services.feedback.intake import (
    FeedbackIntakeService,
    get_feedback_intake_service,
)
from app.services.workflows import WorkflowService, get_workflow_service

_log = logging.getLogger("kestrel.feedback.poll")

#: Statuses with nothing left to poll for (mirrors
#: ``app.services.workflows.shared._TERMINAL_STATUSES``, duplicated here
#: rather than imported since that name is private to the workflows
#: package).
_TERMINAL_STATUSES = frozenset({"done", "failed", "rejected", "escalated"})


class FeedbackPollService:
    """Polls every non-terminal run's task source for new feedback."""

    def __init__(
        self,
        workflows: WorkflowService,
        store: FeedbackStore,
        intake: FeedbackIntakeService,
    ) -> None:
        self._workflows = workflows
        self._store = store
        self._intake = intake

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
        """Poll every non-terminal run once; failures are isolated."""
        for run in self._workflows.list():
            if run.status in _TERMINAL_STATUSES:
                continue
            await self._poll_run(run)

    async def _poll_run(self, run: WorkflowRun) -> None:
        source = self._workflows.task_source_for(run)
        ref = run.task_ref or f"{run.repo}#{run.issue_number}"
        scope = f"ticket:{ref}"
        cursor = self._store.cursor(scope)
        try:
            items = await source.list_comments(ref, since=cursor)
        except Exception:  # noqa: BLE001 — one run must not stop the rest
            _log.exception("feedback poll failed for %s", ref)
            return
        for feedback in items:
            await self._intake.intake(feedback, task_ref=ref, source=source)
        if items:
            newest = max(item.created_at for item in items)
            self._store.set_cursor(scope, newest.isoformat())

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
        get_feedback_intake_service(),
    )
