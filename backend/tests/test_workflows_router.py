"""Tests for the workflows router (service mocked)."""
from __future__ import annotations

import httpx
import pytest

from app.main import create_app
from app.models_workflow import WorkflowRun, WorkflowStep
from app.services.exceptions import (
    InvalidWorkflowStateError,
    WorkflowNotFoundError,
)
from app.services.workflows import get_workflow_service


class _FakeService:
    def __init__(self) -> None:
        self.approved: list[str] = []

    async def create(self, repo: str, issue_number: int) -> str:
        return "wf-1"

    def list(self):
        return [WorkflowRun(id="wf-1", repo="o/r", issue_number=3,
                            status="planning")]

    def get(self, workflow_id: str) -> WorkflowRun:
        if workflow_id != "wf-1":
            raise WorkflowNotFoundError(workflow_id)
        return WorkflowRun(
            id="wf-1", repo="o/r", issue_number=3, issue_title="T",
            status="awaiting_plan_approval",
            steps=[WorkflowStep("refine", "s0", "done", "refined"),
                   WorkflowStep("plan", "s1", "awaiting_approval", "the plan"),
                   WorkflowStep("implement")],
        )

    def current_session_id(self, run) -> str:
        return "s1"

    def approve(self, workflow_id: str, deliverable=None) -> None:
        if workflow_id != "wf-1":
            raise WorkflowNotFoundError(workflow_id)
        self.approved.append(workflow_id)

    def reject(self, workflow_id: str) -> None: ...

    def reply(self, workflow_id: str, text: str) -> None:
        raise InvalidWorkflowStateError("not awaiting a refine reply")


def _client(service):
    app = create_app()
    app.dependency_overrides[get_workflow_service] = lambda: service
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.mark.asyncio
async def test_create_returns_id() -> None:
    """Ensure POST /api/workflows returns a workflow id."""
    async with _client(_FakeService()) as c:
        r = await c.post("/api/workflows", json={"repo": "o/r", "issue_number": 3})
    assert r.status_code == 200
    assert r.json()["workflow_id"] == "wf-1"


@pytest.mark.asyncio
async def test_detail_exposes_steps_and_current_session() -> None:
    """Ensure GET detail returns steps, deliverables, and current session."""
    async with _client(_FakeService()) as c:
        r = await c.get("/api/workflows/wf-1")
    body = r.json()
    assert r.status_code == 200
    assert body["current_session_id"] == "s1"
    assert body["steps"][1]["deliverable"] == "the plan"


@pytest.mark.asyncio
async def test_detail_unknown_returns_404() -> None:
    """Ensure an unknown workflow id maps to 404."""
    async with _client(_FakeService()) as c:
        r = await c.get("/api/workflows/nope")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_approve_ok_and_reply_conflict() -> None:
    """Ensure approve returns 200 and a bad reply maps to 409."""
    svc = _FakeService()
    async with _client(svc) as c:
        ok = await c.post("/api/workflows/wf-1/approve", json={})
        conflict = await c.post("/api/workflows/wf-1/reply", json={"text": "x"})
    assert ok.status_code == 200
    assert svc.approved == ["wf-1"]
    assert conflict.status_code == 409
