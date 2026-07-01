"""Tests for the in-memory workflow registry."""
from __future__ import annotations

from app.models_workflow import WorkflowRun, WorkflowStep
from app.storage.workflow_registry import WorkflowRegistry


def test_create_get_list() -> None:
    """Ensure runs can be created, fetched, and listed."""
    reg = WorkflowRegistry()
    run = WorkflowRun(
        id="wf-1", repo="o/r", issue_number=3,
        steps=[WorkflowStep(name="refine")],
    )
    reg.create(run)
    assert reg.get("wf-1") is run
    assert reg.get("missing") is None
    assert [r.id for r in reg.list()] == ["wf-1"]
    assert reg.get("wf-1").steps[0].status == "pending"
