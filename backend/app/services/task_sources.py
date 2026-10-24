"""Task-source and code-host adapter registry (feature 026 Phase 10).

Extracted from the old fixed driver's ``WorkflowService`` construction so
board-routed ingestion and source-health checks can resolve GitHub/Jira/
local adapters without depending on the (now removed) driver.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.config import Settings, get_settings
from app.config_models import TaskSourceConfig
from app.ports import CodeHost, TaskSource
from app.services.github import GitHubClient, GitHubCodeHost
from app.services.github_tasksource import GitHubTaskSource
from app.services.gitlab import GitLabCodeHost
from app.services.jira import JiraClient, JiraTaskSource
from app.services.local_code_host import LocalCodeHost
from app.services.local_task_source import LocalTaskSource


@dataclass(frozen=True)
class TaskSourceRegistry:
    """Configured adapters keyed by run source id (``"github-issue"`` etc.)."""

    sources: dict[str, TaskSource]
    code_hosts: dict[str, CodeHost]


def build_task_source_registry(settings: Settings) -> TaskSourceRegistry:
    """Build the adapter registry from *settings* (no caching)."""
    gh_verify = all(s.verify_ssl for s in settings.github_sources())
    github = GitHubClient(
        settings.github_api_base, settings.github_token, verify=gh_verify
    )
    gh_source = GitHubTaskSource(
        github,
        settings.public_base_url,
        config_for=settings.github_source_for,
        comment_sentinel_enabled=settings.comment_sentinel_enabled,
    )
    gh_host = GitHubCodeHost(github, settings.git_base)
    sources: dict[str, TaskSource] = {"github-issue": gh_source}
    code_hosts: dict[str, CodeHost] = {"github-issue": gh_host}
    _register_jira(settings, sources, code_hosts)
    _register_local(settings, sources, code_hosts)
    return TaskSourceRegistry(sources, code_hosts)


def _register_jira(
    settings: Settings,
    sources: dict[str, TaskSource],
    code_hosts: dict[str, CodeHost],
) -> None:
    jira_sources = settings.jira_sources()
    if not jira_sources:
        return
    entry = jira_sources[0]
    jira = JiraClient(
        entry.base_url,
        auth=entry.auth,
        email=entry.email,
        token=entry.token() or "",
        verify=entry.verify_ssl,
        deployment=entry.deployment,
    )
    sources["jira-issue"] = JiraTaskSource(
        jira,
        settings.public_base_url,
        config=entry,
        comment_sentinel_enabled=settings.comment_sentinel_enabled,
    )
    jira_github = GitHubClient(
        settings.github_api_base, settings.github_token, verify=entry.verify_ssl
    )
    code_hosts["jira-issue"] = build_code_host(
        entry, jira_github, settings.git_base
    )


def _register_local(
    settings: Settings,
    sources: dict[str, TaskSource],
    code_hosts: dict[str, CodeHost],
) -> None:
    local_sources = settings.local_sources()
    if not local_sources:
        return
    entry = local_sources[0]
    sources["local-task"] = LocalTaskSource(
        entry.tasks_dir,
        settings.comment_sentinel_enabled,
    )
    code_hosts["local-task"] = LocalCodeHost()


def build_code_host(
    source: TaskSourceConfig, github: GitHubClient, git_base: str
) -> CodeHost:
    """Build the code host for a Jira source's resolved repos.

    Self-hostable (feature 003, FR-023a): ``gitlab``/``gitea`` point at an
    on-prem instance; ``github`` reuses the GitHub client. The code-host
    token falls back to ``github_token`` when the host is GitHub.
    """
    if source.code_host in ("gitlab", "gitea"):
        return GitLabCodeHost(
            source.code_host_base_url,
            source.code_host_token() or "",
            verify=source.verify_ssl,
            is_gitea=source.code_host == "gitea",
        )
    return GitHubCodeHost(github, git_base)


@lru_cache
def get_task_source_registry() -> TaskSourceRegistry:
    """Return the process-wide TaskSourceRegistry singleton."""
    return build_task_source_registry(get_settings())
