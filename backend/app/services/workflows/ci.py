"""Required-CI state transitions and bounded repair dispatch."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.ports import RequiredCiStatus
from app.services.workflows.driver import deliver
from app.services.workflows.driver.branch_resume import (
    _provision_existing_branch,
)
from app.services.workflows.driver.code_verify import code_and_verify

if TYPE_CHECKING:
    from app.models_workflow import WorkflowRun
    from app.services.workflows import WorkflowService


async def inspect_required_ci(
    service: "WorkflowService", run: "WorkflowRun"
) -> None:
    """Advance a waiting run after its configured CI checks settle."""
    names = service.required_ci_statuses(run)
    if not names or run.pr_number is None:
        return
    statuses = await service._code_host(run).required_ci_statuses(
        run.repo, run.pr_number, names
    )
    if any(status.state == "pending" for status in statuses):
        return
    if all(status.state == "passed" for status in statuses):
        run.status = "technically_ready"
        service._save(run)
        return
    if run.ci_repair_round >= service.settings.max_ci_repair_iterations:
        run.status = "escalated"
        run.error = "required CI failed after the repair budget was exhausted"
        service._save(run)
        return
    run.ci_repair_round += 1
    run.status = "repairing_ci"
    service._save(run)
    await _provision_existing_branch(service, run)
    feedback = _failure_feedback(statuses)
    escalated = await code_and_verify(service, run, initial_feedback=feedback)
    if not escalated:
        await deliver(service, run)


def _failure_feedback(statuses: list[RequiredCiStatus]) -> str:
    """Render a concise repair instruction from failed provider statuses."""
    failed = [status for status in statuses if status.state == "failed"]
    return "Required CI failed:\n" + "\n".join(
        f"- {status.name}: {status.detail or 'no provider detail'}"
        for status in failed
    )
