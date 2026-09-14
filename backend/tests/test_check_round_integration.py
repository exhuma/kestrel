"""Focused workflow coverage for backend-owned local check rounds."""
from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.services.workflows import WorkflowService
from app.storage.registry import SessionRegistry
from app.storage.workflow_registry import WorkflowRegistry
from tests.conftest import (
    _approve_prd,
    _FakeGit,
    _FakeGitHub,
    _FakeNotifier,
    _FakeRunner,
    _subtask_body,
    _wait,
)


def _service(runner: _FakeRunner, tmp_path) -> WorkflowService:
    """Build a workflow service whose worktree survives for the assertion."""
    return WorkflowService(
        settings=Settings(
            git_base="https://github.com",
            github_token="t",
            max_verify_iterations=2,
            workspace_root=str(tmp_path),
            workflow_debug=True,
        ),
        sessions=runner.sessions,
        workflows=WorkflowRegistry(),
        backends=runner,
        git=_FakeGit(),
        github=_FakeGitHub(body=_subtask_body("Build a widget")),
        notifier=_FakeNotifier(),
    )


@pytest.mark.asyncio
async def test_failed_local_check_retries_coder_without_verifier(
    tmp_path,
) -> None:
    """A failed contract check consumes the existing code/verify budget."""
    contract = json.dumps({
        "version": 1,
        "plan": "Build a widget.",
        "boundary": "none",
        "acceptance": [],
        "tasks": [],
        "checks": [{
            "command": "false",
            "cwd": ".",
            "timeout_seconds": 1,
            "rationale": "Fails deliberately.",
        }],
    })
    runner = _FakeRunner(
        SessionRegistry(),
        outputs=[
            f"<DESIGN_CONTRACT>{contract}</DESIGN_CONTRACT>",
            "coded first attempt",
            "coded second attempt",
        ],
    )
    service = _service(runner, tmp_path)
    workflow_id = await service.create("o/r", 5, source="github-issue")
    await _approve_prd(service, workflow_id)
    await _wait(lambda: service.get(workflow_id).status == "escalated")
    calls = runner.calls
    assert [call["permission_mode"] for call in calls] == [
        "plan",
        "acceptEdits",
        "acceptEdits",
    ]
    assert "Deterministic local checks failed" in calls[-1]["prompt"]
    assert "<VERDICT>" not in calls[-1]["prompt"]
