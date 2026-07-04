"""Server-Sent Events transport encoding.

The only place that knows the SSE wire frame format. Services yield
event payload dicts; routers encode them here before streaming.
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, TypeVar

#: How long a stream may stay idle before it sends a keepalive comment.
#: A long-running step (e.g. a slow local LLM) can otherwise leave a
#: stream silent for minutes; without traffic the connection can go
#: half-open and the browser never sees the next event (nor reconnects),
#: so the user must reload. Periodic keepalives keep it genuinely alive.
HEARTBEAT_SECONDS = 15.0

#: An SSE comment frame. EventSource ignores it, but it keeps the
#: connection warm and flushes through any buffering proxy.
KEEPALIVE = b": keepalive\n\n"

#: Response headers that stop intermediaries from buffering the stream.
HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",  # disable nginx-style proxy buffering
}

_T = TypeVar("_T")


async def with_heartbeat(
    queue: asyncio.Queue[_T],
) -> AsyncIterator[_T | None]:
    """
    Yield each queued item, or ``None`` when idle past the heartbeat.

    Callers send a real SSE frame for an item and :data:`KEEPALIVE` for a
    ``None`` tick, so an idle stream stays alive instead of silently dying
    during a long-running step.

    :param queue: The pub/sub queue to drain.
    :returns: Items as they arrive, interleaved with ``None`` keepalives.
    """
    while True:
        try:
            yield await asyncio.wait_for(queue.get(), HEARTBEAT_SECONDS)
        except asyncio.TimeoutError:
            yield None


def encode(data: dict[str, object]) -> bytes:
    """
    Encode a payload dict as one SSE ``data:`` frame.

    :param data: The JSON-serialisable payload to send.
    :returns: A UTF-8 ``data: <json>\\n\\n`` SSE frame.
    """
    return ("data: " + json.dumps(data) + "\n\n").encode("utf-8")
