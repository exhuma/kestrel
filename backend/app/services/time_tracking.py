"""Active/wait-time clock for a workflow run (feature 006).

A run is, at any moment, in exactly one of three clock states: not
started, active (genuinely being worked), or waiting (parked at a human
gate). ``_set_clock`` is the single place that ever mutates a run's
clock fields — stop whichever clock is running (accumulating its
elapsed time), then start the requested one (or none, at a terminal).
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.models_workflow import WorkflowRun

_ClockState = Literal["active", "waiting"] | None


def set_clock(run: "WorkflowRun", state: _ClockState, now: datetime) -> None:
    """Stop the running clock (if any) and start ``state``'s clock.

    :param run: The run whose clock is transitioning.
    :param state: ``"active"``, ``"waiting"``, or ``None`` (terminal —
        stop tracking entirely).
    :param now: The current time (naive UTC, matching this repo's
        timestamp convention).
    """
    if run.clock_since is not None and run.clock_state is not None:
        elapsed = (now - run.clock_since).total_seconds()
        if run.clock_state == "active":
            run.active_seconds += elapsed
        else:
            run.wait_seconds += elapsed
    run.clock_state = state
    run.clock_since = now if state is not None else None
