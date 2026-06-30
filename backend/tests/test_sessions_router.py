"""Tests for the sessions router (runner mocked)."""
from __future__ import annotations

import json

import httpx
import pytest

from app.main import create_app
from app.models import ParsedEvent
from app.services.runner import SessionRunner, get_runner
from app.storage.registry import SessionRegistry, get_registry


class _FakeRunner(SessionRunner):
    """Runner that records a session without a real subprocess."""

    async def start(self, prompt: str) -> str:
        self.registry.create("fake-1", "/tmp/fake-1")
        self.registry.append_event(
            "fake-1", ParsedEvent("result", "fake-1", {})
        )
        self.registry.set_status("fake-1", "idle")
        return "fake-1"


def _client_with_fakes() -> tuple[httpx.AsyncClient, SessionRegistry]:
    app = create_app()
    registry = SessionRegistry()
    app.dependency_overrides[get_registry] = lambda: registry
    app.dependency_overrides[get_runner] = lambda: _FakeRunner(
        None, registry  # type: ignore[arg-type]
    )
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(
        transport=transport, base_url="http://test"
    )
    return client, registry


@pytest.mark.asyncio
async def test_create_session_returns_id() -> None:
    """Ensure POST /api/sessions returns a session id."""
    client, _ = _client_with_fakes()
    async with client:
        resp = await client.post(
            "/api/sessions", json={"prompt": "hi"}
        )
    assert resp.status_code == 200
    assert resp.json()["session_id"] == "fake-1"


@pytest.mark.asyncio
async def test_list_sessions() -> None:
    """Ensure GET /api/sessions lists created sessions."""
    client, registry = _client_with_fakes()
    registry.create("s1", "/tmp/s1")
    async with client:
        resp = await client.get("/api/sessions")
    assert resp.status_code == 200
    ids = [s["session_id"] for s in resp.json()]
    assert "s1" in ids


def test_sse_frame_matches_session_event_shape() -> None:
    """Ensure SSE frames carry type, session_id and raw."""
    from app.routers.sessions import _sse

    frame = _sse(ParsedEvent("system", "s1", {"subtype": "init"}))
    text = frame.decode("utf-8")
    assert text.startswith("data: ")
    assert text.endswith("\n\n")
    payload = json.loads(text[len("data: ") :].strip())
    assert payload == {
        "type": "system",
        "session_id": "s1",
        "raw": {"subtype": "init"},
    }
