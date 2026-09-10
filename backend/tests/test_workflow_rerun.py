"""Tests for WorkflowService.rerun(): the visibility-gated discard-and-
restart action (feature 008), distinct from cleanup()'s reset-and-wait-
for-poll behavior."""
from __future__ import annotations

import pytest

from app.models_workflow import WorkflowRun
from app.services.exceptions import (
    RerunNotAllowedError,
    WorkflowNotFoundError,
)
from app.services.github import GitHubCodeHost
from app.services.github_tasksource import GitHubTaskSource
from app.services.local_task_source import LocalTaskSource
from app.services.workflows import WorkflowService
from app.storage.registry import SessionRegistry
from app.storage.workflow_registry import WorkflowRegistry
from tests.conftest import (
    _FakeDismissals,
    _FakeGit,
    _FakeGitHub,
    _FakeNotifier,
    _FakeRunner,
    _settings,
)


def _private_service(tmp_path, dismissals=None):
    runner = _FakeRunner(SessionRegistry(), outputs=[])
    git = _FakeGit()
    local_source = LocalTaskSource(str(tmp_path))
    fake_gh = _FakeGitHub()
    svc = WorkflowService(
        settings=_settings(),
        sessions=runner.sessions,
        workflows=WorkflowRegistry(),
        backends=runner,
        git=git,
        github=fake_gh,
        notifier=_FakeNotifier(),
        dismissals=dismissals or _FakeDismissals(),
        sources={"local-task": local_source},
        code_hosts={
            "local-task": GitHubCodeHost(fake_gh, "https://gh"),
        },
    )
    return svc, git


def _local_run(**overrides) -> WorkflowRun:
    fields = {
        "id": "wf-rerun",
        "repo": "me/sandbox",
        "issue_number": None,
        "source": "local-task",
        "task_ref": "local:hello-task",
        "branch": "kestrel/local-hello-task",
    }
    fields.update(overrides)
    return WorkflowRun(**fields)


def _write_local_task(tmp_path) -> None:
    task_dir = tmp_path / "hello-task"
    task_dir.mkdir()
    (task_dir / "task.json").write_text(
        '{"title": "t", "body": "b", "code_repo": "me/sandbox", '
        '"base_branch": null}'
    )


@pytest.mark.asyncio
async def test_rerun_unknown_raises_not_found() -> None:
    """Ensure rerunning an unknown run raises the domain error."""
    runner = _FakeRunner(SessionRegistry(), ["x"])
    svc = WorkflowService(
        settings=_settings(),
        sessions=runner.sessions,
        workflows=WorkflowRegistry(),
        backends=runner,
        git=_FakeGit(),
        github=_FakeGitHub(),
        notifier=_FakeNotifier(),
        dismissals=_FakeDismissals(),
    )
    with pytest.raises(WorkflowNotFoundError):
        await svc.rerun("nope")


@pytest.mark.asyncio
async def test_rerun_success_for_private_source(tmp_path) -> None:
    """rerun() deletes the branch, clears the dismissal, and immediately
    starts a fresh run for the same task_ref when the source is private."""
    _write_local_task(tmp_path)
    svc, git = _private_service(tmp_path)
    svc.workflows.create(_local_run())

    new_id = await svc.rerun("wf-rerun")

    assert new_id != "wf-rerun"
    mirror = svc._mirror_dir("me/sandbox")
    assert git.deleted_local == [(mirror, "kestrel/local-hello-task")]
    assert len(git.deleted_remote) == 1
    with pytest.raises(WorkflowNotFoundError):
        svc.get("wf-rerun")
    new_run = svc.get(new_id)
    assert new_run.task_ref == "local:hello-task"
    assert new_run.repo == "me/sandbox"
    assert new_run.source == "local-task"


@pytest.mark.asyncio
async def test_rerun_clears_dismissal(tmp_path) -> None:
    """rerun() clears any dismissal, like cleanup(), instead of adding one."""
    _write_local_task(tmp_path)
    dismissals = _FakeDismissals()
    dismissals.add("local:hello-task")
    svc, _git = _private_service(tmp_path, dismissals=dismissals)
    svc.workflows.create(_local_run())

    await svc.rerun("wf-rerun")

    assert not dismissals.is_dismissed("local:hello-task")


def _public_service(dismissals=None):
    """A WorkflowService with a github-issue and a jira-issue run, both
    resolving to a public TaskSource (feature 008, US3)."""
    runner = _FakeRunner(SessionRegistry(), outputs=[])
    git = _FakeGit()
    fake_gh = _FakeGitHub()
    gh_source = GitHubTaskSource(fake_gh)
    gh_host = GitHubCodeHost(fake_gh, "https://gh")
    svc = WorkflowService(
        settings=_settings(),
        sessions=runner.sessions,
        workflows=WorkflowRegistry(),
        backends=runner,
        git=git,
        github=fake_gh,
        notifier=_FakeNotifier(),
        dismissals=dismissals or _FakeDismissals(),
        sources={"github-issue": gh_source, "jira-issue": gh_source},
        code_hosts={"github-issue": gh_host, "jira-issue": gh_host},
    )
    return svc, git


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["github-issue", "jira-issue"])
async def test_rerun_refused_for_public_source(source: str) -> None:
    """rerun() refuses a GitHub- or Jira-sourced run, leaving it untouched."""
    dismissals = _FakeDismissals()
    svc, git = _public_service(dismissals=dismissals)
    run = _local_run(
        id="wf-public",
        repo="o/r",
        issue_number=7 if source == "github-issue" else None,
        source=source,
        task_ref="o/r#7" if source == "github-issue" else "RFC-1",
        branch="kestrel/issue-7",
    )
    svc.workflows.create(run)

    with pytest.raises(RerunNotAllowedError):
        await svc.rerun("wf-public")

    # Completely unchanged: branch untouched, dismissal untouched, run intact.
    assert git.deleted_local == []
    assert git.deleted_remote == []
    assert not dismissals.is_dismissed(run.task_ref)
    still_there = svc.get("wf-public")
    assert still_there.status == run.status
