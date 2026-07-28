"""Runs one stateless refine sub-agent turn, tracking its own session."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.backends.base import TurnRequest
from app.models_workflow import StepSession, WorkflowRun
from app.policy import get_policy

if TYPE_CHECKING:
    from app.services.workflows import WorkflowService


async def run_refine_agent(
    service: "WorkflowService",
    run: WorkflowRun,
    prompt: str,
    slot: StepSession,
    substep: str = "refine",
) -> str:
    """Run one stateless refine sub-agent, tracking its own session.

    Each call is a fresh (non-resumed) read-only session. It fills in
    its own *slot* — so concurrent generators never race on a single
    shared field — and marks it idle when done; ``step.session_id``
    still tracks the latest for back-compat.

    *substep* is a dotted policy key (e.g. ``"refine.reconcile"``) so
    a deployment can route just one sub-agent — most usefully the
    reconciler — to a stronger backend/model; it falls back to the
    ``refine`` step's backend and model when unconfigured.
    """
    step = run.steps[0]

    def _bind(s: str) -> None:
        slot.session_id = s
        step.session_id = s

    backend = service.backends.backend_for(substep)
    result = await service._run_turn_tracked(
        run,
        backend,
        TurnRequest(
            prompt=prompt, cwd=run.workspace,
            permission_mode="plan",
            model=get_policy().model_for(substep),
        ),
        slot,
        _bind,
    )
    slot.status = "idle"
    return result.final_text
