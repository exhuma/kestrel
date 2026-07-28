"""Optional static-mockup screenshot capture during the refine stage.

Structured like verify's optional explore turn, but gated on backend
*capability* rather than ``run.boundary``: a refine backend that can edit
files and drive a browser (claude, opencode) produces static HTML/CSS
mockups of the PRD's screens and screenshots them for the approval gate;
a text-only refine backend silently skips (mirroring how the verify
explore turn degrades when browser tooling is absent).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.backends.base import Capability, TurnRequest
from app.models_workflow import Step, StepSession, WorkflowRun
from app.policy import get_policy
from app.services.workflows import screenshots
from app.services.workflows.prompts import (
    EXPLORE_PERMISSION_MODE,
    MOCKUP_PROMPT,
)
from app.services.workflows.sessions import _bind

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.services.workflows import WorkflowService

#: Extra capabilities a backend needs to mock up and screenshot the PRD.
_MOCKUP_CAPS = frozenset({Capability.FILE_EDITS, Capability.TOOL_USE})


async def capture_mockups(
    service: "WorkflowService", run: WorkflowRun, prd: str
) -> None:
    """Best-effort: mock up the PRD's screens and screenshot them.

    Runs one tracked turn on the refine backend when it can serve
    ``FILE_EDITS``+``TOOL_USE`` (honouring an optional ``refine.mockup``
    sub-step backend), else returns immediately. Never fails the run.
    """
    backend = service.backends.optional_backend_for(
        "refine.mockup", _MOCKUP_CAPS
    )
    if backend is None:
        return
    step = run.steps[0]
    slot = StepSession(profile_id="mockup", label="Mockups", badge="agent")
    step.active_sessions = [slot]
    service._save(run)
    prompt = MOCKUP_PROMPT.format(
        prd=prd, screenshots_dir=screenshots.stage_reldir(run, "refine")
    )
    service._debug_log(run, "REFINE — MOCKUP PROMPT", prompt)
    result = await service._run_turn_tracked(
        run,
        backend,
        TurnRequest(
            prompt=prompt,
            cwd=run.workspace,
            permission_mode=EXPLORE_PERMISSION_MODE,
            model=get_policy().model_for(Step.REFINE),
        ),
        slot,
        _bind(step, slot),
    )
    service._debug_log(run, "REFINE — MOCKUP RESULT", result.final_text)
