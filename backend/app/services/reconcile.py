"""Poll reconciliation: catch up on webhook deliveries that were missed.

Periodically lists each of a GitHub source's trigger-labelled issues and starts
any run the webhook path missed, idempotently with webhooks via the shared
ingestion guard. Also clears dismissals whose trigger label was removed
(feature 002, US2 / FR-012..FR-015 / FR-008a). One service instance is bound to
one ``github`` task source (feature 004).
"""
from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from app.config import get_settings
from app.config_models import TaskSourceConfig
from app.persistence.dismissal_store import DismissalStore, get_dismissal_store
from app.ports import WorkItem
from app.services.github import GitHubClient, Issue
from app.services.ingestion import IngestionService, get_ingestion_service

_log = logging.getLogger("kestrel.reconcile")


class ReconcileService:
    """Runs reconciliation cycles over one GitHub source's repositories."""

    def __init__(
        self,
        source: TaskSourceConfig,
        github: GitHubClient,
        ingestion: IngestionService,
        dismissals: DismissalStore,
    ) -> None:
        self.source = source
        self.github = github
        self.ingestion = ingestion
        self.dismissals = dismissals

    @property
    def name(self) -> str:
        """Display label for the poll dry-run listing."""
        return f"github [{', '.join(self.source.watched_repos)}]"

    async def _list_labelled(self, repo: str) -> list[Issue]:
        """List ``repo``'s trigger-labelled issues; ``[]`` on error."""
        try:
            return await self.github.list_issues_by_label(
                repo, self.source.trigger_label
            )
        except Exception:  # noqa: BLE001 — unreachable/rate-limited/etc.
            _log.exception("reconcile: could not list issues for %s", repo)
            return []

    async def run_cycle(self) -> None:
        """Reconcile every repo in this source once; failures are isolated."""
        for repo in self.source.watched_repos:
            await self._reconcile_repo(repo)

    async def _reconcile_repo(self, repo: str) -> None:
        issues = await self._list_labelled(repo)
        labelled = {issue.number for issue in issues}
        self._clear_stale_dismissals(repo, labelled)
        for issue in issues:
            await self._maybe_start(repo, issue)

    def _clear_stale_dismissals(self, repo: str, labelled: set[int]) -> None:
        # Clear dismissals whose trigger label is gone (self-heal a missed
        # `unlabeled` delivery), so a re-label can start fresh. Dismissals are
        # keyed by the source-neutral task_ref (``owner/name#n`` for GitHub).
        prefix = f"{repo}#"
        for ref in self.dismissals.all():
            if not ref.startswith(prefix):
                continue
            try:
                number = int(ref[len(prefix):])
            except ValueError:
                continue
            if number not in labelled:
                self.dismissals.clear(ref)

    async def _maybe_start(self, repo: str, issue: Issue) -> None:
        try:
            await self.ingestion.maybe_start_run(
                source="github-issue",
                task_ref=f"{repo}#{issue.number}",
                code_repo=repo,
                issue_number=issue.number,
            )
        except Exception:  # noqa: BLE001 — one issue must not stop the rest
            _log.exception(
                "reconcile: start failed %s#%s", repo, issue.number
            )

    async def list_work_items(self) -> list[WorkItem]:
        """List this source's qualifying issues; starts no run (dry-run)."""
        items: list[WorkItem] = []
        for repo in self.source.watched_repos:
            for issue in await self._list_labelled(repo):
                items.append(
                    WorkItem(
                        "github-issue",
                        f"{repo}#{issue.number}",
                        issue.title,
                        repo,
                    )
                )
        return items

    async def run_forever(self) -> None:
        """Run a cycle immediately, then every configured interval."""
        while True:
            await self.run_cycle()
            await asyncio.sleep(get_settings().poll_interval_seconds)


@lru_cache
def get_reconcile_services() -> tuple[ReconcileService, ...]:
    """One ReconcileService per configured GitHub task source."""
    settings = get_settings()
    ingestion = get_ingestion_service()
    dismissals = get_dismissal_store()
    return tuple(
        ReconcileService(
            source,
            GitHubClient(
                settings.github_api_base,
                source.token() or "",
                verify=source.verify_ssl,
            ),
            ingestion,
            dismissals,
        )
        for source in settings.github_sources()
    )
