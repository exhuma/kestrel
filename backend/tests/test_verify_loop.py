"""Tests for the autonomous code<->verify loop (feature 003, US3)."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.ports import Evidence, Observation
from app.services.workflows import WorkflowService, _parse_verdict
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


class _FakeCheckRunner:
    """A check runner returning a canned Evidence bundle."""

    def __init__(self, evidence: Evidence) -> None:
        self._evidence = evidence

    async def run(self, workspace: str) -> Evidence:
        return self._evidence


def _svc(gh, runner, git, *, max_iter=3, check_runner=None) -> WorkflowService:
    return WorkflowService(
        settings=Settings(
            git_base="https://github.com", github_token="t",
            max_verify_iterations=max_iter,
        ),
        sessions=runner.sessions,
        workflows=WorkflowRegistry(),
        backends=runner,
        git=git,
        github=gh,
        notifier=_FakeNotifier(),
        check_runner=check_runner,
    )


def test_parse_verdict() -> None:
    """Ensure the verdict parser reads accept/feedback and fails safe."""
    txt = '<VERDICT>{"accept": true, "feedback": ""}</VERDICT>'
    assert _parse_verdict(txt) == (True, "")
    txt = 'x <VERDICT>{"accept": false, "feedback": "no"}</VERDICT>'
    assert _parse_verdict(txt) == (False, "no")
    # Unparseable ⇒ reject (never ship unverified work).
    assert _parse_verdict("no verdict here")[0] is False


@pytest.mark.asyncio
async def test_accept_first_round_opens_pr() -> None:
    """Ensure an accepted verdict opens the change request."""
    gh, git = _FakeGitHub(body="vague"), _FakeGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("prd"),
        "<PLAN>d</PLAN>", "coded", _verdict(accept=True),
    ])
    svc = _svc(gh, runner, git)
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")
    assert svc.get(wid).pr_url == "https://github.com/o/r/pull/1"


@pytest.mark.asyncio
async def test_reject_then_accept_reruns_coder() -> None:
    """Ensure a rejected verdict re-runs the coder, then accepts."""
    gh, git = _FakeGitHub(body="vague"), _FakeGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("prd"),
        "<PLAN>d</PLAN>",                       # design
        "coded v1", _verdict(accept=False, feedback="fix the edge case"),
        "coded v2", _verdict(accept=True),
    ])
    svc = _svc(gh, runner, git)
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")
    # Coder ran twice; the re-run carried the verifier's feedback.
    coder_prompts = [
        c["prompt"] for c in runner.calls
        if "implement" in c["prompt"].lower()
    ]
    assert any("fix the edge case" in p for p in coder_prompts)


@pytest.mark.asyncio
async def test_exhaustion_escalates_without_pr() -> None:
    """Ensure the loop escalates (no PR) when verification never passes."""
    gh, git = _FakeGitHub(body="vague"), _FakeGit()
    notifier = _FakeNotifier()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("prd"),
        "<PLAN>d</PLAN>",
        "coded", _verdict(accept=False, feedback="nope"),
        "coded", _verdict(accept=False, feedback="still nope"),
    ])
    svc = WorkflowService(
        settings=Settings(git_base="https://github.com", github_token="t",
                          max_verify_iterations=2),
        sessions=runner.sessions, workflows=WorkflowRegistry(),
        backends=runner, git=git, github=gh, notifier=notifier,
    )
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "escalated")
    assert svc.get(wid).pr_url is None
    assert git.pushed == []
    assert "escalated" in notifier.notified


@pytest.mark.asyncio
async def test_failing_check_forces_reject() -> None:
    """Ensure a failing observation rejects even if the model says accept."""
    gh, git = _FakeGitHub(body="vague"), _FakeGit()
    evidence = Evidence([
        Observation(name="uv run pytest", kind="check", passed=False,
                    detail="1 failed"),
    ])
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("prd"),
        "<PLAN>d</PLAN>",
        "coded", _verdict(accept=True),   # model says accept ...
    ])
    # max_iter=1 so exhaustion escalates after the single forced reject.
    svc = _svc(gh, runner, git, max_iter=1,
               check_runner=_FakeCheckRunner(evidence))
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    # ... but the failing check forces a reject → exhaustion → escalated.
    await _wait(lambda: svc.get(wid).status == "escalated")
    assert svc.get(wid).pr_url is None


@pytest.mark.asyncio
async def test_no_awaiting_gate_during_autonomous_phases() -> None:
    """Ensure design/code/verify never enter an awaiting_* gate (FR-014)."""
    gh, git = _FakeGitHub(body="vague"), _FakeGit()
    seen: list[str] = []

    class _RecordingNotifier(_FakeNotifier):
        def notify(self, run) -> None:
            seen.append(run.status)
            super().notify(run)

    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("prd"),
        "<PLAN>d</PLAN>", "coded", _verdict(accept=True),
    ])
    svc = WorkflowService(
        settings=Settings(git_base="https://github.com", github_token="t"),
        sessions=runner.sessions, workflows=WorkflowRegistry(),
        backends=runner, git=git, github=gh, notifier=_RecordingNotifier(),
    )
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")
    # The only awaiting_* status ever seen is the PRD gate.
    awaiting = [s for s in seen if s.startswith("awaiting_")]
    assert set(awaiting) <= {
        "awaiting_refine_approval", "awaiting_refine_input"
    }
    assert "designing" in seen and "coding" in seen and "verifying" in seen
