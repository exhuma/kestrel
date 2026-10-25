"""Claude Code CLI backend.

Wraps :class:`app.services.runner.SessionRunner` (which spawns
``claude`` and maps its stream-json into canonical events) behind the
:class:`app.backends.base.Backend` contract. Being a file-editing agent,
it advertises both ``TEXT`` and ``FILE_EDITS``, so it can serve reasoning
steps too — leaning on the Claude subscription rather than an API key.
"""
from __future__ import annotations

from typing import Callable

from app.backends.base import (
    Backend,
    BackendTurnError,
    Capability,
    ModelCatalog,
    TurnRequest,
    TurnResult,
)
from app.backends.limiter import BackendLimiter
from app.config import Settings
from app.services.runner import SessionRunner


class ClaudeCliBackend(Backend):
    """Dispatches to the claude CLI via a per-instance SessionRunner."""

    caps = frozenset({Capability.TEXT, Capability.FILE_EDITS})

    def __init__(
        self,
        settings: Settings,
        backend_id: str = "claude",
        limiter: BackendLimiter | None = None,
    ) -> None:
        self.id = backend_id
        self._limiter = limiter or BackendLimiter()
        self._runner = SessionRunner(settings, self._limiter)

    async def list_models(self) -> ModelCatalog:
        """Report unknown because the CLI has no stable catalogue interface."""
        return ModelCatalog(state="unknown")

    async def run_turn(
        self,
        req: TurnRequest,
        on_queue_change: Callable[[bool], None] | None = None,
    ) -> TurnResult:
        """Run one admitted Claude turn to its terminal event."""
        turn = await self._runner.run_blocking(req, on_queue_change)
        result = turn.result
        text = result.text if result and isinstance(result.text, str) else ""
        if result is not None and result.is_error:
            raise BackendTurnError(
                f"agent backend error: {text or 'the agent reported an error'}"
            )
        assert turn.session_id is not None  # run_blocking guarantees it
        return TurnResult(session_id=turn.session_id, final_text=text)
