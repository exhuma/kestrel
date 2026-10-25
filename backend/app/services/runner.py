"""Service that runs one claude CLI turn to completion."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Callable

from app.backends.agent_log import AgentLog
from app.backends.base import (
    PERMISSION_EDIT,
    PERMISSION_READ_ONLY,
    BackendTurnError,
    TurnRequest,
)
from app.backends.limiter import BackendLimiter
from app.config import Settings
from app.models import CanonicalEvent, EventKind, map_claude_line

# Claude Code's own names for the backend-neutral permission modes; any other
# value (e.g. a configured ``bypassPermissions``) is passed through as is.
_CLAUDE_PERMISSION_MODES = {
    PERMISSION_READ_ONLY: "plan",
    PERMISSION_EDIT: "acceptEdits",
}

# asyncio.create_subprocess_exec's default per-line StreamReader limit
# is 64 KiB (65536 bytes); a single stream-json event (e.g. a
# tool_result embedding a large file or diff) can legitimately exceed
# that before its terminating newline, raising
# "ValueError: Separator is found, but chunk is longer than limit".
# 10 MiB comfortably covers real event sizes seen in practice.
_STREAM_LIMIT = 10 * 1024 * 1024


@dataclass
class ClaudeTurn:
    """What one claude CLI run produced."""

    #: The session id the stream reported, or None if it never did.
    session_id: str | None
    #: The stream's terminal ``result`` event, or None if it never sent one.
    result: CanonicalEvent | None


async def _stdout_lines(
    proc: asyncio.subprocess.Process,
) -> AsyncIterator[str]:
    """Yield decoded lines from a subprocess's stdout as they arrive."""
    assert proc.stdout is not None
    async for raw in proc.stdout:
        yield raw.decode("utf-8", "replace")


async def _drain(stream: AsyncIterator[object]) -> None:
    """Consume and discard every item from an async iterator."""
    async for _ in stream:
        pass


class SessionRunner:
    """Spawns claude subprocesses and reads their stream-json output."""

    def __init__(
        self, settings: Settings, limiter: BackendLimiter | None = None
    ) -> None:
        """Create a CLI runner, optionally sharing a backend turn limiter."""
        self.settings = settings
        self._limiter = limiter

    def build_argv(
        self,
        prompt: str,
        resume_id: str | None = None,
        permission_mode: str | None = None,
        model: str | None = None,
    ) -> list[str]:
        """
        Build the claude CLI argument vector.

        :param prompt: The prompt text to pass to claude.
        :param resume_id: Session id to resume, or None to start
            a new session.
        :param permission_mode: Overrides the settings default when given.
        :param model: Model alias for ``--model``, or None to
            use the CLI's default.
        :returns: The argument vector to pass to the subprocess.
        """
        mode = permission_mode or self.settings.permission_mode
        argv = [
            self.settings.claude_bin,
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            _CLAUDE_PERMISSION_MODES.get(mode, mode),
        ]
        if model is not None:
            argv += ["--model", model]
        if resume_id is not None:
            argv += ["--resume", resume_id]
        return argv

    async def consume(
        self, lines: AsyncIterator[str], req: TurnRequest
    ) -> ClaudeTurn:
        """
        Consume a line stream down to the turn's session id and result.

        ``req.on_session_id`` fires once, the moment the session id is
        first known (immediately for a resume, or on the first event
        carrying an id for a fresh start).

        :param lines: Async iterator of raw JSONL lines.
        :param req: The turn being run; its ``card_id`` tags the log lines.
        :returns: The session id (None if never seen) and the terminal
            ``result`` event (None if the stream sent none).
        """
        session_id = req.resume_id
        log = self._open(session_id, req) if session_id else None
        result: CanonicalEvent | None = None
        try:
            async for line in lines:
                event = map_claude_line(line)
                if event is None:
                    continue
                if session_id is None and event.session_id is not None:
                    session_id = event.session_id
                    log = self._open(session_id, req)
                if log is not None:
                    log.event(event)
                if event.kind == EventKind.RESULT:
                    result = event
        except asyncio.CancelledError:
            if log is not None:
                log.failed("the turn was cancelled (timeout or shutdown)")
            raise
        if log is not None:
            self._log_outcome(log, result)
        return ClaudeTurn(session_id, result)

    def _open(self, session_id: str, req: TurnRequest) -> AgentLog:
        """Start logging a session the moment its id is known."""
        log = AgentLog(session_id, req.card_id, backend_id="claude_cli")
        log.started(resumed=req.resume_id is not None)
        if req.on_session_id is not None:
            req.on_session_id(session_id)
        return log

    @staticmethod
    def _log_outcome(log: AgentLog, result: CanonicalEvent | None) -> None:
        """Log how the stream ended: its result, or the lack of one."""
        if result is None:
            log.failed("the stream ended without a result event")
            return
        log.finished(
            result.text,
            is_error=result.is_error,
            duration_ms=result.duration_ms,
        )

    async def run_blocking(
        self,
        req: TurnRequest,
        on_queue_change: Callable[[bool], None] | None = None,
    ) -> ClaudeTurn:
        """
        Run a claude turn to completion.

        :param req: The turn to run (prompt, cwd, permission mode, model,
            optional session to resume).
        :param on_queue_change: Told when the turn starts or stops
            waiting for a backend slot.
        :returns: The turn's session id and terminal result.
        :raises BackendTurnError: If the stream reports no session id.
        """
        Path(req.cwd).mkdir(parents=True, exist_ok=True)
        if self._limiter is None:
            return await self._run_blocking(req)
        async with self._limiter.slot(on_queue_change):
            return await self._run_blocking(req)

    async def _run_blocking(self, req: TurnRequest) -> ClaudeTurn:
        """Execute an already admitted CLI subprocess until it completes."""
        argv = self.build_argv(
            req.prompt, req.resume_id, req.permission_mode, req.model
        )
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=req.cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=_STREAM_LIMIT,
        )
        assert proc.stderr is not None
        stderr_task = asyncio.create_task(_drain(proc.stderr))
        try:
            turn = await self.consume(_stdout_lines(proc), req)
            await proc.wait()
            await stderr_task
        finally:
            if proc.returncode is None:
                proc.kill()
            stderr_task.cancel()
        if turn.session_id is None:
            raise BackendTurnError("claude produced no session id")
        return turn
