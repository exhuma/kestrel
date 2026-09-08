"""Tests for the hand-curated health-check registration list
(feature 014, research.md R6): a GitHub profile is one entry even though
it plays two roles; Jira and its configured code host are two.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config_models import TaskSourceConfig
from app.services import health as health_module


class _FakeAdapter:
    def __init__(self, label: str) -> None:
        self.label = label

    async def check_health(self) -> bool:
        return True


def _fake_service(sources: dict, code_hosts: dict) -> SimpleNamespace:
    return SimpleNamespace(sources=sources, code_hosts=code_hosts)


def _settings(
    github: bool = False, jira_code_host: str | None = None,
    fixture: bool = False,
):
    github_sources = (
        [TaskSourceConfig(type="github", watched_repos=["o/r"])]
        if github else []
    )
    jira_sources = (
        [TaskSourceConfig(
            type="jira", code_host=jira_code_host,
            base_url="https://jira.example", jql="project = X", key="X",
        )]
        if jira_code_host else []
    )
    fixture_sources = (
        [TaskSourceConfig(type="fixture", fixtures_dir="/tmp/fixtures")]
        if fixture else []
    )
    return SimpleNamespace(
        github_sources=lambda: github_sources,
        jira_sources=lambda: jira_sources,
        fixture_sources=lambda: fixture_sources,
    )


@pytest.mark.asyncio
async def test_github_profile_registers_exactly_one_entry(
    monkeypatch,
) -> None:
    """A GitHub profile's task-source and code-host share one connection
    (FR-010) — only one "github" entry is registered, not two."""
    gh_source, gh_host = _FakeAdapter("gh-source"), _FakeAdapter("gh-host")
    service = _fake_service(
        {"github-issue": gh_source}, {"github-issue": gh_host}
    )
    settings = _settings(github=True)
    monkeypatch.setattr(health_module, "get_settings", lambda: settings)
    monkeypatch.setattr(health_module, "get_workflow_service", lambda: service)

    checks = health_module._health_checks()

    assert [name for name, _ in checks] == ["github"]


@pytest.mark.asyncio
async def test_jira_and_its_gitlab_code_host_are_two_independent_entries(
    monkeypatch,
) -> None:
    """Jira's task source and its configured GitLab code host are
    genuinely different systems/credentials — two entries, not one."""
    jira_source = _FakeAdapter("jira-source")
    gitlab_host = _FakeAdapter("gitlab-host")
    service = _fake_service(
        {"jira-issue": jira_source}, {"jira-issue": gitlab_host}
    )
    monkeypatch.setattr(
        health_module, "get_settings",
        lambda: _settings(jira_code_host="gitlab"),
    )
    monkeypatch.setattr(health_module, "get_workflow_service", lambda: service)

    checks = health_module._health_checks()

    assert [name for name, _ in checks] == ["jira", "gitlab"]


@pytest.mark.asyncio
async def test_unconfigured_roles_register_nothing(monkeypatch) -> None:
    """An operator who never set up GitHub never sees a "github" entry
    at all, even though ``sources["github-issue"]`` always exists as the
    fallback default."""
    gh = _FakeAdapter("gh")
    service = _fake_service({"github-issue": gh}, {"github-issue": gh})
    settings = _settings()
    monkeypatch.setattr(health_module, "get_settings", lambda: settings)
    monkeypatch.setattr(health_module, "get_workflow_service", lambda: service)

    assert health_module._health_checks() == []


@pytest.mark.asyncio
async def test_fixture_only_setup_registers_one_entry(monkeypatch) -> None:
    """A local-only setup registers just the fixture entry."""
    fx = _FakeAdapter("fx")
    service = _fake_service({"fixture-issue": fx}, {"fixture-issue": fx})
    settings = _settings(fixture=True)
    monkeypatch.setattr(health_module, "get_settings", lambda: settings)
    monkeypatch.setattr(health_module, "get_workflow_service", lambda: service)

    assert [name for name, _ in health_module._health_checks()] == ["fixture"]
