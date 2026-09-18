"""Ensure the driver uploads/persists screenshots at the right points."""

from __future__ import annotations

import pytest

from app.services.workflows import screenshots
from app.storage.registry import SessionRegistry
from tests.conftest import (
    _approve_prd,
    _FakeGit,
    _FakeGitHub,
    _FakeRunner,
    _refine_noquestions,
    _service,
    _subtask_body,
    _verdict,
    _wait,
)


@pytest.mark.asyncio
async def test_refine_screenshots_uploaded_at_prd_approval(
    monkeypatch,
) -> None:
    """Refine mockups are uploaded at PRD approval time (inside refine()
    itself, before technical_analysis runs).

    A plain ticket parks for decomposition approval after technical_analysis
    (FR-014) — it never reaches deliver(), so this only exercises the
    refine-stage upload; the verify-stage one is covered by the
    autonomous-design/code/verify test below.
    """
    uploads: list[str] = []

    async def _fake_upload(_source, _run, _root, stage) -> None:
        uploads.append(stage)

    monkeypatch.setattr(screenshots, "upload_screenshots", _fake_upload)

    gh, git = _FakeGitHub(body="vague issue"), _FakeGit()
    runner = _FakeRunner(
        SessionRegistry(),
        outputs=[
            "<UNDERSTANDING>Build a clear widget.</UNDERSTANDING>",
            *_refine_noquestions("Build a clear widget"),
            "<TECH_ANALYSIS>analysis</TECH_ANALYSIS>",  # technical_analysis
            '<CONTAINMENT>{"verdicts": []}</CONTAINMENT>',  # critic
        ],
    )
    svc = _service(gh, runner, git)

    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "awaiting_describe_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(
        lambda: svc.get(wid).status == "awaiting_decomposition_approval"
    )
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "decomposed")

    assert uploads == ["refine"]


@pytest.mark.asyncio
async def test_verify_screenshots_uploaded_and_persisted(monkeypatch) -> None:
    """Verify shots are uploaded at deliver() time and screenshots are
    persisted before the worktree is torn down.

    A follow-up (SUBTASK_SENTINEL) body skips describe/refine/
    technical_analysis entirely (FR-015) — the only way to reach deliver() at
    all now that a plain ticket's run always ends at technical_analysis
    instead (FR-014).
    """
    uploads: list[str] = []
    persisted: list[str] = []

    async def _fake_upload(_source, _run, _root, stage) -> None:
        uploads.append(stage)

    def _fake_persist(run, _root) -> None:
        persisted.append(run.id)

    monkeypatch.setattr(screenshots, "upload_screenshots", _fake_upload)
    monkeypatch.setattr(screenshots, "persist_screenshots", _fake_persist)

    gh = _FakeGitHub(body=_subtask_body("Build a clear widget"))
    git = _FakeGit()
    runner = _FakeRunner(
        SessionRegistry(),
        outputs=[
            "<PLAN>\nStep 1: do X\n</PLAN>",
            "Implemented X",
            _verdict(accept=True),
        ],
    )
    svc = _service(gh, runner, git)

    wid = await svc.create("o/r", 5, source="github-issue")
    await _approve_prd(svc, wid)
    await _wait(lambda: svc.get(wid).status == "done")

    # The sentinel-seeded PRD still passes the approval gate, so its refine
    # mockups upload before verify's delivery-time upload.
    assert uploads == ["refine", "verify"]
    # Screenshots preserved before the worktree is torn down.
    assert wid in persisted
