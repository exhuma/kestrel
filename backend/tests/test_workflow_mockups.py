"""Tests for uiux-round mockup capture gating, dispatch, and reconcile."""
from __future__ import annotations

import os

import pytest

from app.backends.base import Capability, TurnResult
from app.models_workflow import WorkflowRun, WorkflowStep
from app.policy import BackendPolicy
from app.questionnaire import Questionnaire
from app.services.workflows.interview import mockups


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
    """Ensure a real {TEXT, FILE_EDITS} backend is offered for mockups."""
    policy = _policy({Capability.TEXT, Capability.FILE_EDITS})
    assert policy.optional_backend_for(
        "refine.mockup", mockups._MOCKUP_CAPS
    ) is not None


def test_mockup_caps_satisfiable_by_real_backend() -> None:
    """Regression: the gate must be satisfiable by a real backend's caps.

    claude_cli/opencode declare {TEXT, FILE_EDITS}; if the requirement ever
    re-introduces a never-declared cap (e.g. TOOL_USE) the gate becomes
    dead — capture would silently never run. Guard against that here.
    """
    real_caps = frozenset({Capability.TEXT, Capability.FILE_EDITS})
    assert real_caps >= mockups._MOCKUP_CAPS


@pytest.mark.asyncio
async def test_capture_skips_when_incapable() -> None:
    """Ensure no turn runs when the refine backend can't mock up."""
    class _Backends:
        def optional_backend_for(self, _step, _req):
            return None

    class _Service:
        backends = _Backends()
        turns = 0

        async def _run_turn_tracked(self, *_args):
            _Service.turns += 1

    qn = Questionnaire(questions=[])
    await mockups.capture_round_mockups(
        _Service(), WorkflowRun(id="r", repo="o/r"), "issue", qn
    )
    assert _Service.turns == 0
    assert qn.mockups == []


def _service(tmp_path, final_text):
    """A fake WorkflowService capturing one mockup turn's output."""
    backend = _FakeBackend({Capability.TEXT, Capability.FILE_EDITS})

    class _Backends:
        def optional_backend_for(self, _step, _req):
            return backend

    class _Settings:
        screenshots_root = str(tmp_path / "durable")

    class _Service:
        backends = _Backends()
        settings = _Settings()
        prompts: list[str] = []

        def _save(self, _run) -> None:
            pass

        def _debug_log(self, _run, _heading, _content) -> None:
            pass

        async def _run_turn_tracked(self, _run, _be, req, _slot, _bind):
            _Service.prompts.append(req.prompt)
            return TurnResult(session_id="s", final_text=final_text)

    return _Service()


@pytest.mark.asyncio
async def test_capture_reconciles_files_with_explanations(
    tmp_path, monkeypatch
) -> None:
    """On-disk files are the source of truth; parsed captions attach to
    them, a caption naming no file is dropped, a file with no caption
    gets ''."""
    class _Stub:
        def model_for(self, _step):
            return "sonnet"

    monkeypatch.setattr(mockups, "get_policy", _Stub)
    run = WorkflowRun(
        id="r", repo="o/r", workspace=str(tmp_path),
        artifact_dir=".kestrel/d-001", steps=[WorkflowStep("refine")],
    )
    refine_dir = os.path.join(
        str(tmp_path), run.artifact_dir, "screenshots", "refine"
    )
    os.makedirs(refine_dir, exist_ok=True)
    for name in ("login-01.png", "dash-02.png"):
        with open(os.path.join(refine_dir, name), "wb") as handle:
            handle.write(b"\x89PNG")
    final = (
        "did it\n<MOCKUPS>["
        '{"file": "login-01.png", "explanation": "the login screen"},'
        '{"file": "ghost.png", "explanation": "no such file"}'
        "]</MOCKUPS>"
    )
    service = _service(tmp_path, final)
    qn = Questionnaire(questions=[])

    await mockups.capture_round_mockups(service, run, "issue text", qn)

    assert "issue text" in service.prompts[0]
    by_name = {m.name: m for m in qn.mockups}
    assert set(by_name) == {"login-01.png", "dash-02.png"}  # ghost dropped
    assert by_name["login-01.png"].explanation == "the login screen"
    assert by_name["dash-02.png"].explanation == ""  # no caption → ""
    assert by_name["login-01.png"].url == (
        "/api/workflows/r/screenshots/refine/login-01.png"
    )
