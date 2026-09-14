"""Tests for the refine/design/deliver orchestration (driver/__init__)."""

from __future__ import annotations

import asyncio

import pytest

from app.backends.base import BackendTurnError, Capability
from app.models_workflow import WorkflowRun, WorkflowStep
from app.services.exceptions import InvalidWorkflowStateError
from app.services.workflows.driver import design
from app.storage.registry import SessionRegistry
from tests.conftest import (
    _coord,
    _FakeGit,
    _FakeGitHub,
    _FakeRunner,
    _q,
    _qs,
    _refine_noquestions,
    _RoutingPolicy,
    _service,
    _settings,
    _subtask_body,
    _verdict,
    _wait,
)


async def _reach_refine_approval(gh, outputs: list[str]):
    """Drive a fresh run through describe approval up to the refine
    gate — the common prefix shared by the reject-at-refine tests below."""
    runner = _FakeRunner(SessionRegistry(), outputs=outputs)
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "awaiting_describe_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    return svc, wid


@pytest.mark.asyncio
async def test_active_and_wait_seconds_accumulate_through_both_gates() -> None:
    """Ensure the run-level clock (feature 006) tracks real elapsed time
    across an input-gate round and the approval gate, excluding both
    waits from active_seconds and stopping entirely once the run is done.
    """
    gh, git = _FakeGitHub(body="vague issue"), _FakeGit()
    runner = _FakeRunner(
        SessionRegistry(),
        outputs=[
            "<UNDERSTANDING>Build a clear widget.</UNDERSTANDING>",
            _coord(["developer"]),
            _qs(_q(prompt="Which?", options=[{"value": "a", "label": "A"}])),
            _coord([]),
            "<REFINED_ISSUE>\nBuild a clear widget\n</REFINED_ISSUE>",
            "<TECH_ANALYSIS>analysis</TECH_ANALYSIS>",  # gap_analysis
            '<CONTAINMENT>{"verdicts": []}</CONTAINMENT>',  # critic
        ],
    )
    svc = _service(gh, runner, git)

    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "awaiting_describe_approval")
    svc.approve(wid)

    await _wait(lambda: svc.get(wid).status == "awaiting_refine_input")
    assert svc.get(wid).clock_state == "waiting"
    await asyncio.sleep(0.05)  # simulate the operator taking a moment
    svc.submit_answers(wid, {"developer:q0": "a"})

    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    assert svc.get(wid).clock_state == "waiting"
    await asyncio.sleep(0.05)  # simulate the operator taking a moment
    svc.approve(wid)

    # A plain ticket pauses after gap_analysis until its decomposition is
    # approved, then it never reaches design/code/verify (FR-014).
    await _wait(
        lambda: svc.get(wid).status == "awaiting_decomposition_approval"
    )
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "decomposed")
    run = svc.get(wid)
    assert run.clock_state is None
    assert run.clock_since is None
    assert run.active_seconds > 0
    assert run.wait_seconds > 0


@pytest.mark.asyncio
async def test_design_sets_boundary_from_tag() -> None:
    """Ensure a well-formed <BOUNDARY> tag sets run.boundary (feature 005).

    A follow-up (SUBTASK_SENTINEL) body skips describe/refine/gap_analysis
    entirely (FR-015) — the only way a run still reaches design/code/verify
    at all now that a plain ticket always ends at gap_analysis (FR-014).
    """
    gh = _FakeGitHub(body=_subtask_body("Build a clear widget"))
    git = _FakeGit()
    runner = _FakeRunner(
        SessionRegistry(),
        outputs=[
            "<PLAN>\nStep 1\n</PLAN>\n<BOUNDARY>http</BOUNDARY>",
            "Implemented",
            "explored",  # http boundary -> an explore turn runs before verdict
            _verdict(
                accept=True,
                observations=[
                    {
                        "name": "GET /widget",
                        "kind": "http",
                        "passed": True,
                        "detail": "200 OK",
                    }
                ],
            ),
        ],
    )
    svc = _service(gh, runner, git)
    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")
    assert svc.get(wid).boundary == "http"


@pytest.mark.asyncio
async def test_design_missing_boundary_tag_leaves_it_none() -> None:
    """Ensure a missing/malformed tag leaves boundary None without
    failing the design step (feature 005)."""
    gh = _FakeGitHub(body=_subtask_body("Build a clear widget"))
    git = _FakeGit()
    runner = _FakeRunner(
        SessionRegistry(),
        outputs=[
            "<PLAN>\nStep 1\n</PLAN>",  # no <BOUNDARY> tag at all
            "Implemented",
            _verdict(accept=True),
        ],
    )
    svc = _service(gh, runner, git)
    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")
    assert svc.get(wid).boundary is None


