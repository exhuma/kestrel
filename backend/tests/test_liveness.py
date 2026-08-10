"""Tests for the shared active-liveness-probe helper."""
from __future__ import annotations

import pytest

from app.backends.base import LivenessResult
from app.models import CanonicalEvent, EventKind
from app.services import liveness
from app.storage.registry import SessionRegistry


class _FakeBackend:
    """A backend whose check_alive result is set per test."""

    def __init__(self, result: LivenessResult) -> None:
        self.result = result
        self.probed: list[str] = []

    async def check_alive(self, session_id: str) -> LivenessResult:
        self.probed.append(session_id)
        return self.result


@pytest.mark.asyncio
async def test_poll_session_unknown_session_is_a_noop() -> None:
    """Ensure polling an unknown session neither probes nor records."""
    registry = SessionRegistry()
    backend = _FakeBackend(LivenessResult(alive=False, reason="n/a"))

    result = await liveness.poll_session(backend, registry, "missing")

    assert result.alive is True
    assert backend.probed == []


@pytest.mark.asyncio
async def test_poll_session_alive_leaves_status_untouched() -> None:
    """Ensure a healthy probe result changes nothing."""
    registry = SessionRegistry()
    registry.create("s1", "/tmp/s1")
    backend = _FakeBackend(LivenessResult(alive=True))

    result = await liveness.poll_session(backend, registry, "s1")

    assert result.alive is True
    rec = registry.get("s1")
    assert rec.status == "running"
    assert rec.events == []


@pytest.mark.asyncio
async def test_poll_session_dead_flips_status_and_records_error() -> None:
    """Ensure a dead probe result escalates the session visibly."""
    registry = SessionRegistry()
    registry.create("s1", "/tmp/s1")
    backend = _FakeBackend(
        LivenessResult(alive=False, reason="opencode session gone")
    )

    result = await liveness.poll_session(backend, registry, "s1")

    assert result.alive is False
    rec = registry.get("s1")
    assert rec.status == "error"
    assert rec.events[-1].kind is EventKind.RESULT
    assert rec.events[-1].is_error is True
    assert rec.events[-1].text == "opencode session gone"


@pytest.mark.asyncio
async def test_poll_session_dead_result_defaults_reason_text() -> None:
    """Ensure a reason-less dead result still records something readable."""
    registry = SessionRegistry()
    registry.create("s1", "/tmp/s1")
    backend = _FakeBackend(LivenessResult(alive=False, reason=None))

    await liveness.poll_session(backend, registry, "s1")

    assert registry.get("s1").events[-1].text == "session no longer alive"


@pytest.mark.asyncio
async def test_poll_session_does_not_re_record_an_already_errored_session() -> (
    None
):
    """Ensure repeated polling of an already-errored session is idempotent."""
    registry = SessionRegistry()
    registry.create("s1", "/tmp/s1")
    registry.append_event(
        "s1",
        CanonicalEvent(
            kind=EventKind.RESULT, session_id="s1", is_error=True,
            text="first failure",
        ),
    )
    registry.set_status("s1", "error")
    backend = _FakeBackend(LivenessResult(alive=False, reason="still gone"))

    await liveness.poll_session(backend, registry, "s1")

    rec = registry.get("s1")
    assert len(rec.events) == 1
    assert rec.events[0].text == "first failure"
