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
        "What colour?",
    ])
    svc1 = _persistent_service(
        store, _FakeGitHub(body="vague"), runner1, _FakeGit()
    )
    wid = await svc1.create("o/r", 5)
    await _wait(
        lambda: svc1.get(wid).status
        == "awaiting_refine_input"
    )
    old_sid = svc1.get(wid).steps[0].session_id

    # --- simulated restart: fresh registry/service/fakes ---
    runner2 = _FakeRunner(SessionRegistry(), outputs=[
        "<REFINED_ISSUE>\nBuild a blue widget\n"
        "</REFINED_ISSUE>",
    ])
    svc2 = _persistent_service(
        store, _FakeGitHub(body="vague"), runner2, _FakeGit()
    )
    await svc2.recover()

    run = svc2.get(wid)
    assert run.status == "awaiting_refine_input"

    svc2.reply(wid, "Blue, please")
    await _wait(
        lambda: svc2.get(wid).status
        == "awaiting_refine_approval"
    )
    # The reply resumed the ORIGINAL claude session.
    assert runner2.calls[0]["resume_id"] == old_sid
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
        _FakeGitHub(body="x\n\n<!-- kestrel:refined -->"),
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
        _FakeGitHub(body="x\n\n<!-- kestrel:refined -->"),
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
        "What colour?",
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
