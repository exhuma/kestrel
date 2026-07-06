"""Tests for the claude CLI backend's turn-result handling."""
from __future__ import annotations

import pytest

from app.backends.base import BackendTurnError, TurnRequest
from app.backends.claude_cli import ClaudeCliBackend
from app.config import Settings
from app.models import CanonicalEvent, EventKind, SessionRecord
from app.storage.registry import SessionRegistry


def _backend(registry: SessionRegistry) -> ClaudeCliBackend:
    return ClaudeCliBackend(Settings(), registry, backend_id="claude")


def _fake_run_blocking(
    registry: SessionRegistry, sid: str, event: CanonicalEvent
):
    """Return a run_blocking stub that records *event* under *sid*."""
    async def _run(prompt, cwd, permission_mode, *, resume_id=None,
                   on_session_id=None, model=None):
        registry._records[sid] = SessionRecord(session_id=sid, cwd=cwd)
        registry._records[sid].events.append(event)
        if on_session_id:
            on_session_id(sid)
        return sid

    return _run


@pytest.mark.asyncio
async def test_run_turn_raises_on_error_result() -> None:
    """Ensure an errored terminal result fails the turn, not passes as text.

    A claude auth failure ("Not logged in · Please run /login") arrives as
    a RESULT event with is_error=True; it must raise so the run fails
    loudly rather than becoming a bogus deliverable.
    """
    reg = SessionRegistry()
    backend = _backend(reg)
    backend._runner.run_blocking = _fake_run_blocking(  # type: ignore[method-assign]
        reg, "sess-err",
        CanonicalEvent(
            EventKind.RESULT, "sess-err",
            text="Not logged in · Please run /login", is_error=True,
        ),
    )
    with pytest.raises(BackendTurnError) as exc:
        await backend.run_turn(
            TurnRequest(prompt="p", cwd="/tmp", permission_mode="plan")
        )
    assert "Not logged in" in str(exc.value)


@pytest.mark.asyncio
async def test_run_turn_returns_text_on_ok_result() -> None:
    """Ensure a normal (non-error) result still returns its text."""
    reg = SessionRegistry()
    backend = _backend(reg)
    backend._runner.run_blocking = _fake_run_blocking(  # type: ignore[method-assign]
        reg, "sess-ok",
        CanonicalEvent(
            EventKind.RESULT, "sess-ok", text="all good", is_error=False
        ),
    )
    result = await backend.run_turn(
        TurnRequest(prompt="p", cwd="/tmp", permission_mode="plan")
    )
    assert result.final_text == "all good"
