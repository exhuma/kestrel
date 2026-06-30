"""Service that spawns and resumes claude CLI sessions."""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import AsyncIterator

from fastapi import Depends

from app.config import Settings, get_settings
from app.models import parse_event
from app.storage.registry import SessionRegistry, get_registry


class SessionRunner:
    """Spawns claude subprocesses and streams events to the registry."""

    def __init__(
        self, settings: Settings, registry: SessionRegistry
    ) -> None:
        self.settings = settings
        self.registry = registry

    def build_argv(
        self, prompt: str, resume_id: str | None = None
    ) -> list[str]:
        """
        Build the claude CLI argument vector.

        :param prompt: The prompt text to pass to claude.
        :param resume_id: Session id to resume, or None to start
            a new session.
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
            self.settings.permission_mode,
        ]
        if resume_id is not None:
            argv += ["--resume", resume_id]
        return argv

    async def consume(
        self,
        lines: AsyncIterator[str],
        cwd: str,
        record_id: str | None = None,
    ) -> str | None:
        """
        Consume a line stream, updating the registry.

        :param lines: Async iterator of raw JSONL lines.
        :param cwd: Working directory the session runs in.
        :param record_id: Existing record id (resume), or None to
            create a record when the first session id appears.
        :returns: The resolved session id, or None if never seen.
        """
        session_id = record_id
        async for line in lines:
            event = parse_event(line)
            if event is None:
                continue
            if session_id is None and event.session_id is not None:
                session_id = event.session_id
                self.registry.create(session_id, cwd)
            if session_id is not None:
                self.registry.append_event(session_id, event)
                if event.type == "result":
                    self.registry.set_status(session_id, "idle")
        return session_id

    async def _spawn(
        self, argv: list[str], cwd: str, record_id: str | None
    ) -> str:
        """Spawn the subprocess and drain its stdout via consume."""
        os.makedirs(cwd, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def _stdout() -> AsyncIterator[str]:
            assert proc.stdout is not None
            async for raw in proc.stdout:
                yield raw.decode("utf-8", "replace")

        async def _drain_stderr() -> None:
            assert proc.stderr is not None
            async for _ in proc.stderr:
                pass

        stderr_task = asyncio.create_task(_drain_stderr())
        try:
            sid = await self.consume(_stdout(), cwd, record_id)
            await proc.wait()
            await stderr_task
        finally:
            if proc.returncode is None:
                proc.kill()
            stderr_task.cancel()
        if sid is None:
            raise RuntimeError("claude produced no session id")
        return sid

    async def start(self, prompt: str) -> str:
        """
        Start a new session and return its session id.

        :param prompt: The prompt text to start the session with.
        :returns: The resolved session id.
        """
        base = os.path.join(self.settings.workspace_root, "session")
        cwd = base + "-" + uuid.uuid4().hex[:8]
        argv = self.build_argv(prompt)
        return await self._spawn(argv, cwd, record_id=None)

    async def resume(self, session_id: str, prompt: str) -> str:
        """
        Resume an existing session with new input.

        :param session_id: Id of the session to resume.
        :param prompt: The prompt text to resume the session with.
        :returns: The resolved session id.
        """
        record = self.registry.get(session_id)
        if record is None:
            raise KeyError(session_id)
        argv = self.build_argv(prompt, resume_id=session_id)
        return await self._spawn(argv, record.cwd, record_id=session_id)


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
