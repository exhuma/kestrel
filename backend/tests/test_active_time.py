"""Tests for the active/wait-time clock (feature 006)."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.models_workflow import WorkflowRun
from app.services.time_tracking import set_clock


def _run() -> WorkflowRun:
    return WorkflowRun(id="wf-1", repo="o/r", issue_number=5)


def test_not_started_clock_is_a_noop_until_set() -> None:
    """Ensure a fresh run has no accumulated time and no running clock."""
    run = _run()
    assert run.active_seconds == 0.0
    assert run.wait_seconds == 0.0
    assert run.clock_state is None
    assert run.clock_since is None


def test_start_then_stop_accumulates_active_seconds() -> None:
    """Ensure a single active span accumulates into active_seconds."""
    run = _run()
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    active_span = 90.0
    set_clock(run, "active", t0)
    assert run.clock_state == "active"
    assert run.clock_since == t0
    set_clock(run, None, t0 + timedelta(seconds=active_span))
    assert run.active_seconds == active_span
    assert run.wait_seconds == 0.0
    assert run.clock_state is None
    assert run.clock_since is None


def test_gate_round_trip_accumulates_both_independently() -> None:
    """Ensure active -> waiting -> active -> terminal splits correctly."""
    run = _run()
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    first_active, gate_wait, second_active = 60.0, 120.0, 50.0
    set_clock(run, "active", t0)
    set_clock(run, "waiting", t0 + timedelta(seconds=first_active))
    set_clock(
        run, "active", t0 + timedelta(seconds=first_active + gate_wait)
    )
    set_clock(
        run,
        None,
        t0 + timedelta(seconds=first_active + gate_wait + second_active),
    )
    assert run.active_seconds == first_active + second_active
    assert run.wait_seconds == gate_wait


def test_multiple_gate_rounds_accumulate_across_rounds() -> None:
    """Ensure repeated gate rounds sum correctly, not just the last one."""
    run = _run()
    t = datetime(2026, 1, 1, 12, 0, 0)
    active_spans = [10.0, 20.0, 7.0]
    wait_spans = [5.0, 15.0]

    def advance(seconds: float) -> datetime:
        nonlocal t
        t = t + timedelta(seconds=seconds)
        return t

    set_clock(run, "active", t)  # start
    set_clock(run, "waiting", advance(active_spans[0]))
    set_clock(run, "active", advance(wait_spans[0]))
    set_clock(run, "waiting", advance(active_spans[1]))
    set_clock(run, "active", advance(wait_spans[1]))
    set_clock(run, None, advance(active_spans[2]))  # terminal
    assert run.active_seconds == sum(active_spans)
    assert run.wait_seconds == sum(wait_spans)
    assert run.clock_state is None


def test_terminal_call_is_idempotent() -> None:
    """Ensure calling set_clock(None) twice does not double-count."""
    run = _run()
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    active_span = 30.0
    set_clock(run, "active", t0)
    set_clock(run, None, t0 + timedelta(seconds=active_span))
    assert run.active_seconds == active_span
    # A second terminal call (e.g. a second _save() on an already-stopped
    # run) must be a pure no-op — nothing is running to accumulate.
    set_clock(run, None, t0 + timedelta(seconds=active_span + 999))
    assert run.active_seconds == active_span
    assert run.wait_seconds == 0.0
