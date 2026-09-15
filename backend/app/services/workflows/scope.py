"""PRD-scope decisions for technical-analysis and child-task amendments."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.backends.base import TurnRequest
from app.policy import get_policy
from app.services.workflows.prompts import PRD_SCOPE_PROMPT

if TYPE_CHECKING:
    from app.models_workflow import WorkflowRun
    from app.services.workflows import WorkflowService

_SCOPE_TAG = "SCOPE"


@dataclass(frozen=True)
class ScopeDecision:
    """The fail-closed result of evaluating one requested technical change."""

    allowed: bool
    reason: str


def _parse_decision(text: str) -> ScopeDecision:
    """Parse a scope response, refusing malformed or inconclusive output."""
    start = text.find(f"<{_SCOPE_TAG}>")
    end = text.find(f"</{_SCOPE_TAG}>")
    if start < 0 or end < start:
        return ScopeDecision(False, "Kestrel could not validate this request.")
    raw = text[start + len(_SCOPE_TAG) + 2 : end]
    try:
        payload = json.loads(raw)
    except ValueError:
        return ScopeDecision(False, "Kestrel could not validate this request.")
    allowed = payload.get("allowed") if isinstance(payload, dict) else None
    reason = payload.get("reason") if isinstance(payload, dict) else None
    invalid = not isinstance(allowed, bool) or not isinstance(reason, str)
    if invalid or not reason:
        return ScopeDecision(False, "Kestrel could not validate this request.")
    return ScopeDecision(bool(allowed), reason)


async def evaluate_scope(
    service: "WorkflowService", run: "WorkflowRun", request: str
) -> ScopeDecision:
    """Evaluate ``request`` against ``run``'s immutable accepted PRD."""
    prd = run.approved_prd
    if not prd:
        return ScopeDecision(
            False, "No accepted PRD is available for this task."
        )
    backend = service.backends.backend_for("gap_analysis.scope")
    try:
        result = await backend.run_turn(
            TurnRequest(
                prompt=PRD_SCOPE_PROMPT.format(prd=prd, request=request),
                cwd=run.workspace,
                permission_mode="plan",
                model=get_policy().model_for("gap_analysis.scope"),
            )
        )
    except Exception:
        return ScopeDecision(False, "Kestrel could not validate this request.")
    return _parse_decision(result.final_text)


def refusal_message(decision: ScopeDecision) -> str:
    """Render the standard requester-visible explanation for a refusal."""
    return (
        "Kestrel cannot apply this technical change because it conflicts with "
        f"the accepted PRD: {decision.reason} Revise and approve the PRD first "
        "to expand or change the approved scope."
    )
