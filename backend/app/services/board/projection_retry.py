"""Posting again what a task source refused (feature 046, R7).

A comment kestrel failed to post (Jira unreachable) stays in the
projection ledger as ``retryable_failure``, with its document and where to
post it. This loop takes each such row on again, later and later as it
keeps failing, and posts it. A row is taken on by one atomic update
(``begin_retry``), so it is posted at most once however many loops, cycles
or restarts reach for it.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from app.models_board_records import ExternalProjectionRecord
from app.persistence.board_store import BoardStore
from app.persistence.board_time import now_utc
from app.services.board.projections import ProjectionsService
from app.services.task_sources import TaskSourceRegistry

_logger = logging.getLogger("kestrel.board.projection_retry")

#: Retries a row gets before it is left in the ledger, still failed, for
#: the operator to see.
MAX_ATTEMPTS = 8
#: The wait before retry n is the loop interval times two to this power
#: at most, so a long outage settles to one try every 2**5 intervals.
_MAX_BACKOFF_DOUBLINGS = 5


def due_at(record: ExternalProjectionRecord, interval: float) -> datetime:
    """When *record* may be tried again: the loop interval, doubled for
    each retry it has already had (up to a limit), after it last failed."""
    doublings = min(record.attempts, _MAX_BACKOFF_DOUBLINGS)
    last = record.updated_at or datetime.min
    return last + timedelta(seconds=interval * 2**doublings)


class ProjectionRetryService:
    """Re-posts failed projections, once each, with backoff."""

    def __init__(
        self,
        projections: ProjectionsService,
        store: BoardStore,
        task_sources: TaskSourceRegistry,
        *,
        interval_seconds: float,
    ) -> None:
        self._projections = projections
        self._store = store
        self._task_sources = task_sources
        self._interval_seconds = interval_seconds

    async def run_forever(self) -> None:
        """Retry failed posts until cancelled; one bad cycle never stops
        the loop."""
        while True:
            try:
                await self.poll_once()
            except Exception:  # the loop must outlive a cycle
                _logger.exception("projection retry cycle failed")
            await asyncio.sleep(self._interval_seconds)

    async def poll_once(self, *, now: datetime | None = None) -> int:
        """Retry every failed projection that is due.

        :returns: How many were posted.
        """
        moment = now_utc(now)
        posted = 0
        for record in self._projections.retryable():
            if not self._due(record, moment):
                continue
            if await self._retry(record):
                posted += 1
        return posted

    def _due(self, record: ExternalProjectionRecord, now: datetime) -> bool:
        if record.task_ref is None or record.payload is None:
            return False  # a row from before the ledger kept its payload
        if record.attempts >= MAX_ATTEMPTS:
            return False
        return due_at(record, self._interval_seconds) <= now

    async def _retry(self, record: ExternalProjectionRecord) -> bool:
        workflow = self._store.get_workflow(record.workflow_id)
        source = (
            self._task_sources.sources.get(workflow.source)
            if workflow is not None else None
        )
        if source is None:
            _logger.warning(
                "projection %s: no task source to post to", record.id
            )
            return False
        if not self._projections.begin_retry(record.id):
            return False
        try:
            external_id = await source.post_comment(
                record.task_ref, record.payload
            )
        except Exception as exc:  # record it, try again later
            self._projections.fail(record.id, str(exc))
            _logger.warning(
                "projection %s: retry %d failed", record.id,
                record.attempts + 1, exc_info=True,
            )
            return False
        self._projections.complete(record.id, external_id=external_id)
        _logger.info(
            "projection %s: posted on retry %d", record.id,
            record.attempts + 1,
        )
        return True
