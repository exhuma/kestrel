"""Tests for the workflow chip liveness-probe helper."""
from __future__ import annotations

import pytest

from app.backends.base import LivenessResult
from app.models_workflow import StepSession, WorkflowRun, WorkflowStep
from app.services.workflows import liveness as wf_liveness
from app.storage.registry import SessionRegistry


class _FakeBackend:
    def __init__(self, result: LivenessResult) -> None:
        self.result = result
        self.probed: list[str] = []

    async def check_alive(self, session_id: str) -> LivenessResult:
        self.probed.append(session_id)
        return self.result


def _run(step: WorkflowStep) -> WorkflowRun:
    return WorkflowRun(
        id="wf-1", repo="o/r", issue_number=1,
        steps=[step, WorkflowStep(name="design")],
    )


@pytest.mark.asyncio
async def test_poll_active_step_noop_when_nothing_is_running() -> None:
    """Ensure polling a gate-parked run (no running step) does nothing."""
    step = WorkflowStep(name="refine", status="awaiting_approval")
    run = _run(step)
    saved: list[WorkflowRun] = []
    backend = _FakeBackend(LivenessResult(alive=False, reason="n/a"))

    await wf_liveness.poll_active_step(
        lambda _name: backend, SessionRegistry(), saved.append, run
    )

    assert backend.probed == []
    assert saved == []


@pytest.mark.asyncio
async def test_poll_active_step_ignores_chips_without_a_session_id() -> None:
    """Ensure a chip whose session id isn't known yet is skipped."""
    chip = StepSession(profile_id="designer", label="Designer")
    step = WorkflowStep(name="design", status="running", active_sessions=[chip])
    run = _run(step)
    backend = _FakeBackend(LivenessResult(alive=False, reason="n/a"))

    await wf_liveness.poll_active_step(
        lambda _name: backend, SessionRegistry(), lambda _r: None, run
    )

    assert backend.probed == []
    assert chip.status == "running"


@pytest.mark.asyncio
async def test_poll_active_step_alive_chip_is_untouched() -> None:
    """Ensure a healthy chip is neither escalated nor persisted."""
    chip = StepSession(
        profile_id="designer", label="Designer", session_id="s1",
        status="running",
    )
    step = WorkflowStep(name="design", status="running", active_sessions=[chip])
    run = _run(step)
    saved: list[WorkflowRun] = []
    backend = _FakeBackend(LivenessResult(alive=True))
    sessions = SessionRegistry()
    sessions.create("s1", "/tmp/s1")

    await wf_liveness.poll_active_step(
        lambda _name: backend, sessions, saved.append, run
    )

    assert backend.probed == ["s1"]
    assert chip.status == "running"
    assert saved == []


@pytest.mark.asyncio
async def test_poll_active_step_dead_chip_is_escalated_and_saved() -> None:
    """Ensure a dead chip flips to error with a reason and gets persisted."""
    chip = StepSession(
        profile_id="designer", label="Designer", session_id="s1",
        status="running",
    )
    step = WorkflowStep(name="design", status="running", active_sessions=[chip])
    run = _run(step)
    saved: list[WorkflowRun] = []
    backend = _FakeBackend(
        LivenessResult(alive=False, reason="opencode session gone")
    )
    sessions = SessionRegistry()
    sessions.create("s1", "/tmp/s1")

    await wf_liveness.poll_active_step(
        lambda _name: backend, sessions, saved.append, run
    )

    assert chip.status == "error"
    assert chip.error == "opencode session gone"
    assert saved == [run]


@pytest.mark.asyncio
async def test_poll_active_step_resolves_backend_per_step_name() -> None:
    """Ensure the running step's own backend is used, not any other step's."""
    chip = StepSession(
        profile_id="coder", label="Coder", session_id="s1", status="running"
    )
    step = WorkflowStep(name="code", status="running", active_sessions=[chip])
    run = _run(step)
    seen_steps: list[str] = []

    def backend_for(name: str) -> _FakeBackend:
        seen_steps.append(name)
        return _FakeBackend(LivenessResult(alive=True))

    await wf_liveness.poll_active_step(
        backend_for, SessionRegistry(), lambda _r: None, run
    )

    assert seen_steps == ["code"]
