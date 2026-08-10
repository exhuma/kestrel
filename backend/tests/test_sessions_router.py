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
        self, session_id: str, resume_after: int = 0
    ) -> AsyncIterator[tuple[int, dict[str, object]]]:
        events = [
            {"type": "system", "session_id": session_id, "raw": {}},
            {"type": "result", "session_id": session_id, "raw": {}},
        ]
        for index, event in enumerate(events, start=1):
            if index > resume_after:
                yield index, event

    def delete(self, session_id: str) -> None:
        if not self._known:
            raise SessionNotFoundError(session_id)
        self.deleted = session_id

    async def poll(self, session_id: str) -> SessionSummary:
        if not self._known:
            raise SessionNotFoundError(session_id)
        return SessionSummary(
            session_id=session_id, status="error", event_count=3
        )


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
async def test_poll_session_returns_updated_summary() -> None:
    """Ensure POST /api/sessions/{id}/poll returns the probed summary."""
    async with _client(_FakeService()) as client:
        resp = await client.post("/api/sessions/s1/poll")
    assert resp.status_code == 200
    assert resp.json()["status"] == "error"


@pytest.mark.asyncio
async def test_poll_unknown_session_returns_404() -> None:
    """Ensure polling an unknown session maps to HTTP 404."""
    async with _client(_FakeService(known=False)) as client:
        resp = await client.post("/api/sessions/nope/poll")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_backends_endpoint_reports_effective_config() -> None:
    """Ensure GET /api/backends surfaces the resolved backend config."""
    async with _client(_FakeService()) as client:
        resp = await client.get("/api/backends")
    assert resp.status_code == 200
    body = resp.json()
    # Hermetic default config (see tests/conftest.py): claude only.
    assert body["default_session_backend"] == "claude"
    assert body["backends"] == [
        {"id": "claude", "type": "claude_cli", "model": None}
    ]


@pytest.mark.asyncio
def _data_frames(text: str) -> list[dict]:
    """Extract the JSON body of every ``data:`` frame in an SSE response."""
    out = []
    for chunk in text.split("\n\n"):
        for line in chunk.split("\n"):
            if line.startswith("data: "):
                out.append(json.loads(line[len("data: ") :]))
    return out


@pytest.mark.asyncio
async def test_events_stream_returns_sse_frames() -> None:
    """Ensure GET events streams SSE data frames from the service."""
    async with _client(_FakeService()) as client:
        resp = await client.get("/api/sessions/s1/events")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    # Anti-buffering headers so intermediaries flush frames promptly.
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.headers["x-accel-buffering"] == "no"
    frames = _data_frames(resp.text)
    assert len(frames) == 2
    assert frames[0] == {"type": "system", "session_id": "s1", "raw": {}}


@pytest.mark.asyncio
async def test_events_stream_carries_a_resumable_id_per_frame() -> None:
    """Ensure each frame carries an id: so a reconnect can resume from it."""
    async with _client(_FakeService()) as client:
        resp = await client.get("/api/sessions/s1/events")
    ids = [
        line[len("id: ") :]
        for chunk in resp.text.split("\n\n")
        for line in chunk.split("\n")
        if line.startswith("id: ")
    ]
    assert ids == ["1", "2"]


@pytest.mark.asyncio
async def test_events_stream_honours_last_event_id() -> None:
    """Ensure a reconnect with Last-Event-ID only replays what's new."""
    async with _client(_FakeService()) as client:
        resp = await client.get(
            "/api/sessions/s1/events", headers={"Last-Event-ID": "1"}
        )
    frames = _data_frames(resp.text)
    assert frames == [{"type": "result", "session_id": "s1", "raw": {}}]
