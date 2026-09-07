"""Tests for the reshaped unified workflow skeleton (feature 003)."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.services.workflows import WorkflowService
from app.services.workflows.shared import TicketRef, build_run
from app.storage.registry import SessionRegistry
from app.storage.workflow_registry import WorkflowRegistry
from tests.conftest import (
    _FakeGit,
    _FakeGitHub,
    _FakeNotifier,
    _FakeRunner,
    _subtask_body,
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


def test_build_run_sets_task_ref_and_reshaped_steps() -> None:
    """build_run() sets task_ref and the full pipeline's steps.

    A pure-construction unit test (feature 012's test-pyramid fix): no
    WorkflowService, no fakes, no event loop — this only asserts on
    build_run()'s deterministic output, so there's no driver task to
    spawn or drain.
    """
    run = build_run(
        TicketRef("o/r", 5), source="github-issue", workspace_root="/tmp"
    )
    assert run.task_ref == "o/r#5"
    assert [s.name for s in run.steps] == [
        "describe", "refine", "gap_analysis", "design", "code", "verify",
    ]


@pytest.mark.asyncio
async def test_github_run_traverses_reshaped_status_sequence() -> None:
    """Ensure a GitHub run traverses autonomous design/code/verify -> PR,
    with no plan/implement gates.

    A follow-up (SUBTASK_SENTINEL) body skips describe/refine/
    gap_analysis entirely (FR-015) — the only way to reach design/code/
    verify at all now that a plain ticket's run always ends at
    gap_analysis instead (FR-014); the PRD gate itself is covered by the
    describe/refine tests, not this one.
    """
    seen: list[str] = []

    class _Recorder(_FakeNotifier):
        def notify(self, run) -> None:
            if run.status not in seen:
                seen.append(run.status)
            super().notify(run)

    gh, git = _FakeGitHub(body=_subtask_body("vague")), _FakeGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "<PLAN>d</PLAN>", "coded", _verdict(accept=True),
    ])
    svc = WorkflowService(
        settings=Settings(git_base="https://github.com", github_token="t"),
        sessions=runner.sessions, workflows=WorkflowRegistry(),
        backends=runner, git=git, github=gh, notifier=_Recorder(),
    )
    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "done")

    # The reshaped statuses appear; the removed ones never do.
    for s in ("designing", "coding", "verifying", "opening_pr", "done"):
        assert s in seen, s
    for removed in ("planning", "implementing", "awaiting_plan_approval",
                    "awaiting_implement_approval", "awaiting_implement_input"):
        assert removed not in seen, removed
