"""Tests for the shared-secret bearer gate on /api routes."""
from __future__ import annotations

import httpx
import pytest

from app.config import Settings, get_settings
from app.main import create_app


def _client(token: str):
    """Build a test client whose settings carry the given api_token."""
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(api_token=token)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.mark.asyncio
async def test_open_when_no_token_configured() -> None:
    """Ensure an unset api_token leaves the API open (dev default)."""
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(api_token="")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get("/api/backends")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_missing_token_rejected() -> None:
    """Ensure a configured token rejects requests that omit it."""
    async with _client("s3cret") as c:
        r = await c.get("/api/backends")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_wrong_token_rejected() -> None:
    """Ensure a mismatched bearer token is rejected."""
    async with _client("s3cret") as c:
        r = await c.get(
            "/api/backends", headers={"Authorization": "Bearer nope"}
        )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_correct_bearer_accepted() -> None:
    """Ensure the correct bearer token passes the gate."""
    async with _client("s3cret") as c:
        r = await c.get(
            "/api/backends", headers={"Authorization": "Bearer s3cret"}
        )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_query_param_token_accepted_for_sse() -> None:
    """Ensure the access_token query param authenticates (EventSource path)."""
    async with _client("s3cret") as c:
        r = await c.get("/api/backends?access_token=s3cret")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_healthz_stays_open() -> None:
    """Ensure the health probe is reachable without a token."""
    async with _client("s3cret") as c:
        r = await c.get("/healthz")
    assert r.status_code in (200, 503)  # 503 only if DB unreachable
