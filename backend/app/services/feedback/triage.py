"""The feedback-triage turn (feature 013, US3/US4).

Runs once per dispatched feedback item that needs a re-entry decision
(review-origin feedback on an open PR this phase; terminal-run feedback
once US4 lands — see ``feedback/dispatch.py``'s routing table). Reads the
feedback body alongside the run's PRD/design deliverables and, when
available, the change's diffstat, and asks a single turn which step the
feedback actually concerns. Parsed via
:func:`app.services.workflow_text.extract_feedback_triage`, which already
defaults to ``"code"`` on a parse miss or an out-of-vocabulary step — this
module never needs a second fallback layer of its own.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.backends.base import TurnRequest
from app.models_workflow import WorkflowRun
from app.policy import get_policy
from app.services.workflow_text import extract_feedback_triage
from app.services.workflows.prompts_feedback import (
    DIFFSTAT_SECTION,
    FEEDBACK_TRIAGE_PROMPT,
)

if TYPE_CHECKING:
    from app.services.workflows import WorkflowService

#: Sub-step key for backend/model resolution (falls back to ``"verify"``'s
#: text-only capability requirement and model — triage is a judgment/
#: classification task, the same shape as a verify verdict turn).
_TRIAGE_SUBSTEP = "verify.triage"


async def triage_feedback(
    service: "WorkflowService",
    run: WorkflowRun,
    feedback_body: str,
    *,
    diffstat: str = "",
) -> dict[str, str]:
    """
    Run the triage turn and return its classified re-entry decision.

    :param service: The owning ``WorkflowService`` (backend/model
        resolution only — this turn is never chip-tracked; it is
        internal bookkeeping, not a step a human watches live).
    :param run: The run the feedback targets. Must already have a live
        ``run.workspace`` (the caller, ``driver/resume.py``, restores it
        before calling this) — the PRD/design come from ``run.steps``,
        but the backend itself still needs a real ``cwd``.
    :param feedback_body: The raw (marker/author already gated upstream)
        feedback text.
    :param diffstat: The change's diffstat, when available (review-origin
        feedback on an open PR); omitted for feedback with no PR context.
    :returns: ``{"step", "reason", "instruction"}`` — see
        :func:`app.services.workflow_text.extract_feedback_triage`.
    """
    model = get_policy().model_for(_TRIAGE_SUBSTEP)
    backend = service.backends.backend_for(_TRIAGE_SUBSTEP)
    prompt = FEEDBACK_TRIAGE_PROMPT.format(
        feedback=feedback_body,
        prd=run.steps[0].deliverable or "",
        design=run.steps[1].deliverable or "",
        diffstat_section=(
            DIFFSTAT_SECTION.format(diffstat=diffstat) if diffstat else ""
        ),
    )
    result = await backend.run_turn(
        TurnRequest(
            prompt=prompt, cwd=run.workspace, permission_mode="plan",
            model=model,
        )
    )
    return extract_feedback_triage(result.final_text)
