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
    _coord,
    _FakeGit,
    _FakeGitHub,
    _FakeRunner,
    _q,
    _qs,
    _refined,
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
async def test_recover_resumes_awaiting_refine_approval(
    tmp_path: Path,
) -> None:
    """Ensure a run parked at the PRD-approval gate survives restart, then
    runs the autonomous design/code/verify loop to a PR."""
    store = _store(tmp_path)
    runner1 = _FakeRunner(SessionRegistry(), outputs=[
        _coord([]), _refined("refined issue"),
    ])
    svc1 = _persistent_service(
        store, _FakeGitHub(body="vague issue"), runner1, _FakeGit(),
    )
    wid = await svc1.create("o/r", 5)
    await _wait(
        lambda: svc1.get(wid).status == "awaiting_refine_approval"
    )

    runner2 = _FakeRunner(SessionRegistry(), outputs=[
        "<PLAN>\nDo it\n</PLAN>",                                  # design
        "Implemented",                                            # code
        '<VERDICT>{"accept": true, "feedback": ""}</VERDICT>',    # verify
    ])
    git2 = _FakeGit()
    svc2 = _persistent_service(
        store, _FakeGitHub(body="vague issue"), runner2, git2,
    )
    await svc2.recover()
    assert svc2.get(wid).status == "awaiting_refine_approval"

    svc2.approve(wid)  # PRD approved → autonomous loop
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


# NOTE: the mid-implementation blocker gate (awaiting_implement_input) was
# removed by the feature-003 reshape — design/code/verify are transient and
# fail loudly on restart (they are in _TRANSIENT), covered by
# test_recover_fails_mid_step_runs above and the US5 recovery tests.


class _CountingNotifier:
    """Records every notify() call, to prove recovery does not re-notify."""

    def __init__(self) -> None:
        self.statuses: list[str] = []

    def notify(self, run) -> None:
        self.statuses.append(run.status)


@pytest.mark.asyncio
async def test_recovery_does_not_renotify_gate(tmp_path: Path) -> None:
    """Ensure recovering an awaiting_* run posts no fresh notification.

    Pins research R-07 / FR-030: recovered gates re-park without _save(),
    so the notifier (and thus the GitHub gate comment) never re-fires.
    """
    import asyncio

    from app.config import Settings
    from app.services.workflows import WorkflowService
    from app.storage.workflow_registry import WorkflowRegistry

    store = _store(tmp_path)
    runner1 = _FakeRunner(SessionRegistry(), outputs=[
        _coord(["developer"]),
        _qs(_q(prompt="What colour?", qtype="free_text", options=[])),
    ])
    svc1 = _persistent_service(
        store, _FakeGitHub(body="vague"), runner1, _FakeGit()
    )
    wid = await svc1.create("o/r", 5)
    await _wait(lambda: svc1.get(wid).status == "awaiting_refine_input")

    # --- simulated restart with a counting notifier ---
    reg = WorkflowRegistry(store=store)
    reg.preload(store.load_all())
    counter = _CountingNotifier()
    svc2 = WorkflowService(
        settings=Settings(git_base="https://github.com", github_token="t"),
        sessions=_FakeRunner(SessionRegistry(), outputs=[]).sessions,
        workflows=reg,
        backends=_FakeRunner(SessionRegistry(), outputs=[]),
        git=_FakeGit(),
        github=_FakeGitHub(body="vague"),
        notifier=counter,
    )
    await svc2.recover()
    await asyncio.sleep(0.05)

    assert svc2.get(wid).status == "awaiting_refine_input"
    assert counter.statuses == []
