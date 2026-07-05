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
    TurnRequest,
    TurnResult,
)
from app.config import Settings
from app.models import CanonicalEvent, EventKind
from app.services.runner import SessionRunner
from app.storage.registry import SessionRegistry


class ClaudeCliBackend(Backend):
    """Dispatches to the claude CLI via a per-instance SessionRunner."""

    caps = frozenset({Capability.TEXT, Capability.FILE_EDITS})

    def __init__(
        self,
        settings: Settings,
        registry: SessionRegistry,
        backend_id: str = "claude",
    ) -> None:
        self.id = backend_id
        self.registry = registry
        self._runner = SessionRunner(settings, registry)

    async def start(self, prompt: str) -> str:
        return await self._runner.start(prompt)

    async def resume(self, session_id: str, prompt: str) -> str:
        return await self._runner.resume(session_id, prompt)

    def terminate(self, session_id: str) -> bool:
        return self._runner.terminate(session_id)

    async def run_turn(
        self,
        req: TurnRequest,
        on_session_id: Callable[[str], None] | None = None,
    ) -> TurnResult:
        sid = await self._runner.run_blocking(
            req.prompt,
            req.cwd,
            req.permission_mode,
            resume_id=req.resume_id,
            on_session_id=on_session_id,
            model=req.model,
        )
        result = self._terminal_result(sid)
        text = result.text if result and isinstance(result.text, str) else ""
        if result is not None and result.is_error:
            # The agent errored (e.g. "Not logged in · Please run /login")
            # rather than producing a deliverable; fail loudly so the run
            # goes to `failed` with the message instead of parking the
            # error text at an approval gate as a bogus deliverable.
            raise BackendTurnError(
                f"agent backend error: {text or 'the agent reported an error'}"
            )
        return TurnResult(session_id=sid, final_text=text)

    def _terminal_result(self, session_id: str) -> CanonicalEvent | None:
        """Return the session's terminal RESULT event, or None."""
        record = self.registry.get(session_id)
        if record is None:
            return None
        for event in reversed(record.events):
            if event.kind == EventKind.RESULT:
                return event
        return None
