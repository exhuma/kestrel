"""Tests for workflow domain exceptions."""
from __future__ import annotations

from app.services.exceptions import (
    InvalidWorkflowStateError,
    WorkflowNotFoundError,
)


def test_workflow_not_found_carries_id() -> None:
    """Ensure WorkflowNotFoundError records the missing id."""
    exc = WorkflowNotFoundError("wf-1")
    assert exc.workflow_id == "wf-1"


def test_invalid_state_carries_detail() -> None:
    """Ensure InvalidWorkflowStateError records a human detail."""
    exc = InvalidWorkflowStateError("not awaiting approval")
    assert "awaiting" in str(exc)
