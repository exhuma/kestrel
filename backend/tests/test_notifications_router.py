"""Tests for the notifications router (store mocked)."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from app.auth import tickets
from app.auth.dependencies import get_ticket_claims
from app.config import get_settings
from app.main import create_app
from app.notifications import Notification
from app.persistence.notification_store import get_notification_store
from tests.conftest import (
    _auth_enabled_settings,
    _fake_authenticated_user,
    override_auth,
)


class _FakeStore:
    def __init__(self) -> None:
        self.read_ids: list[int] = []

    def list_all(self) -> list[Notification]:
        return [
            Notification(
                id=2, workflow_id="wf-1", repo="o/r", issue_number=5,
                status="done", message="PR opened for o/r#5.",
                created_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
                read=False,
            ),
            Notification(
                id=1, workflow_id="wf-1", repo="o/r", issue_number=5,
                status="awaiting_plan_approval",
                message="Implementation plan ready for review: o/r#5.",
                created_at=datetime(2026, 7, 2, tzinfo=timezone.utc),
                read=True,
            ),
        ]

    def mark_read(self, notification_id: int) -> None:
        self.read_ids.append(notification_id)


def _client(store):
    app = create_app()
    app.dependency_overrides[get_notification_store] = lambda: store
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.mark.asyncio
async def test_list_notifications_newest_first() -> None:
    """Ensure the list endpoint returns the store's order and fields."""
    async with _client(_FakeStore()) as client:
        resp = await client.get("/api/notifications")
    assert resp.status_code == 200
    body = resp.json()
    assert [n["id"] for n in body] == [2, 1]
    assert body[0]["message"] == "PR opened for o/r#5."
    assert body[0]["read"] is False
    assert body[1]["read"] is True
    # done -> summary; awaiting_* -> action_required.
    assert body[0]["signal_class"] == "summary"
    assert body[1]["signal_class"] == "action_required"


@pytest.mark.asyncio
async def test_mark_read_calls_store() -> None:
    """Ensure marking a notification read reaches the store."""
    store = _FakeStore()
    async with _client(store) as client:
        resp = await client.post("/api/notifications/1/read")
    assert resp.status_code == 200
    assert store.read_ids == [1]


def _client_auth_enabled(store, *, authenticated: bool):
    app = create_app()
    app.dependency_overrides[get_notification_store] = lambda: store
    app.dependency_overrides[get_settings] = _auth_enabled_settings
    override_auth(app, permissions=frozenset() if authenticated else None)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.mark.asyncio
async def test_list_notifications_requires_auth_when_enabled() -> None:
    """GET /api/notifications is authenticated-only, no permission needed."""
    async with _client_auth_enabled(
        _FakeStore(), authenticated=False
    ) as client:
        resp = await client.get("/api/notifications")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_mark_read_requires_auth_when_enabled() -> None:
    """POST /api/notifications/{id}/read is authenticated-only."""
    async with _client_auth_enabled(
        _FakeStore(), authenticated=False
    ) as client:
        resp = await client.post("/api/notifications/1/read")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_mark_read_ok_when_authenticated() -> None:
    """Any authenticated identity (no specific permission) may mark read."""
    async with _client_auth_enabled(
        _FakeStore(), authenticated=True
    ) as client:
        resp = await client.post("/api/notifications/1/read")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_events_stream_requires_a_ticket_when_auth_enabled() -> None:
    """GET /api/notifications/events rejects a connection with no ticket."""
    app = create_app()
    app.dependency_overrides[get_notification_store] = _FakeStore
    app.dependency_overrides[get_settings] = _auth_enabled_settings
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/notifications/events")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_events_route_accepts_a_valid_ticket() -> None:
    """A valid ticket authenticates the notifications /events dependency.

    Like the workflow streams, this stream never terminates on its own
    (heartbeats forever), so a full HTTP round-trip can't observe
    "streaming started" without hanging on the infinite body — see
    test_workflows_router_auth.py for the same reasoning. Exercise the
    shared ``get_ticket_claims`` dependency directly instead.
    """
    settings = _auth_enabled_settings()
    ticket = tickets.mint(_fake_authenticated_user(frozenset({"x"})))
    user = await get_ticket_claims(ticket=ticket, settings=settings)
    assert user is not None
    assert user.permissions == frozenset({"x"})


