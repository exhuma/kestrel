"""Tests for LifecycleTransitioner / render_footer (feature 006)."""
from __future__ import annotations

import asyncio

import pytest

from app.models_workflow import WorkflowRun
from app.ports import LifecycleEvent
from app.services.lifecycle import (
    LifecycleTransitioner,
    _build_event,
    _is_lifecycle_event,
    render_footer,
)


class _FakeSource:
    """A fake TaskSource recording transition/comment calls."""

    def __init__(
        self, *, native_status: bool = True, time_supported: bool = False
    ) -> None:
        self.transitions: list[LifecycleEvent] = []
        self.comments: list[tuple[str, str]] = []
        self._native_status = native_status
        self._time_supported = time_supported

    async def transition(self, _ref: str, event: LifecycleEvent) -> bool:
        self.transitions.append(event)
        return self._native_status

    async def post_comment(self, ref: str, body: str) -> str:
        self.comments.append((ref, body))
        return "https://ticket/comment/1"

    def supports_time_spent(self) -> bool:
        return self._time_supported


def _run(status: str, *, source: str = "github-issue",
         task_ref: str = "o/r#5") -> WorkflowRun:
    return WorkflowRun(
        id="wf-1", repo="o/r", issue_number=5, status=status,
        source=source, task_ref=task_ref,
    )


async def _tick() -> None:
    await asyncio.sleep(0)
    await asyncio.sleep(0)


# --- kind-exclusivity invariant (T006) --------------------------------

@pytest.mark.parametrize(
    ("status", "kind"),
    [
        ("cloning", "start"),
        ("done", "done"),
        ("failed", "failed"),
        ("escalated", "escalated"),
        ("rejected", "rejected"),
    ],
)
def test_kind_matches_status_exactly(status: str, kind: str) -> None:
    """Ensure each lifecycle-worthy status maps to exactly one kind."""
    run = _run(status)
    event = _build_event(run, "")
    assert event.kind == kind


@pytest.mark.parametrize("status", ["failed", "escalated", "rejected"])
def test_failure_terminals_never_yield_done(status: str) -> None:
    """Ensure a failure terminal's event.kind is never "done"."""
    event = _build_event(_run(status), "")
    assert event.kind != "done"


@pytest.mark.parametrize(
    "status",
    ["pending", "refining", "designing", "coding", "verifying",
     "opening_pr", "awaiting_refine_input", "awaiting_refine_approval"],
)
def test_non_terminal_non_start_statuses_are_not_lifecycle_events(
    status: str,
) -> None:
    """Ensure only start/terminal statuses trigger a lifecycle dispatch."""
    assert _is_lifecycle_event(status) is False


# --- render_footer (T009) ----------------------------------------------

def test_render_footer_status_only() -> None:
    """Ensure a status-only footer carries the status, not time."""
    event = LifecycleEvent(kind="done")
    footer = render_footer(event, include_status=True, include_time=False)
    assert "status → done" in footer
    assert "active" not in footer


def test_render_footer_neither_is_empty() -> None:
    """Ensure nothing is rendered when both fields were natively applied."""
    event = LifecycleEvent(kind="done")
    footer = render_footer(event, include_status=False, include_time=False)
    assert footer == ""


def test_render_footer_time_without_a_value_is_empty() -> None:
    """Ensure a time-only footer with no active_seconds yet renders nothing."""
    event = LifecycleEvent(kind="start")
    footer = render_footer(event, include_status=False, include_time=True)
    assert footer == ""


# --- integration: start -> done, start -> failed (T014) ----------------

@pytest.mark.asyncio
async def test_start_then_done_applies_native_status_and_no_footer() -> None:
    """Ensure a source covering both status and time posts no footer."""
    source = _FakeSource(native_status=True, time_supported=True)
    transitioner = LifecycleTransitioner({"github-issue": source})
    transitioner.notify(_run("cloning"))
    await _tick()
    transitioner.notify(_run("done"))
    await _tick()
    assert [e.kind for e in source.transitions] == ["start", "done"]
    assert source.comments == []


@pytest.mark.asyncio
async def test_native_status_but_unsupported_time_still_gets_footer() -> None:
    """Ensure a GitHub-like source (native status, no time field) still
    reports time via the footer even though status was applied natively.
    """
    source = _FakeSource(native_status=True, time_supported=False)
    transitioner = LifecycleTransitioner({"github-issue": source})
    transitioner.notify(_run("done"))
    await _tick()
    assert len(source.comments) == 1
    ref, body = source.comments[0]
    assert ref == "o/r#5"
    assert "status" not in body
    assert "active" in body


@pytest.mark.asyncio
async def test_start_then_failed_never_reports_done() -> None:
    """Ensure a failed run's dispatch reports "failed", never "done"."""
    source = _FakeSource(native_status=True)
    transitioner = LifecycleTransitioner({"github-issue": source})
    transitioner.notify(_run("cloning"))
    await _tick()
    transitioner.notify(_run("failed"))
    await _tick()
    kinds = [e.kind for e in source.transitions]
    assert kinds == ["start", "failed"]
    assert "done" not in kinds


@pytest.mark.asyncio
async def test_unsupported_native_status_falls_back_to_footer() -> None:
    """Ensure a source that can't apply status natively gets a footer."""
    source = _FakeSource(native_status=False)
    transitioner = LifecycleTransitioner({"github-issue": source})
    transitioner.notify(_run("done"))
    await _tick()
    assert len(source.comments) == 1
    ref, body = source.comments[0]
    assert ref == "o/r#5"
    assert "status → done" in body


@pytest.mark.asyncio
async def test_unknown_source_or_no_task_ref_dispatches_nothing() -> None:
    """Ensure a run with no bound source (e.g. manual) is skipped entirely."""
    source = _FakeSource()
    transitioner = LifecycleTransitioner({"github-issue": source})
    transitioner.notify(_run("done", source="manual"))
    transitioner.notify(_run("done", task_ref=""))
    await _tick()
    assert source.transitions == []
    assert source.comments == []
