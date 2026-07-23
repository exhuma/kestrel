"""Jira poll ingestion: detect qualifying RFCs and start runs (feature 003).

Poll-only transport (no inbound endpoint). Each cycle queries one configured
Jira task source by its whole JQL, resolves each RFC's target code repository
(from a configurable field or a titled web link), and funnels it through the
shared source-neutral ingestion guard. Also clears dismissals for RFCs that have
left the qualifying filter — the Jira re-trigger gesture (FR-033), scoped by the
source's issue-key prefix. One service instance is bound to one ``jira`` task
source (feature 004).
"""
from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from urllib.parse import urlparse

from app.config import get_settings
from app.config_models import TaskSourceConfig
from app.persistence.dismissal_store import DismissalStore, get_dismissal_store
from app.ports import WorkItem
from app.services.github import GitHubClient
from app.services.ingestion import IngestionService, get_ingestion_service
from app.services.jira import JiraClient, JiraTaskSource

_log = logging.getLogger("kestrel.jira_poll")

_FIELDS = ["summary", "description"]
#: Minimum path segments for an ``owner/name`` repository URL.
_MIN_REPO_PARTS = 2


def _repo_from_url(url: str) -> str | None:
    """Parse ``owner/name`` from a hosted-repository URL, else ``None``.

    Handles ``github.com/owner/name`` and ``gitlab.host/group/sub/name``
    (truncating a GitLab ``/-/`` deep-link tail); tolerates a trailing
    ``.git``. A path without at least two segments is treated as unresolved.
    """
    parts = [p for p in urlparse(url).path.split("/") if p]
    if "-" in parts:  # GitLab inserts "/-/" before tree/blob/issues/...
        parts = parts[: parts.index("-")]
    if len(parts) < _MIN_REPO_PARTS:
        return None
    return "/".join(parts).removesuffix(".git")


class JiraPollService:
    """Runs Jira poll cycles over one configured Jira task source."""

    def __init__(
        self,
        source: TaskSourceConfig,
        jira: JiraClient,
        task_source: JiraTaskSource,
        code_host: object,
        ingestion: IngestionService,
        dismissals: DismissalStore,
    ) -> None:
        self.source = source
        self.jira = jira
        self.task_source = task_source
        self.code_host = code_host
        self.ingestion = ingestion
        self.dismissals = dismissals

    @property
    def name(self) -> str:
        """Display label for the poll dry-run listing."""
        return f"jira [{self.source.base_url}]"

    async def _search_tasks(self) -> list:
        """Run the source's JQL once, returning the qualifying ``Task``s."""
        return await self.jira.search(
            self.source.jql, fields=_FIELDS, max_results=50
        )

    async def _repo_ref(self, key: str) -> str | None:
        """The raw ``owner/name[@base]`` ref: field first, else a web link."""
        if self.source.repo_field:
            raw = await self.jira.get_field(key, self.source.repo_field)
            if raw and raw.strip():
                return raw.strip()
        return await self._repo_ref_from_links(key)

    async def _repo_ref_from_links(self, key: str) -> str | None:
        """Resolve ``owner/name`` from a web link titled ``repo_link_text``."""
        wanted = self.source.repo_link_text.casefold()
        try:
            links = await self.jira.get_remote_links(key)
        except Exception:  # noqa: BLE001 — best-effort fallback
            _log.warning("jira: could not read remote links for %s", key)
            return None
        for link in links:
            obj = link.get("object") or {}
            if (obj.get("title") or "").casefold() == wanted:
                return _repo_from_url(obj.get("url") or "")
        return None

    async def _resolve_repo(self, key: str) -> tuple[str, str] | None:
        """Resolve an RFC to ``(code_repo, base_branch)`` or ``None``."""
        ref = await self._repo_ref(key)
        if not ref:
            return None
        repo, _, base = ref.partition("@")
        repo = repo.strip()
        if not repo:
            return None
        return await self._probe(key, repo, base.strip())

    async def _probe(
        self, key: str, repo: str, base: str
    ) -> tuple[str, str] | None:
        """Probe the code host for reachability + the default branch."""
        try:
            default = await self.code_host.get_default_branch(repo)
        except Exception:  # noqa: BLE001 — unreachable/misconfigured repo
            _log.warning("jira: repo %r for %s is unreachable", repo, key)
            return None
        return repo, (base or default)

    def _clear_stale_dismissals(self, qualifying: set[str]) -> None:
        # Re-trigger gesture (FR-033): clear the dismissal of any RFC in this
        # source that no longer qualifies, so re-qualifying starts fresh.
        prefix = f"{self.source.key}-"
        for ref in self.dismissals.all():
            if ref.startswith(prefix) and ref not in qualifying:
                self.dismissals.clear(ref)

    async def run_cycle(self) -> None:
        """Poll the source once; failures are isolated per cycle/issue."""
        try:
            tasks = await self._search_tasks()
        except Exception:  # noqa: BLE001 — unreachable/rate-limited/etc.
            _log.exception("jira: poll query failed")
            return
        _log.info("jira: %d qualifying RFC(s)", len(tasks))
        self._clear_stale_dismissals({t.ref for t in tasks})
        for task in tasks:
            await self._ingest(task)

    async def _ingest(self, task) -> None:
        try:
            resolved = await self._resolve_repo(task.ref)
            if resolved is None:
                _log.info("ingest outcome=unresolved-repo %s", task.ref)
                await self._comment_unresolved(task.ref)
                return
            repo, base = resolved
            await self.ingestion.maybe_start_run(
                source="jira-issue",
                task_ref=task.ref,
                code_repo=repo,
                base_branch=base,
            )
        except Exception:  # noqa: BLE001 — one RFC must not stop the rest
            _log.exception("jira: start failed for %s", task.ref)

    async def list_work_items(self) -> list[WorkItem]:
        """List qualifying RFCs and their resolved repos; starts no run."""
        items: list[WorkItem] = []
        for task in await self._search_tasks():
            resolved = await self._resolve_repo(task.ref)
            repo, base = resolved if resolved else (None, None)
            items.append(
                WorkItem("jira-issue", task.ref, task.title, repo, base)
            )
        return items

    async def _comment_unresolved(self, key: str) -> None:
        try:
            await self.task_source.post_comment(
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
            await asyncio.sleep(get_settings().poll_interval_seconds)


def _build_jira_service(source: TaskSourceConfig) -> JiraPollService:
    """Construct one JiraPollService from a jira task-source entry."""
    from app.services.workflows import build_code_host

    settings = get_settings()
    github = GitHubClient(settings.github_api_base, settings.github_token)
    jira = JiraClient(
        source.base_url,
        auth=source.auth,
        email=source.email,
        token=source.token() or "",
    )
    return JiraPollService(
        source,
        jira,
        JiraTaskSource(jira, settings.public_base_url),
        build_code_host(source, github, settings.git_base),
        get_ingestion_service(),
        get_dismissal_store(),
    )


@lru_cache
def get_jira_poll_services() -> tuple[JiraPollService, ...]:
    """One JiraPollService per configured Jira task source."""
    return tuple(
        _build_jira_service(source)
        for source in get_settings().jira_sources()
    )
