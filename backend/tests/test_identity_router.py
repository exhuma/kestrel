"""Tests for the identity router (oauth2-proxy header passthrough)."""
from __future__ import annotations

from http import HTTPStatus

import httpx
import pytest

from app.main import create_app


def _client():
    app = create_app()
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.mark.asyncio
async def test_identity_reflects_forwarded_headers() -> None:
    """Ensure the three oauth2-proxy headers map onto the response."""
    async with _client() as client:
        resp = await client.get(
            "/api/identity",
            headers={
                "X-Forwarded-User": "alice",
                "X-Forwarded-Email": "alice@example.com",
                "X-Forwarded-Preferred-Username": "Alice",
            },
        )
    assert resp.status_code == HTTPStatus.OK
    assert resp.json() == {
        "username": "alice",
        "email": "alice@example.com",
        "preferred_username": "Alice",
    }


@pytest.mark.asyncio
async def test_identity_is_all_null_without_a_proxy_in_front() -> None:
    """Ensure a missing proxy (e.g. local dev) yields null fields, not 4xx."""
    async with _client() as client:
        resp = await client.get("/api/identity")
    assert resp.status_code == HTTPStatus.OK
    assert resp.json() == {
        "username": None,
        "email": None,
        "preferred_username": None,
    }
