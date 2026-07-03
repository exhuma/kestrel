"""Service that spawns and resumes claude CLI sessions."""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import AsyncIterator, Callable

from fastapi import Depends

from app.config import Settings, get_settings
from app.models import parse_event
from app.services.exceptions import SessionNotFoundError, SessionStartError
from app.storage.registry import SessionRegistry, get_registry

# Strong references to in-flight streaming tasks. A SessionRunner is
# created per request, so the task cannot live on the instance; the
# event loop keeps only weak references, so we hold them here for the
# process lifetime and drop each when it finishes.
_TASKS: set[asyncio.Task[None]] = set()

# asyncio.create_subprocess_exec's default per-line StreamReader limit
# is 64 KiB (65536 bytes); a single stream-json event (e.g. a
# tool_result embedding a large file or diff) can legitimately exceed
# that before its terminating newline, raising
# "ValueError: Separator is found, but chunk is longer than limit".
# 10 MiB comfortably covers real event sizes seen in practice.
_STREAM_LIMIT = 10 * 1024 * 1024


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
    """Spawns claude subprocesses and streams events to the registry."""

    def __init__(
        self, settings: Settings, registry: SessionRegistry
    ) -> None:
        self.settings = settings
        self.registry = registry

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
        argv = [
            self.settings.claude_bin,
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            permission_mode or self.settings.permission_mode,
        ]
        if model is not None:
            argv += ["--model", model]
        if resume_id is not None:
            argv += ["--resume", resume_id]
        return argv

    async def consume(
        self,
        lines: AsyncIterator[str],
        cwd: str,
        record_id: str | None = None,
        on_session_id: Callable[[str], None] | None = None,
    ) -> str | None:
        """
        Consume a line stream, updating the registry.

        Events are appended as they arrive, so subscribers see them
        live. ``on_session_id`` fires once, the moment the session id
        is first known (immediately for a resume, or on the first event
        carrying an id for a fresh start).

        :param lines: Async iterator of raw JSONL lines.
        :param cwd: Working directory the session runs in.
        :param record_id: Existing record id (resume), or None to
            create a record when the first session id appears.
        :param on_session_id: Optional callback invoked with the id the
            first time it becomes known.
        :returns: The resolved session id, or None if never seen.
        """
        session_id = record_id
        if session_id is not None and on_session_id is not None:
            on_session_id(session_id)
        async for line in lines:
            event = parse_event(line)
            if event is None:
                continue
            if session_id is None and event.session_id is not None:
                session_id = event.session_id
                self.registry.create(session_id, cwd)
                if on_session_id is not None:
                    on_session_id(session_id)
            if session_id is not None:
                self.registry.append_event(session_id, event)
                if event.type == "result":
                    self.registry.set_status(session_id, "idle")
        return session_id

    async def _launch(
        self, argv: list[str], cwd: str, record_id: str | None
    ) -> str:
        """
        Spawn the subprocess and stream it in the background.

        Returns as soon as the session id is known; consuming the rest
        of stdout continues in a detached task so events keep flowing to
        subscribers after the caller's request has returned.
        """
        os.makedirs(cwd, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=_STREAM_LIMIT,
        )
        loop = asyncio.get_running_loop()
        sid_future: asyncio.Future[str] = loop.create_future()

        def _resolve(sid: str) -> None:
            if not sid_future.done():
                sid_future.set_result(sid)

        async def _stdout() -> AsyncIterator[str]:
            assert proc.stdout is not None
            async for raw in proc.stdout:
                yield raw.decode("utf-8", "replace")

        async def _drain_stderr() -> None:
            assert proc.stderr is not None
            async for _ in proc.stderr:
                pass

        async def _run() -> None:
            stderr_task = asyncio.create_task(_drain_stderr())
            try:
                sid = await self.consume(
                    _stdout(), cwd, record_id, on_session_id=_resolve
                )
                await proc.wait()
                await stderr_task
                if sid is None and not sid_future.done():
                    sid_future.set_exception(
                        SessionStartError("claude produced no session id")
                    )
            except Exception as exc:  # surface to the awaiting caller
                if not sid_future.done():
                    sid_future.set_exception(exc)
            finally:
                if proc.returncode is None:
                    proc.kill()
                stderr_task.cancel()
                if not sid_future.done():
                    sid_future.set_exception(
                        SessionStartError("session ended without a session id")
                    )

        task = asyncio.create_task(_run())
        _TASKS.add(task)
        task.add_done_callback(_TASKS.discard)
        return await sid_future

    async def run_blocking(
        self,
        prompt: str,
        cwd: str,
        permission_mode: str,
        resume_id: str | None = None,
        on_session_id: Callable[[str], None] | None = None,
        model: str | None = None,
    ) -> str:
        """
        Run a claude step to completion, streaming events live.

        Unlike start/resume (which return early and stream in the
        background), this awaits the subprocess so the caller can read
        the finished session's deliverable. Events still reach
        subscribers live as they arrive.

        :param prompt: The prompt text to pass to claude.
        :param cwd: Working directory to run the subprocess in.
        :param permission_mode: Permission mode to pass to claude.
        :param resume_id: Session id to resume, or None to start a new
            session.
        :param on_session_id: Optional callback invoked with the id the
            first time it becomes known.
        :param model: Model alias for ``--model``, or None to use the
            CLI's default.
        :returns: The resolved session id.
        :raises SessionStartError: If no session id is produced.
        """
        os.makedirs(cwd, exist_ok=True)
        argv = self.build_argv(prompt, resume_id, permission_mode, model)
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=_STREAM_LIMIT,
        )
        stderr_task = asyncio.create_task(_drain(proc.stderr))
        try:
            sid = await self.consume(
                _stdout_lines(proc), cwd, resume_id, on_session_id
            )
            await proc.wait()
            await stderr_task
        finally:
            if proc.returncode is None:
                proc.kill()
            stderr_task.cancel()
        if sid is None:
            raise SessionStartError("claude produced no session id")
        return sid

    async def start(self, prompt: str) -> str:
        """
        Start a new session and return its session id.

        Returns once the id is known; the run streams on in the
        background.

        :param prompt: The prompt text to start the session with.
        :returns: The resolved session id.
        """
        base = os.path.join(self.settings.workspace_root, "session")
        cwd = base + "-" + uuid.uuid4().hex[:8]
        argv = self.build_argv(prompt)
        return await self._launch(argv, cwd, record_id=None)

    async def resume(self, session_id: str, prompt: str) -> str:
        """
        Resume an existing session with new input.

        Returns immediately (the id is already known); the run streams
        on in the background.

        :param session_id: Id of the session to resume.
        :param prompt: The prompt text to resume the session with.
        :returns: The resolved session id.
        :raises SessionNotFoundError: If the session is unknown.
        """
        record = self.registry.get(session_id)
        if record is None:
            raise SessionNotFoundError(session_id)
        argv = self.build_argv(prompt, resume_id=session_id)
        return await self._launch(argv, record.cwd, record_id=session_id)


def get_runner(
    settings: Settings = Depends(get_settings),
    registry: SessionRegistry = Depends(get_registry),
) -> SessionRunner:
    """
    Provide a SessionRunner as a FastAPI dependency.

    :param settings: Application settings, injected.
    :param registry: Session registry, injected.
    :returns: A SessionRunner instance.
    """
    return SessionRunner(settings, registry)
