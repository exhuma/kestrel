"""Tests for the application factory and root route."""
from __future__ import annotations

import httpx
import pytest

from app.main import create_app


@pytest.mark.asyncio
async def test_healthz_reports_ok_and_version() -> None:
    """The readiness probe reports ok (DB reachable) and the version."""
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    # Baked in via KESTREL_VERSION; defaults to the from-source sentinel.
    assert body["version"] == "0.0.0-dev"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://[::1]:5174",
    ],
)
async def test_cors_preflight_allows_loopback_origins(origin: str) -> None:
    """Ensure the SPA is allowed from any loopback host and port."""
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        resp = await client.options(
            "/api/sessions",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == origin