class _RaisingBackend:
    """A backend whose turns always explode, to exercise the in-flight
    step being marked failed when a step raises mid-run."""

    caps = frozenset({Capability.TEXT})

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def run_turn(self, req, on_session_id=None):
        raise RuntimeError("boom: design backend exploded")

    def terminate(self, session_id: str) -> bool:
        return True


@pytest.mark.asyncio
async def test_step_exception_marks_active_step_failed() -> None:
    """An exception while a step is running fails that step, not just the run.

    Otherwise the run shows ``failed`` while the design step stays
    ``running`` and the UI keeps spinning."""
    # A follow-up body (FR-015) lands straight at design — the only way
    # to exercise design at all now that a plain ticket always ends at
    # gap_analysis (FR-014).
    gh = _FakeGitHub(body=_subtask_body("Build a clear widget"))
    sessions = SessionRegistry()
    code = _FakeRunner(sessions, outputs=[], id_prefix="ses-")
    policy = _RoutingPolicy(sessions, _RaisingBackend(), code)
    svc = _service(gh, policy, _FakeGit())

    wid = await svc.create("o/r", 5, source="github-issue")  # design raises
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "failed")

    run = svc.get(wid)
    assert "boom" in (run.error or "")
    design_step = run.steps[3]
    assert design_step.status == "failed"
    assert design_step.active_sessions == []


@pytest.mark.asyncio
async def test_sentinel_skips_refine() -> None:
    """Ensure an already-refined issue still waits for PRD approval."""
    gh = _FakeGitHub(body="clear issue\n\n<!-- kestrel:refined -->")
    runner = _FakeRunner(
        SessionRegistry(),
        outputs=[
            "<TECH_ANALYSIS>analysis</TECH_ANALYSIS>",  # gap_analysis
            '<CONTAINMENT>{"verdicts": []}</CONTAINMENT>',  # critic
        ],
    )
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    assert svc.get(wid).prd_approved is False
    svc.approve(wid)
    await _wait(
        lambda: svc.get(wid).status == "awaiting_decomposition_approval"
    )
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "decomposed")
    assert svc.get(wid).steps[0].status == "done"  # describe skipped
    assert svc.get(wid).steps[1].status == "done"  # refine skipped
    assert svc.get(wid).steps[1].deliverable == gh.body
    assert svc.get(wid).prd_approved is True


@pytest.mark.asyncio
async def test_subtask_sentinel_waits_for_prd_approval() -> None:
    """Ensure a follow-up marker cannot bypass the PRD approval gate."""
    gh = _FakeGitHub(body=_subtask_body("Build a clear widget"))
    svc = _service(gh, _FakeRunner(SessionRegistry(), []), _FakeGit())
    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    run = svc.get(wid)
    assert run.steps[0].status == "done"
    assert run.steps[2].status == "done"
    assert run.prd_approved is False


@pytest.mark.asyncio
async def test_design_requires_explicit_prd_approval(tmp_path) -> None:
    """Ensure completed refine without provenance cannot start design."""
    svc = _service(
        _FakeGitHub(),
        _FakeRunner(SessionRegistry(), []),
        _FakeGit(),
        settings=_settings(workspace_root=str(tmp_path)),
    )
    run = WorkflowRun(
        id="wf-prd-gate",
        repo="o/r",
        task_ref="o/r#5",
        workspace=str(tmp_path),
        steps=[
            WorkflowStep(name="describe", status="done"),
            WorkflowStep(name="refine", status="done", deliverable="PRD"),
            WorkflowStep(name="gap_analysis", status="done"),
            WorkflowStep(name="design"),
        ],
    )
    with pytest.raises(InvalidWorkflowStateError, match="approved PRD"):
        await design(svc, run)


@pytest.mark.asyncio
async def test_reject_ends_run() -> None:
    """Ensure rejecting the PRD gate ends the run as rejected."""
    svc, wid = await _reach_refine_approval(
        _FakeGitHub(body="vague issue"),
        [
            "<UNDERSTANDING>refined</UNDERSTANDING>",
            *_refine_noquestions("refined"),
        ],
    )
    svc.reject(wid)
    await _wait(lambda: svc.get(wid).status == "rejected")


