"""Thin refine/PRD notifications carry no content (feature 003, US2/FR-029)."""
from __future__ import annotations

import asyncio

import pytest

from app.models_workflow import WorkflowRun, WorkflowStep
from app.notifications import TaskSourceNotifier, render_message


def _run(status: str) -> WorkflowRun:
    """A run whose refine step holds sensitive PRD/question content."""
    return WorkflowRun(
        id="wf-1", repo="team/svc", issue_number=None, status=status,
        source="jira-issue", task_ref="RFC-1",
        steps=[WorkflowStep(
            name="refine", status="awaiting_approval",
            deliverable="SECRET PRD BODY with confidential design details",
        )],
    )


def test_render_message_is_thin_for_refine_gates() -> None:
    """Ensure the rendered message never contains deliverable content."""
    for status in ("awaiting_refine_input", "awaiting_refine_approval"):
        msg = render_message(_run(status))
        assert "SECRET PRD BODY" not in msg
        assert "RFC-1" in msg
    assert "input" in render_message(_run("awaiting_refine_input")).lower()
    assert "PRD" in render_message(_run("awaiting_refine_approval"))


class _FakeSource:
    def __init__(self) -> None:
        self.comments: list[tuple[str, str]] = []

    async def post_comment(self, ref, body):
        self.comments.append((ref, body))
        return "url"


@pytest.mark.asyncio
async def test_refine_gate_comment_is_deep_link_only() -> None:
    """Ensure the posted comment carries only status + deep-link, no content."""
    src = _FakeSource()
    TaskSourceNotifier({"jira-issue": src}, "https://k.example").notify(
        _run("awaiting_refine_input")
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert len(src.comments) == 1
    _, body = src.comments[0]
    assert "SECRET PRD BODY" not in body
    assert "https://k.example/?run=wf-1" in body
