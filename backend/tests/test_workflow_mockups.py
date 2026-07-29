"""Tests for refine-stage mockup capture gating and dispatch."""
from __future__ import annotations

import pytest

from app.backends.base import Capability, TurnResult
from app.models_workflow import WorkflowRun, WorkflowStep
from app.policy import BackendPolicy
from app.services.workflows.driver import mockups


class _FakeBackend:
    def __init__(self, caps) -> None:
        self.id = "b"
        self.caps = frozenset(caps)


class _FakeRegistry:
    def __init__(self, backend) -> None:
        self._backend = backend

    def get(self, _id):
        return self._backend

    def all(self):
        return [self._backend]


def _policy(caps) -> BackendPolicy:
    return BackendPolicy(_FakeRegistry(_FakeBackend(caps)), {}, "b")


def test_optional_backend_none_for_text_only() -> None:
    """Ensure a text-only refine backend yields no mockup backend."""
    policy = _policy({Capability.TEXT})
    assert policy.optional_backend_for(
        "refine.mockup", mockups._MOCKUP_CAPS
    ) is None


def test_optional_backend_returned_when_capable() -> None:
    """Ensure a FILE_EDITS+TOOL_USE backend is offered for mockups."""
    policy = _policy(
        {Capability.TEXT, Capability.FILE_EDITS, Capability.TOOL_USE}
    )
    assert policy.optional_backend_for(
        "refine.mockup", mockups._MOCKUP_CAPS
    ) is not None


def test_optional_backend_none_without_registry() -> None:
    """Ensure a label-only policy (no registry) offers nothing."""
    assert BackendPolicy(None, {}, "b").optional_backend_for(
        "refine.mockup", mockups._MOCKUP_CAPS
    ) is None


@pytest.mark.asyncio
async def test_capture_mockups_skips_when_incapable() -> None:
    """Ensure no turn runs when the refine backend can't mock up."""
    class _Backends:
        def optional_backend_for(self, _step, _req):
            return None

    class _Service:
        backends = _Backends()
        turns = 0

        async def _run_turn_tracked(self, *_args):
            _Service.turns += 1

    await mockups.capture_mockups(_Service(), WorkflowRun(id="r", repo="o/r"),
                                  "PRD")
    assert _Service.turns == 0


@pytest.mark.asyncio
async def test_capture_mockups_dispatches_when_capable(monkeypatch) -> None:
    """Ensure a capable backend gets a mockup turn scoped to the worktree."""
    class _Stub:
        def model_for(self, _step):
            return "sonnet"

    monkeypatch.setattr(mockups, "get_policy", _Stub)
    backend = _FakeBackend({Capability.FILE_EDITS, Capability.TOOL_USE})
    captured: dict[str, str] = {}

    class _Backends:
        def optional_backend_for(self, _step, _req):
            return backend

    class _Service:
        backends = _Backends()

        def _save(self, _run) -> None:
            pass

        def _debug_log(self, _run, _heading, _content) -> None:
            pass

        async def _run_turn_tracked(self, _run, _be, req, _slot, _bind):
            captured["cwd"] = req.cwd
            captured["prompt"] = req.prompt
            return TurnResult(session_id="s", final_text="ok")

    run = WorkflowRun(
        id="r", repo="o/r", workspace="/ws",
        artifact_dir=".kestrel/d-001", steps=[WorkflowStep("refine")],
    )
    await mockups.capture_mockups(_Service(), run, "The PRD text")
    assert captured["cwd"] == "/ws"
    assert "The PRD text" in captured["prompt"]
    assert ".kestrel/d-001/screenshots/refine" in captured["prompt"]
