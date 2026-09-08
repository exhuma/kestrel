"""HTTP + SSE routes for source health status (feature 014)."""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app import sse
from app.schemas import HealthOut
from app.services.health import HealthPollService, get_health_poll_service

router = APIRouter(prefix="/api/health")

#: Keeps fire-and-forget refresh tasks referenced so they aren't GC'd
#: mid-flight (mirrors routers/github_webhook.py's own ``_TASKS``).
_TASKS: set[asyncio.Task] = set()


def _fire_and_forget(coro) -> None:
    """Run ``coro`` in the background; the caller's response has already
    been sent (contracts/health-api.md: 202, result observed via SSE)."""
    task = asyncio.create_task(coro)
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


def _current(service: HealthPollService) -> list[HealthOut]:
    """Every registered entry's current state, in registration order."""
    return [
        HealthOut(name=e.name, state=e.state.value, checked_at=e.checked_at)
        for e in service.store.list_all()
    ]


def _payload(service: HealthPollService) -> list[dict[str, object]]:
    """Serialise the current health list for an SSE frame."""
    return [h.model_dump(mode="json") for h in _current(service)]


@router.get("", response_model=list[HealthOut])
async def list_health(
    service: HealthPollService = Depends(get_health_poll_service),
) -> list[HealthOut]:
    """List every configured source's current health."""
    return _current(service)


async def _frames(service: HealthPollService) -> AsyncIterator[bytes]:
    """Yield the current list, then a fresh one on every bus tick.

    A module-level (not route-nested) generator, so it can be iterated
    directly in a test with a bounded ``anext()``/timeout — the ASGI test
    transport cannot partially drain a route whose response never
    finishes on its own (this one runs until the client disconnects).
    """
    q = service.bus.subscribe()
    try:
        yield sse.encode({"health": _payload(service)})
        async for tick in sse.with_heartbeat(q):
            if tick is None:
                yield sse.KEEPALIVE
            else:
                yield sse.encode({"health": _payload(service)})
    finally:
        service.bus.unsubscribe(q)


@router.get("/events")
async def stream_health(
    service: HealthPollService = Depends(get_health_poll_service),
) -> StreamingResponse:
    """
    Stream the health list as Server-Sent Events.

    Emits the current list immediately, then a fresh list after every
    completed check cycle or manual refresh.
    """
    return StreamingResponse(
        _frames(service), media_type="text/event-stream", headers=sse.HEADERS
    )


@router.post("/{name}/refresh", status_code=202)
async def refresh_health(
    name: str,
    service: HealthPollService = Depends(get_health_poll_service),
) -> dict[str, str]:
    """Trigger an immediate recheck of one source (FR-004)."""
    if service.store.get(name) is None:
        raise HTTPException(status_code=404, detail="unknown source")
    _fire_and_forget(service.refresh(name))
    return {"status": "accepted"}
