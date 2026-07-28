"""Turn-execution and session-chip tracking shared by every workflow step."""
from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Callable

from app.backends.base import Backend, TurnRequest, TurnResult
from app.models_workflow import StepSession, WorkflowRun, WorkflowStep
from app.services.workflow_text import activity_for
from app.storage.registry import SessionRegistry

#: Cap on a failure reason's length so it still fits a chip.
_MAX_REASON_LENGTH = 200


def _failure_reason(exc: BaseException) -> str:
    """A concise reason from a failed generator turn, for chip + gate.

    The backend's own errors already read well ("LLM request … timed out
    after 120s (model 'llama3')"); fall back to the type name and cap the
    length so it fits a chip.
    """
    message = str(exc).strip() or type(exc).__name__
    if len(message) <= _MAX_REASON_LENGTH:
        return message
    return message[:_MAX_REASON_LENGTH - 3] + "…"


def _bind(step: WorkflowStep, slot: StepSession) -> Callable[[str], None]:
    """Return an on_session_id callback that records the resolved id on
    both the step's chip slot and its primary session pointer."""

    def _on(sid: str) -> None:
        slot.session_id = sid
        step.session_id = sid

    return _on


def show_sessions(
    run: WorkflowRun,
    slots: list[StepSession],
    save: Callable[[WorkflowRun], None],
) -> None:
    """Publish the sessions active on the refine step right now.

    Each ``save`` pushes the chip state to the UI (via the poll today,
    the SSE stream in a later phase). The slots are the ephemeral,
    non-persisted telemetry the workflow view animates.
    """
    run.steps[0].active_sessions = slots
    save(run)


def watch_activity(
    sessions_registry: SessionRegistry,
    save: Callable[[WorkflowRun], None],
    run: WorkflowRun,
    session_id: str,
    slot: StepSession,
) -> asyncio.Task:
    """Track a session's live activity onto its chip.

    Subscribes to the session's canonical event stream and maps each
    event to a 1-2 word activity (:func:`activity_for`), updating the
    chip and re-publishing the run **only when the word changes** — so
    a chatty stream costs a handful of SSE ticks, not one per event.
    Returns the monitor task; the caller cancels it when the turn ends.
    """
    # Subscribe synchronously (before the task is scheduled) so no
    # event slips through between session-id resolution and the
    # monitor first running.
    queue = sessions_registry.subscribe(session_id)

    async def _watch() -> None:
        try:
            while True:
                event = await queue.get()
                word = activity_for(event)
                if word is not None and word != slot.activity:
                    slot.activity = word
                    save(run)
        finally:
            sessions_registry.unsubscribe(session_id, queue)

    return asyncio.create_task(_watch())


@dataclass
class ChipTracker:
    """The chip-tracking collaborators for one tracked turn."""

    slot: StepSession
    bind: Callable[[str], None]
    watch: Callable[[WorkflowRun, str, StepSession], asyncio.Task]


async def run_turn_tracked(
    run: WorkflowRun,
    backend: Backend,
    req: TurnRequest,
    tracker: ChipTracker,
) -> TurnResult:
    """Run one turn while streaming its live activity onto the chip.

    Wraps ``tracker.bind`` (the existing ``on_session_id`` that records
    the session id) so that, once the id is known, ``tracker.watch``
    starts a monitor; it is always cancelled and the activity cleared
    when the turn finishes, however it finishes.
    """
    monitor: asyncio.Task | None = None

    def _on_sid(session_id: str) -> None:
        nonlocal monitor
        tracker.bind(session_id)
        monitor = tracker.watch(run, session_id, tracker.slot)

    try:
        return await backend.run_turn(req, on_session_id=_on_sid)
    finally:
        if monitor is not None:
            monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await monitor
        tracker.slot.activity = None
