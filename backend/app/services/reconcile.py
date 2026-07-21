"""Poll reconciliation: catch up on webhook deliveries that were missed.

Periodically lists each watched repo's trigger-labelled issues and starts
any run the webhook path missed, idempotently with webhooks via the shared
ingestion guard. Also clears dismissals whose trigger label was removed
(feature 002, US2 / FR-012..FR-015 / FR-008a).
"""
from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from app.config import Settings, get_settings
from app.persistence.dismissal_store import DismissalStore, get_dismissal_store
from app.services.github import GitHubClient
from app.services.ingestion import IngestionService, get_ingestion_service

_log = logging.getLogger("kestrel.reconcile")


class ReconcileService:
    """Runs reconciliation cycles over the watched repositories."""

    def __init__(
        self,
        settings: Settings,
        github: GitHubClient,
        ingestion: IngestionService,
        dismissals: DismissalStore,
    ) -> None:
        self.settings = settings
        self.github = github
        self.ingestion = ingestion
        self.dismissals = dismissals

    async def run_cycle(self) -> None:
        """Reconcile every watched repo once; failures are isolated."""
        for repo in self.settings.watched_repos:
            await self._reconcile_repo(repo)

    async def _reconcile_repo(self, repo: str) -> None:
        try:
            issues = await self.github.list_issues_by_label(
                repo, self.settings.trigger_label
            )
        except Exception:  # noqa: BLE001 — unreachable/rate-limited/etc.
            _log.exception("reconcile: could not list issues for %s", repo)
            return
        labelled = {issue.number for issue in issues}
        # Clear dismissals whose trigger label is gone (self-heal a missed
        # `unlabeled` delivery), so a re-label can start fresh.
        for number in self.dismissals.list_dismissed(repo):
            if number not in labelled:
                self.dismissals.clear(repo, number)
        for issue in issues:
            try:
                await self.ingestion.maybe_start_run(
                    repo, issue.number, source="github-issue"
                )
            except Exception:  # noqa: BLE001 — one issue must not stop the rest
                _log.exception(
                    "reconcile: start failed %s#%s", repo, issue.number
                )

    async def run_forever(self) -> None:
        """Run a cycle immediately, then every configured interval."""
        while True:
            await self.run_cycle()
            await asyncio.sleep(self.settings.reconcile_interval_seconds)


@lru_cache
def get_reconcile_service() -> ReconcileService:
    """Return the process-wide ReconcileService singleton."""
    settings = get_settings()
    return ReconcileService(
        settings,
        GitHubClient(settings.github_api_base, settings.github_token),
        get_ingestion_service(),
        get_dismissal_store(),
    )
