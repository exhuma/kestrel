"""Tests for the autonomous coder<->verifier loop (driver/code_verify)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models_workflow import WorkflowRun, WorkflowStep
from app.persistence.tables import FeedbackItemRow
from app.services.workflows.driver.code_verify import code_and_verify
from app.storage.registry import SessionRegistry
from tests.conftest import (
    _FakeFeedbackStore,
    _FakeGit,
    _FakeGitHub,
    _FakeRunner,
    _RoutingPolicy,
    _service,
    _settings,
    _subtask_body,
    _verdict,
    _wait,
)


@pytest.mark.asyncio
async def test_code_step_reuses_same_backend_design_session() -> None:
    """When design and code share a backend, the coder resumes the
    designer's session for context continuity (the intended handoff)."""
    gh = _FakeGitHub(body=_subtask_body("Build a clear widget"))
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "<PLAN>\ndo X\n</PLAN>",          # design → mints a session id
        "Implemented X",                   # code → should resume it
        _verdict(accept=True),
    ])
    svc = _service(gh, runner, _FakeGit())

    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "done")

    design_sid = svc.get(wid).steps[3].session_id
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
    gh = _FakeGitHub(body=_subtask_body("Build a clear widget"))
    sessions = SessionRegistry()
    design = _FakeRunner(
        sessions, outputs=["<PLAN>\ndo X\n</PLAN>"], id_prefix="llm-"
    )
    code = _FakeRunner(
        sessions,
        outputs=[
            "Implemented X",                                # code
            _verdict(accept=True),                          # verify
        ],
        id_prefix="ses-",
    )
    policy = _RoutingPolicy(sessions, design, code)
    svc = _service(gh, policy, _FakeGit())

    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "done")

    # The design step really did mint an id that would have leaked...
    assert svc.get(wid).steps[3].session_id.startswith("llm-")
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
    gh = _FakeGitHub(body=_subtask_body("Build a clear widget"))
    sessions = SessionRegistry()
    design = _FakeRunner(
        sessions, outputs=["<PLAN>\nAdd a shiny widget\n</PLAN>"],
        id_prefix="llm-",
    )
    code = _FakeRunner(
        sessions,
        outputs=[
            "Implemented X",
            _verdict(accept=True),
        ],
        id_prefix="ses-",
    )
    policy = _RoutingPolicy(sessions, design, code)
    svc = _service(gh, policy, _FakeGit())

    wid = await svc.create("o/r", 5, source="github-issue")
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
    gh = _FakeGitHub(body=_subtask_body("Build a clear widget"))
    git = _FakeGit()
    git.diffs = [""]  # coder produces no changes
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "<PLAN>\ndo X\n</PLAN>",
        "I looked but changed nothing",
    ])
    svc = _service(gh, runner, git)

    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "escalated")

    run = svc.get(wid)
    assert run.error == "escalated: the coder produced no changes"
    code_step = run.steps[4]
    assert code_step.status == "failed"
    assert code_step.active_sessions == []


@pytest.mark.asyncio
async def test_verifier_diff_excludes_artifact_folder(tmp_path) -> None:
    """The code diff is taken with the .kestrel folder excluded."""
    gh = _FakeGitHub(body=_subtask_body("Build a widget"))
    sessions = SessionRegistry()
    runner = _FakeRunner(
        sessions,
        outputs=[
            "<PLAN>plan</PLAN>",
            "Implemented X",
            _verdict(accept=True),
        ],
    )
    git = _FakeGit()
    svc = _service(
        gh, runner, git, settings=_settings(workspace_root=str(tmp_path))
    )

    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "done")

    assert ".kestrel" in git.diff_excludes


@pytest.mark.asyncio
async def test_drained_feedback_folds_into_the_round_start(tmp_path) -> None:
    """Feedback already queued for a run is picked up at the TOP of the
    very next code_and_verify round — folded into that round's coder
    prompt — and marked applied (feature 013, US2).

    Drives ``code_and_verify`` directly (design/refine already "done" on
    the run passed in) so this proves the round-start drain itself,
    independent of continue_run's separate pre-design boundary hook
    (covered in test_workflow_driver.py).
    """
    store = _FakeFeedbackStore()
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(
        SessionRegistry(), outputs=["Implemented X", _verdict(accept=True)]
    )
    svc = _service(
        gh, runner, _FakeGit(),
        settings=_settings(workspace_root=str(tmp_path)),
        feedback_store=store,
    )
    run = WorkflowRun(
        id="wf-1", repo="o/r", issue_number=5, task_ref="o/r#5",
        base_branch="main", branch="kestrel/5", workspace=str(tmp_path),
        status="coding",
        steps=[
            WorkflowStep(name="describe", status="done", deliverable="U"),
            WorkflowStep(name="refine", status="done", deliverable="PRD"),
            WorkflowStep(name="gap_analysis", status="done", deliverable=""),
            WorkflowStep(name="design", status="done", deliverable="Design"),
            WorkflowStep(name="code", status="pending"),
            WorkflowStep(name="verify", status="pending"),
        ],
    )
    svc.workflows.create(run)
    store.claim(FeedbackItemRow(
        external_id="fb-1", workflow_id="wf-1", task_ref="o/r#5",
        origin="ticket", author="octocat",
        body="Also handle the empty-input case",
        state="queued", created_at=datetime.now(timezone.utc),
    ))

    escalated = await code_and_verify(svc, run)

    assert escalated is False
    code_call = next(
        c for c in runner.calls if c["permission_mode"] == "acceptEdits"
    )
    assert "Also handle the empty-input case" in code_call["prompt"]
    assert store.items["fb-1"].state == "applied"
