"""Tests for the autonomous coder<->verifier loop (driver/code_verify)."""
from __future__ import annotations

import pytest

from app.storage.registry import SessionRegistry
from tests.conftest import (
    _FakeGit,
    _FakeGitHub,
    _FakeRunner,
    _refine_noquestions,
    _RoutingPolicy,
    _service,
    _settings,
    _verdict,
    _wait,
)


@pytest.mark.asyncio
async def test_code_step_reuses_same_backend_design_session() -> None:
    """When design and code share a backend, the coder resumes the
    designer's session for context continuity (the intended handoff)."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("Build a clear widget"),
        "<PLAN>\ndo X\n</PLAN>",          # design → mints a session id
        "Implemented X",                   # code → should resume it
        _verdict(accept=True),
    ])
    svc = _service(gh, runner, _FakeGit())

    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")

    design_sid = svc.get(wid).steps[1].session_id
    code_call = next(
        c for c in runner.calls if c["permission_mode"] == "acceptEdits"
    )
    assert design_sid is not None
    assert code_call["resume_id"] == design_sid


@pytest.mark.asyncio
async def test_code_step_does_not_reuse_foreign_backend_session() -> None:
    """A design session id must not leak into a different code backend.

    Regression: when ``design`` runs on an LLM backend (``llm-…`` ids)
    and ``code`` on opencode (``ses-…`` ids), the coder must start a
    fresh session rather than resume the designer's foreign id — which
    opencode would reject with a 500 (``Expected a string starting with
    "ses"``).
    """
    gh = _FakeGitHub(body="vague issue")
    sessions = SessionRegistry()
    design = _FakeRunner(
        sessions, outputs=["<PLAN>\ndo X\n</PLAN>"], id_prefix="llm-"
    )
    code = _FakeRunner(
        sessions,
        outputs=[
            *_refine_noquestions("Build a clear widget"),  # refine substeps
            "Implemented X",                                # code
            _verdict(accept=True),                          # verify
        ],
        id_prefix="ses-",
    )
    policy = _RoutingPolicy(sessions, design, code)
    svc = _service(gh, policy, _FakeGit())

    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")

    # The design step really did mint an id that would have leaked...
    assert svc.get(wid).steps[1].session_id.startswith("llm-")
    # ...but the coder started fresh instead of resuming it.
    code_call = next(
        c for c in code.calls if c["permission_mode"] == "acceptEdits"
    )
    assert code_call["resume_id"] is None


@pytest.mark.asyncio
async def test_code_handover_via_file_on_cross_backend() -> None:
    """Cross-backend: the coder gets the design as a worktree file, not inline.

    On a cross-backend route the coder starts a fresh session (no memory of
    the designer's turn). The design is handed over as ``design.md`` in the
    shared ``.kestrel/`` folder — which the file-capable coder reads — rather
    than embedded verbatim in the prompt, so a large plan never bloats the
    context window.
    """
    gh = _FakeGitHub(body="vague issue")
    sessions = SessionRegistry()
    design = _FakeRunner(
        sessions, outputs=["<PLAN>\nAdd a shiny widget\n</PLAN>"],
        id_prefix="llm-",
    )
    code = _FakeRunner(
        sessions,
        outputs=[
            *_refine_noquestions("Build a clear widget"),
            "Implemented X",
            _verdict(accept=True),
        ],
        id_prefix="ses-",
    )
    policy = _RoutingPolicy(sessions, design, code)
    svc = _service(gh, policy, _FakeGit())

    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")

    code_call = next(
        c for c in code.calls if c["permission_mode"] == "acceptEdits"
    )
    assert code_call["resume_id"] is None  # fresh session, no memory
    # Handover is by file reference, not inlined plan text.
    assert "design.md" in code_call["prompt"]
    assert "Add a shiny widget" not in code_call["prompt"]


@pytest.mark.asyncio
async def test_no_changes_escalation_fails_code_step() -> None:
    """An empty coder diff escalates the run AND marks the code step failed.

    The UI keys its activity spinner off step status, so a terminal run must
    not leave the code step stuck ``running`` (FR: any failure stops the
    activity indicators).
    """
    gh = _FakeGitHub(body="vague issue")
    git = _FakeGit()
    git.diffs = [""]  # coder produces no changes
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("Build a clear widget"),
        "<PLAN>\ndo X\n</PLAN>",
        "I looked but changed nothing",
    ])
    svc = _service(gh, runner, git)

    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "escalated")

    run = svc.get(wid)
    assert run.error == "escalated: the coder produced no changes"
    code_step = run.steps[2]
    assert code_step.status == "failed"
    assert code_step.active_sessions == []


@pytest.mark.asyncio
async def test_verifier_diff_excludes_artifact_folder(tmp_path) -> None:
    """The code diff is taken with the .kestrel folder excluded."""
    gh = _FakeGitHub(body="vague issue")
    sessions = SessionRegistry()
    runner = _FakeRunner(
        sessions,
        outputs=[
            *_refine_noquestions("Build a widget"),
            "<PLAN>plan</PLAN>",
            "Implemented X",
            _verdict(accept=True),
        ],
    )
    git = _FakeGit()
    svc = _service(
        gh, runner, git, settings=_settings(workspace_root=str(tmp_path))
    )

    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")

    assert ".kestrel" in git.diff_excludes
