"""Claude Code CLI backend.

Wraps :class:`app.services.runner.SessionRunner` (which spawns
``claude`` and maps its stream-json into canonical events) behind the
:class:`app.backends.base.Backend` contract. Being a file-editing agent,
it advertises both ``TEXT`` and ``FILE_EDITS``, so it can serve reasoning
steps too — leaning on the Claude subscription rather than an API key.
"""
from __future__ import annotations

from typing import Callable

from app.backends.base import Backend, Capability, TurnRequest, TurnResult
from app.config import Settings
from app.models import EventKind
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
        return TurnResult(session_id=sid, final_text=self._final_text(sid))

    def _final_text(self, session_id: str) -> str:
        """Read the deliverable from the session's terminal RESULT event."""
        record = self.registry.get(session_id)
        if record is None:
            return ""
        for event in reversed(record.events):
            if event.kind == EventKind.RESULT:
                return event.text if isinstance(event.text, str) else ""
        return ""
