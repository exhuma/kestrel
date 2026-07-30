"""Optional UI-mockup capture during the ``uiux`` refine round.

When the coordinator summons the ``uiux`` profile, a ``FILE_EDITS``-capable
refine backend produces mockups — preferring the running project, else
static HTML/CSS — screenshots them into the run's ``screenshots/refine``
folder, and self-reports a per-file explanation in a ``<MOCKUPS>`` block.
The screenshots + captions are attached to that round's questionnaire so
the human sees them inline while answering. Gated on backend capability; a
text-only refine backend silently skips (the browser is the agent's own
runtime tool, self-reported when absent — like the verify explore turn).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.backends.base import Capability, TurnRequest
from app.models_workflow import Step, StepSession, WorkflowRun
from app.policy import get_policy
from app.questionnaire import Mockup, Questionnaire
from app.services.workflow_text import extract_mockups
from app.services.workflows import screenshots
from app.services.workflows.prompts import (
    EXPLORE_PERMISSION_MODE,
    MOCKUP_PROMPT,
)
from app.services.workflows.sessions import _bind

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.services.workflows import WorkflowService

#: Capability a backend needs to mock up and screenshot the UI (only
#: FILE_EDITS — the browser is the agent's own runtime tool, self-reported).
_MOCKUP_CAPS = frozenset({Capability.FILE_EDITS})


def _reconcile_mockups(
    run: WorkflowRun, parsed: list[dict[str, str]], root: str
) -> list[Mockup]:
    """Build Mockups from on-disk refine screenshots (the source of truth).

    Each screenshot file becomes a Mockup carrying the agent's explanation
    for it (``""`` when unmatched); a parsed explanation naming no on-disk
    file is dropped.
    """
    captions = {m["file"]: m["explanation"] for m in parsed}
    mockups: list[Mockup] = []
    for shot in screenshots.list_screenshots(run, root):
        if shot.stage != "refine":
            continue
        mockups.append(
            Mockup(
                name=shot.name,
                url=screenshots.stage_url(run, "refine", shot.name),
                explanation=captions.get(shot.name, ""),
            )
        )
    return mockups


async def capture_round_mockups(
    service: "WorkflowService",
    run: WorkflowRun,
    issue: str,
    questionnaire: Questionnaire,
) -> None:
    """Best-effort: mock up the round's UI and attach shots to the round's
    ``questionnaire``.

    No-op when no ``FILE_EDITS`` refine backend is available. Never fails
    the run — a failing/empty turn simply yields no mockups.
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
        prd=issue, screenshots_dir=screenshots.stage_reldir(run, "refine")
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
    questionnaire.mockups = _reconcile_mockups(
        run,
        extract_mockups(result.final_text),
        service.settings.screenshots_root,
    )
