"""Tests for the reshaped unified workflow skeleton (feature 003)."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.services.workflows import WorkflowService
from app.storage.registry import SessionRegistry
from app.storage.workflow_registry import WorkflowRegistry
from tests.test_workflow_service import (
    _FakeGit,
    _FakeGitHub,
    _FakeNotifier,
    _FakeRunner,
    _refine_noquestions,
    _verdict,
    _wait,
)


def _svc(gh, runner, git) -> WorkflowService:
    return WorkflowService(
        settings=Settings(git_base="https://github.com", github_token="t"),
        sessions=runner.sessions,
        workflows=WorkflowRegistry(),
        backends=runner,
        git=git,
        github=gh,
        notifier=_FakeNotifier(),
    )


@pytest.mark.asyncio
async def test_create_sets_task_ref_and_reshaped_steps() -> None:
    """Ensure create() sets task_ref and the design/code/verify steps."""
    runner = _FakeRunner(SessionRegistry(), outputs=[*_refine_noquestions("x")])
    svc = _svc(_FakeGitHub(body="vague"), runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    run = svc.get(wid)
    assert run.task_ref == "o/r#5"
    assert [s.name for s in run.steps] == ["refine", "design", "code", "verify"]


@pytest.mark.asyncio
async def test_github_run_traverses_reshaped_status_sequence() -> None:
    """Ensure a GitHub run traverses refine -> PRD gate -> autonomous
    design/code/verify -> PR, with no plan/implement gates."""
    seen: list[str] = []

    class _Recorder(_FakeNotifier):
        def notify(self, run) -> None:
            if run.status not in seen:
                seen.append(run.status)
            super().notify(run)

    gh, git = _FakeGitHub(body="vague"), _FakeGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("prd"),
        "<PLAN>d</PLAN>", "coded", _verdict(accept=True),
    ])
    svc = WorkflowService(
        settings=Settings(git_base="https://github.com", github_token="t"),
        sessions=runner.sessions, workflows=WorkflowRegistry(),
        backends=runner, git=git, github=gh, notifier=_Recorder(),
    )
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")

    # The reshaped statuses appear; the removed ones never do.
    for s in ("designing", "coding", "verifying", "opening_pr", "done"):
        assert s in seen, s
    for removed in ("planning", "implementing", "awaiting_plan_approval",
                    "awaiting_implement_approval", "awaiting_implement_input"):
        assert removed not in seen, removed
