"""Poll transport for feedback: walks every run's ticket, and — for a
run whose change request is still worth watching — its code host too.

Mirrors ``JiraPollService``/``FixturePollService``/``ReconcileService``'s
``PollSource`` shape (feature 004) so it plugs into the same lifespan/CLI
loop (``services/poll_source.py``) as every other source's background
cycle. One instance covers every task source AND every code host
uniformly — including GitHub's own poll backstop for a missed webhook
delivery (research.md R2) — since it walks runs, not a specific source's
ticket list.

A run's *code host* — not its task source — is where GitLab/GitHub review
feedback lives (``CodeHost.list_review_comments``); a run's task source
is where ticket comments live (``TaskSource.list_comments``). Both are
polled per run, independently, since which one(s) a human actually left
feedback on depends on the ecosystem, not on kestrel's own state.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from functools import lru_cache

from app.config import get_settings
from app.models_workflow import WorkflowRun
from app.persistence.feedback_store import FeedbackStore, get_feedback_store
from app.ports import Acknowledgeable, Feedback, WorkItem
from app.services.feedback.intake import (
    FeedbackIntakeService,
    get_feedback_intake_service,
)
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
    """Polls every still-relevant run's task source and code host."""

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
        """Poll every still-relevant run once; failures are isolated."""
        for run in self._workflows.list():
            if not self._worth_polling(run):
                continue
            await self._poll_ticket(run)
            await self._poll_review(run)

    def _worth_polling(self, run: WorkflowRun) -> bool:
        """Whether ``run`` still has anything left to poll for.

        Non-terminal: always. ``failed``/``rejected``/``decomposed``:
        never (nothing left to act on). ``done``/``escalated``: only
        within ``feedback_window_days`` of last going terminal.
        """
        if run.status in _NEVER_REPOLL_STATUSES:
            return False
        if run.status not in _REPOLLABLE_TERMINAL_STATUSES:
            return True
        if run.terminal_at is None:
            return True  # pre-migration row; err on the side of polling
        window = timedelta(days=get_settings().feedback_window_days)
        return _now_utc() - run.terminal_at < window

    async def _poll_ticket(self, run: WorkflowRun) -> None:
        source = self._workflows.task_source_for(run)
        ref = run.task_ref or f"{run.repo}#{run.issue_number}"
        await self._poll_one(
            source, f"ticket:{ref}", lambda since: source.list_comments(
                ref, since=since
            ), ref,
        )

    async def _poll_review(self, run: WorkflowRun) -> None:
        """Poll the run's change request for review feedback, if one
        exists yet (``run.pr_number`` is only set once ``deliver()`` has
        opened or confirmed one — feature 012/013).

        The ``ref`` handed to intake is the PR's own identity
        (``"owner/name#<pr-number>"``), not the run's ticket ``task_ref``
        — ``FeedbackIntakeService._route_review`` parses exactly this
        shape to find the run by its ``pr_number``, independent of
        whichever ticket originally started it.
        """
        if run.pr_number is None:
            return
        code_host = self._workflows.code_host_for(run)
        pr_ref = f"{run.repo}#{run.pr_number}"
        await self._poll_one(
            code_host, f"pr:{pr_ref}",
            lambda since: code_host.list_review_comments(
                run.repo, run.pr_number, since=since
            ),
            pr_ref,
        )

    async def _poll_one(
        self, source: Acknowledgeable, scope: str, fetch, ref: str
    ) -> None:
        cursor = self._store.cursor(scope)
        try:
            items: list[Feedback] = await fetch(cursor)
        except Exception:  # noqa: BLE001 — one run must not stop the rest
            _log.exception("feedback poll failed for %s", scope)
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
