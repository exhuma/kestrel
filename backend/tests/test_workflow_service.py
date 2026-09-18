"""Tests for WorkflowService lifecycle/CRUD, persistence, and artifacts."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.models_workflow import WorkflowRun
from app.services.exceptions import WorkflowNotFoundError
from app.services.workflows import WorkflowService
from app.storage.registry import SessionRegistry
from app.storage.workflow_registry import WorkflowRegistry
from tests.conftest import (
    _approve_prd,
    _FakeDismissals,
    _FakeGit,
    _FakeGitHub,
    _FakeNotifier,
    _FakeRunner,
    _refine_noquestions,
    _service,
    _settings,
    _subtask_body,
    _verdict,
    _wait,
)


@pytest.mark.asyncio
async def test_happy_path_refine_then_technical_analysis_decomposes() -> None:
    """Ensure approvals publish the PRD and decomposition before completion.

    A plain ticket never reaches design/code/verify/PR; only a
    SUBTASK_SENTINEL follow-up does (FR-011/FR-014/FR-015).
    """
    gh = _FakeGitHub(body="vague issue")
    git = _FakeGit()
    runner = _FakeRunner(
        SessionRegistry(),
        outputs=[
            "<UNDERSTANDING>Build a clear widget.</UNDERSTANDING>",  # describe
            *_refine_noquestions("Build a clear widget"),  # refine
            "<TECH_ANALYSIS>analysis</TECH_ANALYSIS>",  # technical_analysis
            '<CONTAINMENT>{"verdicts": []}</CONTAINMENT>',  # critic
        ],
    )
    svc = _service(gh, runner, git)

    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "awaiting_describe_approval")
    svc.approve(wid)

    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    assert svc.get(wid).steps[1].deliverable == "Build a clear widget"
    svc.approve(wid)  # PRD approved → technical_analysis runs

    await _wait(
        lambda: svc.get(wid).status == "awaiting_decomposition_approval"
    )
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "decomposed")
    assert gh.updated is not None and "kestrel:refined" in gh.updated


def test_get_unknown_raises() -> None:
    """Ensure get on an unknown id raises WorkflowNotFoundError."""
    svc = _service(
        _FakeGitHub(), _FakeRunner(SessionRegistry(), ["x"]), _FakeGit()
    )
    with pytest.raises(WorkflowNotFoundError):
        svc.get("nope")


@pytest.mark.asyncio
async def test_save_publishes_to_bus() -> None:
    """Ensure every state transition ticks the SSE bus for that run."""

    class _Bus:
        def __init__(self) -> None:
            self.ticks: list[str] = []

        def publish(self, workflow_id: str) -> None:
            self.ticks.append(workflow_id)

    bus = _Bus()
    gh = _FakeGitHub(body=_subtask_body("x"))
    runner = _FakeRunner(
        SessionRegistry(), outputs=["plan", "impl", _verdict(accept=True)]
    )
    svc = WorkflowService(
        settings=Settings(git_base="https://github.com", github_token="t"),
        sessions=runner.sessions,
        workflows=WorkflowRegistry(),
        backends=runner,
        git=_FakeGit(),
        github=gh,
        notifier=_FakeNotifier(),
        bus=bus,
    )
    wid = await svc.create("o/r", 5, source="github-issue")
    await _approve_prd(svc, wid)
    await _wait(lambda: svc.get(wid).status == "done")
    assert bus.ticks  # at least one push happened
    assert all(t == wid for t in bus.ticks)


@pytest.mark.asyncio
async def test_notifier_fires_on_awaiting_and_done() -> None:
    """Ensure attention-worthy statuses reach the notifier."""
    gh = _FakeGitHub(body=_subtask_body("x"))
    runner = _FakeRunner(
        SessionRegistry(), outputs=["plan", "impl", _verdict(accept=True)]
    )
    notifier = _FakeNotifier()
    svc = WorkflowService(
        settings=Settings(git_base="https://github.com", github_token="t"),
        sessions=runner.sessions,
        workflows=WorkflowRegistry(),
        backends=runner,
        git=_FakeGit(),
        github=gh,
        notifier=notifier,
    )
    wid = await svc.create("o/r", 5, source="github-issue")
    await _approve_prd(svc, wid)
    await _wait(lambda: svc.get(wid).status == "done")
    assert "done" in notifier.notified
    # The gateless autonomous phases are transient and never notified.
    assert "designing" not in notifier.notified
    assert "coding" not in notifier.notified
    assert "verifying" not in notifier.notified


@pytest.mark.asyncio
async def test_notifier_does_not_fire_on_reject() -> None:
    """Ensure a bare PRD rejection does not produce a notification."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(
        SessionRegistry(),
        outputs=[
            "<UNDERSTANDING>refined</UNDERSTANDING>",
            *_refine_noquestions("refined"),
        ],
    )
    notifier = _FakeNotifier()
    svc = WorkflowService(
        settings=Settings(git_base="https://github.com", github_token="t"),
        sessions=runner.sessions,
        workflows=WorkflowRegistry(),
        backends=runner,
        git=_FakeGit(),
        github=gh,
        notifier=notifier,
    )
    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "awaiting_describe_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.reject(wid)
    await _wait(lambda: svc.get(wid).status == "rejected")
    assert "rejected" not in notifier.notified


