"""Stop an opencode session kestrel has stopped waiting for (#66).

Cancelling kestrel's own request (a turn timeout, for example) does not
stop opencode: its agent keeps working the session, and keeps calling
the model, with nothing in kestrel watching. So a cancelled turn asks
opencode to abort the session, in the background — the caller being
cancelled must not wait on it.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

_logger = logging.getLogger("kestrel.backends.opencode")

#: Strong references to in-flight abort requests, so they are not
#: garbage-collected mid-flight.
_TASKS: set[asyncio.Task[None]] = set()

#: ``OpenCodeBackend._request``'s shape: (method, path, directory=...).
Request = Callable[..., Awaitable[object]]


def abort_on_cancel(
    request: Request, session_id: str | None, directory: str
) -> None:
    """Schedule ``POST /session/{id}/abort`` for *session_id*, if any."""
    if session_id is None:
        return
    task = asyncio.create_task(_abort(request, session_id, directory))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


async def _abort(request: Request, session_id: str, directory: str) -> None:
    try:
        await request(
            "POST", f"/session/{session_id}/abort",
            directory=directory or None,
        )
    except Exception:
        _logger.warning(
            "opencode session %s: abort after cancel failed", session_id,
            exc_info=True,
        )
        return
    _logger.info("opencode session %s: aborted after cancel", session_id)
