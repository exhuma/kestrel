"""Tests for the source-health router (feature 014, service mocked)."""
from __future__ import annotations

import asyncio
import json
from http import HTTPStatus

import httpx
import pytest

from app.main import create_app
from app.routers.health import _frames, stream_health
from app.services.health import (
    HealthPollService,
    HealthState,
    get_health_poll_service,
)


def _client(service: HealthPollService) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_health_poll_service] = lambda: service
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


def _data_frame(chunk: bytes) -> dict | None:
    for line in chunk.decode().split("\n"):
        if line.startswith("data: "):
            return json.loads(line[len("data: ") :])
    return None


@pytest.mark.asyncio
async def test_list_health_returns_every_registered_entry() -> None:
    """Ensure GET /api/health lists every entry, unknown before any check."""

    async def ok() -> bool:
        return True

    service = HealthPollService([("github", ok), ("jira", ok)])
    async with _client(service) as client:
        resp = await client.get("/api/health")
    assert resp.status_code == HTTPStatus.OK
    body = resp.json()
    assert [e["name"] for e in body] == ["github", "jira"]
    assert all(e["state"] == "unknown" for e in body)
    assert all(e["checked_at"] is None for e in body)


@pytest.mark.asyncio
async def test_stream_health_returns_an_sse_streaming_response() -> None:
    """Ensure the route wires up the right media type + anti-buffering
    headers (the ASGI test transport cannot drain this response's body,
    since it never finishes on its own — see ``_frames``'s docstring;
    frame content is covered directly below)."""
    service = HealthPollService([])
    resp = await stream_health(service=service)
    assert resp.media_type == "text/event-stream"
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.headers["x-accel-buffering"] == "no"


@pytest.mark.asyncio
async def test_frames_sends_the_current_snapshot_first() -> None:
    """Ensure the first yielded frame is the current list."""

    async def ok() -> bool:
        return True

    service = HealthPollService([("github", ok)])
    service.store.set("github", healthy=True)

    gen = _frames(service)
    try:
        first = await asyncio.wait_for(gen.__anext__(), timeout=5)
    finally:
        await gen.aclose()

    frame = _data_frame(first)
    assert frame["health"][0]["name"] == "github"
    assert frame["health"][0]["state"] == "healthy"


@pytest.mark.asyncio
async def test_frames_sends_a_fresh_frame_after_a_tick() -> None:
    """Ensure a bus publish delivers a second, updated frame."""

    async def ok() -> bool:
        return True

    service = HealthPollService([("github", ok)])
    gen = _frames(service)
    try:
        first = _data_frame(
            await asyncio.wait_for(gen.__anext__(), timeout=5)
        )
        assert first["health"][0]["state"] == "unknown"

        service.store.set("github", healthy=False)
        service.bus.publish()
        second = _data_frame(
            await asyncio.wait_for(gen.__anext__(), timeout=5)
        )
    finally:
        await gen.aclose()

    assert second["health"][0]["state"] == "unhealthy"


@pytest.mark.asyncio
async def test_refresh_returns_404_for_an_unknown_name() -> None:
    """Ensure refreshing a name that isn't registered is a clean 404."""
    service = HealthPollService([])
    async with _client(service) as client:
        resp = await client.post("/api/health/does-not-exist/refresh")
    assert resp.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_refresh_triggers_a_check_and_updates_the_store() -> None:
    """Ensure POST refresh reaches the service and the outcome lands in
    the store (observed here directly; the SSE contract is covered
    above)."""
    calls: list[str] = []

    async def ok() -> bool:
        calls.append("checked")
        return True

    service = HealthPollService([("github", ok)])
    async with _client(service) as client:
        resp = await client.post("/api/health/github/refresh")
    assert resp.status_code == HTTPStatus.ACCEPTED

    async def _settled() -> None:
        while service.store.get("github").state == HealthState.UNKNOWN:
            await asyncio.sleep(0.01)

    await asyncio.wait_for(_settled(), timeout=2)
    assert calls == ["checked"]
    assert service.store.get("github").state == HealthState.HEALTHY
