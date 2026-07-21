"""Jira poll ingestion: detect qualifying RFCs and start runs (feature 003).

Poll-only transport (no inbound endpoint). Each cycle queries the configured
RFC project by JQL, resolves each RFC's target code repository from a
configurable field, and funnels it through the shared source-neutral ingestion
guard. Also clears dismissals for RFCs that have left the qualifying filter —
the Jira re-trigger gesture (FR-033), mirroring the GitHub reconcile clear.
"""
from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from app.config import Settings, get_settings
from app.persistence.dismissal_store import DismissalStore, get_dismissal_store
from app.services.github import GitHubClient
from app.services.ingestion import IngestionService, get_ingestion_service
from app.services.jira import JiraClient, JiraTaskSource

_log = logging.getLogger("kestrel.jira_poll")

_FIELDS = ["summary", "description"]


class JiraPollService:
    """Runs Jira poll cycles over the configured RFC project."""

    def __init__(
        self,
        settings: Settings,
        jira: JiraClient,
        source: JiraTaskSource,
        code_host: object,
        ingestion: IngestionService,
        dismissals: DismissalStore,
    ) -> None:
        self.settings = settings
        self.jira = jira
        self.source = source
        self.code_host = code_host
        self.ingestion = ingestion
        self.dismissals = dismissals

    def _jql(self) -> str:
        base = f'project = "{self.settings.jira_project}"'
        if self.settings.jira_jql_filter:
            return f"{base} AND ({self.settings.jira_jql_filter})"
        return base

    async def _resolve_repo(self, key: str) -> tuple[str, str] | None:
        """Resolve an RFC to ``(code_repo, base_branch)`` or ``None``.

        Reads the configurable repo field (``owner/name[@base_branch]``) and
        probes the code host for reachability + the default branch (FR-006/
        FR-007). ``None`` ⇒ unresolvable (empty field or unreachable repo).
        """
        raw = await self.jira.get_field(key, self.settings.jira_repo_field)
        if not raw or not raw.strip():
            return None
        repo, _, base = raw.strip().partition("@")
        repo = repo.strip()
        if not repo:
            return None
        try:
            default = await self.code_host.get_default_branch(repo)
        except Exception:  # noqa: BLE001 — unreachable/misconfigured repo
            _log.warning("jira: repo %r for %s is unreachable", repo, key)
            return None
        return repo, (base.strip() or default)

    async def run_cycle(self) -> None:
        """Poll the RFC project once; failures are isolated per cycle/issue."""
        try:
            tasks = await self.jira.search(
                self._jql(), fields=_FIELDS, max_results=50
            )
        except Exception:  # noqa: BLE001 — unreachable/rate-limited/etc.
            _log.exception("jira: poll query failed")
            return
        _log.info("jira: %d qualifying RFC(s)", len(tasks))
        qualifying = {t.ref for t in tasks}
        # Re-trigger gesture (FR-033): clear the dismissal of any RFC in this
        # project that no longer qualifies, so re-qualifying starts fresh.
        prefix = f"{self.settings.jira_project}-"
        for ref in self.dismissals.all():
            if ref.startswith(prefix) and ref not in qualifying:
                self.dismissals.clear(ref)
        for task in tasks:
            try:
                resolved = await self._resolve_repo(task.ref)
                if resolved is None:
                    _log.info("ingest outcome=unresolved-repo %s", task.ref)
                    await self._comment_unresolved(task.ref)
                    continue
                repo, base = resolved
                await self.ingestion.maybe_start_run(
                    source="jira-issue",
                    task_ref=task.ref,
                    code_repo=repo,
                    base_branch=base,
                )
            except Exception:  # noqa: BLE001 — one RFC must not stop the rest
                _log.exception("jira: start failed for %s", task.ref)

    async def _comment_unresolved(self, key: str) -> None:
        try:
            await self.source.post_comment(
                key,
                "Kestrel could not determine the target repository for this "
                "RFC. Set the repository field to owner/name[@base_branch].",
            )
        except Exception:  # noqa: BLE001 — best-effort
            _log.exception("jira: could not comment unresolved %s", key)

    async def run_forever(self) -> None:
        """Run a cycle immediately, then every configured interval."""
        while True:
            await self.run_cycle()
            await asyncio.sleep(self.settings.jira_poll_interval_seconds)


@lru_cache
def get_jira_poll_service() -> JiraPollService:
    """Return the process-wide JiraPollService singleton."""
    from app.services.workflows import _build_code_host

    settings = get_settings()
    github = GitHubClient(settings.github_api_base, settings.github_token)
    jira = JiraClient(
        settings.jira_base_url,
        auth=settings.jira_auth,
        email=settings.jira_email,
        token=settings.jira_api_token,
    )
    return JiraPollService(
        settings,
        jira,
        JiraTaskSource(jira, settings.public_base_url),
        _build_code_host(settings, github),
        get_ingestion_service(),
        get_dismissal_store(),
    )
