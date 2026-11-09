"""Answers opencode's tool-permission prompts for the duration of a turn.

opencode's permissions are ``ask`` by default, so a headless turn would
block on the first tool call. A background task streams the server-wide
``/event`` bus and replies to each ``permission.asked`` for the turn's
session so it proceeds unattended.
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable

import httpx

from app.backends.base import BackendUnavailable

_logger = logging.getLogger(__name__)

#: How long to wait before reopening a lost event stream, in seconds.
RECONNECT_SECONDS = 2.0

#: What httpx raises when the server has gone away. A timeout is not one
#: of these: a slow model is not an outage.
CONNECTION_LOST = (httpx.NetworkError, httpx.RemoteProtocolError)

#: Told each ``message.part.updated`` part of the turn's session
#: (feature 036: the tool-loop guard).
PartWatcher = Callable[[object], Awaitable[None]]

#: File-mutating opencode tools. On a read-only step (refine, plan) these
#: are both disabled per message AND their permission requests are
#: rejected here, so the agent cannot modify the workspace
#: (defense-in-depth).
DENY_WRITE_TOOLS = frozenset({"edit", "write", "patch"})
READ_ONLY_DENY_TOOLS = DENY_WRITE_TOOLS | {"question", "task"}


@dataclass
class OpenCodeConnection:
    """The connection details permission handling needs from the backend."""

    base_url: str
    auth: httpx.BasicAuth | None
    client: httpx.AsyncClient | None
    request: Callable[..., Awaitable[object]]


@asynccontextmanager
async def permission_handler(
    conn: OpenCodeConnection,
    session_id: str,
    directory: str | None,
    read_only: bool,
    watch: PartWatcher | None = None,
) -> AsyncIterator[None]:
    """Answer this session's permission prompts for the wrapped turn, and
    show *watch* its message parts."""
    task = asyncio.create_task(
        run_permission_loop(conn, session_id, directory, read_only, watch)
    )
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def directory_params(directory: str | None) -> dict[str, str] | None:
    """The ``directory`` query parameter, as an absolute path (or ``None``)."""
    if not directory:
        return None
    return {"directory": str(Path(directory).absolute())}


async def run_permission_loop(
    conn: OpenCodeConnection,
    session_id: str,
    directory: str | None,
    read_only: bool,
    watch: PartWatcher | None = None,
) -> None:
    """Stream ``/event``, answer this session's permission prompts, and
    show *watch* its message parts.

    A lost connection is not this loop's failure to report: if the
    server is gone the turn's own request fails, and if only the stream
    dropped the turn goes on. So the stream is reopened until the turn
    ends and cancels this task.
    """
    turn = _Turn(conn, session_id, directory, read_only, watch)
    client = conn.client or httpx.AsyncClient(timeout=None)
    reported = False
    try:
        while not await _follow_events(client, conn, directory, turn):
            log = _logger.debug if reported else _logger.warning
            log("opencode event stream lost for session %s", session_id)
            reported = True
            await asyncio.sleep(RECONNECT_SECONDS)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _logger.exception(
            "opencode permission handling failed for session %s", session_id
        )
        raise RuntimeError("opencode permission handling failed") from exc
    finally:
        if conn.client is None:
            await client.aclose()


async def _follow_events(
    client: httpx.AsyncClient,
    conn: OpenCodeConnection,
    directory: str | None,
    turn: _Turn,
) -> bool:
    """Handle the event stream until it ends.

    :returns: ``True`` when the server ended the stream, ``False`` when
        the connection was lost.
    """
    try:
        async with client.stream(
            "GET",
            f"{conn.base_url}/event",
            params=directory_params(directory),
            auth=conn.auth,
        ) as resp:
            async for line in resp.aiter_lines():
                event = _parse(line)
                if event is not None:
                    await turn.handle(event)
    except (*CONNECTION_LOST, BackendUnavailable):
        return False
    return True


def _parse(line: str) -> dict | None:
    """One ``data:`` line of the event stream, or ``None``."""
    if not line.startswith("data:"):
        return None
    try:
        event = json.loads(line[len("data:") :].strip())
    except json.JSONDecodeError:
        return None
    return event if isinstance(event, dict) else None


@dataclass
class _Turn:
    """What one turn's event loop answers and watches."""

    conn: OpenCodeConnection
    session_id: str
    directory: str | None
    read_only: bool
    watch: PartWatcher | None

    async def handle(self, event: dict) -> None:
        props = event.get("properties") or {}
        if props.get("sessionID") != self.session_id:
            return
        kind = event.get("type")
        if kind == "permission.asked":
            await _answer_permission(
                self.conn, self.session_id, props, self.directory,
                self.read_only,
            )
        elif kind == "message.part.updated" and self.watch is not None:
            await self.watch(props.get("part"))


async def _answer_permission(
    conn: OpenCodeConnection,
    session_id: str,
    request: dict[str, object],
    directory: str | None,
    read_only: bool,
) -> None:
    """Approve or reject a single opencode permission request.

    Rejects a file-mutating tool on a read-only turn (defense-in-depth
    alongside the disabled tools); approves everything else — including
    ``bash``. Approving shell execution inside the workspace is a
    deliberate, documented prompt-injection risk in this alpha.
    """
    request_id = request.get("id")
    tool = request.get("permission")
    if not isinstance(request_id, str):
        return
    reject = read_only and tool in READ_ONLY_DENY_TOOLS
    await conn.request(
        "POST",
        f"/session/{session_id}/permissions/{request_id}",
        json={"response": "reject" if reject else "once"},
        directory=directory,
    )
