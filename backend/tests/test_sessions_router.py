"""Tests for the sessions router (service mocked)."""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx
import pytest

from app.auth import tickets
from app.auth.identity import AuthenticatedUser
from app.config import get_settings
from app.main import create_app
from app.schemas import SessionSummary
from app.services.exceptions import SessionNotFoundError, SessionStartError
from app.services.sessions import get_session_service
from tests.conftest import _auth_enabled_settings, override_auth


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


def _client_auth_enabled(
    service: _FakeService, *, authenticated: bool
) -> httpx.AsyncClient:
    """A client with auth enabled, either authenticated or not."""
    return _client_with_permissions(
        service, frozenset() if authenticated else None
    )


def _client_with_permissions(
    service: _FakeService, permissions: frozenset[str] | None
) -> httpx.AsyncClient:
    """A client with auth enabled and a specific permission set (or,
    when ``permissions`` is None, an unauthenticated caller)."""
    app = create_app()
    app.dependency_overrides[get_session_service] = lambda: service
    app.dependency_overrides[get_settings] = _auth_enabled_settings
    override_auth(app, permissions=permissions)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_list_sessions_requires_auth_when_enabled() -> None:
    """GET /api/sessions is authenticated-only, no permission needed."""
    async with _client_auth_enabled(
        _FakeService(), authenticated=False
    ) as client:
        resp = await client.get("/api/sessions")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_sessions_ok_when_authenticated() -> None:
    """Any authenticated identity (no specific permission) may list."""
    async with _client_auth_enabled(
        _FakeService(), authenticated=True
    ) as client:
        resp = await client.get("/api/sessions")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_poll_session_requires_auth_when_enabled() -> None:
    """POST /api/sessions/{id}/poll is authenticated-only."""
    async with _client_auth_enabled(
        _FakeService(), authenticated=False
    ) as client:
        resp = await client.post("/api/sessions/s1/poll")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_events_stream_requires_a_ticket_when_auth_enabled() -> None:
    """GET /sessions/{id}/events rejects a connection with no ticket."""
    app = create_app()
    app.dependency_overrides[get_session_service] = _FakeService
    app.dependency_overrides[get_settings] = _auth_enabled_settings
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        resp = await client.get("/api/sessions/s1/events")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_events_stream_accepts_a_valid_ticket() -> None:
    """GET /sessions/{id}/events opens the stream with a valid ticket."""
    user = AuthenticatedUser(
        sub="user-1", email=None, preferred_username=None,
        permissions=frozenset(),
    )
    ticket = tickets.mint(user)
    app = create_app()
    app.dependency_overrides[get_session_service] = _FakeService
    app.dependency_overrides[get_settings] = _auth_enabled_settings
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        resp = await client.get(
            f"/api/sessions/s1/events?ticket={ticket}"
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_create_session_requires_sessions_write() -> None:
    """POST /api/sessions 403s without sessions:write."""
    async with _client_with_permissions(_FakeService(), frozenset()) as client:
        resp = await client.post("/api/sessions", json={"prompt": "hi"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_session_ok_with_sessions_write() -> None:
    """POST /api/sessions succeeds with sessions:write."""
    perms = frozenset({"sessions:write"})
    async with _client_with_permissions(_FakeService(), perms) as client:
        resp = await client.post("/api/sessions", json={"prompt": "hi"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_resume_session_requires_sessions_write() -> None:
    """POST /api/sessions/{id}/resume 403s without sessions:write."""
    async with _client_with_permissions(_FakeService(), frozenset()) as client:
        resp = await client.post(
            "/api/sessions/s1/resume", json={"prompt": "again"}
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_session_requires_sessions_delete() -> None:
    """DELETE /api/sessions/{id} 403s without sessions:delete."""
    service = _FakeService()
    # Holds sessions:write but not sessions:delete — proves the two are
    # gated independently, not folded into one "sessions:write" catch-all.
    perms = frozenset({"sessions:write"})
    async with _client_with_permissions(service, perms) as client:
        resp = await client.delete("/api/sessions/s1")
    assert resp.status_code == 403
    assert not hasattr(service, "deleted")


@pytest.mark.asyncio
async def test_delete_session_ok_with_sessions_delete() -> None:
    """DELETE /api/sessions/{id} succeeds with sessions:delete."""
    service = _FakeService()
    perms = frozenset({"sessions:delete"})
    async with _client_with_permissions(service, perms) as client:
        resp = await client.delete("/api/sessions/s1")
    assert resp.status_code == 200
    assert service.deleted == "s1"
