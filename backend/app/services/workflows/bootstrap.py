"""Composition root: builds the process-wide WorkflowService singleton."""
from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.config_models import TaskSourceConfig
from app.models_workflow import WorkflowRun
from app.notifications import (
    CompositeNotifier,
    InAppNotifier,
    TaskSourceNotifier,
)
from app.persistence.dismissal_store import get_dismissal_store
from app.persistence.notification_store import get_notification_store
from app.policy import get_backend_policy
from app.services.git import GitService
from app.services.github import (
    GitHubClient,
    GitHubCodeHost,
    GitHubTaskSource,
    parse_github_ref,
)
from app.services.lifecycle import LifecycleTransitioner
from app.services.workflows.service import WorkflowService
from app.storage.notification_bus import get_notification_bus
from app.storage.registry import get_registry
from app.storage.workflow_bus import get_workflow_bus
from app.storage.workflow_registry import get_workflow_registry


@lru_cache
def get_workflow_service() -> WorkflowService:
    """Return the process-wide WorkflowService singleton."""
    settings = get_settings()
    registry = get_registry()
    gh_verify = all(s.verify_ssl for s in settings.github_sources())
    github = GitHubClient(
        settings.github_api_base, settings.github_token, verify=gh_verify
    )
    gh_source = GitHubTaskSource(
        github, settings.public_base_url, config_for=settings.github_source_for
    )
    gh_host = GitHubCodeHost(github, settings.git_base)
    # Task Source / Code Host per run source. GitHub and manual runs collapse
    # onto the GitHub adapters; the Jira source + its configured code host are
    # registered below when Jira ingestion is configured (feature 003).
    sources: dict[str, object] = {
        "manual": gh_source, "github-issue": gh_source,
    }
    code_hosts: dict[str, object] = {
        "manual": gh_host, "github-issue": gh_host,
    }
    jira_sources = settings.jira_sources()
    if jira_sources:
        from app.services.jira import JiraClient, JiraTaskSource

        entry = jira_sources[0]
        jira = JiraClient(
            entry.base_url,
            auth=entry.auth,
            email=entry.email,
            token=entry.token() or "",
            verify=entry.verify_ssl,
        )
        sources["jira-issue"] = JiraTaskSource(
            jira, settings.public_base_url, config=entry
        )
        jira_github = GitHubClient(
            settings.github_api_base,
            settings.github_token,
            verify=entry.verify_ssl,
        )
        code_hosts["jira-issue"] = build_code_host(
            entry, jira_github, settings.git_base
        )

    fixture_sources = settings.fixture_sources()
    if fixture_sources:
        from app.services.fixture import FixtureTaskSource

        entry = fixture_sources[0]
        sources["fixture-issue"] = FixtureTaskSource(entry.fixtures_dir)
        fixture_github = GitHubClient(
            settings.github_api_base,
            settings.github_token,
            verify=entry.verify_ssl,
        )
        code_hosts["fixture-issue"] = build_code_host(
            entry, fixture_github, settings.git_base
        )

    def hooks_dir_for(run: WorkflowRun) -> str:
        """Resolve a run's configured hooks_dir (feature 006), if any."""
        if run.source == "github-issue" and run.task_ref:
            try:
                repo, _num = parse_github_ref(run.task_ref)
            except ValueError:
                return ""
            cfg = settings.github_source_for(repo)
            return cfg.hooks_dir if cfg else ""
        if run.source == "jira-issue" and jira_sources:
            return jira_sources[0].hooks_dir
        return ""

    # In-app first (always records the durable fallback row), then the
    # best-effort ticket comment via the run's source (feature 003).
    notifier = CompositeNotifier(
        [
            InAppNotifier(get_notification_store(), get_notification_bus()),
            TaskSourceNotifier(sources, settings.public_base_url),
            LifecycleTransitioner(
                sources, settings.public_base_url, hooks_dir_for
            ),
        ]
    )
    return WorkflowService(
        settings=settings,
        sessions=registry,
        workflows=get_workflow_registry(),
        backends=get_backend_policy(),
        git=GitService(settings.github_token),
        github=github,
        notifier=notifier,
        bus=get_workflow_bus(),
        dismissals=get_dismissal_store(),
        sources=sources,
        code_hosts=code_hosts,
    )


def build_code_host(
    source: TaskSourceConfig, github: GitHubClient, git_base: str
) -> object:
    """Build the code host for a Jira source's resolved repos.

    Self-hostable (feature 003, FR-023a): ``gitlab``/``gitea`` point at an
    on-prem instance; ``github`` reuses the GitHub client. The code-host token
    falls back to ``github_token`` when the host is GitHub.
    """
    if source.code_host in ("gitlab", "gitea"):
        from app.services.gitlab import GitLabCodeHost

        return GitLabCodeHost(
            source.code_host_base_url,
            source.code_host_token() or "",
            verify=source.verify_ssl,
        )
    return GitHubCodeHost(github, git_base)