class _SpyGitHub(_FakeGitHub):
    """Records any *mutating* GitHub call so a test can assert none fire."""

    def __init__(self, body: str = "") -> None:
        super().__init__(body)
        self.mutations: list[str] = []

    async def update_issue(self, repo, number, body) -> None:
        self.mutations.append("update_issue")
        await super().update_issue(repo, number, body)

    async def create_pull_request(
        self, repo, head, base, title, body, draft=True
    ) -> str:
        self.mutations.append("create_pull_request")
        return await super().create_pull_request(
            repo, head, base, title, body, draft
        )


@pytest.mark.asyncio
async def test_delete_drops_run_without_touching_github() -> None:
    """Ensure abandoning a run removes it and makes no GitHub calls."""
    gh = _SpyGitHub(body="vague issue")
    runner = _FakeRunner(
        SessionRegistry(),
        outputs=[
            "<UNDERSTANDING>v1</UNDERSTANDING>",
            *_refine_noquestions("v1"),
        ],
    )
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "awaiting_describe_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    before = list(gh.mutations)

    await svc.delete(wid)

    assert gh.mutations == before  # abandon touched nothing on GitHub
    assert wid not in svc._tasks  # the driver task was cancelled/cleared
    with pytest.raises(WorkflowNotFoundError):
        svc.get(wid)


@pytest.mark.asyncio
async def test_delete_removes_workspace_dir(tmp_path) -> None:
    """Ensure abandoning a run deletes its local workspace clone."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(
        SessionRegistry(),
        outputs=[
            "<UNDERSTANDING>v1</UNDERSTANDING>",
            *_refine_noquestions("v1"),
        ],
    )
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "awaiting_describe_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    workspace = tmp_path / "clone"
    workspace.mkdir()
    (workspace / "file.txt").write_text("work")
    svc.get(wid).workspace = str(workspace)

    await svc.delete(wid)

    assert not workspace.exists()
    with pytest.raises(WorkflowNotFoundError):
        svc.get(wid)


@pytest.mark.asyncio
async def test_delete_removes_all_workspace_sessions() -> None:
    """Ensure abandoning a run terminates and deletes every session it
    spawned in its workspace, not just the ids a step still points at."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(
        SessionRegistry(),
        outputs=[
            "<UNDERSTANDING>v1</UNDERSTANDING>",
            *_refine_noquestions("v1"),
        ],
    )
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "awaiting_describe_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    workspace = svc.get(wid).workspace
    workspace_sids = [
        record.session_id
        for record in runner.sessions.list()
        if record.cwd == workspace
    ]
    step_sids = {s.session_id for s in svc.get(wid).steps if s.session_id}
    # The refine leg spawns more sessions (coordinator + writer) than any
    # single step still points at — that gap is what we must clean up.
    assert any(sid not in step_sids for sid in workspace_sids)

    await svc.delete(wid)

    for sid in workspace_sids:
        assert runner.sessions.get(sid) is None  # record + rows dropped
        assert sid in runner.terminated  # subprocess terminated


@pytest.mark.asyncio
async def test_delete_unknown_raises_not_found() -> None:
    """Ensure abandoning an unknown run raises the domain error."""
    svc = _service(
        _FakeGitHub(), _FakeRunner(SessionRegistry(), ["x"]), _FakeGit()
    )
    with pytest.raises(WorkflowNotFoundError):
        await svc.delete("nope")


@pytest.mark.asyncio
async def test_abandon_records_dismissal() -> None:
    """Ensure delete() records a dismissal for the run's (repo, issue)."""
    runner = _FakeRunner(SessionRegistry(), outputs=[])
    dismissals = _FakeDismissals()
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
        id="wf-abandon", repo="o/r", issue_number=9, source="github-issue"
    )
    reg.create(run)

    await svc.delete("wf-abandon")

    assert dismissals.is_dismissed("o/r#9")


class _SpyGit(_FakeGit):
    """FakeGit that records worktree removals."""

    def __init__(self) -> None:
        super().__init__()
        self.removed: list[tuple[str, str]] = []

    async def remove_worktree(self, mirror_dir: str, dest: str) -> None:
        self.removed.append((mirror_dir, dest))


@pytest.mark.asyncio
async def test_teardown_removes_worktree_and_directory(tmp_path) -> None:
    """Ensure teardown removes the worktree and its debug sibling."""
    git = _SpyGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[])
    svc = WorkflowService(
        settings=_settings(workspace_root=str(tmp_path)),
        sessions=runner.sessions,
        workflows=WorkflowRegistry(),
        backends=runner,
        git=git,
        github=_FakeGitHub(),
        notifier=_FakeNotifier(),
    )
    ws = tmp_path / "wf-x"
    ws.mkdir()
    (ws / "f.txt").write_text("x")
    debug = tmp_path / "wf-x-debug"
    debug.mkdir()
    (debug / "dialogue.log").write_text("debug")
    run = WorkflowRun(id="wf-x", repo="o/r", issue_number=1, workspace=str(ws))

    await svc._teardown_workspace(run)

    assert not ws.exists()
    assert not debug.exists()
    assert git.removed == [(svc._mirror_dir("o/r"), str(ws))]


@pytest.mark.asyncio
async def test_abandon_one_run_leaves_others_worktree_intact(tmp_path) -> None:
    """Ensure abandoning one run does not disturb another's worktree."""
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
    ws_a = tmp_path / "a"
    ws_a.mkdir()
    ws_b = tmp_path / "b"
    ws_b.mkdir()
    reg.create(
        WorkflowRun(id="a", repo="o/r", issue_number=1, workspace=str(ws_a))
    )
    reg.create(
        WorkflowRun(id="b", repo="o/r", issue_number=2, workspace=str(ws_b))
    )

    await svc.delete("a")

    assert not ws_a.exists()
    assert ws_b.exists()
