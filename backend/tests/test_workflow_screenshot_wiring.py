"""Ensure the driver uploads/persists screenshots at the right points."""
from __future__ import annotations

import pytest

from app.services.workflows import screenshots
from app.storage.registry import SessionRegistry
from tests.conftest import (
    _FakeGit,
    _FakeGitHub,
    _FakeRunner,
    _refine_noquestions,
    _service,
    _verdict,
    _wait,
)


@pytest.mark.asyncio
async def test_screenshots_uploaded_and_persisted(monkeypatch) -> None:
    """A full run uploads refine + verify shots and persists on teardown."""
    uploads: list[str] = []
    persisted: list[str] = []

    async def _fake_upload(_source, _run, _root, stage) -> None:
        uploads.append(stage)

    def _fake_persist(run, _root) -> None:
        persisted.append(run.id)

    monkeypatch.setattr(screenshots, "upload_screenshots", _fake_upload)
    monkeypatch.setattr(screenshots, "persist_screenshots", _fake_persist)

    gh, git = _FakeGitHub(body="vague issue"), _FakeGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("Build a clear widget"),
        "<PLAN>\nStep 1: do X\n</PLAN>",
        "Implemented X",
        _verdict(accept=True),
    ])
    svc = _service(gh, runner, git)

    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")

    # refine mockups uploaded at PRD approval; verify shots at deliver.
    assert uploads == ["refine", "verify"]
    # Screenshots preserved before the worktree is torn down.
    assert wid in persisted
