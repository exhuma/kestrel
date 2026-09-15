"""Tests for WorkflowService.cleanup(): the branch-deleting, un-dismissing
reset of a run, distinct from delete()'s abandon-and-dismiss (feature
"clean up a workflow"). Split out from test_workflow_service.py rather
than added there to keep both files under the module-length limit."""
from __future__ import annotations

import pytest

from app.models_workflow import WorkflowArtifact, WorkflowRun
from app.services.exceptions import WorkflowNotFoundError
from app.services.github import GitHubCodeHost
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


class _ArtifactStore:
    """In-memory cleanup ledger double for cleanup behavior tests."""

    def __init__(self, artifacts: list[WorkflowArtifact]) -> None:
        self.artifacts = artifacts

    def list_for(self, _workflow_id: str) -> list[WorkflowArtifact]:
        """Return all artifacts supplied to this test ledger."""
        return self.artifacts

    def set_state(self, artifact_id: int, state: str, error=None) -> None:
        """Set one artifact state as production cleanup does."""
        for artifact in self.artifacts:
            if artifact.id == artifact_id:
                artifact.state = state
                artifact.error = error

    def discard_resolved(self, _workflow_id: str) -> None:
        """Discard terminal cleanup records while retaining failures."""
        self.artifacts = [a for a in self.artifacts if a.state == "failed"]


class _CleanupSource:
    """Task source double that records owned artifact cleanup requests."""

    def __init__(self) -> None:
        self.cleaned: list[tuple[str, str]] = []

    async def cleanup_artifact(self, kind: str, external_id: str) -> str:
        """Record cleanup and report a missing comment as already absent."""
        self.cleaned.append((kind, external_id))
        return "absent" if kind == "comment" else "cleaned"

    def visibility(self) -> str:
        """Report a public source for cleanup test compatibility."""
        return "public"


@pytest.mark.asyncio
async def test_cleanup_removes_owned_source_artifacts_before_reset() -> None:
    """Cleanup reverses owned source artifacts and drops their memory."""
    runner = _FakeRunner(SessionRegistry(), outputs=[])
    source = _CleanupSource()
    artifacts = _ArtifactStore(
        [
            WorkflowArtifact(
                "wf-cleanup", "source_body", "o/r#9\0original", "PRD",
                "restore", id=1,
            ),
            WorkflowArtifact(
                "wf-cleanup", "subtask", "o/r#10", "o/r#10",
                "delete_or_close", id=2,
            ),
            WorkflowArtifact(
                "wf-cleanup", "comment", "missing", "note",
                "best_effort", id=3,
            ),
        ]
    )
    reg = WorkflowRegistry()
    svc = WorkflowService(
        settings=_settings(), sessions=runner.sessions, workflows=reg,
        backends=runner, git=_FakeGit(), github=_FakeGitHub(),
        notifier=_FakeNotifier(), dismissals=_FakeDismissals(),
        sources={"github-issue": source},
        artifact_store=artifacts,
    )
    reg.create(WorkflowRun(id="wf-cleanup", repo="o/r", issue_number=9))

    await svc.cleanup("wf-cleanup")

    assert source.cleaned == [
        ("source_body", "o/r#9\0original"),
        ("subtask", "o/r#10"),
        ("comment", "missing"),
    ]
    assert artifacts.artifacts == []


class _SpyTaskSource:
    """Records any write-back call so a test can assert none happened
    (feature 008 regression guard: delete/cleanup must stay ticket-safe)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_task(self, _ref):
        return None

    async def post_comment(self, _ref, _body):
        self.calls.append("post_comment")
        return ""

    async def attach(self, _ref, _name, _data, _mimetype):
        self.calls.append("attach")

    async def publish_refined(self, _ref, _content):
        self.calls.append("publish_refined")

    def deep_link_ref(self, _ref):
        return ""

    async def transition(self, _ref, _event):
        self.calls.append("transition")
        return False

    def supports_time_spent(self) -> bool:
        return False

    def visibility(self):
        return "public"


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["github-issue", "jira-issue"])
async def test_delete_never_calls_task_source_write_back(source: str) -> None:
    """delete() must never comment/attach/publish/transition on the ticket,
    for any public source — pins the existing guarantee (spec FR-009)."""
    runner = _FakeRunner(SessionRegistry(), outputs=[])
    spy = _SpyTaskSource()
    reg = WorkflowRegistry()
    svc = WorkflowService(
        settings=_settings(),
        sessions=runner.sessions,
        workflows=reg,
        backends=runner,
        git=_FakeGit(),
        github=_FakeGitHub(),
        notifier=_FakeNotifier(),
        dismissals=_FakeDismissals(),
        sources={source: spy},
        code_hosts={source: _FakeGit()},
    )
    run = WorkflowRun(
        id="wf-delete", repo="o/r", issue_number=9, source=source,
    )
    reg.create(run)

    await svc.delete("wf-delete")

    assert spy.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["github-issue", "jira-issue"])
async def test_cleanup_never_calls_task_source_write_back(source: str) -> None:
    """cleanup() must never comment/attach/publish/transition on the
    ticket either — it reaches the code host (branch delete), never the
    task source (spec FR-009)."""
    runner = _FakeRunner(SessionRegistry(), outputs=[])
    spy = _SpyTaskSource()
    reg = WorkflowRegistry()
    svc = WorkflowService(
        settings=_settings(),
        sessions=runner.sessions,
        workflows=reg,
        backends=runner,
        git=_FakeGit(),
        github=_FakeGitHub(),
        notifier=_FakeNotifier(),
        dismissals=_FakeDismissals(),
        sources={source: spy},
        code_hosts={source: GitHubCodeHost(_FakeGitHub(), "https://gh")},
    )
    run = WorkflowRun(
        id="wf-cleanup2", repo="o/r", issue_number=9,
        source=source, branch="kestrel/issue-9",
    )
    reg.create(run)

    await svc.cleanup("wf-cleanup2")

    assert spy.calls == []
