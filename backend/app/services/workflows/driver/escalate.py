"""Escalation: stop the autonomous loop and flag a run for a human."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.models_workflow import WorkflowRun

if TYPE_CHECKING:
    from app.services.workflows import WorkflowService


def fail_active_steps(service: "WorkflowService", run: WorkflowRun) -> None:
    """Flip any in-flight step to a terminal ``failed`` state.

    A terminal run status (``escalated``/``failed``) must not leave a step
    still ``running`` (or parked on a gate): the UI keys its activity
    indicators off step status, so a stranded ``running`` step spins
    forever. Retires the live session chips into round history too.
    """
    for step in run.steps:
        if step.status in ("running", "awaiting_input", "awaiting_approval"):
            step.status = "failed"
            service._retire_sessions(run, step)


async def escalate(
    service: "WorkflowService", run: WorkflowRun, reason: str
) -> bool:
    """Stop the autonomous loop and flag the ticket for human attention.

    :returns: ``True`` (so the caller skips delivery).
    """
    run.error = f"escalated: {reason}"
    run.status = "escalated"
    fail_active_steps(service, run)
    service._save(run)
    await service._teardown_workspace(run)
    return True
