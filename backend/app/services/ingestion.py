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

    def has_run(self, repo: str, issue_number: int) -> bool:
        """Return whether a run already exists for ``(repo, issue)``."""
        return any(
            r.repo == repo and r.issue_number == issue_number
            for r in self.workflows.list()
        )

    async def maybe_start_run(
        self,
        repo: str,
        issue_number: int,
        *,
        source: str = "github-issue",
    ) -> str | None:
        """
        Start a run for the issue unless it is filtered out.

        Filters, in order: unwatched repo, dismissed issue, an existing run
        for the pair. Otherwise creates a run and returns its id. A failure
        to create raises before any run row persists, leaving nothing for
        reconciliation to trip over (FR-013a).

        :param repo: ``owner/name``.
        :param issue_number: The flagged issue.
        :param source: Run origin, stored on the run.
        :returns: The new run id, or ``None`` if filtered out.
        """
        ref = f"{repo}#{issue_number}"
        if not self.is_watched(repo):
            _log.info("ingest ignored (unwatched repo) %s", ref)
            return None
        if self.dismissals.is_dismissed(repo, issue_number):
            _log.info("ingest ignored (dismissed) %s", ref)
            return None
        if self.has_run(repo, issue_number):
            _log.info("ingest ignored (run exists) %s", ref)
            return None
        run_id = await self.workflows.create(
            repo, issue_number, source=source
        )
        _log.info("ingest run-started %s -> %s", ref, run_id)
        return run_id


@lru_cache
def get_ingestion_service() -> IngestionService:
    """Return the process-wide IngestionService singleton."""
    return IngestionService(
        get_settings(), get_workflow_service(), get_dismissal_store()
    )
