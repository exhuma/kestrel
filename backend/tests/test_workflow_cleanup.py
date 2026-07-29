"""Tests for WorkflowService.cleanup(): the branch-deleting, un-dismissing
reset of a run, distinct from delete()'s abandon-and-dismiss (feature
"clean up a workflow"). Split out from test_workflow_service.py rather
than added there to keep both files under the module-length limit."""
from __future__ import annotations

import pytest

from app.models_workflow import WorkflowRun
from app.services.exceptions import WorkflowNotFoundError
from app.services.workflows import WorkflowService
from app.storage.registry import SessionRegistry
from app.storage.workflow_registry import WorkflowRegistry
from tests.conftest import (
    _FakeDismissals,
    _FakeGit,
    _FakeGitHub,
    _FakeNotifier,
    _FakeRunner,
    _service,
    _settings,
)


@pytest.mark.asyncio
async def test_cleanup_unknown_raises_not_found() -> None:
    """Ensure cleaning up an unknown run raises the domain error."""
    svc = _service(
        _FakeGitHub(), _FakeRunner(SessionRegistry(), ["x"]), _FakeGit()
    )
    with pytest.raises(WorkflowNotFoundError):
        await svc.cleanup("nope")


@pytest.mark.asyncio
async def test_cleanup_deletes_branch_locally_and_remotely() -> None:
    """cleanup() force-deletes the run's branch in the mirror and remote."""
    runner = _FakeRunner(SessionRegistry(), outputs=[])
    git = _FakeGit()
    reg = WorkflowRegistry()
    svc = WorkflowService(
        settings=_settings(),
        sessions=runner.sessions,
        workflows=reg,
        backends=runner,
        git=git,
        github=_FakeGitHub(),
        notifier=_FakeNotifier(),
        dismissals=_FakeDismissals(),
    )
    run = WorkflowRun(
        id="wf-cleanup", repo="o/r", issue_number=9,
        source="github-issue", branch="kestrel/issue-9",
    )
    reg.create(run)

    await svc.cleanup("wf-cleanup")

    mirror = svc._mirror_dir("o/r")
    assert git.deleted_local == [(mirror, "kestrel/issue-9")]
    assert git.deleted_remote == [
        (mirror, "kestrel/issue-9", ("x-access-token", "fake-gh-token"))
    ]


@pytest.mark.asyncio
async def test_cleanup_clears_dismissal_instead_of_adding() -> None:
    """cleanup() clears any dismissal so ingestion re-adopts the ticket,
    unlike delete() which adds one."""
    runner = _FakeRunner(SessionRegistry(), outputs=[])
    dismissals = _FakeDismissals()
    dismissals.add("o/r#9")  # simulate a prior abandon/dismissal
    reg = WorkflowRegistry()
    svc = WorkflowService(
        settings=_settings(),
        sessions=runner.sessions,
        workflows=reg,
        backends=runner,
        git=_FakeGit(),
        github=_FakeGitHub(),
        notifier=_FakeNotifier(),
        dismissals=dismissals,
    )
    run = WorkflowRun(
        id="wf-cleanup", repo="o/r", issue_number=9, source="github-issue",
    )
    reg.create(run)

    await svc.cleanup("wf-cleanup")

    assert not dismissals.is_dismissed("o/r#9")


@pytest.mark.asyncio
async def test_cleanup_removes_workspace_dir(tmp_path) -> None:
    """cleanup() also drops the run's local workspace clone, like delete()."""
    runner = _FakeRunner(SessionRegistry(), outputs=[])
    reg = WorkflowRegistry()
    svc = WorkflowService(
        settings=_settings(workspace_root=str(tmp_path)),
        sessions=runner.sessions,
        workflows=reg,
        backends=runner,
        git=_FakeGit(),
        github=_FakeGitHub(),
        notifier=_FakeNotifier(),
        dismissals=_FakeDismissals(),
    )
    workspace = tmp_path / "clone"
    workspace.mkdir()
    (workspace / "file.txt").write_text("work")
    run = WorkflowRun(
        id="wf-cleanup", repo="o/r", issue_number=9,
        source="github-issue", workspace=str(workspace),
    )
    reg.create(run)

    await svc.cleanup("wf-cleanup")

    assert not workspace.exists()
    with pytest.raises(WorkflowNotFoundError):
        svc.get("wf-cleanup")
