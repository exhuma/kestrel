"""Tests for design handover artifacts and prompt inputs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.backends.base import Capability
from app.models_workflow import WorkflowRun, WorkflowStep
from app.persistence.tables import FeedbackItemRow
from app.services.workflows.driver import continue_run
from app.storage.registry import SessionRegistry
from tests.conftest import (
    _artifact_service,
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
async def test_design_writes_structured_contract_artifacts(tmp_path) -> None:
    """A structured response persists all versioned handover contracts."""
    contract = json.dumps(
        {
            "version": 1,
            "plan": "Add a widget.",
            "boundary": "none",
            "acceptance": [
                {
                    "id": "AC-1",
                    "parent_prd": "FR-1",
                    "description": "Works.",
                    "disposition": "automated",
                    "rationale": "Covered by a test.",
                }
            ],
            "tasks": [
                {"id": "TASK-1", "title": "Add widget", "prerequisites": []}
            ],
            "checks": [
                {
                    "command": "true",
                    "cwd": ".",
                    "timeout_seconds": 60,
                    "rationale": "Runs backend tests.",
                }
            ],
        }
    )
    runner = _FakeRunner(
        SessionRegistry(),
        outputs=[
            f"<DESIGN_CONTRACT>{contract}</DESIGN_CONTRACT>",
            "Implemented",
            _verdict(accept=True),
        ],
    )
    svc = _service(
        _FakeGitHub(body=_subtask_body("Build a widget")),
        runner,
        _FakeGit(),
        settings=_settings(workspace_root=str(tmp_path), workflow_debug=True),
    )
    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")
    artifact_dir = Path(svc.get(wid).workspace, svc.get(wid).artifact_dir)
    assert "AC-1" in (artifact_dir / "acceptance.md").read_text()
    task_graph = json.loads((artifact_dir / "task-graph.json").read_text())
    checks = json.loads((artifact_dir / "check-contract.json").read_text())
    assert task_graph["version"] == 1
    assert checks["commands"]


@pytest.mark.asyncio
async def test_text_only_design_backend_inlines_the_prd(tmp_path) -> None:
    """A text-only design backend receives an inline PRD rather than a path."""
    gh = _FakeGitHub(body=_subtask_body("UNIQUE-PRD-MARKER body"))
    sessions = SessionRegistry()
    design_backend = _FakeRunner(
        sessions, outputs=["<PLAN>the plan</PLAN>"], id_prefix="llm-"
    )
    design_backend.caps = frozenset({Capability.TEXT})
    code = _FakeRunner(
        sessions,
        outputs=["Implemented X", _verdict(accept=True)],
        id_prefix="ses-",
    )
    policy = _RoutingPolicy(sessions, design_backend, code)
    svc = _artifact_service(tmp_path, policy, gh)

    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")

    assert "UNIQUE-PRD-MARKER" in design_backend.calls[0]["prompt"]


@pytest.mark.asyncio
async def test_drained_feedback_folds_into_the_design_prompt(tmp_path) -> None:
    """Queued feedback is applied at the pre-design boundary."""
    store = _FakeFeedbackStore()
    runner = _FakeRunner(
        SessionRegistry(),
        outputs=[
            "<PLAN>\nStep 1\n</PLAN>",
            "Implemented",
            _verdict(accept=True),
        ],
    )
    svc = _service(
        _FakeGitHub(body="vague issue"),
        runner,
        _FakeGit(),
        settings=_settings(workspace_root=str(tmp_path)),
        feedback_store=store,
    )
    run = WorkflowRun(
        id="wf-1",
        repo="o/r",
        issue_number=5,
        task_ref="o/r#5",
        base_branch="main",
        branch="kestrel/5",
        workspace=str(tmp_path),
        status="refining",
        prd_approved=True,
        steps=[
            WorkflowStep(name="describe", status="done", deliverable="U"),
            WorkflowStep(name="refine", status="done", deliverable="PRD"),
            WorkflowStep(
                name="technical_analysis", status="done", deliverable=""
            ),
            WorkflowStep(name="design", status="pending"),
            WorkflowStep(name="code", status="pending"),
            WorkflowStep(name="verify", status="pending"),
        ],
    )
    svc.workflows.create(run)
    store.claim(
        FeedbackItemRow(
            external_id="fb-1",
            workflow_id="wf-1",
            task_ref="o/r#5",
            origin="ticket",
            author="octocat",
            body="Please also update the README",
            state="queued",
            created_at=datetime.now(timezone.utc),
        )
    )

    await continue_run(svc, run)
    await _wait(lambda: svc.get("wf-1").status == "done")

    design_call = next(
        call for call in runner.calls if "high-level design" in call["prompt"]
    )
    assert "Please also update the README" in design_call["prompt"]
    assert store.items["fb-1"].state == "applied"
