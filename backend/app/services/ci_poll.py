"""Background polling for required CI on delivered change requests."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.ports import WorkItem
from app.services.workflows.ci import inspect_required_ci

if TYPE_CHECKING:
    from app.services.workflows import WorkflowService

_logger = logging.getLogger(__name__)


class CiPollService:
    """Poll waiting CI runs without coupling the loop to a provider."""

    def __init__(
        self, workflows: "WorkflowService", interval_seconds: int
    ) -> None:
        """Create a CI polling loop for the supplied workflow service."""
        self._workflows = workflows
        self._interval_seconds = interval_seconds

    @property
    def name(self) -> str:
        """Return the source-listing label used by the polling protocol."""
        return "required-ci"

    async def list_work_items(self) -> list[WorkItem]:
        """Return no ticket items because this poller only advances runs."""
        return []

    async def run_forever(self) -> None:
        """Poll CI until cancelled, isolating failures to an individual run."""
        while True:
            await self.run_once()
            await asyncio.sleep(self._interval_seconds)

    async def run_once(self) -> None:
        """Inspect every run currently awaiting required CI."""
        for run in self._workflows.list():
            if run.status != "awaiting_ci":
                continue
            try:
                await inspect_required_ci(self._workflows, run)
            except Exception:
                _logger.exception(
                    "required CI poll failed for workflow %s", run.id
                )
