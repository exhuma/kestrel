"""Tests for the /api/auth router (config bootstrap, permissions, tickets)."""
from __future__ import annotations

from http import HTTPStatus

import httpx
from fastapi import HTTPException

from app.auth import tickets
from app.auth.dependencies import get_current_claims
from app.auth.identity import AuthenticatedUser
from app.config import Settings, get_settings
from app.main import create_app


def _client(settings: Settings, user: AuthenticatedUser | None = None):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    if user is not None:
        app.dependency_overrides[get_current_claims] = lambda: user
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def test_auth_config_disabled() -> None:
    """Disabled auth reports enabled=false with empty authority/client_id."""
    async with _client(Settings(auth_enabled=False)) as client:
        resp = await client.get("/api/auth/config")
    assert resp.status_code == HTTPStatus.OK
    assert resp.json() == {"enabled": False, "authority": "", "client_id": ""}


async def test_auth_config_enabled_reports_settings() -> None:
    """Enabled auth reports the configured authority and client id."""
    settings = Settings(
        auth_enabled=True,
        oidc_authority="https://idp.example.com/realms/kestrel",
        oidc_audience="kestrel-spa",
    )
    async with _client(settings) as client:
        resp = await client.get("/api/auth/config")
    assert resp.status_code == HTTPStatus.OK
    assert resp.json() == {
        "enabled": True,
        "authority": "https://idp.example.com/realms/kestrel",
        "client_id": "kestrel-spa",
    }


async def test_auth_config_requires_no_authentication() -> None:
    """The bootstrap endpoint is reachable with zero Authorization header,
    even when auth is enabled — the SPA must be able to call it pre-login."""
    settings = Settings(
        auth_enabled=True,
        oidc_authority="https://idp.example.com/realms/kestrel",
        oidc_audience="kestrel-spa",
    )
    async with _client(settings) as client:
        resp = await client.get("/api/auth/config")
    assert resp.status_code == HTTPStatus.OK


async def test_sse_ticket_requires_authentication() -> None:
    """A caller without a valid identity cannot mint a ticket."""
    settings = Settings(
        auth_enabled=True, oidc_authority="x", oidc_audience="y"
    )
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings

    async def _reject():
        raise HTTPException(status_code=401, detail="missing bearer token")

    app.dependency_overrides[get_current_claims] = _reject
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/auth/sse-ticket")
    assert resp.status_code == HTTPStatus.UNAUTHORIZED


async def test_sse_ticket_mint_returns_a_usable_ticket() -> None:
    """An authenticated caller gets a ticket that validates back to them."""
    user = AuthenticatedUser(
        sub="user-1", email=None, preferred_username=None,
        permissions=frozenset({"workflows:cleanup"}),
    )
    settings = Settings(
        auth_enabled=True, oidc_authority="x", oidc_audience="y"
    )
    async with _client(settings, user=user) as client:
        resp = await client.post("/api/auth/sse-ticket")
    assert resp.status_code == HTTPStatus.OK
    ticket = resp.json()["ticket"]
    validated = tickets.validate(ticket)
    assert validated is not None
    assert validated.sub == "user-1"
    assert validated.permissions == frozenset({"workflows:cleanup"})
