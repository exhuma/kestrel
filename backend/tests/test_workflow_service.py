"""Tests for the WorkflowService state machine (integrations faked)."""
from __future__ import annotations

import asyncio

import pytest

from app.config import Settings
from app.models import ParsedEvent, SessionRecord
from app.services.exceptions import (
    InvalidWorkflowStateError,
    WorkflowNotFoundError,
)
from app.services.github import Issue
from app.services.workflows import WorkflowService
from app.storage.registry import SessionRegistry
from app.storage.workflow_registry import WorkflowRegistry


class _FakeGit:
    def __init__(self) -> None:
        self.pushed: list[str] = []

    async def clone(self, remote_url: str, dest: str) -> None: ...
    async def checkout_branch(self, dest: str, branch: str) -> None: ...
    async def commit_all(self, dest: str, message: str) -> None: ...
    async def diff(self, dest: str) -> str:
        return "diff --git a/x b/x"
    async def push(self, dest: str, branch: str) -> None:
        self.pushed.append(branch)


class _FakeGitHub:
    def __init__(self, body: str = "Please add a widget") -> None:
        self.body = body
        self.updated: str | None = None

    async def get_issue(self, repo: str, number: int) -> Issue:
        return Issue(number=number, title="Add widget", body=self.body)
    async def get_default_branch(self, repo: str) -> str:
        return "main"
    async def update_issue(self, repo: str, number: int, body: str) -> None:
        self.updated = body
    async def create_pull_request(self, repo, head, base, title, body,
                                  draft=True) -> str:
        return "https://github.com/o/r/pull/1"


class _FakeRunner:
    """Records a session with a canned final result text per call."""

    def __init__(self, sessions: SessionRegistry, outputs: list[str]) -> None:
        self.sessions = sessions
        self._outputs = list(outputs)
        self._n = 0

    async def run_blocking(self, prompt, cwd, permission_mode,
                           resume_id=None, on_session_id=None) -> str:
        sid = resume_id or f"s{self._n}"
        self._n += 1
        text = self._outputs.pop(0)
        if self.sessions.get(sid) is None:
            self.sessions._records[sid] = SessionRecord(session_id=sid, cwd=cwd)
        rec = self.sessions.get(sid)
        rec.events.append(ParsedEvent("result", sid, {"result": text}))
        rec.status = "idle"
        if on_session_id:
            on_session_id(sid)
        return sid


def _service(github, runner, git) -> WorkflowService:
    return WorkflowService(
        settings=Settings(git_base="https://github.com", github_token="t"),
        sessions=runner.sessions,
        workflows=WorkflowRegistry(),
        runner=runner,
        git=git,
        github=github,
    )


async def _wait(pred, timeout=2.0) -> None:
    for _ in range(int(timeout / 0.02)):
        if pred():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not reached")


@pytest.mark.asyncio
async def test_happy_path_refine_plan_implement_pr() -> None:
    """Ensure a run refines, plans, implements, and opens a PR."""
    gh = _FakeGitHub(body="vague issue")
    git = _FakeGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "<REFINED_ISSUE>\nBuild a clear widget\n</REFINED_ISSUE>",  # refine
        "The plan: do X then Y",                                    # plan
        "Implemented X and Y",                                      # implement
    ])
    svc = _service(gh, runner, git)

    wid = await svc.create("o/r", 5)

    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    assert svc.get(wid).steps[0].deliverable == "Build a clear widget"
    svc.approve(wid)  # writes issue + sentinel, advances to plan

    await _wait(lambda: svc.get(wid).status == "awaiting_plan_approval")
    assert "plan" in svc.get(wid).steps[1].deliverable.lower()
    assert gh.updated is not None and "agent-dispatcher:refined" in gh.updated
    svc.approve(wid)

    await _wait(lambda: svc.get(wid).status == "awaiting_implement_approval")
    assert "diff" in svc.get(wid).steps[2].deliverable
    svc.approve(wid)

    await _wait(lambda: svc.get(wid).status == "done")
    assert svc.get(wid).pr_url == "https://github.com/o/r/pull/1"
    assert git.pushed == [svc.get(wid).branch]


@pytest.mark.asyncio
async def test_sentinel_skips_refine() -> None:
    """Ensure an already-refined issue jumps straight to plan."""
    gh = _FakeGitHub(body="clear issue\n\n<!-- agent-dispatcher:refined -->")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "The plan", "Implemented",
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_plan_approval")
    assert svc.get(wid).steps[0].status == "done"  # refine skipped


@pytest.mark.asyncio
async def test_reject_ends_run() -> None:
    """Ensure rejecting a gate ends the run as rejected."""
    gh = _FakeGitHub(body="x\n\n<!-- agent-dispatcher:refined -->")
    runner = _FakeRunner(SessionRegistry(), outputs=["The plan"])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_plan_approval")
    svc.reject(wid)
    await _wait(lambda: svc.get(wid).status == "rejected")


@pytest.mark.asyncio
async def test_step_failure_is_logged_and_recorded(caplog) -> None:
    """Ensure a failing step logs the exception (not just swallows it)."""

    class _BrokenGitHub(_FakeGitHub):
        async def get_issue(self, repo: str, number: int) -> Issue:
            raise RuntimeError("boom: simulated GitHub failure")

    svc = _service(
        _BrokenGitHub(), _FakeRunner(SessionRegistry(), ["x"]), _FakeGit()
    )
    with caplog.at_level("ERROR", logger="app.services.workflows"):
        wid = await svc.create("o/r", 5)
        await _wait(lambda: svc.get(wid).status == "failed")

    assert svc.get(wid).error is not None
    assert "boom: simulated GitHub failure" in svc.get(wid).error
    assert any(
        wid in record.message
        and record.exc_info is not None
        and "boom" in str(record.exc_info[1])
        for record in caplog.records
    )


def test_get_unknown_raises() -> None:
    """Ensure get on an unknown id raises WorkflowNotFoundError."""
    svc = _service(_FakeGitHub(), _FakeRunner(SessionRegistry(), ["x"]),
                   _FakeGit())
    with pytest.raises(WorkflowNotFoundError):
        svc.get("nope")


@pytest.mark.asyncio
async def test_reply_wrong_state_raises() -> None:
    """Ensure reply outside the refine interview raises InvalidWorkflowState."""
    from app.models_workflow import WorkflowRun, WorkflowStep

    svc = _service(_FakeGitHub(), _FakeRunner(SessionRegistry(), ["x"]),
                   _FakeGit())
    run = WorkflowRun(id="wf", repo="o/r", issue_number=1,
                      steps=[WorkflowStep(name="refine", status="pending")])
    svc.workflows.create(run)
    svc._control["wf"] = svc._new_control()  # needs a running loop
    with pytest.raises(InvalidWorkflowStateError):
        svc.reply("wf", "an answer")
