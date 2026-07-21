"""Shared ingestion path: decide whether an issue should start a run.

Called by both the webhook handler and the reconciliation loop so the
one-run-per-issue and dismissal rules live in exactly one place (feature
002, FR-007/FR-008/FR-008a/FR-013a).
"""
from __future__ import annotations

import logging
from functools import lru_cache

from app.config import Settings, get_settings
from app.persistence.dismissal_store import DismissalStore, get_dismissal_store
from app.services.workflows import WorkflowService, get_workflow_service

_log = logging.getLogger("kestrel.ingestion")


class IngestionService:
    """Starts a run for a qualifying issue, idempotently."""

    def __init__(
        self,
        settings: Settings,
        workflows: WorkflowService,
        dismissals: DismissalStore,
    ) -> None:
        self.settings = settings
        self.workflows = workflows
        self.dismissals = dismissals

    def is_watched(self, repo: str) -> bool:
        """Return whether ``repo`` is in the configured allow-list."""
        return repo in self.settings.watched_repos

    def has_run(self, task_ref: str) -> bool:
        """Return whether a run already exists for ``task_ref``."""
        return any(r.task_ref == task_ref for r in self.workflows.list())

    async def maybe_start_run(
        self,
        *,
        source: str,
        task_ref: str,
        code_repo: str,
        issue_number: int | None = None,
        base_branch: str | None = None,
    ) -> str | None:
        """
        Start a run for a ticket unless it is filtered out.

        The single source-neutral entry point every trigger calls (GitHub
        webhook, GitHub reconcile, Jira poll) so one-run-per-ticket, dismissal,
        and (GitHub) watched-repo rules live in one place (FR-031/FR-033/
        FR-034). A future Jira webhook is one more caller of this method.

        Filters, in order: (GitHub) unwatched repo, dismissed ticket, an
        existing run for the ``task_ref``. Otherwise creates a run and returns
        its id. A failure to create raises before any run row persists, leaving
        nothing for reconciliation to trip over (FR-013a).

        :param source: Run origin (``github-issue`` | ``jira-issue``).
        :param task_ref: Source-native ticket id (dedup/dismissal key).
        :param code_repo: The target code repository (``owner/name``).
        :param issue_number: GitHub issue number; ``None`` for Jira.
        :param base_branch: Resolved base branch (Jira); ``None`` ⇒ resolved by
            the driver.
        :returns: The new run id, or ``None`` if filtered out.
        """
        if source == "github-issue" and not self.is_watched(code_repo):
            _log.info("ingest outcome=skipped-filtered %s (unwatched)", task_ref)
            return None
        if self.dismissals.is_dismissed(task_ref):
            _log.info("ingest outcome=dismissed %s", task_ref)
            return None
        if self.has_run(task_ref):
            _log.info("ingest outcome=skipped-duplicate %s", task_ref)
            return None
        run_id = await self.workflows.create(
            code_repo,
            issue_number,
            source=source,
            task_ref=task_ref,
            base_branch=base_branch,
        )
        _log.info("ingest outcome=started %s -> %s", task_ref, run_id)
        return run_id


@lru_cache
def get_ingestion_service() -> IngestionService:
    """Return the process-wide IngestionService singleton."""
    return IngestionService(
        get_settings(), get_workflow_service(), get_dismissal_store()
    )
