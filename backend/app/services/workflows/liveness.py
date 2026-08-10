"""Active liveness probing for a workflow's currently-live chips.

Backs the "force poll now" action on the chip row: everything else in a
workflow's UI is push-based (SSE ticks off the driver's own state
changes), so a chip whose backend session died with no terminal event
would otherwise sit "running" forever with nothing to notice it.
"""
from __future__ import annotations

from typing import Callable

from app.backends.base import Backend
from app.models_workflow import WorkflowRun
from app.services import liveness
from app.storage.registry import SessionRegistry


async def poll_active_step(
    backend_for: Callable[[str], Backend],
    sessions: SessionRegistry,
    save: Callable[[WorkflowRun], None],
    run: WorkflowRun,
) -> None:
    """Probe every live chip on the run's currently-running step.

    Escalates any chip whose backend reports it's no longer alive to
    ``"error"`` with a diagnostic reason; persists only if something
    actually changed.
    """
    step = next((s for s in run.steps if s.status == "running"), None)
    if step is None:
        return
    changed = False
    for chip in step.active_sessions:
        if chip.status != "running" or chip.session_id is None:
            continue
        backend = backend_for(step.name)
        result = await liveness.poll_session(backend, sessions, chip.session_id)
        if not result.alive:
            chip.status = "error"
            chip.error = result.reason
            changed = True
    if changed:
        save(run)
