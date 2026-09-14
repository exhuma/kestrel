"""Retire closed published child tasks after their monitoring retention."""

from __future__ import annotations

import logging
from datetime import timedelta

from app.config import Settings
from app.documents import Text, document, paragraph
from app.persistence.child_task_store import ChildTaskLinks
from app.services.workflows import WorkflowService
from app.services.workflows.shared import _now_utc

_log = logging.getLogger("kestrel.feedback.retention")

RETIREMENT_NOTICE = document(
    paragraph(
        Text(
            "Kestrel has retired this closed child task. "
            "Create a new task for further work."
        )
    )
)


class ChildTaskRetentionService:
    """Posts one notice and durably retires due closed child tasks."""

    def __init__(
        self,
        settings: Settings,
        workflows: WorkflowService,
        child_tasks: ChildTaskLinks,
    ) -> None:
        """Create a monitor using supplied settings, workflows, and store."""
        self._settings = settings
        self._workflows = workflows
        self._child_tasks = child_tasks

    async def run_cycle(self) -> None:
        """Post notices for every child whose source closure has expired."""
        cutoff = _now_utc() - timedelta(
            days=self._settings.child_task_closure_retention_days
        )
        runs = {run.id: run for run in self._workflows.list()}
        candidates = self._child_tasks.retirement_candidates(cutoff)
        for task_ref, workflow_id in candidates:
            run = runs.get(workflow_id)
            if run is not None and self._child_tasks.claim_retirement(task_ref):
                await self._retire(task_ref, run)

    async def _retire(self, task_ref: str, run) -> None:
        """Post a notice, leaving the child eligible when its source fails."""
        try:
            await self._workflows.task_source_for(run).post_comment(
                task_ref, RETIREMENT_NOTICE
            )
        except Exception:
            _log.exception("retirement notice failed for %s", task_ref)
            self._child_tasks.release_retirement(task_ref)
            return
        self._child_tasks.mark_retired(task_ref, _now_utc())
