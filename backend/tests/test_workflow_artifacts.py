"""Tests for workflow artifact storage and delivery."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from app.backends.base import Capability
from app.models_workflow import Step, WorkflowRun, WorkflowStep
from app.storage.registry import SessionRegistry
from tests.conftest import (
    _artifact_service,
    _FakeGit,
    _FakeGitHub,
    _FakeRunner,
    _RoutingPolicy,
    _service,
    _settings,
)


@pytest.mark.asyncio
async def test_ensure_artifact_dir_picks_next_free_serial(tmp_path) -> None:
    """The run's artifact folder is the next free serial for today's date."""
    svc = _service(
        _FakeGitHub(),
        _FakeRunner(SessionRegistry(), outputs=[]),
        _FakeGit(),
        settings=_settings(workspace_root=str(tmp_path)),
    )
    workspace = tmp_path / "wf-1"
    workspace.mkdir()
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (workspace / ".kestrel" / f"{date}-001").mkdir(parents=True)
    run = WorkflowRun(id="wf-1", repo="o/r", workspace=str(workspace))
    svc.workflows.create(run)

    svc._ensure_artifact_dir(run)

    expected = os.path.join(".kestrel", f"{date}-002")
    assert run.artifact_dir == expected
    assert (workspace / run.artifact_dir).is_dir()
    svc._ensure_artifact_dir(run)
    assert run.artifact_dir == expected


@pytest.mark.asyncio
async def test_write_artifact_persists_file(tmp_path) -> None:
    """Writing an artifact creates it inside the run's artifact folder."""
    svc = _service(
        _FakeGitHub(),
        _FakeRunner(SessionRegistry(), outputs=[]),
        _FakeGit(),
        settings=_settings(workspace_root=str(tmp_path)),
    )
    workspace = tmp_path / "wf-2"
    workspace.mkdir()
    run = WorkflowRun(id="wf-2", repo="o/r", workspace=str(workspace))
    svc.workflows.create(run)

    svc._write_artifact(run, "prd.md", "PRD BODY")

    assert (workspace / run.artifact_dir / "prd.md").read_text() == "PRD BODY"


@pytest.mark.asyncio
async def test_artifact_slot_refs_file_or_inlines_by_capability(
    tmp_path,
) -> None:
    """File-capable steps receive references; text-only steps receive text."""
    sessions = SessionRegistry()
    design = _FakeRunner(sessions, outputs=[])
    design.caps = frozenset({Capability.TEXT})
    svc = _artifact_service(
        tmp_path,
        _RoutingPolicy(sessions, design, _FakeRunner(sessions, outputs=[])),
    )
    workspace = tmp_path / "wf-3"
    workspace.mkdir()
    run = WorkflowRun(id="wf-3", repo="o/r", workspace=str(workspace))
    svc.workflows.create(run)
    svc._ensure_artifact_dir(run)

    text_slot = svc._artifact_slot("design", run, "prd.md", "FULL PRD TEXT")
    file_slot = svc._artifact_slot("code", run, "prd.md", "FULL PRD TEXT")

    assert text_slot == "FULL PRD TEXT"
    assert "prd.md" in file_slot
    assert "FULL PRD TEXT" not in file_slot


def _delivery_run(workspace: str) -> WorkflowRun:
    """Build a minimal verified run ready to invoke delivery directly."""
    return WorkflowRun(
        id="wf-deliver",
        repo="o/r",
        issue_number=5,
        issue_title="Add widget",
        task_ref="o/r#5",
        base_branch="main",
        branch="kestrel/issue-5",
        workspace=workspace,
        steps=[WorkflowStep(name=step) for step in Step.sequence()],
    )


@pytest.mark.asyncio
async def test_deliver_commits_when_tree_is_dirty(tmp_path) -> None:
    """Delivery commits a dirty working tree before pushing it."""
    github, git = _FakeGitHub(body="x"), _FakeGit()
    git.mark_dirty("diff --git a/z b/z")
    svc = _service(github, _FakeRunner(SessionRegistry(), []), git)
    run = _delivery_run(str(tmp_path))
    svc.workflows.create(run)

    await svc._deliver(run)

    assert git.commit_messages == ["Implement #5"]
    assert git.pushed == [run.branch]
    assert run.status == "done"


@pytest.mark.asyncio
async def test_deliver_skips_commit_when_tree_is_clean(tmp_path) -> None:
    """Delivery pushes a clean tree without issuing an empty commit."""
    github, git = _FakeGitHub(body="x"), _FakeGit()
    svc = _service(github, _FakeRunner(SessionRegistry(), []), git)
    run = _delivery_run(str(tmp_path))
    svc.workflows.create(run)

    await svc._deliver(run)

    assert git.commit_messages == []
    assert git.pushed == [run.branch]
    assert run.status == "done"
