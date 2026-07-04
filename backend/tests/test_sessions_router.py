"""Tests for the sessions router (service mocked)."""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx
import pytest

from app.main import create_app
from app.schemas import SessionSummary
from app.services.exceptions import SessionNotFoundError, SessionStartError
from app.services.sessions import get_session_service


class _FakeService:
    """Stand-in service with configurable behaviour per test."""

    def __init__(
        self,
        *,
        start_error: bool = False,
        known: bool = True,
    ) -> None:
        self._start_error = start_error
        self._known = known

    async def start(self, prompt: str) -> str:
        if self._start_error:
            raise SessionStartError("no session id")
        return "fake-1"

    async def resume(self, session_id: str, prompt: str) -> str:
        if not self._known:
            raise SessionNotFoundError(session_id)
        return session_id

    def list_summaries(self) -> list[SessionSummary]:
        return [
            SessionSummary(session_id="s1", status="idle", event_count=2)
        ]

    async def stream(
        self, session_id: str
    ) -> AsyncIterator[dict[str, object]]:
        yield {"type": "system", "session_id": session_id, "raw": {}}
        yield {"type": "result", "session_id": session_id, "raw": {}}

    def delete(self, session_id: str) -> None:
        if not self._known:
            raise SessionNotFoundError(session_id)
        self.deleted = session_id


def _client(service: _FakeService) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session_service] = lambda: service
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_create_session_returns_id() -> None:
    """Ensure POST /api/sessions returns a session id."""
    async with _client(_FakeService()) as client:
        resp = await client.post("/api/sessions", json={"prompt": "hi"})
    assert resp.status_code == 200
    assert resp.json()["session_id"] == "fake-1"


@pytest.mark.asyncio
async def test_start_failure_returns_502() -> None:
    """Ensure a SessionStartError maps to HTTP 502."""
    async with _client(_FakeService(start_error=True)) as client:
        resp = await client.post("/api/sessions", json={"prompt": "hi"})
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_resume_unknown_returns_404() -> None:
    """Ensure a SessionNotFoundError maps to HTTP 404."""
    async with _client(_FakeService(known=False)) as client:
        resp = await client.post(
            "/api/sessions/nope/resume", json={"prompt": "again"}
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_sessions() -> None:
    """Ensure GET /api/sessions returns summary shapes."""
    async with _client(_FakeService()) as client:
        resp = await client.get("/api/sessions")
    assert resp.status_code == 200
    body = resp.json()
    assert body == [
        {
            "session_id": "s1", "status": "idle", "event_count": 2,
            "created_at": None, "workflow": None,
        }
    ]


@pytest.mark.asyncio
async def test_delete_session_ok() -> None:
    """Ensure DELETE /api/sessions/{id} returns 200."""
    service = _FakeService()
    async with _client(service) as client:
        resp = await client.delete("/api/sessions/s1")
    assert resp.status_code == 200
    assert service.deleted == "s1"


@pytest.mark.asyncio
async def test_delete_unknown_session_returns_404() -> None:
    """Ensure deleting an unknown session maps to HTTP 404."""
    async with _client(_FakeService(known=False)) as client:
        resp = await client.delete("/api/sessions/nope")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_events_stream_returns_sse_frames() -> None:
    """Ensure GET events streams SSE data frames from the service."""
    async with _client(_FakeService()) as client:
        resp = await client.get("/api/sessions/s1/events")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    frames = [
        line for line in resp.text.split("\n\n") if line.startswith("data: ")
    ]
    assert len(frames) == 2
    first = json.loads(frames[0][len("data: ") :])
    assert first == {"type": "system", "session_id": "s1", "raw": {}}
