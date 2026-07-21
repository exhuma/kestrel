"""A blocked coder escalates rather than parking on a gate (feature 003, US3)."""
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
    _wait,
)


@pytest.mark.asyncio
async def test_coder_with_no_diff_escalates_not_input_gate() -> None:
    """Ensure a coder that makes no changes escalates (FR-020), never parking
    on the removed awaiting_implement_input human gate."""
    gh = _FakeGitHub(body="vague")
    git = _FakeGit()
    git.diffs = [""]  # coder produced no changes
    notifier = _FakeNotifier()
    seen: list[str] = []

    class _Recorder(_FakeNotifier):
        def notify(self, run) -> None:
            seen.append(run.status)
            super().notify(run)

    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("prd"),
        "<PLAN>d</PLAN>",       # design
        "I couldn't make changes",   # code — yields an empty diff
    ])
    svc = WorkflowService(
        settings=Settings(git_base="https://github.com", github_token="t"),
        sessions=runner.sessions,
        workflows=WorkflowRegistry(),
        backends=runner,
        git=git,
        github=gh,
        notifier=_Recorder(),
    )
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "escalated")

    assert "awaiting_implement_input" not in seen
    assert svc.get(wid).pr_url is None
    assert "no changes" in (svc.get(wid).error or "")