class _BoomDismissals:
    """A dismissal store that always explodes — used to force a secondary
    failure inside ``_drive``'s own ``except _Rejected:`` block, which has
    no try/except of its own around this call."""

    def add(self, task_ref: str) -> None:
        raise RuntimeError("boom: dismissal store exploded")


@pytest.mark.asyncio
async def test_driver_task_exception_is_logged_not_swallowed(caplog) -> None:
    """A secondary failure that escapes ``_drive`` entirely (past its own
    except block) must not vanish as asyncio's generic "never retrieved"
    warning — the driver task's done-callback (``_log_driver_exception``)
    must log it loudly instead."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(
        SessionRegistry(),
        outputs=[
            "<UNDERSTANDING>refined</UNDERSTANDING>",
            *_refine_noquestions("refined"),
        ],
    )
    svc = _service(gh, runner, _FakeGit())
    svc.dismissals = _BoomDismissals()
    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "awaiting_describe_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")

    with caplog.at_level("ERROR", logger="app.services.workflows"):
        svc.reject(wid)  # -> _Rejected -> dismissals.add() raises uncaught
        await _wait(lambda: wid not in svc._tasks)

    assert any(
        "driver task failed unexpectedly" in record.message
        and record.exc_info is not None
        and "boom: dismissal store exploded" in str(record.exc_info[1])
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_step_failure_is_logged_and_recorded(caplog) -> None:
    """Ensure a failing step logs the exception (not just swallows it)."""

    class _BrokenGitHub(_FakeGitHub):
        async def get_issue(self, repo: str, number: int):
            raise RuntimeError("boom: simulated GitHub failure")

    svc = _service(
        _BrokenGitHub(), _FakeRunner(SessionRegistry(), ["x"]), _FakeGit()
    )
    with caplog.at_level("ERROR", logger="app.services.workflows"):
        wid = await svc.create("o/r", 5, source="github-issue")
        await _wait(lambda: svc.get(wid).status == "failed")

    assert svc.get(wid).error is not None
    assert "boom: simulated GitHub failure" in svc.get(wid).error
    assert any(
        wid in record.message
        and record.exc_info is not None
        and "boom" in str(record.exc_info[1])
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_steps_use_policy_models() -> None:
    """Ensure each phase that actually runs passes its policy model to
    claude. A follow-up (SUBTASK_SENTINEL) body is the only way to reach
    design/code/verify at all (FR-014/FR-015) — describe/refine/
    gap_analysis never run for it, so they keep their initial ``None``
    model."""
    gh = _FakeGitHub(body=_subtask_body("Build it"))
    runner = _FakeRunner(
        SessionRegistry(),
        outputs=[
            "<PLAN>\nDo it\n</PLAN>",
            "Implemented",
            _verdict(accept=True),
        ],
    )
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")
    assert {c["model"] for c in runner.calls} == {"sonnet"}
    assert [s.model for s in svc.get(wid).steps] == [
        None,
        "sonnet",
        None,
        "sonnet",
        "sonnet",
        "sonnet",
    ]


@pytest.mark.asyncio
async def test_reject_refine_without_prompt_ends_run() -> None:
    """Ensure terminal reject at the refine gate ends the run as rejected."""
    svc, wid = await _reach_refine_approval(
        _FakeGitHub(body="vague issue"),
        ["<UNDERSTANDING>v1</UNDERSTANDING>", *_refine_noquestions("v1")],
    )
    svc.reject(wid)
    await _wait(lambda: svc.get(wid).status == "rejected")


@pytest.mark.asyncio
async def test_backend_error_result_fails_run_loudly() -> None:
    """Ensure an errored agent turn fails the run with the message.

    A claude auth failure surfaces as a BackendTurnError; the run must go
    to "failed" carrying the message rather than parking a bogus
    deliverable at an approval gate.
    """

    class _ErroringRunner(_FakeRunner):
        async def run_turn(self, req, on_session_id=None):
            raise BackendTurnError(
                "agent backend error: Not logged in · Please run /login"
            )

    runner = _ErroringRunner(SessionRegistry(), outputs=[])
    svc = _service(_FakeGitHub(body="vague issue"), runner, _FakeGit())
    wid = await svc.create("o/r", 5, source="github-issue")

    await _wait(lambda: svc.get(wid).status == "failed")
    assert "Not logged in" in (svc.get(wid).error or "")
