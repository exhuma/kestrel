"""Tests for the claude CLI backend's turn-result handling."""
from __future__ import annotations

import pytest

from app.backends.base import BackendTurnError, TurnRequest
from app.backends.claude_cli import ClaudeCliBackend
from app.config import Settings
from app.models import CanonicalEvent, EventKind
from app.services.runner import ClaudeTurn


def _backend(sid: str, event: CanonicalEvent) -> ClaudeCliBackend:
    """A backend whose runner reports *event* as the turn's result."""
    backend = ClaudeCliBackend(Settings(), backend_id="claude")

    async def _run(req, on_queue_change=None):
        return ClaudeTurn(sid, event)

    backend._runner.run_blocking = _run  # type: ignore[method-assign]
    return backend


@pytest.mark.asyncio
async def test_run_turn_raises_on_error_result() -> None:
    """Ensure an errored terminal result fails the turn, not passes as text.

    A claude auth failure ("Not logged in · Please run /login") arrives as
    a RESULT event with is_error=True; it must raise so the run fails
    loudly rather than becoming a bogus deliverable.
    """
    backend = _backend(
        "sess-err",
        CanonicalEvent(
            EventKind.RESULT, "sess-err",
            text="Not logged in · Please run /login", is_error=True,
        ),
    )
    with pytest.raises(BackendTurnError) as exc:
        await backend.run_turn(
            TurnRequest(prompt="p", cwd="/tmp", permission_mode="read_only")
        )
    assert "Not logged in" in str(exc.value)


@pytest.mark.asyncio
async def test_run_turn_returns_text_on_ok_result() -> None:
    """Ensure a normal (non-error) result still returns its text."""
    backend = _backend(
        "sess-ok",
        CanonicalEvent(
            EventKind.RESULT, "sess-ok", text="all good", is_error=False
        ),
    )
    result = await backend.run_turn(
        TurnRequest(prompt="p", cwd="/tmp", permission_mode="read_only")
    )
    assert result.final_text == "all good"
