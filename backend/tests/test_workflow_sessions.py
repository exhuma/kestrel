"""Tests for app.services.workflows.sessions (turn/session-chip tracking)."""
from __future__ import annotations

import asyncio
import contextlib

import pytest

from app.models import CanonicalEvent, EventKind
from app.models_workflow import StepSession, WorkflowRun, WorkflowStep
from app.storage.registry import SessionRegistry
from tests.conftest import _FakeGit, _FakeGitHub, _FakeRunner, _service, _wait


@pytest.mark.asyncio
async def test_watch_activity_reflects_live_events_on_chip() -> None:
    """Ensure the activity monitor maps a session's events onto its chip."""
    runner = _FakeRunner(SessionRegistry(), outputs=[])
    svc = _service(_FakeGitHub(), runner, _FakeGit())
    run = WorkflowRun(
        id="wf-x", repo="o/r", issue_number=1,
        steps=[WorkflowStep("refine")],
    )
    svc.workflows.create(run)
    slot = StepSession("writer", "Writer", "agent")
    run.steps[0].active_sessions = [slot]
    sid = "sess-1"
    runner.sessions.create(sid, cwd="/tmp")

    task = svc._watch_activity(run, sid, slot)
    try:
        runner.sessions.append_event(
            sid, CanonicalEvent(EventKind.TOOL_USE, sid, tool_name="Edit")
        )
        await _wait(lambda: slot.activity == "editing")
        # A later tool call updates the hint in place.
        runner.sessions.append_event(
            sid, CanonicalEvent(EventKind.TOOL_USE, sid, tool_name="Bash")
        )
        await _wait(lambda: slot.activity == "running")
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
