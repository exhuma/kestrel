"""Tests for workflow recovery after a backend restart."""
from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from app.persistence.workflow_store import WorkflowStore
from app.storage.registry import SessionRegistry
from tests.test_workflow_persistence import (
    _migrate,
    _persistent_service,
)
from tests.test_workflow_service import (
    _FakeGit,
    _FakeGitHub,
    _FakeRunner,
    _coord,
    _q,
    _qs,
    _refined,
    _refined_body,
    _wait,
)


def _store(tmp_path: Path) -> WorkflowStore:
    url = _migrate(tmp_path / "rec.db")
    return WorkflowStore(
        sessionmaker(bind=sa.create_engine(url))
    )


@pytest.mark.asyncio
async def test_recover_resumes_awaiting_input(
    tmp_path: Path,
) -> None:
    """Ensure a run parked at the interview survives restart."""
    store = _store(tmp_path)
    runner1 = _FakeRunner(SessionRegistry(), outputs=[
        _coord(["developer"]),
        _qs(_q(prompt="What colour?", qtype="free_text", options=[])),
    ])
    svc1 = _persistent_service(
        store, _FakeGitHub(body="vague"), runner1, _FakeGit()
    )
    wid = await svc1.create("o/r", 5)
    await _wait(
        lambda: svc1.get(wid).status
        == "awaiting_refine_input"
    )

    # --- simulated restart: fresh registry/service/fakes ---
    # The interview state is rebuilt from the persisted envelope, so a
    # further coordinator round can run and the writer can finish.
    runner2 = _FakeRunner(SessionRegistry(), outputs=[
        _coord([]),
        _refined("Build a blue widget"),
    ])
    svc2 = _persistent_service(
        store, _FakeGitHub(body="vague"), runner2, _FakeGit()
    )
    await svc2.recover()

    run = svc2.get(wid)
    assert run.status == "awaiting_refine_input"

    svc2.submit_answers(wid, {"developer:q0": "Blue, please"})
    await _wait(
        lambda: svc2.get(wid).status
        == "awaiting_refine_approval"
    )
    assert (
        svc2.get(wid).steps[0].deliverable
        == "Build a blue widget"
    )


@pytest.mark.asyncio
async def test_recover_resumes_awaiting_plan_approval(
    tmp_path: Path,
) -> None:
    """Ensure a run parked at the plan gate survives restart."""
    store = _store(tmp_path)
    runner1 = _FakeRunner(SessionRegistry(), outputs=[
        "The plan",
    ])
    svc1 = _persistent_service(
        store,
        _FakeGitHub(body=_refined_body("x")),
        runner1,
        _FakeGit(),
    )
    wid = await svc1.create("o/r", 5)
    await _wait(
        lambda: svc1.get(wid).status
        == "awaiting_plan_approval"
    )

    runner2 = _FakeRunner(SessionRegistry(), outputs=[
        "Implemented",
    ])
    git2 = _FakeGit()
    svc2 = _persistent_service(
        store,
        _FakeGitHub(body=_refined_body("x")),
        runner2,
        git2,
    )
    await svc2.recover()
    assert svc2.get(wid).status == "awaiting_plan_approval"

    svc2.approve(wid)
    await _wait(
        lambda: svc2.get(wid).status
        == "awaiting_implement_approval"
    )
    svc2.approve(wid)
    await _wait(lambda: svc2.get(wid).status == "done")
    assert git2.pushed == [svc2.get(wid).branch]


@pytest.mark.asyncio
async def test_recover_fails_mid_step_runs(
    tmp_path: Path,
) -> None:
    """Ensure runs that died mid-step fail loudly."""
    store = _store(tmp_path)
    runner1 = _FakeRunner(SessionRegistry(), outputs=[
        _coord(["developer"]),
        _qs(_q(prompt="What colour?", qtype="free_text", options=[])),
    ])
    svc1 = _persistent_service(
        store, _FakeGitHub(body="vague"), runner1, _FakeGit()
    )
    wid = await svc1.create("o/r", 5)
    await _wait(
        lambda: svc1.get(wid).status
        == "awaiting_refine_input"
    )
    # Force a mid-step snapshot into the store.
    run = svc1.get(wid)
    run.status = "refining"
    store.save(run)

    svc2 = _persistent_service(
        store, _FakeGitHub(body="vague"),
        _FakeRunner(SessionRegistry(), outputs=[]),
        _FakeGit(),
    )
    await svc2.recover()
    recovered = svc2.get(wid)
    assert recovered.status == "failed"
    assert "restarted" in (recovered.error or "")
    persisted = {r.id: r for r in store.load_all()}[wid]
    assert persisted.status == "failed"


@pytest.mark.asyncio
async def test_recover_resumes_implement_blocker(
    tmp_path: Path,
) -> None:
    """Ensure a run parked mid-implementation-blocker survives restart."""
    store = _store(tmp_path)
    runner1 = _FakeRunner(SessionRegistry(), outputs=[
        "<PLAN>\nStep 1\n</PLAN>",
        "<QUESTIONS>"
        '{"questions": [{"id": "q1", "prompt": "Which file?", '
        '"type": "single_select", "required": true, '
        '"options": [{"value": "a", "label": "A"}]}]}'
        "</QUESTIONS>",
    ])
    git1 = _FakeGit()
    git1.diffs = [""]
    svc1 = _persistent_service(
        store,
        _FakeGitHub(body=_refined_body("x")),
        runner1,
        git1,
    )
    wid = await svc1.create("o/r", 5)
    await _wait(
        lambda: svc1.get(wid).status == "awaiting_plan_approval"
    )
    svc1.approve(wid)
    await _wait(
        lambda: svc1.get(wid).status == "awaiting_implement_input"
    )

    runner2 = _FakeRunner(SessionRegistry(), outputs=["Implemented"])
    git2 = _FakeGit()
    git2.diffs = ["diff --git a/x b/x"]
    svc2 = _persistent_service(
        store,
        _FakeGitHub(body=_refined_body("x")),
        runner2,
        git2,
    )
    await svc2.recover()
    assert svc2.get(wid).status == "awaiting_implement_input"

    svc2.submit_answers(wid, {"q1": "a"})
    await _wait(
        lambda: svc2.get(wid).status == "awaiting_implement_approval"
    )
    svc2.approve(wid)
    await _wait(lambda: svc2.get(wid).status == "done")
    assert git2.pushed == [svc2.get(wid).branch]
