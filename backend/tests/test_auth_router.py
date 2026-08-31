"""Tests for the /api/auth router (config bootstrap, permissions, tickets)."""
from __future__ import annotations

from http import HTTPStatus

import httpx

from app.config import Settings, get_settings
from app.main import create_app


def _client(settings: Settings):
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
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
