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
import os
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable

import httpx

_logger = logging.getLogger(__name__)

#: File-mutating opencode tools. On a read-only step (refine, plan) these
#: are both disabled per message AND their permission requests are
#: rejected here, so the agent cannot modify the workspace
#: (defense-in-depth).
DENY_WRITE_TOOLS = frozenset({"edit", "write", "patch"})


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
) -> AsyncIterator[None]:
    """Answer this session's permission prompts for the wrapped turn."""
    task = asyncio.create_task(
        run_permission_loop(conn, session_id, directory, read_only)
    )
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def run_permission_loop(
    conn: OpenCodeConnection,
    session_id: str,
    directory: str | None,
    read_only: bool,
) -> None:
    """Stream ``/event`` and answer this session's permission prompts."""
    client = conn.client or httpx.AsyncClient(timeout=None)
    params = {"directory": os.path.abspath(directory)} if directory else None
    try:
        async with client.stream(
            "GET",
            f"{conn.base_url}/event",
            params=params,
            auth=conn.auth,
        ) as resp:
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    event = json.loads(line[len("data:") :].strip())
                except json.JSONDecodeError:
                    continue
                if event.get("type") != "permission.asked":
                    continue
                props = event.get("properties") or {}
                if props.get("sessionID") != session_id:
                    continue
                await _answer_permission(
                    conn, session_id, props, directory, read_only
                )
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
    reject = read_only and tool in DENY_WRITE_TOOLS
    await conn.request(
        "POST",
        f"/session/{session_id}/permissions/{request_id}",
        json={"response": "reject" if reject else "once"},
        directory=directory,
    )
