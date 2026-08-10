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


def encode(data: dict[str, object], event_id: int | None = None) -> bytes:
    """
    Encode a payload dict as one SSE frame, optionally with an ``id:``.

    An ``id:`` frame lets the browser's native ``EventSource`` resume from
    where it left off (via ``Last-Event-ID``) instead of a caller having
    to replay everything from scratch on every reconnect.

    :param data: The JSON-serialisable payload to send.
    :param event_id: A monotonic per-stream sequence number, or None for
        a stream that has nothing to resume (e.g. the workflow list/detail
        streams, which always send a full current snapshot anyway).
    :returns: A UTF-8 SSE frame: ``id: <n>\\ndata: <json>\\n\\n`` when
        ``event_id`` is given, else ``data: <json>\\n\\n``.
    """
    prefix = f"id: {event_id}\n" if event_id is not None else ""
    return (prefix + "data: " + json.dumps(data) + "\n\n").encode("utf-8")
