"""Tests for the source-agnostic poll listing (feature 004, US2)."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.config_models import TaskSourceConfig
from app.ports import Task, WorkItem
from app.services import poll_source
from app.services.github import Issue
from app.services.ingestion import IngestionService
from app.services.jira_poll import JiraPollService
from app.services.reconcile import ReconcileService
from tests.test_jira_poll import (
    _FakeCodeHost,
    _FakeIngestion,
    _FakeJira,
    _FakeSource,
)
from tests.test_jira_poll import (
    _FakeDismissals as _JiraDismissals,
)
from tests.test_reconcile import (
    _FakeDismissals,
    _FakeGitHub,
    _FakeWorkflows,
)


@pytest.mark.asyncio
async def test_reconcile_list_work_items_starts_no_run() -> None:
    """Ensure the GitHub listing returns items and starts no run."""
    source = TaskSourceConfig(type="github", watched_repos=["o/r"])
    wf, dis = _FakeWorkflows(), _FakeDismissals()
    ingestion = IngestionService(
        Settings(_env_file=None, task_sources=[source]), wf, dis
    )
    svc = ReconcileService(
        source, _FakeGitHub(issues=[Issue(5, "Fix", "b")]), ingestion, dis
    )
    items = await svc.list_work_items()
    assert items == [WorkItem("github-issue", "o/r#5", "Fix", "o/r")]
    assert wf.created == []


@pytest.mark.asyncio
async def test_jira_list_work_items_starts_no_run() -> None:
    """Ensure the Jira listing resolves repos and starts no run."""
    cfg = TaskSourceConfig(
        type="jira", base_url="https://j", jql="q", key="RFC",
        repo_field="cf1",
    )
    jira = _FakeJira([Task("RFC-1", "t", "b")], fields={"RFC-1": "team/svc"})
    ing = _FakeIngestion()
    svc = JiraPollService(
        cfg, jira, _FakeSource(), _FakeCodeHost(), ing, _JiraDismissals()
    )
    items = await svc.list_work_items()
    assert items == [
        WorkItem("jira-issue", "RFC-1", "t", "team/svc", "main")
    ]
    assert ing.calls == []


def test_configured_poll_sources_gates_on_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure a PollSource is yielded per configured type, none when empty."""
    monkeypatch.setattr(poll_source, "get_reconcile_services", lambda: ("R",))
    monkeypatch.setattr(poll_source, "get_jira_poll_services", lambda: ("J",))
    gh = TaskSourceConfig(type="github", watched_repos=["o/r"])
    jira = TaskSourceConfig(type="jira", base_url="https://j", jql="q", key="R")
    assert poll_source.configured_poll_sources(Settings(_env_file=None)) == []
    both = Settings(_env_file=None, task_sources=[gh, jira])
    assert poll_source.configured_poll_sources(both) == ["R", "J"]
