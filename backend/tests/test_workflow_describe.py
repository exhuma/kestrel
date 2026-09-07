"""Tests for the describe step: the understanding-checkpoint gate
(feature 012, spec.md User Story 1)."""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.persistence.workflow_store import WorkflowStore
from app.storage.registry import SessionRegistry
from tests.conftest import (
    _FakeDismissals,
    _FakeGit,
    _FakeGitHub,
    _FakeRunner,
    _refine_noquestions,
    _service,
    _wait,
)
from tests.test_workflow_persistence import _migrate, _persistent_service


async def _create_and_park(svc, repo: str = "o/r", issue: int = 5) -> str:
    """Create a run and wait for it to park at the describe gate — the
    common opening beat of every describe-gate test below."""
    wid = await svc.create(repo, issue, source="github-issue")
    await _wait(
        lambda: svc.get(wid).status == "awaiting_describe_approval"
    )
    return wid


async def _park_persistent(
    tmp_path: Path, db_name: str, understanding: str = "v1"
):
    """Migrate a fresh store, run one designer turn, and park a
    store-backed run at the describe gate — the shared setup for both
    recovery tests below."""
    url = _migrate(tmp_path / db_name)
    store = WorkflowStore(sessionmaker(bind=create_engine(url)))
    runner1 = _FakeRunner(
        SessionRegistry(),
        outputs=[f"<UNDERSTANDING>{understanding}</UNDERSTANDING>"],
    )
    svc1 = _persistent_service(
        store, _FakeGitHub(body="vague"), runner1, _FakeGit()
    )
    wid = await _create_and_park(svc1)
    return store, svc1, wid


@pytest.mark.asyncio
async def test_fresh_run_parks_at_describe_before_any_question() -> None:
    """Ensure a fresh run restates its understanding and parks for
    confirmation before refine ever asks a clarifying question."""
    runner = _FakeRunner(
        SessionRegistry(),
        outputs=["<UNDERSTANDING>Add a widget to the page.</UNDERSTANDING>"],
    )
    svc = _service(_FakeGitHub(body="Add a widget"), runner, _FakeGit())

    wid = await _create_and_park(svc)

    run = svc.get(wid)
    assert run.steps[0].name == "describe"
    assert run.steps[0].deliverable == "Add a widget to the page."
    # Refine has not started — no interview question was asked yet.
    assert run.steps[1].status == "pending"
    assert len(runner.calls) == 1


@pytest.mark.asyncio
async def test_approving_understanding_advances_into_refining() -> None:
    """Ensure approving the restatement proceeds into the refine step."""
    runner = _FakeRunner(
        SessionRegistry(),
        outputs=[
            "<UNDERSTANDING>Add a widget.</UNDERSTANDING>",
            *_refine_noquestions("refined issue"),
        ],
    )
    svc = _service(_FakeGitHub(body="Add a widget"), runner, _FakeGit())

    wid = await _create_and_park(svc)
    svc.approve(wid)

    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    assert svc.get(wid).steps[0].status == "done"


@pytest.mark.asyncio
async def test_reject_with_feedback_revises_and_reparks() -> None:
    """Ensure a correction produces a revised restatement and re-parks
    for confirmation again, without touching refine."""
    runner = _FakeRunner(
        SessionRegistry(),
        outputs=[
            "<UNDERSTANDING>v1</UNDERSTANDING>",
            "<UNDERSTANDING>v2 with correction</UNDERSTANDING>",
        ],
    )
    svc = _service(_FakeGitHub(body="vague ask"), runner, _FakeGit())

    wid = await _create_and_park(svc)
    svc.reject(wid, refinement_prompt="Actually it's about the sidebar")

    await _wait(
        lambda: svc.get(wid).steps[0].deliverable == "v2 with correction"
    )
    assert svc.get(wid).status == "awaiting_describe_approval"
    assert svc.get(wid).steps[1].status == "pending"
    assert "Actually it's about the sidebar" in runner.calls[-1]["prompt"]
    assert "v1" in runner.calls[-1]["prompt"]


@pytest.mark.asyncio
async def test_reject_without_feedback_ends_rejected_with_dismissal() -> None:
    """Ensure an unqualified rejection ends the run rejected and records
    a dismissal, the same shape as refine's own no-feedback rejection."""
    dismissals = _FakeDismissals()
    runner = _FakeRunner(
        SessionRegistry(), outputs=["<UNDERSTANDING>v1</UNDERSTANDING>"]
    )
    svc = _service(_FakeGitHub(body="vague ask"), runner, _FakeGit())
    svc.dismissals = dismissals

    wid = await _create_and_park(svc)
    svc.reject(wid)

    await _wait(lambda: svc.get(wid).status == "rejected")
    assert dismissals.is_dismissed("o/r#5")


@pytest.mark.asyncio
async def test_recover_fails_mid_describing(tmp_path: Path) -> None:
    """Ensure a run that died mid-'describing' fails loudly on restart."""
    store, svc1, wid = await _park_persistent(tmp_path, "describe.db")
    # Force a mid-step snapshot, as if the process died before parking.
    run = svc1.get(wid)
    run.status = "describing"
    store.save(run)

    svc2 = _persistent_service(
        store, _FakeGitHub(body="vague"),
        _FakeRunner(SessionRegistry(), outputs=[]), _FakeGit(),
    )
    await svc2.recover()

    recovered = svc2.get(wid)
    assert recovered.status == "failed"
    assert "restarted" in (recovered.error or "")


@pytest.mark.asyncio
async def test_recover_reparks_at_describe_approval_no_new_turn(
    tmp_path: Path,
) -> None:
    """Ensure a run parked at the describe gate survives a restart
    without re-running the restatement turn."""
    store, _svc1, wid = await _park_persistent(tmp_path, "describe2.db")

    # --- simulated restart: fresh registry/service/fakes, no more
    # canned outputs — a re-run of the restatement turn would crash on
    # an empty outputs list (IndexError from _FakeRunner.run_turn).
    svc2 = _persistent_service(
        store, _FakeGitHub(body="vague"),
        _FakeRunner(SessionRegistry(), outputs=[]), _FakeGit(),
    )
    await svc2.recover()

    assert svc2.get(wid).status == "awaiting_describe_approval"
    assert svc2.get(wid).steps[0].deliverable == "v1"
