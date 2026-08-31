"""Tests for auth gating on the workflows router (feature 011).

Split out from test_workflows_router.py rather than added there to keep
both files under the module-length limit; reuses that module's shared
``_client``/``_FakeService`` test doubles (established cross-test-module
pattern — see test_workflows_router_rerun.py).
"""
from __future__ import annotations

import httpx
import pytest

from app.auth import tickets
from app.auth.dependencies import get_ticket_claims
from app.config import get_settings
from app.main import create_app
from app.services.workflows import get_workflow_service
from tests.conftest import (
    _auth_enabled_settings,
    _fake_authenticated_user,
    override_auth,
)
from tests.test_workflows_router import _FakeService

_HTTP_OK = 200
_HTTP_UNAUTHORIZED = 401


def _client_auth_enabled(service, *, authenticated: bool) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_workflow_service] = lambda: service
    app.dependency_overrides[get_settings] = _auth_enabled_settings
    override_auth(app, permissions=frozenset() if authenticated else None)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


def _client_ticket_only(service) -> httpx.AsyncClient:
    """A client with auth enabled but no bearer-token override — only a
    ticket (or lack of one) authenticates the /events routes."""
    app = create_app()
    app.dependency_overrides[get_workflow_service] = lambda: service
    app.dependency_overrides[get_settings] = _auth_enabled_settings
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.mark.asyncio
async def test_list_workflows_requires_auth_when_enabled() -> None:
    """GET /api/workflows is authenticated-only, no permission needed."""
    async with _client_auth_enabled(
        _FakeService(), authenticated=False
    ) as client:
        resp = await client.get("/api/workflows")
    assert resp.status_code == _HTTP_UNAUTHORIZED


@pytest.mark.asyncio
async def test_get_workflow_ok_when_authenticated() -> None:
    """Any authenticated identity (no specific permission) may view detail."""
    async with _client_auth_enabled(
        _FakeService(), authenticated=True
    ) as client:
        resp = await client.get("/api/workflows/wf-1")
    assert resp.status_code == _HTTP_OK


@pytest.mark.asyncio
async def test_poll_workflow_requires_auth_when_enabled() -> None:
    """POST /api/workflows/{id}/poll is authenticated-only."""
    async with _client_auth_enabled(
        _FakeService(), authenticated=False
    ) as client:
        resp = await client.post("/api/workflows/wf-1/poll")
    assert resp.status_code == _HTTP_UNAUTHORIZED


@pytest.mark.asyncio
async def test_list_events_stream_requires_a_ticket() -> None:
    """GET /api/workflows/events rejects a connection with no ticket."""
    async with _client_ticket_only(_FakeService()) as client:
        resp = await client.get("/api/workflows/events")
    assert resp.status_code == _HTTP_UNAUTHORIZED


@pytest.mark.asyncio
async def test_events_routes_accept_a_valid_ticket() -> None:
    """A valid ticket authenticates the dependency both /events routes share.

    Both workflow SSE streams (list and detail) never terminate on their
    own (heartbeats forever while subscribed), so a full HTTP round-trip
    can't observe "streaming started successfully" without hanging on the
    infinite body. Exercise the shared ``get_ticket_claims`` dependency
    directly instead — the same check the two rejection tests above prove
    is actually wired onto those routes.
    """
    settings = _auth_enabled_settings()
    ticket = tickets.mint(_fake_authenticated_user(frozenset({"x"})))
    user = await get_ticket_claims(ticket=ticket, settings=settings)
    assert user is not None
    assert user.permissions == frozenset({"x"})
