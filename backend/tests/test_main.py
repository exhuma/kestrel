"""Tests for the application factory and root route."""
from __future__ import annotations

import httpx
import pytest

from app.main import create_app


@pytest.mark.asyncio
async def test_root_returns_ok() -> None:
    """Ensure the root route reports service status ok."""
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
