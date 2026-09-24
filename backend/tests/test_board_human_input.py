"""Direct-session prompt confirmation boundary tests (feature 026, T020).

A direct session prompt is not automatically quarantined (it intentionally
addresses an agent) but requires bounds and an explicit, recorded
injection-risk confirmation before dispatch (FR-023).

This file used to also cover gate-reply/approval-edit/rejection-feedback/
questionnaire-answer screening through the old fixed-step driver's
``/api/workflows/{id}/reply|approve|reject|answers`` endpoints
(``app.services.workflows``, ``app.models_workflow.WorkflowRun``). Phase 10
deleted that driver and its HTTP surface outright — there is no successor
free-text gate endpoint to screen. The board's own gate resolution
(``POST /api/board/.../interventions`` with ``action=resolve_gate``) takes
only a closed ``"approved"``/``"rejected"`` decision (see
``app/services/board/gates.py``'s ``_DECISION_TARGET_STATE``); there is no
free-text deliverable edit, rejection feedback, or questionnaire-answer
input in the current board model for untrusted content to hide in, so
``QuarantineService.intake_for_existing_workflow`` has no caller today.
That gate-resolution path is already covered directly by
``tests/test_board_gates.py`` and ``tests/test_board_interventions.py``.
"""
from __future__ import annotations

import pytest

from app.services.exceptions import (
    DirectPromptTooLargeError,
    SessionNotFoundError,
    UnconfirmedDirectPromptError,
)
from app.services.sessions import SessionService
from app.storage.registry import SessionRegistry


class TestDirectSessionPromptConfirmation:
    """A direct prompt needs bounds + explicit confirmation, not quarantine."""

    @pytest.mark.asyncio
    async def test_unconfirmed_prompt_is_refused(self) -> None:
        service = SessionService(
            backend=None, registry=SessionRegistry(), max_prompt_bytes=100
        )
        with pytest.raises(UnconfirmedDirectPromptError):
            await service.start("hello", confirmed_injection_risk=False)

    @pytest.mark.asyncio
    async def test_oversized_prompt_is_refused_even_if_confirmed(
        self,
    ) -> None:
        service = SessionService(
            backend=None, registry=SessionRegistry(), max_prompt_bytes=10
        )
        with pytest.raises(DirectPromptTooLargeError):
            await service.start(
                "this prompt is far too long",
                confirmed_injection_risk=True,
            )

    @pytest.mark.asyncio
    async def test_confirmed_prompt_within_bounds_dispatches(self) -> None:
        class _FakeBackend:
            async def start(self, _prompt: str) -> str:
                return "session-1"

        service = SessionService(
            backend=_FakeBackend(),
            registry=SessionRegistry(),
            max_prompt_bytes=100,
        )
        session_id = await service.start(
            "hello", confirmed_injection_risk=True
        )
        assert session_id == "session-1"

    @pytest.mark.asyncio
    async def test_resume_still_checks_session_existence_first(
        self,
    ) -> None:
        """An unconfirmed prompt to an unknown session still reports
        "not found" first — bounds/confirmation only matter once the
        session itself is real."""
        service = SessionService(
            backend=None, registry=SessionRegistry(), max_prompt_bytes=100
        )
        with pytest.raises(SessionNotFoundError):
            await service.resume(
                "missing", "hello", confirmed_injection_risk=False
            )
